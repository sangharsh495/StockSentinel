"""Yahoo downloads with a hard time limit, so one stuck request can't freeze a scheduled job."""

import asyncio
import logging

logger = logging.getLogger(__name__)

DOWNLOAD_LIMIT_SECONDS = 180


async def yf_download(tickers, limit: float = DOWNLOAD_LIMIT_SECONDS, **kwargs):
    """yfinance.download in a worker thread; returns None if it doesn't finish in `limit` seconds."""
    import yfinance as yf

    kwargs.setdefault("progress", False)
    kwargs.setdefault("timeout", 20)          # per HTTP request
    try:
        return await asyncio.wait_for(asyncio.to_thread(yf.download, tickers, **kwargs), timeout=limit)
    except asyncio.TimeoutError:
        logger.warning(f"Yahoo download of {len(tickers)} tickers took over {limit:.0f}s; skipped this round")
        return None
