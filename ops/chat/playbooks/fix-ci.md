## Playbook: fix failing CI on your PR

1. Read the failing log in the brief first. Reproduce the failure locally in your working copy with the same command CI runs.
2. Find the cause, not the symptom. If the failure is in code you don't own, file an issue for its owner and say BLOCKED.
3. Never change or delete an existing test to make it pass (rule 4). If you believe the test is wrong, file an issue for its owner.
4. Fix, run the full test command locally, commit, push to this PR's branch.
5. DONE only when you pushed a fix you saw pass locally. Say which test was failing and why.
