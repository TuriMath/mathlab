"""Dispatcher: turns the task board into agent turns. Replaces the old per-agent shift timer.

Loop (every POLL seconds):
1. Read GitHub (tasks.snapshot) and sync the board. Merge approved + green PRs right here, with no LLM.
2. If anything became ready, or TICK seconds passed, dispatch: ready tasks in priority order, one running task per
   persona, each on the seat seats.pick() gives it. Nothing ready means no Claude run at all.
3. When the team is mostly out of work (and at most hourly), queue a `plan` task for the planner (Hilbert).

A task turn gets: the persona (company docs, rules, role file), the playbook for its kind, a brief read from GitHub
just now, its last handoff and the company-log slice for its ref. It runs in the task's own worktree and keeps the
task's own Claude session, so follow-ups resume where the work stopped. No turn cap; a turn quiet for
`stall_seconds` gets one warning in #needs-sai and keeps running.

Results: DONE posts to #work; BLOCKED-SAI to #needs-sai (only when it changed); IDLE and BLOCKED post nothing.
An issue task that ended DONE continues after `continue_gap`; everything else waits until its GitHub fingerprint
changes. Sai controls it with /pause, /resume and /status.
"""
import asyncio
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import companylog as log
import db
import seats
import tasks
import worktrees
from config import AGENTS, DISPATCH, FACTORY, MODELS, PLANNER, SYSTEM, TASK_KINDS, WORKSPACE
from runner import _show, company_prompt, run_turn

IST = timezone(timedelta(hours=5, minutes=30))
NEEDS_SAI = "needs-sai"
STATUS_LINE = re.compile(r"\W*(DONE|BLOCKED-SAI|BLOCKED|IDLE)\b", re.I)
LIMIT_HIT = re.compile(r"hit your (?:weekly|5-hour|session|usage) limit|usage limit reached", re.I)
REVIEW_TOOLS_OFF = ["Edit", "Write", "NotebookEdit", "Bash(git push:*)", "Bash(git commit:*)"]
BREAK_TOOLS_OFF = ["Bash(git push:*)"]

running: dict[str, str] = {}             # agent -> task key
sai_queue: list[dict] = []
_ctx: dict = {}
_last_tick = 0.0


# ---------- Prompts ----------
def _playbook(kind: str) -> str:
    return _show(f"ops/chat/playbooks/{kind}.md") or ""


def _log_lines(events) -> str:
    out = []
    for e in events:
        when = datetime.fromtimestamp(e["ts"], IST).strftime("%d %b %H:%M IST")
        who = AGENTS[e["actor"]]["name"] if e.get("actor") in AGENTS else (e.get("actor") or e["source"])
        out.append(f"- {when} · {who} · {e['kind']}: {e['summary'][:400]}")
    return "\n".join(out) or "(nothing yet)"


def board_text() -> str:
    rows = []
    for a, v in AGENTS.items():
        mine = [t for t in log.tasks() if t["owner"] == a]
        if not mine:
            rows.append(f"- {v['name']}: nothing on the board")
            continue
        items = "; ".join(f"{t['status']} {TASK_KINDS[t['kind']]['label'].lower()} {t['ref'] or ''}".strip()
                          for t in mine[:6])
        rows.append(f"- {v['name']}: {items}{' …' if len(mine) > 6 else ''}")
    return "\n".join(rows)


def task_prompt(t: dict, where: str, brief: str) -> str:
    label = TASK_KINDS[t["kind"]]["label"]
    head = f"[task turn] {label}: {t['ref']} {t['title']}" if t["ref"] else f"[task turn] {label}"
    return (
        f"{head}\nNobody messaged you: the dispatcher picked this task for you from the board.\n"
        f"Working copy: {where}\n\n"
        f"## Brief (read from GitHub just now)\n{brief}\n\n"
        f"## Last handoff on this task\n{t['handoff'] or '(first turn on this task)'}\n\n"
        f"## Company log for this task\n{_log_lines(log.slice(t['ref'], t['repo']))}\n\n"
        "Work this task as far as you can take it now; there is no turn limit. Follow the playbook for this kind "
        "of task and the rules in agents/_rules.md.\n\n"
        "End your reply with a handoff for whoever picks this task up next (it may be you in a fresh session), "
        "then exactly one status line, nothing after it:\n"
        "HANDOFF:\n<3-6 lines: where it stands, the next concrete step, anything surprising>\n"
        "DONE: <what you finished, with PR/issue refs>\n"
        "BLOCKED-SAI: <what you need from Sai, with ref>  (only Sai can unblock: sai-review, a decision, access)\n"
        "BLOCKED: <what, and which agent can unblock>\n"
        "IDLE  (nothing to do on this task right now)"
    )


def plan_prompt() -> str:
    return (
        "[task turn] Plan the queue\nThe dispatcher woke you because most of the team has nothing on the board.\n\n"
        f"## Board\n{board_text()}\n\n## Roadmap (origin/main)\n{_show('docs/roadmap.md')[:8000]}\n\n"
        f"## Recent company log\n{_log_lines(log.recent(30))}\n\n"
        "Fill the queue with real, next-step work for the current chip: issues titled '<Name>: <task>' in the "
        "chip repo, each small enough for one person and clear about what done means. Move the roadmap to the next "
        "chip when the current one is released. Don't invent busywork; if nothing sensible is left, say so.\n\n"
        "End with:\nHANDOFF:\n<what you queued and why>\nDONE: <issues filed, with refs>  or  IDLE"
    )


def where_section(t: dict, where: str) -> str:
    return (f"## Where you are\nYou are on a task turn, run by the {WORKSPACE} dispatcher. Your working copy for this "
            f"task is {where}. Company docs above are the latest from origin/main. Put real work in the repo; "
            f"chat posts come only from your final status line.")


# ---------- Results ----------
def _last_line(text):
    lines = [l for l in text.strip().splitlines() if l.strip()]
    return lines[-1].strip() if lines else ""


def result_kind(text: str) -> str:
    m = STATUS_LINE.match(_last_line(text))
    return m.group(1).upper() if m else "IDLE"


def handoff_of(text: str) -> str:
    m = re.search(r"HANDOFF:\s*\n?(.*?)\n\s*\W*(?:DONE|BLOCKED-SAI|BLOCKED|IDLE)\b[^\n]*\s*$", text, re.S | re.I)
    if m:
        return m.group(1).strip()[:2000]
    body = text.strip().rsplit("\n", 1)[0] if "\n" in text.strip() else ""
    return body[-800:]


def report_of(text: str) -> str:
    return _last_line(text).strip("*").strip()


# ---------- Task turns ----------
async def _stall_warning(t, minutes):
    db.add(NEEDS_SAI, SYSTEM["id"],
           f"⏳ **{AGENTS[t['owner']]['name']}** has printed nothing for {minutes} min on "
           f"{TASK_KINDS[t['kind']]['label'].lower()} {t['ref'] or ''}. It is still running; nothing was killed.")


async def run_task(t: dict, seat: str):
    agent, key, kind = t["owner"], t["key"], t["kind"]
    working = _ctx["working"]
    own_light = agent not in working
    if own_light:
        working[agent] = {"channel": "work", "parent_id": None}
    model = MODELS[TASK_KINDS[kind]["model"]]
    try:
        if t["role"] == "plan":
            cwd, system, prompt, disallowed = None, None, plan_prompt(), None
            session, resume = str(uuid.uuid4()), False
            system = company_prompt(agent, _playbook(kind), where_section(t, "your home worktree"))
        else:
            wt, where = await asyncio.to_thread(worktrees.ensure, t)
            body = await asyncio.to_thread(tasks.brief, t)
            cwd, prompt = wt, task_prompt(t, f"{wt} ({where})", body)
            system = company_prompt(agent, _playbook(kind), where_section(t, f"{wt} ({where})"))
            disallowed = REVIEW_TOOLS_OFF if kind == "review" else BREAK_TOOLS_OFF if kind == "break" else None
            session, resume = (t["session_id"], True) if t["session_id"] else (str(uuid.uuid4()), False)
        log.append("dispatcher", "turn-start", f"{TASK_KINDS[kind]['label']} on {seat} with {TASK_KINDS[kind]['model']}",
                   repo=t["repo"], ref=t["ref"], actor=agent)
        answer, ok = await run_turn(
            agent, prompt, session, resume, model=model, seat=seat, cwd=cwd, system=system, disallowed=disallowed,
            timeout=DISPATCH["task_timeout_seconds"], stall_seconds=DISPATCH["stall_seconds"],
            on_stall=lambda m: _stall_warning(t, m))
    except Exception as e:
        answer, ok, session, resume = f"BLOCKED-SAI: task turn crashed before it ran: `{e}`", False, None, False
    finally:
        if own_light:
            working.pop(agent, None)
        seats.release(seat)
        running.pop(agent, None)
    finish(t, seat, model, session, resume, answer, ok)


def finish(t, seat, model, session, resume, answer, ok):
    key, agent, now = t["key"], t["owner"], time.time()
    github = t["role"] != "plan"
    if not ok and LIMIT_HIT.search(answer):
        # The seat ran out mid-launch. Not the task's fault: put it back; the budget watcher now skips that seat.
        log.update(key, status="ready", next_at=now + 120)
        log.append("dispatcher", "seat-limit", f"{seat} refused the turn: {answer[:200]}", repo=t["repo"],
                   ref=t["ref"], actor=agent)
        return
    if not ok:
        report = answer[-600:]
        if report != t["last_sai"]:
            db.add(NEEDS_SAI, agent, f"Task turn failed on {t['ref'] or 'planning'}:\n{report}")
        log.update(key, status="ready" if github else "done", next_at=now + 30 * 60, last_sai=report,
                   settle=1 if github else 0)   # a session that never started stays unset
        log.append("dispatcher", "turn-failed", report[:500], repo=t["repo"], ref=t["ref"], actor=agent)
        return
    kind = result_kind(answer)
    report, handoff = report_of(answer), handoff_of(answer)
    f = dict(last_result=kind, handoff=handoff or t["handoff"], turns=t["turns"] + 1, seat=seat, model=model,
             session_id=session, settle=1 if github else 0)
    if not github:
        f.update(status="done", session_id=None)
    elif kind == "DONE" and t["role"] == "issue":
        f.update(status="ready", next_at=now + DISPATCH["continue_gap_seconds"])
    else:
        f.update(status="waiting")
    if kind == "DONE":
        db.add("work", agent, report)
    elif kind == "BLOCKED-SAI" and report != t["last_sai"]:
        db.add(NEEDS_SAI, agent, report)
    f["last_sai"] = report if kind == "BLOCKED-SAI" else ""
    log.update(key, **f)
    log.append("agent", f"turn-{kind.lower()}", report, repo=t["repo"], ref=t["ref"], actor=agent)
    if handoff:
        log.append("agent", "handoff", handoff, repo=t["repo"], ref=t["ref"], actor=agent)


# ---------- Loop ----------
def paused() -> bool:
    return db.kv_get("shift_paused", "0") == "1"


async def loop():
    await asyncio.sleep(15)
    while True:
        try:
            await poll()
        except Exception as e:           # the dispatcher must never die
            print(f"dispatcher poll failed: {e}", flush=True)
        await asyncio.sleep(DISPATCH["poll_seconds"])


async def poll():
    global _last_tick
    if paused():
        return
    snap = await asyncio.to_thread(tasks.snapshot)
    if snap is None:
        return
    sai_queue[:] = snap["sai_review"]
    sai_review_digest()
    changed = tasks.sync(snap["tasks"])
    for pr in snap["merge"]:
        await merge(pr)
    busy = {b for t in log.tasks() if (b := worktrees.branch_of(t))}
    for t in log.tasks(("done",)):
        if t["role"] in ("issue", "pr", "review") and not (t["info"] or {}).get("cleaned"):
            what = await asyncio.to_thread(worktrees.remove, t, busy)
            if what in ("removed", "none"):
                log.update(t["key"], info={**(t["info"] or {}), "cleaned": True})
    maybe_plan()
    if changed or time.time() - _last_tick >= DISPATCH["tick_seconds"]:
        _last_tick = time.time()
        dispatch()


def dispatch():
    for t in log.ready():
        if seats.machine_full():
            break
        if t["owner"] in running or paused():
            continue
        seat = seats.pick(prefer=t["seat"], urgent=TASK_KINDS[t["kind"]]["urgent"])
        if seat is None:
            continue
        seats.acquire(seat)
        running[t["owner"]] = t["key"]
        log.update(t["key"], status="running")
        asyncio.create_task(run_task(t, seat))


async def merge(pr):
    key = f"merge_fail:{pr['ref']}"
    ok, out = await asyncio.to_thread(tasks.merge, pr)
    if ok:
        log.append("dispatcher", "merged", f"Merged {pr['ref']} {pr['title']}", repo=pr["repo"], ref=pr["ref"],
                   actor=pr.get("author"))
        db.add("work", SYSTEM["id"], f"DONE: merged {pr['ref']} {pr['title']} (approved, CI green)")
    elif db.kv_get(key) != out:
        db.kv_set(key, out)
        log.append("dispatcher", "merge-failed", f"{pr['ref']}: {out}", repo=pr["repo"], ref=pr["ref"])


def maybe_plan():
    now = time.time()
    if now - float(db.kv_get("planner_last", "0") or 0) < DISPATCH["planner_gap_seconds"]:
        return
    active = {t["owner"] for t in log.tasks(("ready", "running"))}
    idle = [a for a in AGENTS if a not in active and a not in running]
    if len(idle) < DISPATCH["planner_idle_agents"]:
        return
    t = log.task(f"{PLANNER}:plan")
    if t and t["status"] in ("ready", "running"):
        return
    db.kv_set("planner_last", str(now))
    if t:
        log.update(t["key"], status="ready", next_at=0, session_id=None, settle=0)
    else:
        log.create(f"{PLANNER}:plan", owner=PLANNER, role="plan", kind="plan", repo=f"{DISPATCH['org']}/{FACTORY['company_repo']}",
                   ref=None, number=0, title="Plan the queue", priority=TASK_KINDS["plan"]["priority"], info={})
    log.append("dispatcher", "plan", f"{len(idle)} agents have nothing on the board; planner queued", actor=PLANNER)


def sai_review_digest():
    """Once a day (from sai_digest_hour_ist), list open sai-review PRs in #needs-sai. Nothing if there are none."""
    now = datetime.now(IST)
    today = now.strftime("%Y-%m-%d")
    if now.hour < DISPATCH["sai_digest_hour_ist"] or db.kv_get("sai_digest_day", "") == today:
        return
    db.kv_set("sai_digest_day", today)
    if not sai_queue:
        return
    rows = "\n".join(f"- {p['ref']} {p['title']} (CI {p['ci']})" for p in sai_queue)
    n = len(sai_queue)
    db.add(NEEDS_SAI, SYSTEM["id"], f"📋 **{n} PR{'' if n == 1 else 's'} waiting on your review** "
           f"(label `sai-review`):\n{rows}")


def start(working, locks, slots):
    _ctx.update(working=working)
    log.init()
    if DISPATCH["enabled"]:
        asyncio.create_task(loop())


# ---------- Commands ----------
def status_text() -> str:
    head = "⏸️ **Dispatcher paused.** `/resume` to restart." if paused() else "▶️ **Dispatcher running.** `/pause` to stop."
    if not DISPATCH["enabled"]:
        head = "⛔ **Dispatcher is switched off on this server** (`SHIFT_ENABLED=0`)."
    board = log.tasks()
    rows = []
    for a, v in AGENTS.items():
        mine = [t for t in board if t["owner"] == a]
        run = next((t for t in mine if t["status"] == "running"), None)
        now = (f"🟠 {TASK_KINDS[run['kind']]['label'].lower()} {run['ref'] or ''} on {run['seat'] or '?'}"
               if run else "idle")
        ready = sum(t["status"] == "ready" for t in mine)
        waiting = sum(t["status"] == "waiting" for t in mine)
        rows.append(f"- **{v['name']}** · {now} · {ready} ready · {waiting} waiting")
    return f"{head}\n\n" + "\n".join(rows) + "\n\n**Seats**\n" + seats.summary()


def command(text: str) -> str | None:
    """Handles /pause, /resume, /status. Returns the reply, or None if text isn't a command."""
    cmd = text.strip().split()[0].lower() if text.strip().startswith("/") else ""
    if cmd == "/pause":
        db.kv_set("shift_paused", "1")
        return "⏸️ Dispatcher paused. Turns already running will finish. `/resume` to restart."
    if cmd == "/resume":
        db.kv_set("shift_paused", "0")
        return "▶️ Dispatcher resumed. Ready tasks go out at the next poll."
    if cmd == "/status":
        return status_text()
    return None
