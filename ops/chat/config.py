"""Factory layout. Everything specific to this factory lives here; the rest of ops/chat is the shared harness
(copied from TuriChips). Channels are added here in code, not from the UI."""
import os

# ---------- Factory identity ----------
WORKSPACE = "TuriMath"
FACTORY = {
    "slug": "turimath",                  # unix user, env file, DB and lock names
    "org": "TuriMath",                   # every repo in this org is scanned for issues and PRs
    "company_repo": "mathlab",           # company docs, agents/, ops/ (this repo)
    "work_repo": "theorems",             # the Lean project the theorem pipeline works in
    "about": "a maths lab where AI agents turn classic theorems into machine-checked Lean 4 proofs",
}
MANAGER = {"id": "sai", "name": "Sai", "role": "Operator (direction only)", "color": "#1d9bd1"}


def env(name: str, default: str = "") -> str:
    """FACTORY_<NAME> from the environment ("" or default when unset)."""
    return os.environ.get(f"FACTORY_{name}", default)


# Shared channels. Agents reply inline, like a group chat; in a thread only when Sai replies in one.
# @name pulls in one agent, @all (or @everyone/@channel/@here/@team) pulls in everyone,
# and with no tag a fast model picks who should answer (ROUTER_DEFAULT if unsure).
CHANNELS = [
    {"id": "general", "topic": "Company-wide. Tag @name or @all, or just talk and the right people answer."},
    {"id": "standup", "topic": "Standups: Verified / In progress / Parked."},
    {"id": "reviews", "topic": "Weekly digest: theorems verified and parked, gate rate, planted-error result, seats."},
    {"id": "work", "topic": "Shift log: one line per finished piece of work. /status, /pause, /resume work in any channel."},
    {"id": "needs-sai", "topic": "Direction decisions and access only. Sai is never asked whether maths is correct."},
]

# Dispatcher (dispatcher.py): GitHub becomes tasks on a board; each ready task goes to its owner's persona,
# with a model picked by task kind and a seat picked by headroom.
DISPATCH = {
    "enabled": os.environ.get("SHIFT_ENABLED", "1") == "1",   # SHIFT_ENABLED=0 turns the dispatcher off
    "org": FACTORY["org"],
    "poll_seconds": 120,             # how often GitHub is read; any change dispatches at once
    "tick_seconds": 5 * 60,          # dispatch at least this often even when nothing changed
    "continue_gap_seconds": 5 * 60,  # an issue task that ended DONE continues after this
    "planner_gap_seconds": 60 * 60,  # the planner (Hilbert) runs at most this often
    # Supervisor (dispatcher.py, "Company state"): when nothing is running or ready, one Haiku call decides
    # whether work can move, the queue needs planning, or everything is waiting on Sai.
    "quiet_grace_seconds": 10 * 60,  # nothing running or ready for this long: the team is quiet, check why
    "check_min_seconds": 15 * 60,    # gap after a check that led nowhere; doubles each time...
    "check_max_seconds": 4 * 3600,   # ...up to this. Any DONE resets it.
    "max_nudges": 2,                 # the supervisor may wake one task this often in a row without a DONE
    "planner_idle_limit": 2,         # planner turns in a row that filed nothing: stop planning, tell Sai
    "stall_seconds": 20 * 60,        # no output from a running turn for this long: warn in #needs-sai (never kill)
    "task_timeout_seconds": 6 * 3600,  # safety net only; long-horizon turns are the point
    "sai_digest_hour_ist": 10,       # daily list of open sai-review PRs in #needs-sai (should stay empty here)
}

# ---------- Theorem pipeline (see docs/pipeline.md) ----------
# A theorem is one issue in the work repo, titled "Theorem: <name>". Its `stage:<s>` label says who works on it.
# Each stage lists (agent, task kind). Several agents on one stage get one task each (the blind formalizer pair).
STAGES = {
    "formalize": [("noether", "formalize"), ("gauss", "formalize")],
    "equiv":     [("euler", "equiv")],
    "critique":  [("godel", "critique")],
    "prove":     [("euler", "prove")],
}
PARKED_LABEL = "parked"               # an issue with this label gets no tasks; the reason is in its last comment
DEFAULT_ATTEMPTS = {"equiv": 4, "prove": 6}   # turns per stage before the dispatcher parks it; `budget:<n>` overrides
BLIND_PAIR = ("noether", "gauss")     # formalizers: each is told never to read the other's branch

# Seats: a shared pool, not one seat per agent. Any persona runs on any pool seat; the budget watcher
# (seats.py) picks the seat with the most room against its weekly pace and keeps a buffer on every seat.
# Four seats, shared with TuriChips (same accounts): seat0 is Sai's own (CLAUDE_CODE_OAUTH_TOKEN), seat1-3 the team's.
POOL = [s for s in (env("POOL") or "seat0,seat1,seat2,seat3").split(",") if s]
WEEKLY_BUFFER = 0.08                 # never plan to use the last 8% of a seat's week
FIVE_HOUR_CEILING = 0.95             # no new launches on a seat past this in its 5-hour window
SEAT_MAX_RUNNING = 2                 # turns at once per seat (task + chat)
MACHINE_MAX_RUNNING = int(env("MACHINE_MAX_RUNNING", "3"))   # turns at once on the whole VM; Lean builds are
                                     # memory-heavy (Mathlib), so keep this low on small machines
AHEAD_OF_PACE = 0.10                 # every seat this far ahead of weekly pace: only urgent work goes out
CHAT_FALLBACK_SEAT = "seat0"         # chat with Sai still works when the whole pool is out (past the buffer)

# Models are picked per task kind, not per agent.
MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5"}
TASK_KINDS = {   # priority: lower goes first. urgent: still dispatched when every seat is ahead of pace.
    "fix-ci":      {"priority": 1, "model": "sonnet", "urgent": True,  "label": "Fix failing CI"},
    "conflict":    {"priority": 2, "model": "sonnet", "urgent": True,  "label": "Resolve merge conflict"},
    "review":      {"priority": 3, "model": "sonnet", "urgent": True,  "label": "Review PR"},
    "critique":    {"priority": 3, "model": "opus",   "urgent": True,  "label": "Critique statement"},
    "pr-followup": {"priority": 4, "model": "sonnet", "urgent": False, "label": "Follow up on your PR"},
    "formalize":   {"priority": 5, "model": "opus",   "urgent": False, "label": "Formalize statement"},
    "equiv":       {"priority": 5, "model": "sonnet", "urgent": False, "label": "Prove A ↔ B"},
    "prove":       {"priority": 5, "model": "sonnet", "urgent": False, "label": "Prove theorem"},
    "implement":   {"priority": 6, "model": "sonnet", "urgent": False, "label": "Work on issue"},
    "scout":       {"priority": 6, "model": "opus",   "urgent": False, "label": "Scout work"},
    "plan":        {"priority": 7, "model": "opus",   "urgent": False, "label": "Plan the queue"},
    "chat":        {"priority": 0, "model": "sonnet", "urgent": True,  "label": "Chat"},
}
RETRY_MODEL = {"equiv": "opus", "prove": "opus"}   # from the second attempt on, these kinds run on this model
REVIEW_KIND = {"godel": "critique"}  # reviewer -> kind (Gödel's reviews are statement critiques, on Opus)
ISSUE_KIND = {"hilbert": "scout"}    # owner -> kind for plain issues they own (not theorem issues)
PLANNER = "hilbert"

# Posts from the scheduler itself (command replies) use this author.
SYSTEM = {"id": "shift", "name": "Shift", "role": "Scheduler", "color": "#475569"}

# Seats outside the pool that the Usage tab still tracks, with the label shown in place of agent names.
USAGE_ONLY_SEATS = {"seat4": "shared outside the company, no agents"}

# The personas. Every agent also gets a direct-message channel: dm-<id>.
# Seat tokens are CLAUDE_TOKEN_<SEAT> in the env file (a seat without one falls back to CLAUDE_CODE_OAUTH_TOKEN).
AGENTS = {
    "hilbert": {"name": "Hilbert", "file": "scout",        "role": "Scout and planner",        "color": "#7c3aed"},
    "noether": {"name": "Noether", "file": "formalizer-a", "role": "Formalizer A",             "color": "#2563eb"},
    "gauss":   {"name": "Gauss",   "file": "formalizer-b", "role": "Formalizer B",             "color": "#0891b2"},
    "euler":   {"name": "Euler",   "file": "prover",       "role": "Prover",                   "color": "#059669"},
    "godel":   {"name": "Gödel",   "file": "critic",       "role": "Critic (breaker)",         "color": "#dc2626"},
}

ROUTER_DEFAULT = "hilbert"

# A DM or channel conversation starts a fresh Claude session after this much silence.
DM_IDLE_RESET_SECONDS = 4 * 3600
