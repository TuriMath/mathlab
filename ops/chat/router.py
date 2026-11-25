"""Decides which agents answer an untagged channel message, using a fast, cheap model."""
import asyncio
import json
import os
import re

from config import AGENTS, FACTORY, ROUTER_DEFAULT, WORKSPACE
from gate import wait_turn

CLAUDE = os.environ.get("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))
MODEL = os.environ.get("ROUTER_MODEL", "haiku")
ALL_TAGS = re.compile(r"@(all|everyone|channel|here|team)\b", re.I)
# Status/progress questions get one answer, from the architect, built from the shift table (rule 11).
STATUS_ASK = re.compile(
    r"\b(status|progress|update me|any updates?|what'?s the update|where are we|how far|"
    r"what'?s (?:everyone|the team) (?:doing|working on)|stand ?up|summary|summari[sz]e)\b", re.I)


def is_status_question(text: str) -> bool:
    return bool(STATUS_ASK.search(text)) and not text.strip().startswith("/")


def tagged(text: str) -> list[str]:
    if ALL_TAGS.search(text):
        return list(AGENTS)
    return [a for a in AGENTS if re.search(rf"@{a}\b", text, re.I)]


async def pick(channel: str, text: str, context: str = "") -> list[str]:
    if is_status_question(text):
        return [ROUTER_DEFAULT]
    roster = "\n".join(f"- {a}: {v['name']}, {v['role']}" for a, v in AGENTS.items())
    prompt = (
        f"You route messages in the #{channel} channel of {WORKSPACE}, {FACTORY['about']}.\n"
        f"Team:\n{roster}\n\n"
        + (f"Thread so far:\n{context}\n\n" if context else "")
        + f"The operator, Sai, wrote:\n{text}\n\n"
        "Who should reply? Greetings or messages addressed to everyone or the team: all agents. "
        "A question about a specific area: only the agents who own it. "
        "A request for status, progress or a summary: only the scout, who answers for the whole team. "
        "If unclear: the architect.\n"
        'Answer with JSON only, like {"agents": ["hilbert", "euler"]}.'
    )
    await wait_turn()
    proc = await asyncio.create_subprocess_exec(
        CLAUDE, "-p", prompt, "--model", MODEL, "--output-format", "json", "--max-turns", "1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, cwd="/tmp")
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=60)
        result = json.loads(out).get("result", "")
        names = json.loads(re.search(r"\{.*\}", result, re.S).group(0)).get("agents", [])
        picked = [a for a in AGENTS if a in {str(n).lower() for n in names}]
        return picked or [ROUTER_DEFAULT]
    except Exception:
        if proc.returncode is None:
            proc.kill()
        return [ROUTER_DEFAULT]
