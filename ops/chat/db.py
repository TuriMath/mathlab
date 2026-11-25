"""SQLite storage for messages and Claude sessions."""
import os
import sqlite3
import time
from pathlib import Path

from config import FACTORY, env

DB = Path(env("CHAT_DB") or Path.home() / f".{FACTORY['slug']}-chat.db")


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.executescript("""
        create table if not exists messages(
            id integer primary key autoincrement,
            channel text not null, parent_id integer,
            author text not null, text text not null, ts real not null);
        create index if not exists idx_msg_channel on messages(channel, parent_id);
        create index if not exists idx_msg_parent on messages(parent_id);
        create table if not exists kv(key text primary key, value text not null);
        create table if not exists sessions(
            key text primary key, session_id text not null, last_ts real not null);
        """)
        cols = [r[1] for r in c.execute("pragma table_info(sessions)")]
        if "seen_id" not in cols:  # last message id the agent has been shown in this conversation
            c.execute("alter table sessions add column seen_id integer not null default 0")


_TOP = """select m.*, (select count(*) from messages r where r.parent_id = m.id) as reply_count,
          (select max(ts) from messages r where r.parent_id = m.id) as last_reply_ts
          from messages m"""


def add(channel, author, text, parent_id=None) -> dict:
    with conn() as c:
        cur = c.execute("insert into messages(channel,parent_id,author,text,ts) values(?,?,?,?,?)",
                        (channel, parent_id, author, text, time.time()))
        return get(cur.lastrowid, c)


def get(mid, c=None):
    c = c or conn()
    r = c.execute(_TOP + " where m.id=?", (mid,)).fetchone()
    return dict(r) if r else None


def channel_messages(channel, limit=300):
    with conn() as c:
        rows = c.execute(_TOP + " where m.channel=? and m.parent_id is null order by m.id desc limit ?",
                         (channel, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def thread(parent_id):
    with conn() as c:
        rows = c.execute("select * from messages where parent_id=? order by id", (parent_id,)).fetchall()
    return [dict(r) for r in rows]


def since(after_id):
    with conn() as c:
        rows = c.execute(_TOP + " where m.id>? order by m.id limit 500", (after_id,)).fetchall()
    return [dict(r) for r in rows]


def last_id():
    with conn() as c:
        return c.execute("select coalesce(max(id),0) from messages").fetchone()[0]


def last_agent_in_thread(parent_id, agents):
    with conn() as c:
        r = c.execute("select author from messages where parent_id=? and author in (%s) order by id desc limit 1"
                      % ",".join("?" * len(agents)), (parent_id, *agents)).fetchone()
    return r[0] if r else None


def session(key, idle_reset=None):
    """Existing session id for this conversation, or None if new or gone stale."""
    with conn() as c:
        r = c.execute("select session_id,last_ts from sessions where key=?", (key,)).fetchone()
    if not r or (idle_reset and time.time() - r["last_ts"] > idle_reset):
        return None
    return r["session_id"]


def seen(key):
    with conn() as c:
        r = c.execute("select seen_id from sessions where key=?", (key,)).fetchone()
    return r[0] if r else 0


def save_session(key, session_id, seen_id=0):
    with conn() as c:
        c.execute("insert into sessions(key,session_id,last_ts,seen_id) values(?,?,?,?) "
                  "on conflict(key) do update set session_id=excluded.session_id,last_ts=excluded.last_ts,"
                  "seen_id=excluded.seen_id", (key, session_id, time.time(), seen_id))


def channel_context(channel, before_id, after_id=0, limit=30):
    """Top-level messages in a channel between two ids, oldest first."""
    with conn() as c:
        rows = c.execute("select * from messages where channel=? and parent_id is null and id<? and id>? "
                         "order by id desc limit ?", (channel, before_id, after_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]




def kv_get(key, default=None):
    with conn() as c:
        r = c.execute("select value from kv where key=?", (key,)).fetchone()
    return r[0] if r else default


def kv_set(key, value):
    with conn() as c:
        c.execute("insert into kv(key,value) values(?,?) on conflict(key) do update set value=excluded.value",
                  (key, value))
