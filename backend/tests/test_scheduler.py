"""Scheduled jobs run on the app's own event loop (the DB pool lives there)."""

import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scheduler import jobs  # noqa: E402


def test_job_from_worker_thread_runs_on_main_loop():
    async def main():
        jobs.set_main_loop(asyncio.get_running_loop())
        seen = {}

        async def job():
            seen["loop"] = asyncio.get_running_loop()

        t = threading.Thread(target=jobs._run_async, args=(job(),))
        t.start()
        while t.is_alive():
            await asyncio.sleep(0.01)
        return seen.get("loop") is asyncio.get_running_loop()

    try:
        assert asyncio.run(main())
    finally:
        jobs.set_main_loop(None)
