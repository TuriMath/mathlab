## Playbook: review a PR

You review; you don't fix. Your working copy is detached at the PR head and pushing is turned off. Lean does the real judging; you check everything around it.

1. Read the diff in the brief. Check the PR does what its issue asked and touches only its owner's paths (`agents/_rules.md`, "Who owns what").
2. No locked file changed (`A.lean`, `B.lean`, `Equiv.lean` of a locked theorem, existing `locked.txt` lines).
3. CI gate green. Don't trust the PR text: read the gate run.
4. For proof PRs: `data/tasks/<Slug>.json` is filled in honestly (attempts, lemmas used), and the proof doesn't just cite Mathlib's copy in Tier 0–1.
5. Approve: `gh pr review --comment`, label `approved`, remove `review:<you>`. Changes needed: remove `review:<you>` and say what must change.
6. DONE: approved or changes requested, with the PR ref.
