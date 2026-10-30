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
from typing import Optional
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


# The server's event loop. The database pool belongs to it, so every job's
# coroutine must run on it. Jobs are started from APScheduler's worker
# threads, which have no event loop of their own; creating a new loop there
# (the old behaviour) made every database call fail silently.
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _run_async(coro, timeout: float = 1800):
    """Run an async job on the server's main event loop and wait for it."""
    loop = _MAIN_LOOP
    if loop is None or not loop.is_running():
        # Not inside the web server (e.g. a script): run on a private loop.
        asyncio.run(coro)
        return
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        future.result(timeout=timeout)
    except Exception:
        logger.exception("Scheduled job failed")


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
        from app.scrapers.news_scraper import fetch_news
        await _log_job("news_fetch", fetch_news)
    _run_async(_run())


def job_sentiment():
    """Run sentiment analysis on new headlines."""
    async def _run():
        from app.scrapers.sentiment import analyze_sentiment
        await _log_job("sentiment", analyze_sentiment)
    _run_async(_run())


def job_stock_impact():
    """Run ML stock impact analysis on new headlines."""
    async def _run():
        from app.ml.stock_impact_analyzer import run_stock_impact_analysis
        await _log_job("stock_impact", run_stock_impact_analysis)
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


def job_fetch_fundamentals():
    """Fetch financial fundamentals for top stocks."""
    async def _run():
        from app.scrapers.fundamentals_scraper import fetch_fundamentals_batch
        await _log_job("fundamentals", lambda: fetch_fundamentals_batch(limit=100))
    _run_async(_run())


def job_backfill_price_history():
    """Backfill daily price history for top stocks."""
    async def _run():
        from app.scrapers.fundamentals_scraper import fundamentals_scraper
        from app.database import get_pool
        import yfinance as yf
        import asyncio

        pool = await get_pool()
        async with pool.acquire() as conn:
            stocks = await conn.fetch(
                """
                SELECT symbol, exchange FROM stocks
                WHERE is_active = TRUE AND current_price IS NOT NULL
                ORDER BY market_cap DESC NULLS LAST
                LIMIT 200
                """
            )

        count = 0
        for stock in stocks:
            try:
                sym = stock["symbol"]
                ex = stock["exchange"]
                yf_ticker = fundamentals_scraper._get_yf_ticker(sym, ex) if hasattr(fundamentals_scraper, '_get_yf_ticker') else f"{sym}.NS"

                # Simple yf_ticker resolution
                clean = sym.strip().upper()
                if ex.upper() == "NSE":
                    yf_ticker = f"{clean}.NS"
                elif ex.upper() == "BSE":
                    yf_ticker = f"{clean}.BO"
                else:
                    yf_ticker = clean

                loop = asyncio.get_event_loop()
                hist = await loop.run_in_executor(
                    None,
                    lambda t=yf_ticker: yf.Ticker(t).history(period="1mo", interval="1d")
                )

                if hist is None or hist.empty:
                    continue

                # Get stock_id
                async with pool.acquire() as conn:
                    stock_row = await conn.fetchrow(
                        "SELECT id FROM stocks WHERE UPPER(symbol) = $1 AND UPPER(exchange) = $2",
                        sym.upper(), ex.upper(),
                    )
                    stock_id = stock_row["id"] if stock_row else None

                    for idx, row in hist.iterrows():
                        trade_date = idx.date() if hasattr(idx, 'date') else idx
                        try:
                            await conn.execute(
                                """
                                INSERT INTO price_history
                                    (stock_id, symbol, exchange, trade_date,
                                     open_price, high_price, low_price, close_price, volume)
                                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                                ON CONFLICT (symbol, exchange, trade_date) DO UPDATE SET
                                    close_price = EXCLUDED.close_price,
                                    volume = EXCLUDED.volume
                                """,
                                stock_id, sym.upper(), ex.upper(), trade_date,
                                round(float(row["Open"]), 4),
                                round(float(row["High"]), 4),
                                round(float(row["Low"]), 4),
                                round(float(row["Close"]), 4),
                                int(row["Volume"]),
                            )
                            count += 1
                        except Exception:
                            pass

                await asyncio.sleep(1)  # Rate limit
            except Exception as e:
                logging.getLogger(__name__).debug(f"Price history failed for {stock['symbol']}: {e}")

        return count
    _run_async(_run())


def job_news_outcomes():
    """Measure how stocks actually moved after tagged news (feeds the news model)."""
    async def _run():
        from app.quant.news_events import update_news_outcomes
        await _log_job("news_outcomes", update_news_outcomes)
    _run_async(_run())


def job_live_watch():
    """Market hours: live prices for tonight's watchlist vs their 80% ranges."""
    async def _run():
        from app.quant.live_watch import refresh_live_watch
        await _log_job("live_watch", refresh_live_watch)
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

    # --- News: every 15 min, 24/7 ---
    scheduler.add_job(
        job_fetch_news,
        IntervalTrigger(minutes=15),
        id="news",
        name="News Feed",
    )

    # --- Sentiment: every 30 min, 24/7 (offset by 15 min from news) ---
    scheduler.add_job(
        job_sentiment,
        CronTrigger(minute="10,40"),
        id="sentiment",
        name="Sentiment Analysis",
    )

    # --- Stock Impact ML: every 30 min (offset by 5 min after sentiment) ---
    scheduler.add_job(
        job_stock_impact,
        CronTrigger(minute="20,50"),
        id="stock_impact",
        name="ML Stock Impact Analysis",
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

    # --- Financial Fundamentals: daily at 4 AM IST ---
    scheduler.add_job(
        job_fetch_fundamentals,
        CronTrigger(hour="4", minute="0"),
        id="fundamentals",
        name="Financial Data Fetch",
    )

    # --- Price History Backfill: daily at 4:30 AM IST ---
    scheduler.add_job(
        job_backfill_price_history,
        CronTrigger(hour="4", minute="30"),
        id="price_history",
        name="Price History Backfill",
    )

    # --- News outcome measurement: daily at 5:30 PM IST (after market close) ---
    scheduler.add_job(
        job_news_outcomes,
        CronTrigger(hour="17", minute="30"),
        id="news_outcomes",
        name="News Outcome Measurement",
    )

    # --- Live watchlist tracking: every 15 min, Mon-Fri 9:15-15:30 IST ---
    scheduler.add_job(
        job_live_watch,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/15"),
        id="live_watch",
        name="Live Watchlist Tracking",
    )

    logger.info(f"Scheduler configured with {len(scheduler.get_jobs())} jobs")
    return scheduler
