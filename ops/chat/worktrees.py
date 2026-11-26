"""One git worktree per task.

Each org repo is cloned once into ~/repos/<repo>. A task gets ~/tasks/<agent>/<repo>-<n>:
- an author's PR task: on the PR's branch, tracking origin
- a review: detached at the PR's head (reviews never push)
- an issue: on branch <agent>/<repo>-<n> (an existing remote branch of that name is picked up)
A branch lives in one worktree only: the PR an issue task opened reuses the issue's worktree (git refuses to
check one branch out twice), and a worktree is never removed while an active task still works on its branch.
When the task is done the worktree is removed, unless it holds uncommitted or unpushed work.
"""
import os
import shutil
import subprocess
import threading
from pathlib import Path

from config import env


HOME = Path.home()
REPOS = Path(env("REPOS") or HOME / "repos")
TASKS = Path(env("TASKS") or HOME / "tasks")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(name: str) -> threading.Lock:
    """Task turns run git in worker threads; two tasks on the same repo must not clone or add worktrees at once."""
    with _locks_guard:
        return _locks.setdefault(name, threading.Lock())


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300)


def clone(repo_full: str) -> Path:
    name = repo_full.split("/")[1]
    path = REPOS / name
    if not (path / ".git").exists():
        REPOS.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["git", "clone", "-q", f"https://github.com/{repo_full}", str(path)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"clone {repo_full} failed: {r.stderr.strip()[-300:]}")
    _git("fetch", "-q", "--prune", "origin", cwd=path)
    _git("worktree", "prune", cwd=path)
    return path


def path_for(t: dict) -> Path:
    name = t["repo"].split("/")[1]
    return TASKS / t["owner"] / f"{name}-{t['number']}{'-review' if t['role'] == 'review' else ''}"


def default_branch(repo: Path) -> str:
    r = _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=repo)
    return r.stdout.strip() or "origin/main"


def branch_of(t: dict) -> str | None:
    """The branch an author's task works on (None for reviews, which are detached)."""
    if t["role"] == "pr":
        return t["info"]["branch"]
    if t["role"] == "issue":
        return f"{t['owner']}/{t['repo'].split('/')[1]}-{t['number']}"
    return None


def _checked_out(repo: Path, branch: str) -> Path | None:
    """The worktree that already has this branch checked out, if any."""
    out = _git("worktree", "list", "--porcelain", cwd=repo).stdout
    path = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{branch}" and path and path.exists():
            return path
    return None


def ensure(t: dict) -> tuple[Path, str]:
    """(worktree path, branch description) for a GitHub-backed task. Blocking: call in a thread."""
    with _lock(t["repo"]):
        return _ensure(t)


def _ensure(t: dict) -> tuple[Path, str]:
    repo = clone(t["repo"])
    wt = path_for(t)
    if t["role"] == "review":
        target = f"origin/{t['info']['branch']}"
        if wt.exists():
            _git("checkout", "-q", "--detach", target, cwd=wt)
        else:
            _add(repo, "--detach", str(wt), target)
        return wt, f"detached at {target} (review only, do not push)"
    branch = branch_of(t)
    other = _checked_out(repo, branch)
    if other and other != wt:
        return other, f"branch {branch}"
    if not wt.exists():
        has_local = _git("rev-parse", "--verify", "-q", f"refs/heads/{branch}", cwd=repo).returncode == 0
        has_remote = _git("rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}", cwd=repo).returncode == 0
        if has_local:
            _add(repo, str(wt), branch)
        elif has_remote:
            _add(repo, "--track", "-b", branch, str(wt), f"origin/{branch}")
        else:
            _add(repo, "-b", branch, str(wt), default_branch(repo))
    return wt, f"branch {branch}"


def _add(repo, *args):
    TASKS.mkdir(parents=True, exist_ok=True)
    r = _git("worktree", "add", "-q", *args, cwd=repo)
    if r.returncode != 0:
        raise RuntimeError(f"worktree add failed: {r.stderr.strip()[-300:]}")
    share_lake(repo, Path(args[-2]))   # every caller passes ... <path> <commit-ish>, so the path is second to last


def share_lake(repo: Path, wt: Path) -> None:
    """Lean repos: point the worktree's .lake/packages at the clone's, so Mathlib (about 7 GB unpacked) exists
    once on disk instead of once per task. Safe because the Mathlib pin never changes inside a task (_rules.md,
    rule 10); `.lake/` is gitignored, so the link never shows up as a change. No-op for non-Lean repos or when the
    clone hasn't been primed (`heavy lake exe cache get` in ~/repos/<repo>)."""
    shared = repo / ".lake" / "packages"
    if not (wt / "lakefile.lean").exists() or not shared.is_dir():
        return
    link = wt / ".lake" / "packages"
    if link.exists() or link.is_symlink():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(shared)


def remove(t: dict, busy: set[str] = frozenset()) -> str:
    """Remove a finished task's worktree if nothing would be lost and no active task (busy: their branches)
    still works in it. Returns "removed", "none" or why it was kept."""
    with _lock(t["repo"]):
        return _remove(t, busy)


def _remove(t: dict, busy) -> str:
    wt = path_for(t)
    if not wt.exists():
        return "none"
    if _git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt).stdout.strip() in busy:
        return "kept (in use)"
    dirty = _git("status", "--porcelain", cwd=wt).stdout.strip()
    ahead = _git("log", "--oneline", "@{u}..", cwd=wt)
    unpushed = ahead.returncode == 0 and ahead.stdout.strip()
    no_upstream = ahead.returncode != 0 and t["role"] != "review"
    if no_upstream:                      # a local branch never pushed: keep it if it has commits of its own
        base = default_branch(REPOS / t["repo"].split("/")[1])
        unpushed = _git("log", "--oneline", f"{base}..HEAD", cwd=wt).stdout.strip()
    if dirty or unpushed:
        return "kept (unsaved work)"
    repo = REPOS / t["repo"].split("/")[1]
    if _git("worktree", "remove", "--force", str(wt), cwd=repo).returncode != 0:
        shutil.rmtree(wt, ignore_errors=True)
        _git("worktree", "prune", cwd=repo)
    return "removed"

