# The theorem pipeline

How one theorem goes from a line on a list to a verified Lean proof. The dispatcher (`ops/chat/dispatcher.py`, `tasks.py`) reads this state from GitHub labels; agents move it forward with PRs and labels. No step asks Sai whether the maths is right.

## Where things live

Everything happens in **`TuriMath/theorems`**, a Lean 4 + Mathlib project. One folder per theorem, named by its **slug** (CamelCase, e.g. `WilsonTheorem`):

```
Theorems/<Slug>/A.lean       Noether's statement      namespace TuriMath.<Slug>.A   def Statement : Prop
Theorems/<Slug>/B.lean       Gauss's statement        namespace TuriMath.<Slug>.B   def Statement : Prop
Theorems/<Slug>/Equiv.lean   Euler: A ↔ B             theorem TuriMath.<Slug>.equiv : A.Statement ↔ B.Statement
Theorems/<Slug>/Proof.lean   Euler: the proof         theorem TuriMath.<Slug>.main : A.Statement
data/tasks/<Slug>.json       metadata for the RL environment and trace labels
locked.txt                   sha256 of every locked statement file
```

**The locked statement is `A.lean`** once its Equiv has merged. `B.lean` and `Equiv.lean` stay as evidence.

Each `A.lean` / `B.lean` also contains a **sanity section**: for every hypothesis of the statement, a proved `example` showing the hypotheses can all hold at once (so the statement is not vacuously true). A statement with no hypotheses needs none.

## The issue

Each theorem is one issue in `TuriMath/theorems`, opened by Hilbert, titled `Theorem: <name>`. The body follows `docs/theorem-issue.md`: source statement quoted exactly with its reference, slug, tier, what Mathlib already has, and the attempt budget.

Labels on the issue:

| Label | Meaning |
|---|---|
| `theorem`, `tier:<n>` | It's a theorem issue, and which tier |
| `stage:formalize` / `stage:equiv` / `stage:prove` | Where it is. Exactly one. |
| `formalized:a`, `formalized:b` | Noether / Gauss have pushed their statement |
| `budget:<n>` | Attempts per stage, overriding the default (equiv 4, prove 6) |
| `parked` | Stopped. The reason is the last comment. No tasks run on it. |
| `verified` | Done: the proof merged with the gate green. The issue is closed. |

## The stages

```
Hilbert opens issue ──► stage:formalize ──► stage:equiv ──► Gödel critique ──► stage:prove ──► verified
                         Noether ┐ blind      Euler           (review on        Euler
                         Gauss   ┘            A ↔ B PR         the A↔B PR)       Proof PR
```

1. **formalize.** Noether and Gauss each get a task. Each writes its statement on its own branch (`noether/theorems-<n>`, `gauss/theorems-<n>`), pushes, and adds `formalized:a` or `formalized:b` to the issue. **No PR**, and **never read the other formalizer's branch, files or comments about their statement.** When both labels are on, the dispatcher moves the issue to `stage:equiv` by itself.
2. **equiv.** Euler merges both branches into `euler/theorems-<n>`, proves `A.Statement ↔ B.Statement` in `Equiv.lean`, adds the hashes of A, B and Equiv to `locked.txt`, and opens one PR with `review:godel`.
   - If they are **not** equivalent (Euler finds a counterexample or a missing hypothesis), Euler comments on the issue explaining the difference, removes both `formalized:*` labels and sets `stage:formalize` again. That is one round; rounds count against the budget.
3. **critique.** Gödel reviews the A↔B PR (see `ops/chat/playbooks/critique.md`): back-translation by a subagent that never sees the source, the red-flag report, the sanity section, and a check that A and B were not copied from each other. Pass → `approved`. Fail → close the PR, comment on the issue with the reason and set `stage:formalize` again.
   When the A↔B PR merges (approved + CI green), **the dispatcher moves the issue to `stage:prove`**. From then on `A.lean` is locked: CI fails any change to it.
4. **prove.** Euler proves `main : A.Statement` in `Proof.lean`, fills `data/tasks/<Slug>.json`, and opens a PR with `review:hilbert` (a light check: files, metadata, no stray changes; Lean does the real judging). When it merges, **the dispatcher adds `verified` and closes the issue.**

**The equivalence must match, not prove.** Any two *true* statements are equivalent, so an `Equiv.lean` that proves A and B separately (e.g. by citing Mathlib's copy of the theorem) checks nothing. Each direction has to take the other side as its hypothesis and use it. Lean can't enforce this; Gödel checks it in every critique. This is the pipeline's known weak point, and the monthly planted-error test is what measures it.

**Attempt budgets.** The dispatcher counts Euler's turns in `equiv` and in `prove`. When a stage uses up its budget without moving on, the dispatcher adds `parked` and comments with the last handoff. Parked theorems are published too.

## The CI gate (`scripts/gate.sh` in `theorems`)

A PR is green only if all of these pass:

1. `lake build` succeeds.
2. No `sorry`, `admit` or `axiom` declarations in `Theorems/`.
3. `#print axioms` for every `main` and every `equiv` shows only `propext`, `Classical.choice`, `Quot.sound`.
4. Every `Proof.lean` proves exactly `A.Statement` (CI type-checks `example : A.Statement := main`).
5. Every file in `locked.txt` matches its hash, and no line was removed or changed (lines are only added).
6. Every `data/tasks/*.json` has the required fields.

It also prints a **red-flag report** (not a failure): statements that `decide`, `simp`, `norm_num` or `trivial` closes outright are probably weakened. Gödel reads it.

## What Sai sees

- `#work`: one line per finished step (statement pushed, A↔B merged, verified).
- `#needs-sai`: only direction choices (next tier, textbook, stretch work) and access problems.
- `#reviews`: the weekly digest.
