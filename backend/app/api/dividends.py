"""
Dividends API — upcoming, pending, paid dividends.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.database import fetch

router = APIRouter()


# Status comes from the dates, so old rows never stay "upcoming" after their ex-date.
STATUS_SQL = """CASE WHEN d.ex_date >= CURRENT_DATE THEN 'upcoming'
                     WHEN d.payment_date IS NOT NULL AND d.payment_date > CURRENT_DATE THEN 'pending'
                     ELSE 'paid' END"""


@router.get("/dividends")
async def list_dividends(
    status: Optional[str] = Query(None, description="upcoming, pending, or paid"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List dividends with optional status filter (one row per company, ex-date and amount)."""
    st = (status or "").lower() or None
    if st is not None and st not in ("upcoming", "pending", "paid"):
        raise HTTPException(400, "status must be upcoming, pending or paid")
    dividends = await fetch(
        f"""
        SELECT * FROM (
            SELECT DISTINCT ON (d.symbol, d.ex_date, d.amount)
                   d.*, {STATUS_SQL} AS live_status, s.current_price, s.market
            FROM dividends d
            LEFT JOIN stocks s ON d.stock_id = s.id
            WHERE d.ex_date IS NOT NULL
            ORDER BY d.symbol, d.ex_date, d.amount, (d.dividend_type = 'expected'), d.id DESC
        ) x
        WHERE $1::text IS NULL OR x.live_status = $1
        ORDER BY CASE WHEN $1::text = 'upcoming' THEN x.ex_date END ASC,
                 x.ex_date DESC
        LIMIT $2 OFFSET $3
        """,
        st, limit, offset,
    )
    out = []
    for d in dividends:
        d = dict(d)
        d["status"] = d.pop("live_status")
        out.append(d)
    return {"count": len(out), "dividends": out}


@router.get("/dividends/upcoming")
async def upcoming_dividends(
    days: int = Query(30, ge=1, le=90, description="Days ahead to look"),
    limit: int = Query(50, ge=1, le=200),
):
    """Get dividends with ex-dates in the next N days."""
    dividends = await fetch(
        """
        SELECT * FROM (
            SELECT DISTINCT ON (d.symbol, d.ex_date, d.amount)
                   d.*, s.current_price, s.market, s.name as stock_name
            FROM dividends d
            LEFT JOIN stocks s ON d.stock_id = s.id
            WHERE d.ex_date >= CURRENT_DATE
              AND d.ex_date <= CURRENT_DATE + $1 * INTERVAL '1 day'
            ORDER BY d.symbol, d.ex_date, d.amount, (d.dividend_type = 'expected'), d.id DESC
        ) x
        ORDER BY x.ex_date ASC
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
