## Playbook: resolve a merge conflict on your PR

1. `git fetch origin` and merge the base branch into this PR's branch (don't rebase a pushed branch).
2. Resolve each conflict by understanding both sides. If the other side is someone else's work you don't understand, ask them on the PR instead of guessing.
3. Run the full test command locally after resolving, then push.
4. DONE when the PR is conflict-free and tests pass locally.
