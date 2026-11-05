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


def test_every_schedule_runs_in_indian_time():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from apscheduler.triggers.cron import CronTrigger

    ist = ZoneInfo("Asia/Kolkata")
    sched = jobs.create_scheduler()
    crons = {j.id: j.trigger for j in sched.get_jobs() if isinstance(j.trigger, CronTrigger)}
    assert crons
    for jid, trig in crons.items():
        assert str(trig.timezone) == "Asia/Kolkata", jid
    # Thursday 8:00 AM IST: next live NSE price fetch is 9:00 IST the same morning, not 14:30.
    start = datetime(2026, 11, 5, 8, 0, tzinfo=ist)
    nxt = crons["nse_stocks"].get_next_fire_time(None, start).astimezone(ist)
    assert (nxt.date(), nxt.hour, nxt.minute) == (start.date(), 9, 0)
    # Friday's US session runs past midnight IST into Saturday.
    sat = datetime(2026, 11, 7, 0, 5, tzinfo=ist)
    late = crons["us_stocks_late"].get_next_fire_time(None, sat).astimezone(ist)
    assert late.date() == sat.date() and late.hour == 0
