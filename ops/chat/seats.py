"""Seat pool and budget watcher.

Seats are capacity, not owners: any persona runs on any pool seat. For each launch, pick() chooses the seat
with the most room against its weekly pace. Rules:
- a seat that is blocked, past (1 - WEEKLY_BUFFER) of its week, or past FIVE_HOUR_CEILING of its 5-hour window
  gets no new launches until it resets (running turns are never touched);
- at most SEAT_MAX_RUNNING turns at once per seat;
- a task stays on the seat it started on while that seat is fine (its prompt cache lives there);
- when every usable seat is AHEAD_OF_PACE ahead of its weekly pace, only urgent work is launched.

Utilization comes from usage.py (the last rate_limit_event seen for each seat).
"""
import time

import usage
from config import AHEAD_OF_PACE, FIVE_HOUR_CEILING, MACHINE_MAX_RUNNING, POOL, SEAT_MAX_RUNNING, WEEKLY_BUFFER

WEEK = 7 * 86400
running: dict[str, int] = {s: 0 for s in POOL}
active = 0                               # turns running on this machine, any seat (chat fallback included)


def _window(seat, name, now):
    w = (usage.current(seat).get("windows") or {}).get(name) or {}
    util, reset, status = w.get("utilization") or 0.0, w.get("resetsAt"), w.get("status") or "allowed"
    if reset and reset <= now:           # the window has rolled over since we last saw it
        return 0.0, None, "allowed"
    return util, reset, status


def state(seat, now=None) -> dict:
    """Usable?, why not, and how far ahead of weekly pace (negative = room to spare)."""
    now = now or time.time()
    w_util, w_reset, w_status = _window(seat, "seven_day", now)
    h_util, h_reset, h_status = _window(seat, "five_hour", now)
    elapsed = 1 - (w_reset - now) / WEEK if w_reset else 0.0
    pace = max(0.0, min(1.0, elapsed)) * (1 - WEEKLY_BUFFER)
    why = None
    if w_status == "rejected" or w_util >= 1 - WEEKLY_BUFFER:
        why = "weekly limit"
    elif h_status == "rejected" or h_util >= FIVE_HOUR_CEILING:
        why = "5-hour limit"
    elif running.get(seat, 0) >= SEAT_MAX_RUNNING:
        why = "busy"
    return {"seat": seat, "ok": why is None, "why": why, "weekly": w_util, "five_hour": h_util,
            "pace": pace, "ahead": w_util - pace, "running": running.get(seat, 0),
            "weekly_reset": w_reset, "five_hour_reset": h_reset}


def throttled(now=None) -> bool:
    """True when every seat that could take work is well ahead of its weekly pace."""
    states = [state(s, now) for s in POOL]
    usable = [s for s in states if s["why"] in (None, "busy")]
    return not usable or all(s["ahead"] > AHEAD_OF_PACE for s in usable)


def pick(prefer: str | None = None, urgent: bool = False) -> str | None:
    """The seat for a new turn, or None if no seat may take it now."""
    now = time.time()
    if not urgent and throttled(now):
        return None
    states = [state(s, now) for s in POOL]
    ok = [s for s in states if s["ok"]]
    if not ok:
        return None
    for s in ok:
        if s["seat"] == prefer:
            return prefer
    return min(ok, key=lambda s: (s["ahead"], s["running"], s["five_hour"]))["seat"]


def machine_full() -> bool:
    """The VM is small: past MACHINE_MAX_RUNNING turns, no new task turns start (chat still does)."""
    return active >= MACHINE_MAX_RUNNING


def acquire(seat):
    global active
    active += 1
    if seat in running:
        running[seat] += 1


def release(seat):
    global active
    active = max(0, active - 1)
    if seat in running and running[seat] > 0:
        running[seat] -= 1


def summary() -> str:
    rows = []
    for s in (state(x) for x in POOL):
        flag = f" · ⛔ {s['why']}" if s["why"] and s["why"] != "busy" else ""
        rows.append(f"`{s['seat']}` week {round(s['weekly'] * 100)}% (pace {round(s['pace'] * 100)}%) · "
                    f"5h {round(s['five_hour'] * 100)}% · {s['running']} running{flag}")
    return "\n".join(rows) + ("\n⚠️ every seat is ahead of pace: only urgent work goes out." if throttled() else "")
