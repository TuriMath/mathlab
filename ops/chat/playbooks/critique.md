## Playbook: critique an A↔B PR

You review; you don't fix. Your working copy is detached at the PR head; pushing is off.

1. **Back-translate first, blind.** Before reading the issue or the source quote, launch a fresh subagent (Agent tool) with only the text of `Theorems/<Slug>/A.lean` and the instruction: "State in plain English exactly what `Statement` asserts. Be literal about quantifiers, domains and edge cases." Do the same for `B.lean` in a second subagent.
2. Now read the source quote in the issue. Compare it with each back-translation, part by part: what is quantified, over which type, which hypotheses, edge cases (0, 1, empty, negatives), strict vs non-strict, the conclusion.
3. Read the red-flag report in CI (`gh run view --log` on the PR's gate run). A statement closed by `simp`/`decide`/`trivial` fails unless the source really is that trivial.
4. Check the sanity sections prove the hypotheses can hold together, and that `A.lean` and `B.lean` look independently written.
5. Build it yourself: `lake exe cache get && lake build Theorems.<Slug>.Equiv`.
6. **Pass:** `gh pr review <pr> -R TuriMath/theorems --comment -b "..."` listing each check and its result, then add `approved`, remove `review:godel`.
   **Fail:** review comment with the exact source words and the exact Lean that disagree; `gh pr close <pr>`; on the issue: comment the reason (without pasting one formalizer's statement for the other to copy), remove `formalized:a,formalized:b,stage:equiv`, add `stage:formalize`.
7. DONE: `<Slug> statement approved` or `<Slug> statement rejected: <reason>`, with refs.
