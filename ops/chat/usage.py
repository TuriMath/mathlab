"""Per-seat usage for the Usage tab.

The seat tokens come from `claude setup-token`, which can't read Anthropic's usage API (no user:profile scope).
Instead, every Claude Code run prints a `rate_limit_event` in stream-json output with the seat's 5-hour and
7-day utilization; runner.py hands it to record(). Today's turns/tokens/cost are summed from each run's result.
A seat with no run for STALE_SECONDS gets a tiny Haiku probe so its numbers stay fresh. Seats that run no agents
(USAGE_ONLY_SEATS in config.py) are only ever measured by probes, so their "today" counts are probe runs only.
"""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

import db
from config import POOL, SYSTEM, USAGE_ONLY_SEATS

IST = timezone(timedelta(hours=5, minutes=30))
STALE_SECONDS = 30 * 60
WARN_AT = 0.9
WINDOWS = ("five_hour", "seven_day")
SEATS = sorted(set(POOL) | set(USAGE_ONLY_SEATS))


def _today() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")


def _load(key, default):
    try:
        return json.loads(db.kv_get(key, "") or "null") or default
    except json.JSONDecodeError:
        return default


def _windows(info: dict) -> dict:
    """{window: {utilization, resetsAt, status}} from a rate_limit_info object."""
    out = {}
    for name, w in (info.get("unifiedWindows") or {}).items():
        out[name] = {"utilization": w.get("utilization"), "resetsAt": w.get("resetsAt"), "status": w.get("status")}
    t = info.get("rateLimitType")
    if t and t not in out:   # older events only describe the window that is closest to its limit
        out[t] = {"utilization": info.get("utilization"), "resetsAt": info.get("resetsAt"),
                  "status": info.get("status")}
    return out


def current(seat: str) -> dict:
    """Last known windows for a seat: {"windows": {...}, "status", "updated"}."""
    return _load(f"usage:{seat}", {})


def record(seat: str, rate_info: dict | None, result: dict | None):
    if not seat:
        return
    if rate_info:
        cur = _load(f"usage:{seat}", {})
        wins = cur.get("windows", {})
        wins.update(_windows(rate_info))
        db.kv_set(f"usage:{seat}", json.dumps({"windows": wins, "status": rate_info.get("status"),
                                                "updated": time.time()}))
        _warn(seat, wins)
    if result:
        u = result.get("usage") or {}
        key = f"usage_day:{seat}:{_today()}"
        d = _load(key, {"turns": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "cost": 0.0})
        d["turns"] += 1
        d["input"] += u.get("input_tokens") or 0
        d["output"] += u.get("output_tokens") or 0
        d["cache_read"] += u.get("cache_read_input_tokens") or 0
        d["cache_write"] += u.get("cache_creation_input_tokens") or 0
        # total_cost_usd is the whole session's total so far, so only the growth since the last turn counts.
        sid = result.get("session_id")
        total = result.get("total_cost_usd") or 0.0
        prev = float(db.kv_get(f"cost_seen:{sid}", "0") or 0) if sid else 0.0
        d["cost"] += max(0.0, total - prev)
        if sid:
            db.kv_set(f"cost_seen:{sid}", str(total))
        db.kv_set(key, json.dumps(d))


def _agents_on(seat):
    return ["pool: any agent"] if seat in POOL else [USAGE_ONLY_SEATS.get(seat, "no agents")]


def _warn(seat, wins):
    """One #needs-sai post per seat, window and reset period when a window passes WARN_AT or is blocked."""
    for name in WINDOWS:
        w = wins.get(name) or {}
        util, status = w.get("utilization") or 0, w.get("status") or "allowed"
        if util < WARN_AT and status != "rejected":       # allowed_warning alone is not worth a post
            continue
        key = f"usage_warn:{seat}:{name}:{w.get('resetsAt')}"
        if db.kv_get(key):
            continue
        db.kv_set(key, "1")
        label = {"five_hour": "5-hour", "seven_day": "weekly"}[name]
        reset = (datetime.fromtimestamp(w["resetsAt"], IST).strftime("%a %H:%M IST")
                 if w.get("resetsAt") else "unknown")
        state = "is **blocked**" if status == "rejected" else f"is at **{round(util * 100)}%**"
        db.add("needs-sai", SYSTEM["id"],
               f"⚠️ **{seat}** ({' + '.join(_agents_on(seat))}) {state} of its {label} limit. Resets {reset}.")


def snapshot() -> list[dict]:
    today = _today()
    out = []
    for seat in SEATS:
        cur = _load(f"usage:{seat}", {})
        out.append({"seat": seat, "agents": _agents_on(seat), "windows": cur.get("windows", {}),
                    "status": cur.get("status"), "updated": cur.get("updated"),
                    "today": _load(f"usage_day:{seat}:{today}", None)})
    return out


# ---------- Probes ----------
async def probe(seat: str):
    from runner import CLAUDE, parse_stream, seat_env
    from gate import wait_turn
    await wait_turn()
    proc = await asyncio.create_subprocess_exec(
        CLAUDE, "-p", "say ok", "--model", "haiku", "--max-turns", "1",
        "--output-format", "stream-json", "--verbose",
        cwd="/tmp", env=seat_env(seat), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=90)
    except asyncio.TimeoutError:
        proc.kill()
        return
    result, rate = parse_stream(out)
    record(seat, rate, result)


async def loop():
    await asyncio.sleep(60)
    while True:
        for seat in SEATS:
            updated = _load(f"usage:{seat}", {}).get("updated") or 0
            if time.time() - updated > STALE_SECONDS:
                try:
                    await probe(seat)
                except Exception as e:   # the probe must never take the app down
                    print(f"usage probe {seat} failed: {e}", flush=True)
        await asyncio.sleep(5 * 60)


def start():
    if os.environ.get("USAGE_PROBES", "1") == "1":
        asyncio.create_task(loop())
