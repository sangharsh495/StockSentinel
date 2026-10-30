"""
Is every model and data job up to date?

    python scripts/freshness.py --guard     # used by the nightly workflow: skip if tonight's run already happened
    python scripts/freshness.py --check     # morning health check: exit 1 (GitHub emails the owner) if anything is stale

Reads the database directly (DATABASE_URL), so it works even if the API
server is asleep.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

# model_key -> how often it must be refreshed ("daily" = every weekday, "weekly")
MODELS = {
    "stock_report_card": "daily", "dividend_income": "daily", "market_scanner": "daily",
    "price_ranges": "daily", "stock_swing": "daily", "stock_investor_factor": "daily",
    "market_5d": "daily", "data_quality": "daily", "ipo_listing": "daily",
    "multibagger_radar": "weekly",
}
# background jobs on the API server -> max age in hours
JOBS = {"nse_stocks": 26, "news_fetch": 6, "indices": 26, "dividends": 30, "ipos_india": 30}


def last_weekday_close(now: datetime) -> datetime:
    """The most recent weekday 12:00 UTC (5:30 PM IST, after NSE closes) that is at least 14 hours ago."""
    t = (now - timedelta(hours=14)).replace(hour=12, minute=0, second=0, microsecond=0)
    if t > now - timedelta(hours=14):
        t -= timedelta(days=1)
    while t.weekday() >= 5:
        t -= timedelta(days=1)
    return t


async def status():
    from app.database import close_pool, create_pool, fetch

    await create_pool()
    try:
        models = {r["model_key"]: r["t"] for r in await fetch(
            "SELECT model_key, MAX(trained_at) AS t FROM quant_model_runs GROUP BY model_key")}
        jobs = {r["job_name"]: r["t"] for r in await fetch(
            "SELECT job_name, MAX(finished_at) AS t FROM job_runs WHERE status = 'success' GROUP BY job_name")}
    finally:
        await close_pool()
    return models, jobs


def main(args):
    now = datetime.now(timezone.utc)
    models, jobs = asyncio.run(status())
    if args.guard:
        # Tonight's run counts as done if the report cards were trained after today's close.
        today_close = now.replace(hour=10, minute=0, second=0, microsecond=0)
        t = models.get("stock_report_card")
        done = t is not None and t >= today_close
        print(f"report cards last trained {t}; already done today: {done}")
        if os.environ.get("GITHUB_OUTPUT"):
            with open(os.environ["GITHUB_OUTPUT"], "a") as f:
                f.write(f"done={'true' if done else 'false'}\n")
        return 0

    due = last_weekday_close(now)
    problems = []
    for key, freq in MODELS.items():
        t = models.get(key)
        limit = due - timedelta(days=7) if freq == "weekly" else due
        state = "MISSING" if t is None else ("STALE" if t < limit else "ok")
        print(f"{state:8s} model {key:24s} last trained {t}")
        if state != "ok":
            problems.append(key)
    for job, hours in JOBS.items():
        t = jobs.get(job)
        state = "MISSING" if t is None else ("STALE" if t < now - timedelta(hours=hours) else "ok")
        print(f"{state:8s} job   {job:24s} last success {t}")
        if state != "ok":
            problems.append(job)
    if problems:
        print(f"::error::Out of date: {', '.join(problems)}")
        return 1
    print("Everything is up to date.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--guard", action="store_true")
    g.add_argument("--check", action="store_true")
    sys.exit(main(ap.parse_args()))
