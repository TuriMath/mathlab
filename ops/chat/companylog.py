"""The company log and the task board, in the chat app's SQLite database.

- events: append-only. Everything that happened: GitHub changes, chat, turn results, handoffs, merges.
  This is the company's memory; agents get the slice that touches their task.
- tasks: the board. One row per piece of work, derived from GitHub by tasks.py. A task keeps its own Claude
  session (and seat) for as long as it lives, so follow-ups resume where the work left off.

Task status: ready (dispatch when its turn comes), running, waiting (until its fingerprint changes), done.
"""
import json
import time

import db

ACTIVE = ("ready", "running", "waiting")


def init():
    with db.conn() as c:
        c.executescript("""
        create table if not exists events(
            id integer primary key autoincrement, ts real not null,
            source text not null, kind text not null, repo text, ref text, actor text,
            summary text not null, data text);
        create index if not exists idx_events_ref on events(ref, id);
        create index if not exists idx_events_repo on events(repo, id);
        create table if not exists tasks(
            key text primary key,
            owner text not null, role text not null, kind text not null,
            repo text, ref text, number integer, title text not null default '',
            priority integer not null, status text not null,
            fp text, done_fp text, settle integer not null default 0,
            session_id text, seat text, model text,
            handoff text not null default '', last_result text not null default '', last_sai text not null default '',
            turns integer not null default 0, next_at real not null default 0,
            created real not null, updated real not null, info text);
        create index if not exists idx_tasks_status on tasks(status, priority);
        """)
        # Turns left running when the app stopped never finished: put them back on the board.
        c.execute("update tasks set status='ready' where status='running'")


# ---------- Events ----------
def append(source, kind, summary, repo=None, ref=None, actor=None, data=None):
    with db.conn() as c:
        c.execute("insert into events(ts,source,kind,repo,ref,actor,summary,data) values(?,?,?,?,?,?,?,?)",
                  (time.time(), source, kind, repo, ref, actor, summary[:2000],
                   json.dumps(data) if data is not None else None))


def slice(ref=None, repo=None, n=15) -> list[dict]:
    """Recent events for one task (its ref) plus the latest from its repo, oldest first."""
    with db.conn() as c:
        rows = []
        if ref:
            rows += c.execute("select * from events where ref=? order by id desc limit ?", (ref, n)).fetchall()
        if repo:
            rows += c.execute("select * from events where repo=? and (ref is null or ref<>?) "
                              "order by id desc limit ?", (repo, ref or "", n // 2)).fetchall()
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: r["id"]):
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(dict(r))
    return out


def last_turn(ref, actor) -> dict | None:
    """The last turn result (turn-done/-idle/-blocked/-blocked-sai/-failed) this agent had on this ref."""
    with db.conn() as c:
        q = "select * from events where actor=? and kind like 'turn-%' and kind<>'turn-start' and "
        q += "ref is null " if ref is None else "ref=? "
        r = c.execute(q + "order by id desc limit 1", (actor,) if ref is None else (actor, ref)).fetchone()
    return dict(r) if r else None


def by_kind(kind, n=5) -> list[dict]:
    with db.conn() as c:
        rows = c.execute("select * from events where kind=? order by id desc limit ?", (kind, n)).fetchall()
    return [dict(r) for r in reversed(rows)]


def recent(n=50) -> list[dict]:
    with db.conn() as c:
        rows = c.execute("select * from events order by id desc limit ?", (n,)).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------- Tasks ----------
def task(key) -> dict | None:
    with db.conn() as c:
        r = c.execute("select * from tasks where key=?", (key,)).fetchone()
    return _row(r)


def tasks(statuses=ACTIVE) -> list[dict]:
    q = "select * from tasks where status in (%s) order by priority, created" % ",".join("?" * len(statuses))
    with db.conn() as c:
        return [_row(r) for r in c.execute(q, statuses).fetchall()]


def ready(now=None) -> list[dict]:
    now = now or time.time()
    with db.conn() as c:
        rows = c.execute("select * from tasks where status='ready' and next_at<=? order by priority, created",
                         (now,)).fetchall()
    return [_row(r) for r in rows]


def create(key, **f):
    now = time.time()
    f = {"status": "ready", "created": now, "updated": now, **f, "key": key}
    if isinstance(f.get("info"), dict):
        f["info"] = json.dumps(f["info"])
    cols = ",".join(f)
    with db.conn() as c:
        c.execute(f"insert into tasks({cols}) values({','.join('?' * len(f))})", tuple(f.values()))


def update(key, **f):
    if not f:
        return
    f["updated"] = time.time()
    if isinstance(f.get("info"), dict):
        f["info"] = json.dumps(f["info"])
    with db.conn() as c:
        c.execute(f"update tasks set {','.join(k + '=?' for k in f)} where key=?", (*f.values(), key))


def _row(r):
    if r is None:
        return None
    d = dict(r)
    d["info"] = json.loads(d["info"]) if d.get("info") else {}
    return d
