"""Factory chat: a minimal Slack-like app for talking to the agents."""
import asyncio
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
from config import AGENTS, CHANNELS, CHAT_FALLBACK_SEAT, DM_IDLE_RESET_SECONDS, MANAGER, MODELS, SYSTEM, TASK_KINDS, WORKSPACE
from config import ROUTER_DEFAULT
from router import is_status_question, pick, tagged
from runner import run_turn
import companylog as log
import dispatcher as shift
import seats
import usage
import os

HERE = Path(__file__).parent
MAX_PARALLEL = int(os.environ.get("MAX_PARALLEL_AGENTS", "2"))

app = FastAPI()
app.add_middleware(GZipMiddleware, minimum_size=1000)   # channel payloads are ~100 KB of text; gzip cuts them ~5x
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
db.init()


@app.middleware("http")
async def no_stale_pages(request, call_next):
    """The phone app's WebView caches aggressively; make it revalidate so web changes show at once."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

slots = asyncio.Semaphore(MAX_PARALLEL)
agent_locks = {a: asyncio.Lock() for a in AGENTS}
working: dict[str, dict] = {}  # agent -> {"channel", "parent_id"}
routing: dict[int, bool] = {}  # messages still deciding who answers
CHANNEL_IDS = {c["id"] for c in CHANNELS} | {f"dm-{a}" for a in AGENTS}


@app.on_event("startup")
async def start_shifts():
    shift.start(working, agent_locks, slots)
    usage.start()


@app.get("/api/tasks")
def tasks_view():
    return {"tasks": log.tasks(), "seats": [seats.state(s) for s in seats.POOL], "throttled": seats.throttled()}


@app.get("/api/usage")
def usage_view():
    return {"seats": usage.snapshot(), "now": __import__("time").time()}


class NewMessage(BaseModel):
    channel: str
    text: str
    parent_id: int | None = None


@app.get("/")
def index():
    """index.html with each script/stylesheet stamped by its file time, so no client can run an old copy."""
    html = (HERE / "static" / "index.html").read_text()
    for name in ("style.css", "office.js", "app.js"):
        stamp = int((HERE / "static" / name).stat().st_mtime)
        html = html.replace(f'/static/{name}"', f'/static/{name}?v={stamp}"')
    return HTMLResponse(html)


@app.get("/api/meta")
def meta():
    return {"workspace": WORKSPACE, "me": MANAGER, "system": SYSTEM, "channels": CHANNELS,
            "agents": AGENTS, "last_id": db.last_id()}


@app.get("/api/channel/{channel}")
def channel(channel: str, limit: int = 100):
    if channel not in CHANNEL_IDS:
        raise HTTPException(404)
    return db.channel_messages(channel, max(1, min(limit, 300)))


@app.get("/api/thread/{mid}")
def thread(mid: int):
    parent = db.get(mid)
    if not parent:
        raise HTTPException(404)
    return {"parent": parent, "replies": db.thread(mid)}


@app.get("/api/updates")
def updates(after: int = 0):
    return {"messages": db.since(after), "working": working, "routing": list(routing)}


@app.post("/api/messages")
async def post(m: NewMessage):
    text = m.text.strip()
    if m.channel not in CHANNEL_IDS or not text:
        raise HTTPException(400)
    if m.parent_id is not None:
        parent = db.get(m.parent_id)
        if not parent or parent["channel"] != m.channel or parent["parent_id"] is not None:
            raise HTTPException(400)
    msg = db.add(m.channel, MANAGER["id"], text, m.parent_id)
    log.append("chat", "sai", f"#{m.channel}: {text}", actor="sai")
    reply = shift.command(text)
    if reply is None or not text.lower().startswith("/status"):
        shift.on_sai()                   # a parked team takes another look once Sai has spoken
    if reply is not None:                # /pause, /resume, /status: answered by the scheduler, no agent runs
        db.add(m.channel, SYSTEM["id"], reply, m.parent_id)
        return msg
    if m.channel == "work":              # the shift log is for reports; Sai's messages there don't wake anyone
        return msg
    asyncio.create_task(dispatch(m.channel, text, m.parent_id, msg["id"]))
    return msg


async def dispatch(channel, text, parent_id, msg_id):
    for agent, reply_parent, key, idle in await route(channel, text, parent_id, msg_id):
        asyncio.create_task(respond(agent, channel, reply_parent, key, idle, text, msg_id))


async def route(channel, text, parent_id, msg_id):
    """Decide which agents answer, where their reply goes, and which session continues."""
    if channel.startswith("dm-"):
        agent = channel[3:]
        if parent_id is None:
            return [(agent, None, f"dm:{agent}", DM_IDLE_RESET_SECONDS)]
        return [(agent, parent_id, f"thread:{parent_id}:{agent}", None)]
    agents = tagged(text)
    if parent_id is None:
        # Main channel: agents reply inline, like a normal group chat. Threads only when Sai opens one.
        if not agents:
            routing[msg_id] = True
            try:
                agents = await pick(channel, text, lines(db.channel_context(channel, msg_id, limit=10)))
            finally:
                routing.pop(msg_id, None)
        return [(a, None, f"chan:{channel}:{a}", DM_IDLE_RESET_SECONDS) for a in agents]
    if not agents:
        last = db.last_agent_in_thread(parent_id, list(AGENTS))
        agents = [last] if last else await pick(channel, text, transcript(parent_id, include_last=True))
    return [(a, parent_id, f"thread:{parent_id}:{a}", None) for a in agents]


def silent(answer):
    """True when the agent has nothing to say: an empty reply, or a reply that is only an IDLE line (rule 12)."""
    text = answer.strip()
    return not text or ("\n" not in text and re.match(r"\W*IDLE\b", text, re.I) is not None)


def lines(messages):
    who = lambda a: AGENTS[a]["name"] if a in AGENTS else MANAGER["name"]
    return "\n".join(f"{who(x['author'])}: {x['text']}" for x in messages)


def transcript(parent_id, include_last=False):
    msgs = [db.get(parent_id)] + db.thread(parent_id)
    return lines(msgs if include_last else msgs[:-1])


async def respond(agent, channel, reply_parent, key, idle, text, msg_id):
    where = "a direct message" if channel.startswith("dm-") else f"#{channel}"
    async with agent_locks[agent]:
        session = db.session(key, idle)
        resume = session is not None
        session = session or str(uuid.uuid4())
        prompt = f"[{where}] Sai: {text}"
        if not resume and reply_parent is not None and db.thread(reply_parent):
            prompt = f"[{where}, thread so far]\n{transcript(reply_parent)}\n\n{prompt}"
        elif reply_parent is None and not channel.startswith("dm-"):
            # Group chat: show everything said since this agent was last prompted (recent history on a fresh
            # session). Its own replies are already in its session, so they are skipped when resuming.
            context = db.channel_context(channel, msg_id, db.seen(key) if resume else 0)
            context = [m for m in context if not (resume and m["author"] == agent)]
            if context:
                prompt = f"[{where}, messages since you last spoke]\n{lines(context)}\n\n{prompt}"
        if agent == ROUTER_DEFAULT and not channel.startswith("dm-") and is_status_question(text):
            # Rule 11: one voice. The architect answers for everyone, starting from the live shift table.
            prompt = (f"[live shift status, read from GitHub by the scheduler]\n{shift.status_text()}\n\n"
                      "You are answering this status question for the whole team (rule 11): nobody else will "
                      "reply. Check GitHub for anything you need to confirm.\n\n" + prompt)
        async with slots:
            # Chat runs on a pool seat like any task (the same one as this conversation's last turn if it's
            # fine), and on Sai's own seat when the whole pool is out, so Sai can always reach the team.
            seat = seats.pick(prefer=db.kv_get(f"chat_seat:{key}"), urgent=True) or CHAT_FALLBACK_SEAT
            seats.acquire(seat)
            db.kv_set(f"chat_seat:{key}", seat)
            working[agent] = {"channel": channel, "parent_id": reply_parent}
            try:
                answer, ok = await run_turn(agent, prompt, session, resume,
                                            model=MODELS[TASK_KINDS["chat"]["model"]], seat=seat)
            except Exception as e:  # never leave the user without a reply
                answer, ok = f"Something broke while I was working: `{e}`", False
            finally:
                working.pop(agent, None)
                seats.release(seat)
        if ok:
            db.save_session(key, session, msg_id)
        if ok and silent(answer):        # rule 12: idle means silent, so nothing is posted
            return
        db.add(channel, agent, answer, reply_parent)
        log.append("chat", "reply", f"#{channel}: {answer[:600]}", actor=agent)
