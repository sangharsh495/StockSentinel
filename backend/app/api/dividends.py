"""
Dividends API — upcoming, pending, paid dividends.
"""

from fastapi import APIRouter, Query
from typing import Optional
from app.database import fetch

router = APIRouter()


@router.get("/dividends")
async def list_dividends(
    status: Optional[str] = Query(None, description="upcoming, pending, or paid"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List dividends with optional status filter."""
    if status:
        dividends = await fetch(
            """
            SELECT d.*, s.current_price, s.market
            FROM dividends d
            LEFT JOIN stocks s ON d.stock_id = s.id
            WHERE d.status = $1
            ORDER BY d.ex_date ASC
            LIMIT $2 OFFSET $3
            """,
            status.lower(),
            limit,
            offset,
        )
    else:
        dividends = await fetch(
            """
            SELECT d.*, s.current_price, s.market
            FROM dividends d
            LEFT JOIN stocks s ON d.stock_id = s.id
            ORDER BY d.ex_date DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    return {"count": len(dividends), "dividends": dividends}


@router.get("/dividends/upcoming")
async def upcoming_dividends(
    days: int = Query(30, ge=1, le=90, description="Days ahead to look"),
    limit: int = Query(50, ge=1, le=200),
):
    """Get dividends with ex-dates in the next N days."""
    dividends = await fetch(
        """
        SELECT d.*, s.current_price, s.market, s.name as stock_name
        FROM dividends d
        LEFT JOIN stocks s ON d.stock_id = s.id
        WHERE d.ex_date >= CURRENT_DATE
          AND d.ex_date <= CURRENT_DATE + $1 * INTERVAL '1 day'
        ORDER BY d.ex_date ASC
        LIMIT $2
        """,
        days,
        limit,
    )

    return {"days_ahead": days, "count": len(dividends), "dividends": dividends}


@router.get("/dividends/tomorrow")
async def tomorrow_dividends():
    """Get dividends with ex-date tomorrow (used for push alerts)."""
    dividends = await fetch(
        """
        SELECT d.*, s.current_price, s.market, s.name as stock_name
        FROM dividends d
        LEFT JOIN stocks s ON d.stock_id = s.id
        WHERE d.ex_date = CURRENT_DATE + INTERVAL '1 day'
        ORDER BY d.amount DESC NULLS LAST
        """
    )

    return {"count": len(dividends), "dividends": dividends}
