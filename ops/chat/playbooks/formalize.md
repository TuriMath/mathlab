## Playbook: formalize a statement

You are one half of the blind pair. Your working copy is on `<you>/theorems-<n>`.

1. Read the issue body in the brief: the source quote, slug and tier. If the issue came back with a discrepancy note, read it too, but fix against the **source quote**.
2. Do **not** look at the other formalizer's branch, files, or any comment that describes their statement (rule 4). Don't `git log --all`, `git branch -r` or `gh` your way to it.
3. `lake exe cache get` (once per working copy), then write your file per your role (`A.lean` or `B.lean`): `def Statement : Prop`, the line-by-line mapping comment, the sanity section.
4. `lake env lean Theorems/<Slug>/<A|B>.lean` until it builds with no `sorry`.
5. Commit, `git push -u origin HEAD`, then `gh issue edit <n> -R TuriMath/theorems --add-label formalized:<a|b>`.
6. DONE: `<Slug> statement <A|B> pushed (#<n>)`. If the source quote is too ambiguous to formalize, comment on the issue for Hilbert and say BLOCKED.
