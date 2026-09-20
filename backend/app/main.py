"""
StockSentinel API — Main application entry point.

FastAPI server with:
- REST API endpoints for stocks, dividends, IPOs, news, watchlist
- APScheduler for automated data collection
- Self-ping thread for Render keep-alive (24/7 free tier)
"""

import os
import logging
import threading
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import create_pool, close_pool, init_schema

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Self-ping keep-alive (prevents Render free tier from sleeping)
# ---------------------------------------------------------------------------
_ping_stop = threading.Event()


def _self_ping_loop():
    """Background thread: pings /health every 10 min to keep Render awake."""
    url = settings.RENDER_EXTERNAL_URL
    if not url:
        logger.warning("RENDER_EXTERNAL_URL not set — self-ping disabled")
        return

    health_url = f"{url.rstrip('/')}/health"
    logger.info(f"Self-ping thread started → {health_url} every 10 min")

    while not _ping_stop.is_set():
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(health_url)
                logger.debug(f"Self-ping OK: {resp.status_code}")
        except Exception as e:
            logger.debug(f"Self-ping failed (non-fatal): {e}")

        # Sleep 10 minutes, but check stop event every 5 seconds for fast shutdown
        _ping_stop.wait(timeout=600)


# ---------------------------------------------------------------------------
# APScheduler setup
# ---------------------------------------------------------------------------
def start_scheduler():
    """Start APScheduler with all data collection jobs."""
    try:
        from app.scheduler.jobs import create_scheduler
        scheduler = create_scheduler()
        scheduler.start()
        logger.info("APScheduler started with all jobs")
        return scheduler
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        return None


# ---------------------------------------------------------------------------
# FastAPI lifespan (startup + shutdown)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle — DB pool, scheduler, self-ping."""
    # --- STARTUP ---
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    # 1. Create database pool and init schema
    try:
        await create_pool()
        await init_schema()
        logger.info("Database ready")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    # 2. Start APScheduler
    scheduler = start_scheduler()

    # 3. Start self-ping keep-alive thread
    _ping_stop.clear()
    ping_thread = threading.Thread(target=_self_ping_loop, daemon=True, name="self-ping")
    ping_thread.start()

    logger.info("StockSentinel API is live!")

    yield  # App is running

    # --- SHUTDOWN ---
    _ping_stop.set()  # Signal self-ping thread to stop
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    await close_pool()
    logger.info("Application shutdown complete")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Personal stock intelligence API — India + US markets",
    lifespan=lifespan,
)

# CORS — allow Android app from any origin (personal use)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Grade 1 Enterprise Security Middleware
from app.security import SecurityHeadersMiddleware, RateLimitMiddleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, max_requests=120, window_seconds=60)


# ---------------------------------------------------------------------------
# Health check endpoint (pinged by cron-job.org + UptimeRobot + self-ping)
# ---------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    """Health check — returns OK. Used by keep-alive services."""
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@app.get("/")
async def root():
    """Root endpoint — same as health check."""
    return {
        "status": "ok",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "endpoints": {
            "stocks": "/api/stocks",
            "dividends": "/api/dividends",
            "ipos": "/api/ipos",
            "news": "/api/news",
            "watchlist": "/api/watchlist/{device_id}",
            "search": "/api/stocks/search?q=reliance",
            "fundamentals": "/api/stocks/{symbol}/fundamentals",
            "ratios": "/api/stocks/{symbol}/ratios",
            "technicals": "/api/stocks/{symbol}/technicals",
            "valuation": "/api/stocks/{symbol}/valuation",
            "compare": "/api/stocks/{symbol}/compare?symbols=TCS,WIPRO",
            "health": "/health",
        },
    }


# ---------------------------------------------------------------------------
# Register API routers
# ---------------------------------------------------------------------------
from app.api import stocks, dividends, ipos, news, watchlist, notifications, analyst, fundamentals

app.include_router(stocks.router, prefix="/api", tags=["Stocks"])
app.include_router(dividends.router, prefix="/api", tags=["Dividends"])
app.include_router(ipos.router, prefix="/api", tags=["IPOs"])
app.include_router(news.router, prefix="/api", tags=["News"])
app.include_router(watchlist.router, prefix="/api", tags=["Watchlist"])
app.include_router(notifications.router, prefix="/api", tags=["Notifications"])
app.include_router(analyst.router, prefix="/api", tags=["Analyst"])
app.include_router(fundamentals.router, prefix="/api", tags=["Fundamentals"])

