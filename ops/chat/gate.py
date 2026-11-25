"""Spaces out Claude Code launches so a burst (e.g. @all) doesn't look like bot traffic to the API's edge."""
import asyncio
import os
import time

GAP = float(os.environ.get("LAUNCH_GAP_SECONDS", "3"))
_lock = asyncio.Lock()
_last = 0.0


async def wait_turn():
    global _last
    async with _lock:
        delay = _last + GAP - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        _last = time.monotonic()
