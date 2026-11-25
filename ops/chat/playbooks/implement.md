## Playbook: work on your issue

This task keeps its own session and working copy until the issue closes, so take it as far as you can now.

1. Read the issue and its comments. If what "done" means is unclear, ask the issue's author on the issue and say BLOCKED.
2. Work on this task's branch: code, tests from the spec (not your own tests of your own code: rule 3), commits.
3. When it's ready, push and open a PR with `gh pr create`, body `Closes #<n>`, and add `review:<id>` for the right reviewer (rules, "Task turns").
4. DONE with refs when you've pushed something real. The dispatcher brings you back to continue until the issue is closed; when you're only waiting on review, say IDLE.
