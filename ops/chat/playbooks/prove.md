## Playbook: prove the theorem

Stage `prove`. The statement is locked: `Theorems/<Slug>/A.lean` is on main and in `locked.txt`.

1. `git fetch origin && git reset --hard origin/main` on your branch (your A↔B work is already merged).
2. Read your last handoff: don't repeat an approach that already failed.
3. Write `Theorems/<Slug>/Proof.lean`: `theorem TuriMath.<Slug>.main : TuriMath.<Slug>.A.Statement`. Tier 0–1: prove it from more basic lemmas, not by citing Mathlib's copy of the same theorem.
4. Fill `data/tasks/<Slug>.json` from `data/tasks/_template.json` (attempts, Mathlib lemmas used, notes). Add Proof to `Theorems.lean`.
5. `scripts/gate.sh` must pass locally. Push, open the PR: title `<Slug>: proof (#<n>)`, body `Theorem #<n>`, label `review:hilbert`.
6. Stuck after a real attempt: say what you tried in the handoff and end with BLOCKED (or DONE if you pushed partial lemmas). The dispatcher parks the theorem when the budget runs out.
