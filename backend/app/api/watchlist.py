"""
Watchlist API — add, remove, list stocks in personal watchlist.
"""

import re

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from app.database import fetch, execute, fetchrow

router = APIRouter()

# Android IDs are 16 hex chars; allow other app-generated IDs, but nothing exotic.
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,100}$")


def _check_device(device_id: str) -> str:
    if not DEVICE_ID_RE.match(device_id or ""):
        raise HTTPException(400, "Invalid device id")
    return device_id


class WatchlistAdd(BaseModel):
    device_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{8,100}$")
    stock_id: int = Field(..., gt=0)


@router.get("/watchlist/{device_id}")
async def get_watchlist(device_id: str):
    """Get all watchlist stocks for a device with live prices."""
    _check_device(device_id)
    stocks = await fetch(
        """
        SELECT w.id as watchlist_id, w.added_at,
               s.id as stock_id, s.symbol, s.name, s.exchange, s.market,
               s.current_price, s.prev_close, s.change_pct, s.currency,
               s.day_high, s.day_low, s.volume, s.last_updated
        FROM watchlist w
        JOIN stocks s ON w.stock_id = s.id
        WHERE w.device_id = $1
        ORDER BY w.added_at DESC
        """,
        device_id,
    )

    return {"device_id": device_id, "count": len(stocks), "stocks": stocks}


@router.post("/watchlist")
async def add_to_watchlist(item: WatchlistAdd):
    """Add a stock to the watchlist."""
    # Check if already exists
    existing = await fetchrow(
        "SELECT id FROM watchlist WHERE device_id = $1 AND stock_id = $2",
        item.device_id,
        item.stock_id,
    )

    if existing:
        return {"status": "already_exists", "watchlist_id": existing["id"]}

    await execute(
        """
        INSERT INTO watchlist (device_id, stock_id)
        VALUES ($1, $2)
        """,
        item.device_id,
        item.stock_id,
    )

    return {"status": "added", "device_id": item.device_id, "stock_id": item.stock_id}


@router.delete("/watchlist/stock/{device_id}/{stock_id}")
async def remove_stock_from_watchlist(device_id: str, stock_id: int):
    """Remove a stock from watchlist by device_id and stock_id (only that device's own row)."""
    _check_device(device_id)
    await execute(
        "DELETE FROM watchlist WHERE device_id = $1 AND stock_id = $2",
        device_id,
        stock_id,
    )
    return {"status": "removed", "device_id": device_id, "stock_id": stock_id}
