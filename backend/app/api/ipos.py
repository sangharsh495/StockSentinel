"""
IPOs API — upcoming, open, closed, listed IPOs for India and US.
"""

from fastapi import APIRouter, Query
from typing import Optional
from app.database import fetch

router = APIRouter()


@router.get("/ipos")
async def list_ipos(
    market: Optional[str] = Query(None, description="IN or US"),
    status: Optional[str] = Query(None, description="upcoming, open, closed, listed"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List IPOs with optional market and status filters."""
    conditions = []
    params = []
    param_idx = 1

    if market:
        conditions.append(f"market = ${param_idx}")
        params.append(market.upper())
        param_idx += 1

    if status:
        conditions.append(f"status = ${param_idx}")
        params.append(status.lower())
        param_idx += 1

    where = " AND ".join(conditions) if conditions else "TRUE"

    ipos = await fetch(
        f"""
        SELECT * FROM ipos
        WHERE {where}
        ORDER BY
            CASE status
                WHEN 'open' THEN 1
                WHEN 'upcoming' THEN 2
                WHEN 'closed' THEN 3
                WHEN 'listed' THEN 4
                ELSE 5
            END,
            open_date ASC NULLS LAST
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """,
        *params,
        limit,
        offset,
    )

    return {"count": len(ipos), "ipos": ipos}


@router.get("/ipos/upcoming")
async def upcoming_ipos(
    days: int = Query(30, ge=1, le=90),
    limit: int = Query(50, ge=1, le=200),
):
    """Get IPOs opening in the next N days."""
    ipos = await fetch(
        """
        SELECT * FROM ipos
        WHERE (status = 'upcoming' OR status = 'open')
          AND (open_date IS NULL OR open_date <= CURRENT_DATE + $1 * INTERVAL '1 day')
        ORDER BY open_date ASC NULLS LAST
        LIMIT $2
        """,
        days,
        limit,
    )

    return {"days_ahead": days, "count": len(ipos), "ipos": ipos}


@router.get("/ipos/tomorrow")
async def tomorrow_ipos():
    """Get IPOs opening tomorrow (used for push alerts)."""
    ipos = await fetch(
        """
        SELECT * FROM ipos
        WHERE open_date = CURRENT_DATE + INTERVAL '1 day'
        ORDER BY company_name
        """
    )

    return {"count": len(ipos), "ipos": ipos}
