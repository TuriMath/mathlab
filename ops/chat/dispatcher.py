"""Dispatcher: turns the task board into agent turns. Replaces the old per-agent shift timer.

Loop (every POLL seconds):
1. Read GitHub (tasks.snapshot) and sync the board. Merge approved + green PRs right here, with no LLM.
2. If anything became ready, or TICK seconds passed, dispatch: ready tasks in priority order, one running task per
   persona, each on the seat seats.pick() gives it. Nothing ready means no Claude run at all.
3. Company state (see "Company state" below): when nothing has run or been ready for a while, one cheap Haiku
   call (the supervisor) looks at the board and decides: wake tasks that can move, queue the planner (Hilbert),
   or park in WAITING_ON_SAI, where no LLM runs at all until Sai speaks or GitHub moves.

A task turn gets: the persona (company docs, rules, role file), the playbook for its kind, a brief read from GitHub
just now, its last handoff and the company-log slice for its ref. It runs in the task's own worktree and keeps the
task's own Claude session, so follow-ups resume where the work stopped. No turn cap; a turn quiet for
`stall_seconds` gets one warning in #needs-sai and keeps running.

Theorem pipeline (docs/pipeline.md): a theorem issue's stage label picks its agents (tasks.py). The dispatcher
moves stages that need no judgement: formalize -> equiv when both formalizers are done, equiv -> prove when the
A<->B PR merges, prove -> verified (issue closed) when the proof PR merges. Euler's equiv/prove turns count
against the theorem's budget; a stage out of budget is parked instead of run. Every turn is also appended to the
trace index (TRACES), keyed by Claude session id, so transcripts can be labelled later.

Results: DONE posts to #work; BLOCKED-SAI to #needs-sai (only when it changed); IDLE and BLOCKED post nothing.
An issue task that ended DONE continues after `continue_gap`; everything else waits until its GitHub fingerprint
changes. Sai controls it with /pause, /resume and /status.
"""
import asyncio
import json
from pathlib import Path
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import companylog as log
import db
import seats
import tasks
import worktrees
from config import AGENTS, DISPATCH, FACTORY, MODELS, PLANNER, RETRY_MODEL, SYSTEM, TASK_KINDS, WORKSPACE, env
from router import ask_json
from runner import _show, company_prompt, run_turn

IST = timezone(timedelta(hours=5, minutes=30))
NEEDS_SAI = "needs-sai"
STATUS_LINE = re.compile(r"\W*(DONE|BLOCKED-SAI|BLOCKED|IDLE)\b", re.I)
LIMIT_HIT = re.compile(r"hit your (?:weekly|5-hour|session|usage) limit|usage limit reached", re.I)
REVIEW_TOOLS_OFF = ["Edit", "Write", "NotebookEdit", "Bash(git push:*)", "Bash(git commit:*)"]
BREAK_TOOLS_OFF = ["Bash(git push:*)"]

TRACES = Path(env("TRACES") or Path.home() / f".{FACTORY['slug']}-traces.jsonl")
COUNTED = {"DONE", "BLOCKED", "BLOCKED-SAI"}   # turns that count as an attempt (IDLE is not an attempt)

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


def task_log(t: dict) -> list[dict]:
    """The company-log slice for a task. A formalizer never sees the other formalizer's events (their handoffs
    quote their statement), nor anything that names them: the blind pair has to stay blind."""
    events = log.slice(t["ref"], t["repo"])
    rival = tasks.blind_rival(t)
    if rival:
        events = [e for e in events if e.get("actor") != rival and not tasks.mentions(e.get("summary"), rival)]
    return events


def task_prompt(t: dict, where: str, brief: str, nudge: str = "") -> str:
    label = TASK_KINDS[t["kind"]]["label"]
    head = f"[task turn] {label}: {t['ref']} {t['title']}" if t["ref"] else f"[task turn] {label}"
    why = (f"## Why you were woken\nNothing changed on GitHub; the supervisor thinks this task can move now: "
           f"{nudge}\nIf it really can't, say exactly what blocks it and who can unblock it.\n\n") if nudge else ""
    return (
        f"{head}\nNobody messaged you: the dispatcher picked this task for you from the board.\n"
        f"Working copy: {where}\n\n{why}"
        f"## Brief (read from GitHub just now)\n{brief}\n\n"
        f"## Last handoff on this task\n{t['handoff'] or '(first turn on this task)'}\n\n"
        f"## Company log for this task\n{_log_lines(task_log(t))}\n\n"
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
    hint = db.kv_get("plan_hint", "") or "nothing on the board can move."
    return (
        "[task turn] Plan the queue\nThe dispatcher woke you because the team is quiet. The supervisor's read: "
        f"{hint}\nIf the next step waits on Sai's direction, look for real work that doesn't depend on it "
        "(gate scripts, metadata, write-ups of verified theorems) before you call it IDLE.\n\n"
        f"## Board\n{board_text()}\n\n## Spec and ladder (vision.md on origin/main)\n{_show('vision.md')[:12000]}\n\n"
        f"## Recent company log\n{_log_lines(log.recent(30))}\n\n"
        f"Follow the plan playbook: keep 2-4 theorems in flight in {FACTORY['org']}/{FACTORY['work_repo']} "
        "(issues 'Theorem: <name>' from docs/theorem-issue.md), and ask Sai only for direction when a phase gate "
        "has passed. Don't invent busywork; if nothing sensible is left, say so.\n\n"
        "End with:\nHANDOFF:\n<what you queued and why>\nDONE: <issues opened, with refs>  or  IDLE"
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
    if kind in RETRY_MODEL and attempts(t) >= 1:
        model = MODELS[RETRY_MODEL[kind]]
    try:
        if t["role"] == "plan":
            cwd, system, prompt, disallowed = None, None, plan_prompt(), None
            session, resume = str(uuid.uuid4()), False
            system = company_prompt(agent, _playbook(kind), where_section(t, "your home worktree"))
        else:
            wt, where = await asyncio.to_thread(worktrees.ensure, t)
            body = await asyncio.to_thread(tasks.brief, t)
            nudge = db.kv_get(f"nudge:{key}", "")
            db.kv_set(f"nudge:{key}", "")
            cwd, prompt = wt, task_prompt(t, f"{wt} ({where})", body, nudge)
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
    trace(t, seat, model, session, kind, report)
    if kind in COUNTED and (t["info"] or {}).get("theorem") and t["kind"] in RETRY_MODEL:
        db.kv_set(attempt_key(t), str(attempts(t) + 1))
    f = dict(last_result=kind, handoff=handoff or t["handoff"], turns=t["turns"] + 1, seat=seat, model=model,
             session_id=session, settle=1 if github else 0)
    if not github:
        f.update(status="done", session_id=None)
    elif kind == "DONE" and t["role"] == "issue":
        f.update(status="ready", next_at=now + DISPATCH["continue_gap_seconds"])
    else:
        f.update(status="waiting")
    if kind == "DONE":
        progress_made(key)
    if not github:                       # the planner: in a row that filed nothing, stop asking it
        db.kv_set("planner_idle", "0" if kind == "DONE" else str(int(db.kv_get("planner_idle", "0")) + 1))
    if kind == "DONE":
        db.add("work", agent, report)
    elif kind == "BLOCKED-SAI" and report != t["last_sai"]:
        db.add(NEEDS_SAI, agent, report)
    f["last_sai"] = report if kind == "BLOCKED-SAI" else ""
    log.update(key, **f)
    log.append("agent", f"turn-{kind.lower()}", report, repo=t["repo"], ref=t["ref"], actor=agent)
    if handoff:
        log.append("agent", "handoff", handoff, repo=t["repo"], ref=t["ref"], actor=agent)


# ---------- Theorem pipeline ----------
def attempt_key(t) -> str:
    return f"attempts:{t['ref']}:{t['kind']}"


def attempts(t) -> int:
    return int(db.kv_get(attempt_key(t), "0") or 0)


def out_of_budget(t) -> bool:
    info = t["info"] or {}
    return bool(info.get("theorem")) and t["kind"] in RETRY_MODEL and attempts(t) >= (info.get("budget") or 0) > 0


def trace(t, seat, model, session, result, report):
    """One line per finished turn: the label a transcript needs to become training data."""
    rec = {"ts": time.time(), "task": t["key"], "agent": t["owner"], "kind": t["kind"], "ref": t["ref"],
           "stage": (t["info"] or {}).get("stage"), "attempt": attempts(t) + 1, "session_id": session,
           "seat": seat, "model": model, "result": result, "report": report[:500]}
    try:
        with TRACES.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except OSError as e:
        print(f"trace write failed: {e}", flush=True)


async def park_task(t):
    reason = (f"The {t['kind']} stage used its budget of {(t['info'] or {}).get('budget')} attempts without "
              f"moving on. Last handoff:\n\n{t['handoff'] or '(none)'}")
    if await asyncio.to_thread(tasks.park, t["repo"], t["number"], reason):
        log.update(t["key"], status="done")
        log.append("dispatcher", "parked", f"{t['title']}: {t['kind']} out of budget", repo=t["repo"], ref=t["ref"],
                   actor=t["owner"])
        db.add("work", SYSTEM["id"], f"DONE: parked {t['ref']} {t['title']} ({t['kind']} out of budget)")
    else:
        log.update(t["key"], status="ready", next_at=time.time() + 600)   # GitHub refused: try again later


async def advance(a):
    if await asyncio.to_thread(tasks.set_stage, a["repo"], a["number"], a["from"], a["to"]):
        ref = f"{a['repo']}#{a['number']}"
        log.append("dispatcher", "stage", f"{a['title']}: {a['from']} -> {a['to']}", repo=a["repo"], ref=ref)
        db.add("work", SYSTEM["id"], f"DONE: {ref} {a['title']} moved to {a['to']} (both statements pushed)")


async def after_merge(pr):
    """equiv PR merged -> stage:prove (statement locked); proof PR merged -> verified, issue closed."""
    n = tasks.theorem_of_branch(pr["repo"], pr.get("branch"))
    if n is None or not await asyncio.to_thread(tasks.is_theorem_issue, pr["repo"], n):
        return
    labels = await asyncio.to_thread(tasks.issue_labels, pr["repo"], n)
    ref = f"{pr['repo']}#{n}"
    if "stage:equiv" in labels:
        if await asyncio.to_thread(tasks.set_stage, pr["repo"], n, "equiv", "prove"):
            log.append("dispatcher", "stage", f"statement locked by {pr['ref']}; equiv -> prove", repo=pr["repo"],
                       ref=ref)
            db.add("work", SYSTEM["id"], f"DONE: {ref} statement locked ({pr['ref']}), moved to prove")
    elif "stage:prove" in labels:
        if await asyncio.to_thread(tasks.verify, pr["repo"], n, pr["ref"]):
            log.append("dispatcher", "verified", f"{ref} verified by {pr['ref']}", repo=pr["repo"], ref=ref)
            db.add("work", SYSTEM["id"], f"DONE: ✅ {ref} verified ({pr['ref']})")


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
        set_state("paused", "Sai paused the dispatcher")
        return
    snap = await asyncio.to_thread(tasks.snapshot)
    if snap is None:
        return
    sai_queue[:] = snap["sai_review"]
    sai_review_digest()
    changed = tasks.sync(snap["tasks"])
    for a in snap["advance"]:
        await advance(a)
    for pr in snap["merge"]:
        await merge(pr)
    busy = {b for t in log.tasks() if (b := worktrees.branch_of(t))}
    for t in log.tasks(("done",)):
        if t["role"] in ("issue", "pr", "review") and not (t["info"] or {}).get("cleaned"):
            what = await asyncio.to_thread(worktrees.remove, t, busy)
            if what in ("removed", "none"):
                log.update(t["key"], info={**(t["info"] or {}), "cleaned": True})
    if changed or time.time() - _last_tick >= DISPATCH["tick_seconds"]:
        _last_tick = time.time()
        dispatch()
    await supervise()


def dispatch():
    for t in log.ready():
        if seats.machine_full():
            break
        if t["owner"] in running or paused():
            continue
        if out_of_budget(t):
            log.update(t["key"], status="running")       # not picked again while parking
            asyncio.create_task(park_task(t))
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
        await after_merge(pr)
    elif db.kv_get(key) != out:
        db.kv_set(key, out)
        log.append("dispatcher", "merge-failed", f"{pr['ref']}: {out}", repo=pr["repo"], ref=pr["ref"])


def can_plan() -> bool:
    if time.time() - float(db.kv_get("planner_last", "0") or 0) < DISPATCH["planner_gap_seconds"]:
        return False
    if int(db.kv_get("planner_idle", "0") or 0) >= DISPATCH["planner_idle_limit"]:
        return False
    t = log.task(f"{PLANNER}:plan")
    return not (t and t["status"] in ("ready", "running"))


def queue_plan(why: str):
    db.kv_set("planner_last", str(time.time()))
    db.kv_set("plan_hint", why)
    if log.task(f"{PLANNER}:plan"):
        log.update(f"{PLANNER}:plan", status="ready", next_at=0, session_id=None, settle=0)
    else:
        log.create(f"{PLANNER}:plan", owner=PLANNER, role="plan", kind="plan", repo=f"{DISPATCH['org']}/{FACTORY['company_repo']}",
                   ref=None, number=0, title="Plan the queue", priority=TASK_KINDS["plan"]["priority"], info={})
    log.append("dispatcher", "plan", f"planner queued: {why}", actor=PLANNER)


# ---------- Company state ----------
# One state for the whole company, recomputed every poll. Only QUIET spends an LLM call (Haiku, no tools).
#
#   paused          Sai ran /pause. Nothing launches.
#   working         a turn is running, or a task is ready / due soon. The dispatcher handles it.
#   throttled       tasks are ready but no seat may take them (weekly pace, 5-hour window, VM full). No LLM.
#   quiet           nothing running or ready. After quiet_grace, the supervisor checks why:
#                     work            -> wake the waiting tasks that can move           -> working
#                     plan            -> queue the planner (Hilbert)                    -> working
#                     waiting_on_sai  -> post the asks to #needs-sai once               -> waiting_on_sai
#                     nothing         -> roadmap is empty, tell Sai                     -> idle
#   waiting_on_sai  parked: no LLM at all. Leaves when Sai speaks (on_sai) or GitHub wakes a task.
#   idle            like waiting_on_sai, for "nothing left to do". Same exits.
#
# Guards against the old IDLE-burn: a check that leads nowhere doubles the gap to the next one (15 min .. 4 h);
# any DONE resets it. The supervisor can wake one task at most max_nudges times in a row without a DONE.
PARKED = ("waiting_on_sai", "idle")


def company_state() -> str:
    return db.kv_get("company_state", "working")


def set_state(new: str, why: str = ""):
    old = company_state()
    if new == old:
        return
    db.kv_set("company_state", new)
    db.kv_set("company_state_why", why)
    db.kv_set("company_state_since", str(time.time()))
    log.append("dispatcher", "state", f"{old} -> {new}: {why}"[:500])
    if new == "throttled" and time.time() - float(db.kv_get("throttle_posted", "0") or 0) > 6 * 3600:
        db.kv_set("throttle_posted", str(time.time()))
        db.add(NEEDS_SAI, SYSTEM["id"], f"🧊 Work is ready but nothing can launch: {why}. "
               "It goes out by itself when a seat has room.")


def progress_made(key: str | None = None):
    """A DONE: the team is moving. Checks go back to their shortest gap; the task's nudge count resets."""
    db.kv_set("check_gap", str(DISPATCH["check_min_seconds"]))
    if key:
        db.kv_set(f"nudges:{key}", "0")


def on_sai():
    """Sai said something (chat or a command). A parked company looks again a few minutes later."""
    if company_state() in PARKED:
        db.kv_set("next_check_at", str(time.time() + 5 * 60))
        db.kv_set("quiet_since", "0")
        set_state("quiet", "Sai spoke; checking again in 5 min")


def _blocked_reason() -> str:
    if seats.machine_full():
        return "the VM is running its maximum number of turns"
    if seats.throttled():
        return "every seat is ahead of its weekly pace, so only urgent work (CI, conflicts, reviews) goes out"
    why = ", ".join(f"{s['seat']}: {s['why']}" for s in map(seats.state, seats.POOL) if s["why"])
    return f"no seat will take it ({why or 'no reason reported'})"


async def supervise():
    now = time.time()
    if running:
        db.kv_set("quiet_since", "0")
        set_state("working", f"{len(running)} turn(s) running")
        return
    ready = log.tasks(("ready",))
    if any(t["next_at"] <= now for t in ready):     # ready now: launch it (dispatch() may not have ticked yet)
        db.kv_set("quiet_since", "0")
        dispatch()
        if running:
            set_state("working", f"{len(running)} turn(s) running")
            return
        # dispatch() really couldn't launch any of it: no seat (or no VM slot) would take it
        set_state("throttled", _blocked_reason())
        return
    if ready:                                       # a task continues shortly (continue_gap)
        set_state("working", "a task continues shortly")
        return
    if company_state() == "working":                # the last turn just ended: start counting quiet time
        db.kv_set("quiet_since", "0")
        set_state("quiet", "nothing running or ready")
    if company_state() in PARKED:                   # zero LLM until Sai speaks or GitHub wakes a task
        return
    quiet_since = float(db.kv_get("quiet_since", "0") or 0)
    if not quiet_since:
        db.kv_set("quiet_since", str(now))
        set_state("quiet", "nothing running or ready")
        return
    if now - quiet_since < DISPATCH["quiet_grace_seconds"] or now < float(db.kv_get("next_check_at", "0") or 0):
        return
    await check(now)


def _status_line(t) -> str:
    e = log.last_turn(t["ref"], t["owner"])
    return f"{e['kind'][5:].upper()}: {e['summary'][:300]}" if e else "(no turn yet)"


def supervisor_prompt() -> str:
    board = []
    for t in log.tasks(("waiting",)):
        nudges = int(db.kv_get(f"nudges:{t['key']}", "0") or 0)
        board.append(f"- key={t['key']} · {AGENTS[t['owner']]['name']} · {TASK_KINDS[t['kind']]['label']} "
                     f"{t['ref'] or ''} {t['title']}\n  last result: {_status_line(t)}\n"
                     f"  handoff: {(t['handoff'] or '(none)')[:500]}"
                     + ("\n  (already woken twice with no progress: don't pick it)" if nudges >= DISPATCH["max_nudges"] else ""))
    sai_prs = "\n".join(f"- {p['ref']} {p['title']}" for p in sai_queue) or "(none)"
    sai_said = "\n".join(f"- {datetime.fromtimestamp(e['ts'], IST):%d %b %H:%M}: {e['summary'][:300]}"
                         for e in log.by_kind("sai", 6)) or "(nothing recent)"
    plan_note = "" if can_plan() else "\nThe planner can't run right now (ran recently, or filed nothing twice in a row): don't answer plan.\n"
    return (
        f"You supervise {WORKSPACE}, {FACTORY['about']}. Sai is the only human (the operator). "
        "Right now no agent is working and nothing is queued. Work out why, and what should happen next.\n"
        f"Now: {datetime.now(IST):%a %d %b %H:%M IST}\n\n"
        f"## Parked tasks (each waits until its GitHub item changes)\n{chr(10).join(board) or '(none)'}\n\n"
        f"## PRs waiting on Sai's review\n{sai_prs}\n\n"
        f"## What Sai said recently\n{sai_said}\n\n"
        f"## Recent company log\n{_log_lines(log.recent(25))}\n{plan_note}\n"
        "Decide one state:\n"
        '- "work": one or more parked tasks can make real progress now without Sai (the blocker named in its '
        "last result is gone, or its handoff has a next step nobody else must do first). Put their keys in wake.\n"
        '- "plan": no parked task can move, but the roadmap clearly has more work that is not filed yet and '
        f"doesn't depend on anything Sai still has to decide. The planner ({AGENTS[PLANNER]['name']}) will file it.\n"
        '- "waiting_on_sai": the next real step on everything needs Sai (a review, a decision, access).\n'
        '- "nothing": nothing is blocked on Sai and there is nothing sensible left to do.\n'
        "Don't wake a task that ended IDLE or BLOCKED unless something has visibly changed for it since.\n\n"
        'Answer with JSON only: {"state": "work|plan|waiting_on_sai|nothing", "wake": ["<key>", ...], '
        '"sai": ["<one line per thing only Sai can do, with its ref>"], "why": "<one sentence>"}'
    )


async def check(now: float):
    gap = float(db.kv_get("check_gap", str(DISPATCH["check_min_seconds"])) or DISPATCH["check_min_seconds"])
    db.kv_set("next_check_at", str(now + gap))
    db.kv_set("check_gap", str(min(gap * 2, DISPATCH["check_max_seconds"])))
    d = await ask_json(supervisor_prompt())
    if not isinstance(d, dict):
        log.append("dispatcher", "check-failed", "supervisor gave no usable answer; trying again later")
        return
    state, why = str(d.get("state", "")), str(d.get("why", ""))[:400]
    waiting = {t["key"]: t for t in log.tasks(("waiting",))}
    wake = [k for k in d.get("wake") or []
            if k in waiting and int(db.kv_get(f"nudges:{k}", "0") or 0) < DISPATCH["max_nudges"]]
    log.append("dispatcher", "check", f"{state}: {why} (wake {', '.join(wake) or 'none'})")
    if state == "work" and wake:
        for k in wake:
            db.kv_set(f"nudges:{k}", str(int(db.kv_get(f"nudges:{k}", "0") or 0) + 1))
            db.kv_set(f"nudge:{k}", why)
            log.update(k, status="ready", next_at=0)
            log.append("dispatcher", "task-nudge", why, repo=waiting[k]["repo"], ref=waiting[k]["ref"],
                       actor=waiting[k]["owner"])
        set_state("working", f"supervisor woke {len(wake)} task(s): {why}")
        dispatch()
    elif state in ("work", "plan") and can_plan():
        queue_plan(why)
        set_state("working", f"planner queued: {why}")
        dispatch()
    elif state == "waiting_on_sai":
        asks = [str(a)[:300] for a in d.get("sai") or []] or [why]
        text = "\n".join(f"- {a}" for a in asks)
        if text != db.kv_get("sai_asks", ""):
            db.kv_set("sai_asks", text)
            db.add(NEEDS_SAI, SYSTEM["id"], f"⏸️ **The team is waiting on you.** Nothing else can move until:\n"
                   f"{text}\nI won't spend anything until you reply here or something changes on GitHub.")
        set_state("waiting_on_sai", why)
    elif state == "nothing" or (state == "plan" and int(db.kv_get("planner_idle", "0") or 0)
                                >= DISPATCH["planner_idle_limit"]):
        if company_state() != "idle":
            db.add(NEEDS_SAI, SYSTEM["id"], f"💤 **The team has nothing to do** and nothing is waiting on you: "
                   f"{why}\nTell us what's next (e.g. @igris) and we'll pick it up.")
        set_state("idle", why)
    # else: work it can't wake yet (nudge cap) or a planner that ran recently: stay quiet, look again later


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
    since = float(db.kv_get("company_state_since", "0") or 0)
    state = (f"**Company:** `{company_state()}`"
             + (f" since {datetime.fromtimestamp(since, IST):%d %b %H:%M IST}" if since else "")
             + (f": {db.kv_get('company_state_why')}" if db.kv_get("company_state_why") else ""))
    if company_state() == "waiting_on_sai" and db.kv_get("sai_asks"):
        state += f"\n{db.kv_get('sai_asks')}"
    return f"{head}\n{state}\n\n" + "\n".join(rows) + "\n\n**Seats**\n" + seats.summary()


def command(text: str) -> str | None:
    """Handles /pause, /resume, /status. Returns the reply, or None if text isn't a command."""
    cmd = text.strip().split()[0].lower() if text.strip().startswith("/") else ""
    if cmd == "/pause":
        db.kv_set("shift_paused", "1")
        return "⏸️ Dispatcher paused. Turns already running will finish. `/resume` to restart."
    if cmd == "/resume":
        db.kv_set("shift_paused", "0")
        set_state("quiet", "Sai resumed the dispatcher")
        db.kv_set("quiet_since", "0")
        db.kv_set("next_check_at", "0")
        return "▶️ Dispatcher resumed. Ready tasks go out at the next poll."
    if cmd == "/status":
        return status_text()
    return None
