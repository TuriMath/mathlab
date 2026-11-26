# Factory chat (TuriMath)

Shared harness copied from TuriChips. Everything factory-specific is in `config.py` (`FACTORY`, `AGENTS`, `STAGES`); env vars are `FACTORY_*`.

A minimal Slack-style app for talking to the agents. The UI is for reading and chatting only. Channels and agents are defined in `config.py`.

- **Direct messages** (Hilbert, Gödel, …): the agent replies inline. The conversation is one Claude session, and a new session starts after 4 hours of silence.
- **Channels** (`#general`, `#standup`, `#reviews`, `#needs-sai`): agents reply inline, like a normal group chat, and each sees what was said since they last spoke. `@name` pulls in one agent, `@all` (or `@everyone`, `@channel`, `@here`, `@team`) pulls in everyone, and with no tag a fast model (Haiku) picks who should answer, defaulting to Hilbert.
- **Threads** happen only when you open one: reply in a thread and the agent you tag (or the last agent who replied there) answers inside it.
- **Sessions:** each agent has one Claude session per DM, per channel and per thread. DM and channel sessions restart after 4 hours of silence.
- **Workspaces:** chat turns run in the agent's home worktree at `~/work/<agent>` on branch `agent/<agent>`. Task turns run in a worktree per task, `~/tasks/<agent>/<repo>-<n>`, from clones in `~/repos/<repo>` (`worktrees.py`); it is removed when the task is done unless it holds unpushed work. Company docs are always read fresh from `origin/main`.
- **Launch spacing:** Claude Code processes start at least 3 seconds apart (`LAUNCH_GAP_SECONDS`), so a burst like `@all` doesn't get flagged as bot traffic by the API's Cloudflare edge. That happened once on 2026-11-13 and blocked every agent for about an hour.
- **Seats** (`seats.py`): seat0-3 are a shared pool (`POOL` in `config.py`), the same four accounts TuriChips uses; seat0 is Sai's own. Any agent runs on any pool seat. Each launch goes to the seat with the most room against its weekly pace. A seat past 92% of its week (`WEEKLY_BUFFER` 8%), past 95% of its 5-hour window, or blocked gets no new launches; at most 2 turns run per seat; a task stays on its seat while that seat is fine. When every seat is more than 10% ahead of pace, only urgent work (CI fixes, conflicts, reviews, chat) goes out. Chat falls back to seat0 (Sai's own, `CLAUDE_CODE_OAUTH_TOKEN`) when the pool is out. seat4 is shared outside the company and runs nothing. Tokens are `CLAUDE_TOKEN_SEAT1..4` in the env file; each run only sees its own seat's token.
- **Models:** picked per task kind (`TASK_KINDS` in `config.py`): Opus 5.5 for formalizing, critiques (Gödel), scouting and planning; Sonnet 5.5 for equivalence and proof attempts, switching to Opus from the second attempt (`RETRY_MODEL`), and for CI fixes, conflicts, reviews and chat. The router uses Haiku.
- **Office:** the 🏢 Office button shows the team as pixel-art characters in an office (`static/office.js`, original art drawn in code). Working agents sit at their desks and type; idle ones wander to the lounge. New messages pop up as speech bubbles, and clicking someone opens their DM.
- **Dispatcher** (`dispatcher.py`, `tasks.py`, `companylog.py`): every 2 minutes it reads open issues and PRs in every repo in the factory org and syncs a task board: own issue → `implement`/`spec`, own PR → `fix-ci`/`conflict`/`pr-followup`, `review:<id>` → `review`/`break`. A task is woken only when its fingerprint (CI, conflicts, comments, reviews, labels, PR head) changes, or 5 minutes after an issue turn ended DONE. Ready tasks go out in priority order, one per agent at a time, each with its playbook (`playbooks/<kind>.md`), a brief from GitHub, its last handoff and its slice of the company log, in its own session. No turn cap: a turn quiet for 20 min gets one warning in `#needs-sai`. Approved + green PRs are merged by the dispatcher (`gh pr merge --merge`). Planning and "why is nobody working?" are the supervisor's job (below). `/status` shows the board and seats, `/api/tasks` returns it as JSON. `SHIFT_ENABLED=0` switches the dispatcher off.
- **Theorem pipeline** (`docs/pipeline.md`): a `Theorem:` issue's `stage:` label picks its agents (`STAGES`). The dispatcher moves formalize → equiv when both `formalized:a|b` labels are on, equiv → prove when the A↔B PR merges, and closes the issue as `verified` when the proof PR merges. Euler's equiv/prove turns count against the issue's budget (`DEFAULT_ATTEMPTS`, or a `budget:<n>` label); out of budget means `parked`, with the last handoff as the reason.
- **Trace index:** every finished turn appends a line to `~/.turimath-traces.jsonl` (`FACTORY_TRACES`): task, agent, kind, stage, attempt, Claude session id, seat, model and result. The session id points at the transcript in `~/.claude/projects/`.
- **Company state / supervisor** (`dispatcher.py`, "Company state"): one state for the whole company, shown in `/status`: `working` (turns running or tasks ready), `throttled` (ready work but no seat may take it; no LLM), `quiet` (nothing running or ready), `waiting_on_sai`, `idle`, `paused`. After 10 min of quiet, one Haiku call (no tools) reads the parked tasks with their last result and handoff, the sai-review PRs, Sai's recent messages and the company log, and answers `work` (wake the tasks that can move), `plan` (queue Hilbert), `waiting_on_sai` (post the asks to `#needs-sai` once) or `nothing`. The last two park the company: no LLM runs until Sai says anything or GitHub wakes a task. Guards: a check that leads nowhere doubles the gap to the next (15 min up to 4 h) and any DONE resets it; the supervisor wakes one task at most twice in a row without a DONE; two planner turns in a row that file nothing stop planning until a DONE.
- **Company log:** the `events` table in the chat DB, append-only: GitHub task changes, chat, turn starts and results, handoffs, merges. The `tasks` table is the board.
- **Scripts:** `python post.py <channel> <author> "text"` posts a message, for example from scheduled standups.

## Run on the VM

TuriMath shares the TuriChips VM as its own unix user, `turimath`. Everything per factory (chat DB, traces, `~/repos`, `~/tasks`, `~/work`) lives in that user's home, so the two factories don't touch each other.

- Config in `/home/turimath/.turimath.env` (never committed, mode 600): `CLAUDE_CODE_OAUTH_TOKEN=…` (operator seat, router), `CLAUDE_TOKEN_SEAT1=…` to `CLAUDE_TOKEN_SEAT4=…` (the same accounts TuriChips uses today), `GH_TOKEN=…`, `MAX_PARALLEL_AGENTS=4`, `FACTORY_MACHINE_MAX_RUNNING=1` (3 after the VM upgrade).
- Toolchain for `turimath`: Claude Code in `~/.local/bin`, `heavy` (from `ops/bin`) in `~/.local/bin`, elan in `~/.elan/bin`, the app's venv in `~/venv`. Git identity `TuriMath Agents <agents@turimath.invalid>`; `gh` is the git credential helper.
- **Mathlib once:** `~/repos/theorems` is primed with `heavy lake exe cache get`. Every task worktree links its `.lake/packages` to that copy (`worktrees.share_lake`), so Mathlib is on disk once, not once per task.
- Install the unit: `sudo cp factory-chat.service /etc/systemd/system/turimath-chat.service`, then `sudo systemctl enable --now turimath-chat`. Logs: `journalctl -u turimath-chat -f`
- The app listens on `127.0.0.1:8601` only (TuriChips has 8600). Two ways in:
  - Tailscale (web and phone): TuriMath has its own tailnet machine, **`turimath`**, a second, userspace Tailscale node on the VM (`ops/tailscaled-turimath.service`; TuriChips keeps the system node). It serves the chat at `https://turimath.<tailnet>.ts.net`:
    `sudo tailscale --socket=/run/tailscale-turimath/tailscaled.sock serve --bg 8601`. The Android app in `ops/mobile` opens this URL.
  - SSH tunnel: `ssh -N -L 8601:localhost:8601 <vm>`, then http://localhost:8601

## Posting rules for task turns

- `#work` gets a line only when a turn ends `DONE:` (finished work). `IDLE`, plain `BLOCKED:` and replies with no status line post nothing.
- `#needs-sai` gets `BLOCKED-SAI:` lines (sai-review PRs, decisions, access), once per blocker per agent: the same text again is dropped. A crashed turn also lands here.
- Once a day, at the first poll after `sai_digest_hour_ist` (10:00 IST), the scheduler lists open `sai-review` PRs across the org in `#needs-sai`.
- A status/progress question with no tag wakes only Hilbert, who gets the live `/status` table in the prompt.

## Usage tab

- **📊 Usage** (under Office) shows each Claude Team seat: 5-hour and weekly utilization with reset times (IST), its agents, and today's turns/tokens/cost.
- Source: the seat tokens can't read Anthropic's usage API (setup-token has no `user:profile` scope), so `runner.py` runs Claude Code with `--output-format stream-json` and `usage.py` keeps the last `rate_limit_event` per seat plus daily totals from each run's result.
- A seat with no run for 30 min gets a tiny Haiku probe (`USAGE_PROBES=0` turns probes off).
- A seat at 90% or blocked in either window posts once per reset period to `#needs-sai`.
