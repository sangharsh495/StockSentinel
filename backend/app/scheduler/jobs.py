"""
APScheduler Job Definitions — all scheduled data collection tasks.

Schedule overview:
- Every 5 min during India market (9:15-15:30 IST): NSE/BSE prices
- Every 5 min during US market (9:30-16:00 ET): US prices
- Every 15 min: Market indices
- Every 30 min: News + sentiment
- Every 2 hours: Dividends + IPOs
- Daily at 6 AM IST: Push notification alerts
- Daily at 2 AM IST: Cleanup old data
"""

import logging
import asyncio
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to run async functions from sync APScheduler jobs."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Schedule it on the running loop
            asyncio.ensure_future(coro)
        else:
            loop.run_until_complete(coro)
    except RuntimeError:
        # No running loop — create a new one
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()


async def _log_job(job_name: str, func):
    """Run a job and log its execution."""
    from app.database import execute
    started = datetime.utcnow()
    try:
        result = await func()
        await execute(
            """
            INSERT INTO job_runs (job_name, status, records_processed, started_at, finished_at)
            VALUES ($1, 'success', $2, $3, NOW())
            """,
            job_name, result or 0, started,
        )
    except Exception as e:
        logger.error(f"Job {job_name} failed: {e}")
        try:
            await execute(
                """
                INSERT INTO job_runs (job_name, status, error_message, started_at, finished_at)
                VALUES ($1, 'failed', $2, $3, NOW())
                """,
                job_name, str(e)[:500], started,
            )
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Job wrappers (called by APScheduler)
# ---------------------------------------------------------------------------
def job_fetch_nse():
    """Fetch NSE India stock prices."""
    async def _run():
        from app.scrapers.nse_scraper import fetch_nse_all_stocks
        await _log_job("nse_stocks", fetch_nse_all_stocks)
    _run_async(_run())


def job_fetch_bse():
    """Fetch BSE India stock prices."""
    async def _run():
        from app.scrapers.bse_scraper import fetch_bse_stocks
        await _log_job("bse_stocks", fetch_bse_stocks)
    _run_async(_run())


def job_fetch_us():
    """Fetch US stock prices."""
    async def _run():
        from app.scrapers.us_scraper import fetch_us_prices
        await _log_job("us_stocks", fetch_us_prices)
    _run_async(_run())


def job_fetch_indices():
    """Fetch market indices."""
    async def _run():
        from app.scrapers.us_scraper import fetch_market_indices
        await _log_job("indices", fetch_market_indices)
    _run_async(_run())


def job_fetch_us_stock_list():
    """Fetch US stock list from Finnhub (daily)."""
    async def _run():
        from app.scrapers.us_scraper import fetch_us_stock_list
        await _log_job("us_stock_list", fetch_us_stock_list)
    _run_async(_run())


def job_fetch_news():
    """Fetch news from RSS feeds."""
    async def _run():
        from app.scrapers.news_scraper import fetch_news, extract_related_symbols
        await _log_job("news_fetch", fetch_news)
        await _log_job("news_symbols", extract_related_symbols)
    _run_async(_run())


def job_sentiment():
    """Run sentiment analysis on new headlines."""
    async def _run():
        from app.scrapers.sentiment import analyze_sentiment
        await _log_job("sentiment", analyze_sentiment)
    _run_async(_run())


def job_fetch_dividends():
    """Fetch dividend data."""
    async def _run():
        from app.scrapers.nse_scraper import fetch_nse_dividends
        await _log_job("dividends", fetch_nse_dividends)
    _run_async(_run())


def job_fetch_ipos():
    """Fetch IPO data."""
    async def _run():
        from app.scrapers.ipo_scraper import fetch_india_ipos, fetch_us_ipos
        await _log_job("ipos_india", fetch_india_ipos)
        await _log_job("ipos_us", fetch_us_ipos)
    _run_async(_run())


def job_send_alerts():
    """Send push notification alerts for tomorrow's events."""
    async def _run():
        from app.notifications.fcm import send_dividend_alerts, send_ipo_alerts
        await send_dividend_alerts()
        await send_ipo_alerts()
    _run_async(_run())


def job_cleanup():
    """Clean up old data to keep DB small."""
    async def _run():
        from app.scrapers.news_scraper import cleanup_old_news
        from app.database import execute
        from app.config import settings
        await cleanup_old_news()
        # Clean old job logs
        await execute(
            "DELETE FROM job_runs WHERE started_at < NOW() - $1 * INTERVAL '1 day'",
            settings.JOB_LOG_RETENTION_DAYS,
        )
    _run_async(_run())


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------
def create_scheduler() -> BackgroundScheduler:
    """Create and configure the APScheduler instance."""
    scheduler = BackgroundScheduler(
        timezone="Asia/Kolkata",
        job_defaults={
            "coalesce": True,  # Merge missed runs
            "max_instances": 1,  # No overlapping
            "misfire_grace_time": 300,  # 5 min grace
        },
    )

    # --- India market hours: NSE/BSE prices every 5 min (9:15 AM - 3:30 PM IST, Mon-Fri) ---
    scheduler.add_job(
        job_fetch_nse,
        CronTrigger(minute="*/5", hour="9-15", day_of_week="mon-fri"),
        id="nse_stocks",
        name="NSE Stock Prices",
    )

    scheduler.add_job(
        job_fetch_bse,
        CronTrigger(minute="2,7,12,17,22,27,32,37,42,47,52,57", hour="9-15", day_of_week="mon-fri"),
        id="bse_stocks",
        name="BSE Stock Prices",
    )

    # --- US market hours: US prices every 5 min (7 PM - 1:30 AM IST = 9:30 AM - 4 PM ET, Mon-Fri) ---
    scheduler.add_job(
        job_fetch_us,
        CronTrigger(minute="*/5", hour="19-23,0-1", day_of_week="mon-fri"),
        id="us_stocks",
        name="US Stock Prices",
    )

    # --- Market indices: every 15 min during any market hours ---
    scheduler.add_job(
        job_fetch_indices,
        IntervalTrigger(minutes=15),
        id="indices",
        name="Market Indices",
    )

    # --- News: every 30 min, 24/7 ---
    scheduler.add_job(
        job_fetch_news,
        IntervalTrigger(minutes=30),
        id="news",
        name="News Feed",
    )

    # --- Sentiment: every 30 min, 24/7 (offset by 15 min from news) ---
    scheduler.add_job(
        job_sentiment,
        CronTrigger(minute="15,45"),
        id="sentiment",
        name="Sentiment Analysis",
    )

    # --- Dividends: every 2 hours, 6 AM - 10 PM IST ---
    scheduler.add_job(
        job_fetch_dividends,
        CronTrigger(minute="0", hour="6,8,10,12,14,16,18,20,22"),
        id="dividends",
        name="Dividend Calendar",
    )

    # --- IPOs: every 4 hours ---
    scheduler.add_job(
        job_fetch_ipos,
        CronTrigger(minute="30", hour="6,10,14,18,22"),
        id="ipos",
        name="IPO Pipeline",
    )

    # --- US stock list: daily at 7 PM IST (before US market opens) ---
    scheduler.add_job(
        job_fetch_us_stock_list,
        CronTrigger(hour="19", minute="0"),
        id="us_stock_list",
        name="US Stock List (Daily)",
    )

    # --- Push alerts: daily at 6 AM IST ---
    scheduler.add_job(
        job_send_alerts,
        CronTrigger(hour="6", minute="0"),
        id="alerts",
        name="Push Notification Alerts",
    )

    # --- Cleanup: daily at 2 AM IST ---
    scheduler.add_job(
        job_cleanup,
        CronTrigger(hour="2", minute="0"),
        id="cleanup",
        name="Data Cleanup",
    )

    logger.info(f"Scheduler configured with {len(scheduler.get_jobs())} jobs")
    return scheduler
