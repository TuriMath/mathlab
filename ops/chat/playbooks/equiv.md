## Playbook: prove the two statements equivalent

Stage `equiv`. Both formalizers have pushed. You are on `euler/theorems-<n>`.

1. `git fetch origin` and merge `origin/noether/theorems-<n>` and `origin/gauss/theorems-<n>` into your branch. Don't edit `A.lean` or `B.lean`.
2. **Match, don't prove.** Each direction of the ↔ must take the other statement as hypothesis `h` and genuinely use it. Never prove A or B on its own inside Equiv (no Mathlib copy of the theorem): two true statements are always equivalent, so that would check nothing.
3. `lake exe cache get`, then write `Theorems/<Slug>/Equiv.lean` proving `TuriMath.<Slug>.equiv : A.Statement ↔ B.Statement`. Add both files and Equiv to `Theorems.lean` imports.
4. If you find they differ: build the smallest counterexample in a scratch file, then comment on the issue saying which source words each version reads differently (don't paste either statement), `gh issue edit <n> -R TuriMath/theorems --remove-label formalized:a,formalized:b,stage:equiv --add-label stage:formalize`, and say DONE with "statements differ".
5. If they agree: append `sha256sum Theorems/<Slug>/{A,B,Equiv}.lean` to `locked.txt`, run `scripts/gate.sh`, push, and open the PR: title `<Slug>: statements A, B and equivalence (#<n>)`, body `Theorem #<n>`, label `review:godel`.
6. Handoff: what worked, what didn't, which Mathlib lemmas mattered. Every turn here counts against the budget.
