"""Rules: GitHub -> tasks on the board. No LLM here.

Every poll reads the open issues and PRs of every repo in the factory org and turns them into tasks:
- own PR, CI red          -> fix-ci        (author)
- own PR, merge conflict  -> conflict      (author)
- own PR, anything else   -> pr-followup   (author; only woken when comments/labels/CI change)
- `review:<id>` label     -> review / break (reviewer; Beru's reviews are `break`, on Opus)
- owned open issue        -> implement / spec (owner; Igris's issues are `spec`, on Opus)
- approved + green + no sai-review -> merged by the dispatcher itself (`gh pr merge --merge`), no LLM.
- theorem issue ("Theorem: ...")   -> one task per agent in STAGES[<its stage:* label>] (docs/pipeline.md);
  formalizers drop out once their `formalized:a|b` label is on; `parked`/`verified` issues get no tasks.
  When both formalized labels are on, the snapshot asks the dispatcher to move it to stage:equiv.

Each task has a fingerprint of what should wake it. A waiting task only becomes ready when its fingerprint
moves past done_fp (the fingerprint the first poll after its last turn saw, so the agent's own comments and
pushes don't wake it again). A task whose item disappears (closed, merged, label removed) is done.

Ownership on GitHub (all agents share one GitHub account, so names live in titles, branches and labels):
- issue owner: title starts with "<Name>:" or label "agent:<id>"
- PR author: head branch "agent/<id>" or "<id>/..."
- PR reviewer: label "review:<id>"
"""
import json
import re
import subprocess

import companylog as log
from config import AGENTS, BLIND_PAIR, DEFAULT_ATTEMPTS, DISPATCH, FACTORY, ISSUE_KIND, PARKED_LABEL, REVIEW_KIND, STAGES, TASK_KINDS

ORG = DISPATCH["org"]
NAME_TO_ID = {v["name"].lower(): k for k, v in AGENTS.items()}
IGNORED_LABELS = {"approved"}             # labels that change nothing for the PR's author


def gh(*args, json_out=True, timeout=60):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        return None
    if not json_out:
        return r.stdout
    try:
        return json.loads(r.stdout or "null")
    except json.JSONDecodeError:
        return None


def owner_of_issue(issue) -> str | None:
    for lb in issue.get("labels", []):
        m = re.fullmatch(r"agent:(\w+)", lb["name"])
        if m and m.group(1) in AGENTS:
            return m.group(1)
    m = re.match(r"\s*(\w+)\s*:", issue["title"])
    return NAME_TO_ID.get(m.group(1).lower()) if m else None


THEOREM_TITLE = re.compile(r"\s*theorem\s*:", re.I)
FORMALIZED = {BLIND_PAIR[0]: "formalized:a", BLIND_PAIR[1]: "formalized:b"}


def stage_of(labels) -> str | None:
    found = [lb[len("stage:"):] for lb in labels if lb.startswith("stage:")]
    return found[0] if len(found) == 1 else None


def budget_of(labels, kind) -> int:
    for lb in labels:
        m = re.fullmatch(r"budget:(\d+)", lb)
        if m:
            return int(m.group(1))
    return DEFAULT_ATTEMPTS.get(kind, 0)


def theorem_tasks(full: str, issue: dict, found: dict, advance: list):
    """Tasks for one theorem issue, from its stage label (docs/pipeline.md)."""
    labels = sorted(lb["name"] for lb in issue.get("labels", []))
    if PARKED_LABEL in labels or "verified" in labels:
        return
    stage = stage_of(labels)
    if stage == "formalize" and all(FORMALIZED[a] in labels for a in BLIND_PAIR):
        advance.append({"repo": full, "number": issue["number"], "from": "formalize", "to": "equiv",
                        "title": issue["title"]})
        return
    ref = f"{full}#{issue['number']}"
    for agent, kind in STAGES.get(stage or "", []):
        if kind == "formalize" and FORMALIZED.get(agent) in labels:
            continue                     # this formalizer is done for this round
        found[f"{agent}:issue:{ref}"] = dict(
            owner=agent, role="issue", kind=kind, repo=full, ref=ref, number=issue["number"], title=issue["title"],
            fp=json.dumps([len(issue.get("comments") or []), labels, issue["title"]]),
            info={"theorem": True, "stage": stage, "budget": budget_of(labels, kind)})


def set_stage(repo: str, number: int, old: str | None, new: str) -> bool:
    args = ["issue", "edit", str(number), "-R", repo, "--add-label", f"stage:{new}"]
    if old:
        args += ["--remove-label", f"stage:{old}"]
    return gh(*args, json_out=False) is not None


def issue_labels(repo: str, number: int) -> list[str]:
    i = gh("issue", "view", str(number), "-R", repo, "--json", "labels") or {}
    return [lb["name"] for lb in i.get("labels", [])]


def park(repo: str, number: int, reason: str) -> bool:
    gh("issue", "comment", str(number), "-R", repo, "-b", f"⏸ **Parked by the dispatcher.** {reason}", json_out=False)
    return gh("issue", "edit", str(number), "-R", repo, "--add-label", PARKED_LABEL, json_out=False) is not None


def verify(repo: str, number: int, pr_ref: str) -> bool:
    gh("issue", "edit", str(number), "-R", repo, "--add-label", "verified", "--remove-label", "stage:prove",
       json_out=False)
    return gh("issue", "close", str(number), "-R", repo, "-c",
              f"✅ **Verified.** {pr_ref} merged with the gate green: Lean accepts the proof of the locked statement.",
              json_out=False) is not None


def theorem_of_branch(repo_full: str, branch: str) -> int | None:
    """The theorem issue a prover branch belongs to: `<agent>/<repo>-<n>` in the work repo."""
    name = repo_full.split("/")[1]
    m = re.fullmatch(rf"\w+/{re.escape(name)}-(\d+)", branch or "")
    return int(m.group(1)) if m and name == FACTORY["work_repo"] else None


def author_of_pr(pr) -> str | None:
    m = re.match(r"(?:agent/)?(\w+)(?:/|$)", pr["headRefName"])
    return m.group(1) if m and m.group(1) in AGENTS else None


# CI comes from GitHub Actions runs, not statusCheckRollup: the org's fine-grained token can't read commit
# statuses/check runs, and asking for statusCheckRollup fails the whole PR query.
FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}


def runs_by_sha(repo) -> dict[str, list[dict]] | None:
    runs = gh("run", "list", "-R", repo, "--limit", "200",
              "--json", "headSha,status,conclusion,databaseId,workflowName,createdAt")
    if runs is None:
        return None
    out: dict[str, dict[str, dict]] = {}
    for r in sorted(runs, key=lambda r: r.get("createdAt") or ""):   # newest run per workflow wins
        out.setdefault(r["headSha"], {})[r.get("workflowName") or ""] = r
    return {sha: list(w.values()) for sha, w in out.items()}


def ci_state(runs: list[dict] | None) -> str:
    if not runs:
        return "none"
    if any(r.get("status") != "completed" for r in runs):
        return "running"
    if any((r.get("conclusion") or "") in FAILED for r in runs):
        return "failing"
    return "green"


# ---------- Snapshot ----------
def snapshot() -> dict | None:
    """{"tasks": {key: fields}, "merge": [prs], "sai_review": [prs], "advance": [stage moves]} or None if GitHub
    couldn't be read."""
    repos = gh("repo", "list", ORG, "--no-archived", "--json", "name", "--limit", "100")
    if repos is None:
        return None
    found, merge, waiting, advance = {}, [], [], []
    for repo in repos:
        full = f"{ORG}/{repo['name']}"
        issues = gh("issue", "list", "-R", full, "--state", "open", "--limit", "100",
                    "--json", "number,title,labels,comments")
        prs = gh("pr", "list", "-R", full, "--state", "open", "--limit", "100", "--json",
                 "number,title,headRefName,headRefOid,labels,mergeable,comments,reviews")
        runs = runs_by_sha(full) if prs else {}
        if issues is None or prs is None or runs is None:
            return None                  # a partial read would close tasks that still exist
        for i in issues:
            if THEOREM_TITLE.match(i["title"]):
                theorem_tasks(full, i, found, advance)
                continue
            owner = owner_of_issue(i)
            if not owner:
                continue
            ref = f"{full}#{i['number']}"
            labels = sorted(lb["name"] for lb in i.get("labels", []))
            kind = ISSUE_KIND.get(owner, "implement")
            found[f"{owner}:issue:{ref}"] = dict(
                owner=owner, role="issue", kind=kind, repo=full, ref=ref, number=i["number"], title=i["title"],
                fp=json.dumps([len(i.get("comments") or []), labels, i["title"]]), info={})
        for p in prs:
            labels = {lb["name"] for lb in p.get("labels", [])}
            pr_runs = runs.get(p.get("headRefOid"), [])
            ci, ref = ci_state(pr_runs), f"{full}#{p['number']}"
            conflict = p.get("mergeable") == "CONFLICTING"
            ncom, nrev = len(p.get("comments") or []), len(p.get("reviews") or [])
            info = {"branch": p["headRefName"], "ci": ci, "conflict": conflict,
                    "failed_runs": [r["databaseId"] for r in pr_runs if (r.get("conclusion") or "") in FAILED]}
            author = author_of_pr(p)
            if author:
                kind = "fix-ci" if ci == "failing" else "conflict" if conflict else "pr-followup"
                found[f"{author}:pr:{ref}"] = dict(
                    owner=author, role="pr", kind=kind, repo=full, ref=ref, number=p["number"], title=p["title"],
                    fp=json.dumps([ci, conflict, ncom, nrev, sorted(labels - IGNORED_LABELS
                                                                    - {x for x in labels if x.startswith("review:")})]),
                    info=info)
            for lb in labels:
                m = re.fullmatch(r"review:(\w+)", lb)
                if m and m.group(1) in AGENTS and "approved" not in labels:
                    rv = m.group(1)
                    found[f"{rv}:review:{ref}"] = dict(
                        owner=rv, role="review", kind=REVIEW_KIND.get(rv, "review"), repo=full, ref=ref,
                        number=p["number"], title=p["title"],
                        fp=json.dumps([p.get("headRefOid"), ci, ncom, nrev]), info=info)
            if "sai-review" in labels:
                waiting.append({"ref": ref, "title": p["title"], "ci": ci})
            elif "approved" in labels and ci in ("green", "none") and p.get("mergeable") == "MERGEABLE":
                merge.append({"repo": full, "number": p["number"], "ref": ref, "title": p["title"],
                              "author": author, "branch": p["headRefName"]})
    return {"tasks": found, "merge": merge, "sai_review": waiting, "advance": advance}


# ---------- Board sync ----------
def _same_besides_ci(old_fp, new_fp) -> bool:
    """PR fingerprints are [ci, conflict, comments, reviews, labels]: True if only ci/conflict differ."""
    try:
        return json.loads(old_fp)[2:] == json.loads(new_fp)[2:]
    except (TypeError, ValueError):
        return False


def sync(found: dict) -> bool:
    """Apply a snapshot to the board. Returns True if any task became ready."""
    became_ready = False
    current = {t["key"]: t for t in log.tasks(("ready", "running", "waiting", "done"))}
    for key, f in found.items():
        t = current.get(key)
        prio = TASK_KINDS[f["kind"]]["priority"]
        if t is None:
            # A PR its author just opened needs nothing from them until something happens to it.
            status = "waiting" if f["role"] == "pr" and f["kind"] == "pr-followup" else "ready"
            log.create(key, priority=prio, status=status, done_fp=f["fp"] if status == "waiting" else None, **f)
            log.append("github", "task-new", f"{TASK_KINDS[f['kind']]['label']}: {f['title']}",
                       repo=f["repo"], ref=f["ref"], actor=f["owner"])
            became_ready |= status == "ready"
            continue
        upd = {k: f[k] for k in ("kind", "title", "fp", "info") if t.get(k) != f[k]}
        if upd.get("kind"):
            upd["priority"] = prio
        if (upd.get("kind") == "pr-followup" and t["status"] == "ready" and t["kind"] in ("fix-ci", "conflict")
                and _same_besides_ci(t["fp"], f["fp"])):
            # The CI failure or conflict went away before the author got to it (e.g. CI re-run) and nothing else
            # changed: nothing to do. Back to waiting; a new comment, review or red run wakes it as usual.
            upd.update(status="waiting", done_fp=f["fp"])
            log.append("github", "task-settled", f"{TASK_KINDS[t['kind']]['label']}: {f['title']} resolved itself",
                       repo=f["repo"], ref=f["ref"], actor=f["owner"])
        elif t["status"] == "done":        # reopened, or a review asked for again
            upd.update(status="ready", next_at=0, settle=0)
            became_ready = True
        elif t["settle"]:                # first look after a turn: what the agent did itself is not news
            upd.update(done_fp=f["fp"], settle=0)
        elif t["status"] == "waiting" and f["fp"] != t["done_fp"]:
            upd.update(status="ready", next_at=0)
            became_ready = True
            log.append("github", "task-wake", f"{TASK_KINDS[f['kind']]['label']}: {f['title']} changed",
                       repo=f["repo"], ref=f["ref"], actor=f["owner"])
        if upd:
            log.update(key, **upd)
    for key, t in current.items():
        if t["role"] in ("issue", "pr", "review") and t["status"] != "done" and key not in found:
            if t["status"] == "running":
                continue                 # finishes its turn first; the next poll closes it
            log.update(key, status="done")
            log.append("github", "task-done", f"{TASK_KINDS[t['kind']]['label']}: {t['title']} (closed on GitHub)",
                       repo=t["repo"], ref=t["ref"], actor=t["owner"])
    return became_ready


# ---------- Briefs ----------
def _cut(text, n):
    text = text or ""
    return text if len(text) <= n else text[:n] + f"\n… ({len(text) - n} more characters cut)"


def _comments(items, n=10):
    out = []
    for c in (items or [])[-n:]:
        when = (c.get("createdAt") or c.get("submittedAt") or "")[:16]
        state = f" [{c['state']}]" if c.get("state") else ""
        out.append(f"- {when}{state}: {_cut(c.get('body') or '', 2000)}")
    return "\n".join(out) or "(none)"


def _failed_ci_log(repo, run_ids) -> str:
    for rid in run_ids or []:
        out = gh("run", "view", str(rid), "-R", repo, "--log-failed", json_out=False, timeout=120) or ""
        if out:
            lines = out.splitlines()[-150:]
            return f"Failing run {rid}\n```\n" + "\n".join(lines) + "\n```"
    return "(no failing run log found)"


def brief(t: dict) -> str:
    """What the agent needs to know about its task, read from GitHub just now."""
    repo, n = t["repo"], str(t["number"])
    if t["role"] == "issue":
        i = gh("issue", "view", n, "-R", repo, "--json", "title,body,labels,comments") or {}
        return (f"### Issue {t['ref']}: {i.get('title', t['title'])}\n"
                f"Labels: {', '.join(lb['name'] for lb in i.get('labels', [])) or 'none'}\n\n"
                f"{_cut(i.get('body'), 12000)}\n\n#### Latest comments\n{_comments(i.get('comments'))}")
    p = gh("pr", "view", n, "-R", repo, "--json",
           "title,body,headRefName,baseRefName,labels,comments,reviews,mergeable,files") or {}
    files = ", ".join(f["path"] for f in (p.get("files") or [])[:60])
    parts = [f"### PR {t['ref']}: {p.get('title', t['title'])}",
             f"Branch {p.get('headRefName')} → {p.get('baseRefName')} · CI {t['info'].get('ci', '?')} · "
             f"mergeable {p.get('mergeable')} · labels {', '.join(lb['name'] for lb in p.get('labels', [])) or 'none'}",
             f"Files: {files}", "", _cut(p.get("body"), 6000), "",
             "#### Reviews", _comments(p.get("reviews")), "", "#### Latest comments", _comments(p.get("comments"))]
    if t["kind"] == "fix-ci":
        parts += ["", "#### Failing CI", _failed_ci_log(repo, t["info"].get("failed_runs"))]
    if t["role"] == "review" or t["kind"] in ("conflict",):
        diff = gh("pr", "diff", n, "-R", repo, json_out=False, timeout=120) or ""
        parts += ["", "#### Diff", "```diff", _cut(diff, 40000), "```"]
    return "\n".join(parts)


def merge(pr: dict) -> tuple[bool, str]:
    r = subprocess.run(["gh", "pr", "merge", str(pr["number"]), "-R", pr["repo"], "--merge"],
                       capture_output=True, text=True, timeout=120)
    return r.returncode == 0, (r.stderr or r.stdout).strip()[-400:]
