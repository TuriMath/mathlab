"""Post into the chat from scripts (e.g. scheduled standups).

    python post.py standup hilbert "Passed: ..."
"""
import sys

import db
from config import AGENTS, CHANNELS, MANAGER

if __name__ == "__main__":
    channel, author, text = sys.argv[1], sys.argv[2], " ".join(sys.argv[3:])
    valid = {c["id"] for c in CHANNELS} | {f"dm-{a}" for a in AGENTS}
    assert channel in valid, f"unknown channel {channel}"
    assert author in AGENTS or author == MANAGER["id"], f"unknown author {author}"
    db.init()
    print(db.add(channel, author, text)["id"])
