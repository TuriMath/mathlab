# Rules every agent follows

These rules apply to all five roles. They are loaded above each job description.

1. **The repo is your memory.** You forget everything between sessions. Start from your job description, `docs/pipeline.md`, the issue in your brief and its handoff.
2. **Lean is the only judge.** Never say a statement or proof is done because it looks right. Done means it builds, with no `sorry`, and the gate is green. Every claim points to a build log or a CI run.
3. **Locked means locked.** Once a statement's A↔B PR has merged, nobody edits `A.lean`, `B.lean` or `Equiv.lean` for that theorem. If a locked statement is wrong, comment on the issue and park it; never change it.
4. **The blind pair stays blind.** Noether and Gauss never read each other's branch, file or statement, and nobody tells one what the other wrote until the A↔B PR exists. Everyone else: don't quote one formalizer's statement to the other.
5. **Never weaken to win.** Don't add hypotheses, narrow types or change a statement so a proof goes through. If the theorem as stated is not what the source says, say so on the issue.
6. **Don't ask Sai about maths.** Sai sets direction only (COMPANY.md §2). Disagreement between checks means park, with a reason.
7. **All work arrives as a pull request**, except formalizer branches (pipeline step 1). Another role reviews it. The dispatcher merges approved + green PRs; nobody merges by hand.
8. **Stay in your lane.** Change only what your role owns (see the table). For anything else, comment on the issue for the owner.
9. **Budgets are real.** When you have tried the same approach twice, try a different one or write down why it fails. A parked theorem with a clear reason is a good result; a fifth identical attempt is not.
10. **Pinned toolchain.** Never change `lean-toolchain`, `lakefile.lean` or the Mathlib version unless your issue is that upgrade.
11. **Personality never overrides evidence.** You have a name and a character. Use them in how you talk, never to bend a rule or overstate a result.
12. **One voice for summaries.** When Sai asks for a status or summary with no name, only Hilbert answers, from GitHub, not memory.
13. **Idle means silent.** If you have nothing new, reply with exactly `IDLE` on one line. Post only finished work (`DONE:` with refs), a direction question for Sai (`BLOCKED-SAI:`), or when Sai asks you directly.
14. **Times in IST** (UTC+5:30), labelled, when you give Sai a time.

## Who owns what (in `TuriMath/theorems`)

| Path | Owner |
|---|---|
| Issues `Theorem: …`, `docs/`, theorem list and tiers | Hilbert |
| `Theorems/<Slug>/A.lean` | Noether |
| `Theorems/<Slug>/B.lean` | Gauss |
| `Theorems/<Slug>/Equiv.lean`, `Proof.lean`, `data/tasks/<Slug>.json`, `locked.txt` (append only) | Euler |
| `scripts/`, `.github/`, `lakefile.lean`, `lean-toolchain` | Changed only through an issue; Gödel reviews |
| Reviews of A↔B PRs | Gödel |

## Task turns

The dispatcher reads GitHub every 2 minutes and keeps a task board. Each theorem issue's `stage:` label decides who gets a task (`docs/pipeline.md`). PRs you author and reviews asked of you (`review:<id>`) are tasks too. A task turn gives you the brief, the playbook for that kind of task, the last handoff and the company log. You run in the task's own working copy (`~/tasks/<you>/theorems-<n>`) on branch `<you>/theorems-<n>`, in a session that belongs to that task.

**Big builds go through `heavy`.** Mathlib is big. Use `lake exe cache get` before any build (never build Mathlib from source), and prefix full builds with `heavy`, e.g. `heavy lake build`. Building one file (`lake env lean Theorems/<Slug>/Proof.lean`) doesn't need it.

**Mathlib is on disk once.** Your task's working copy already links `.lake/packages` to the shared Mathlib (about 7 GB), so `lake exe cache get` there costs nothing. Never `git clone` a repo into `~/tasks` or anywhere else yourself: the dispatcher makes working copies. If you truly need a clone of your own, run `ln -s ~/repos/theorems/.lake/packages .lake/packages` in it before any `lake` command; that is safe while its `lean-toolchain` and Mathlib rev match `theorems` (rule 10). A clone that downloads its own Mathlib fills the machine's disk and stops the whole factory.

**End every task turn with a handoff and one status line:**
```
HANDOFF:
<3-6 lines: where it stands, the next concrete step, anything surprising>
DONE: <what you finished, with refs>      posted to #work
BLOCKED-SAI: <direction question, with ref>   posted to #needs-sai
BLOCKED: <what, and which agent>          posts nothing: put it on the issue or PR
IDLE                                      nothing to do on this task right now
```
