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
    """Manage application lifecycle — DB pool, scheduler."""
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

    logger.info("StockSentinel API is live!")

    yield  # App is running

    # --- SHUTDOWN ---
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
            "health": "/health",
        },
    }


# ---------------------------------------------------------------------------
# Register API routers
# ---------------------------------------------------------------------------
from app.api import stocks, dividends, ipos, news, watchlist, notifications

app.include_router(stocks.router, prefix="/api", tags=["Stocks"])
app.include_router(dividends.router, prefix="/api", tags=["Dividends"])
app.include_router(ipos.router, prefix="/api", tags=["IPOs"])
app.include_router(news.router, prefix="/api", tags=["News"])
app.include_router(watchlist.router, prefix="/api", tags=["Watchlist"])
app.include_router(notifications.router, prefix="/api", tags=["Notifications"])
