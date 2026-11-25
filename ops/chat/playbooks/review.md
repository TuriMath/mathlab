## Playbook: review a PR

You review; you don't fix. Your working copy is detached at the PR head and pushing is turned off.

1. Read the diff in the brief against the spec (docs/spec.md of that chip). Check the PR does what its issue asked, stays in its owner's folders, and comes with evidence (test logs).
2. Build and run the tests locally in your working copy. Don't trust the PR text's claims without running them.
3. Leave one review comment with `gh pr review <n> -R <repo> --comment -b "..."`: what you checked, what you ran, and each problem with file:line.
4. Approve: add the label `approved` and remove `review:<you>`. Changes needed: remove `review:<you>` and say what must change. A PR that changes the spec or changes/deletes an existing test also gets `sai-review`.
5. DONE: approved or changes requested, with the PR ref.
