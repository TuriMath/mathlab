## Playbook: plan the queue

You were woken because the team is quiet and the supervisor found nothing on the board that can move. You are the only planner; this runs at most hourly, and after two plan turns in a row that file nothing, the dispatcher stops asking and tells Sai.

1. Read the board, `vision.md` (the ladder and the current phase) and the open/parked/verified theorem issues in `TuriMath/theorems`, plus any open `Hilbert:` issue from Sai (e.g. the calibration queue).
2. If fewer than 2 theorems are in flight (not parked, not verified), open the next ones from the current tier: issue `Theorem: <name>` from `docs/theorem-issue.md`, labels `theorem`, `tier:<n>`, `stage:formalize`. Search Mathlib first and record what exists.
3. If the current phase's gate has passed, don't start the next tier on your own: post the direction question (`BLOCKED-SAI`) with 2–3 options and your pick. Before calling it waiting on Sai, look for real work that doesn't depend on the decision (gate scripts, metadata, write-ups of verified theorems).
4. Non-theorem work (CI, scripts, docs) goes as an issue titled `<Name>: <task>` for the right agent.
5. Don't refile what's open, and don't create busywork. DONE with the issues you opened, or IDLE.
