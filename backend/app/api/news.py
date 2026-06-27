"""
News API — latest news with sentiment, ML stock impact, dividend detection.
"""

from fastapi import APIRouter, Query
from typing import Optional
from app.database import fetch, fetchrow

router = APIRouter()


@router.get("/news")
async def list_news(
    sentiment: Optional[str] = Query(None, description="BULLISH, BEARISH, NEUTRAL"),
    source: Optional[str] = Query(None, description="Filter by source"),
    dividend_only: bool = Query(False, description="Show only dividend-related news"),
    min_impact: Optional[float] = Query(None, ge=0, le=1, description="Min impact score"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get latest news with ML data — sentiment, affected stocks, impact score, dividend detection."""
    conditions = ["TRUE"]
    params = []
    param_idx = 1

    if sentiment:
        conditions.append(f"sentiment = ${param_idx}")
        params.append(sentiment.upper())
        param_idx += 1

    if source:
        conditions.append(f"source = ${param_idx}")
        params.append(source)
        param_idx += 1

    if dividend_only:
        conditions.append("dividend_detected = TRUE")

    if min_impact is not None:
        conditions.append(f"impact_score >= ${param_idx}")
        params.append(min_impact)
        param_idx += 1

    where = " AND ".join(conditions)

    news_items = await fetch(
        f"""
        SELECT id, title, url, source, published_at, sentiment,
               sentiment_score, related_symbols, category,
               impact_score, affected_stocks, dividend_detected,
               created_at
        FROM news
        WHERE {where}
        ORDER BY published_at DESC NULLS LAST
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """,
        *params,
        limit,
        offset,
    )

    return {"count": len(news_items), "news": news_items}


@router.get("/news/sentiment-summary")
async def sentiment_summary(hours: int = Query(24, ge=1, le=168)):
    """Sentiment breakdown for the last N hours."""
    summary = await fetch(
        """
        SELECT sentiment, COUNT(*) as count
        FROM news
        WHERE published_at >= NOW() - $1 * INTERVAL '1 hour'
          AND sentiment IS NOT NULL
        GROUP BY sentiment
        """,
        hours,
    )

    result = {"BULLISH": 0, "BEARISH": 0, "NEUTRAL": 0}
    total = 0
    for row in summary:
        result[row["sentiment"]] = row["count"]
        total += row["count"]

    return {
        "hours": hours,
        "total": total,
        "breakdown": result,
        "bullish_pct": round(result["BULLISH"] / total * 100, 1) if total > 0 else 0,
        "bearish_pct": round(result["BEARISH"] / total * 100, 1) if total > 0 else 0,
        "neutral_pct": round(result["NEUTRAL"] / total * 100, 1) if total > 0 else 0,
    }


@router.get("/news/stock-impact")
async def news_stock_impact(
    symbol: Optional[str] = Query(None, description="Filter by stock symbol"),
    direction: Optional[str] = Query(None, description="BULLISH, BEARISH, NEUTRAL"),
    limit: int = Query(30, ge=1, le=100),
):
    """
    Get news grouped by affected stocks — shows which news impacts which stock.
    The ML model tags each article with affected stocks and impact scores.
    """
    conditions = ["TRUE"]
    params = []
    param_idx = 1

    if symbol:
        conditions.append(f"nsi.symbol = ${param_idx}")
        params.append(symbol.upper())
        param_idx += 1

    if direction:
        conditions.append(f"nsi.impact_direction = ${param_idx}")
        params.append(direction.upper())
        param_idx += 1

    where = " AND ".join(conditions)

    items = await fetch(
        f"""
        SELECT nsi.symbol, nsi.impact_direction, nsi.impact_score, nsi.reason,
               n.id as news_id, n.title, n.url, n.source, n.published_at,
               n.sentiment, n.dividend_detected
        FROM news_stock_impact nsi
        JOIN news n ON nsi.news_id = n.id
        WHERE {where}
        ORDER BY n.published_at DESC
        LIMIT ${param_idx}
        """,
        *params,
        limit,
    )

    return {"count": len(items), "impact": items}


@router.get("/news/dividend-alerts")
async def dividend_alerts(
    limit: int = Query(30, ge=1, le=100),
):
    """
    Get news where the ML model detected dividend announcements.
    Shows which stocks declared dividends based on news analysis.
    """
    items = await fetch(
        """
        SELECT id, title, url, source, published_at, sentiment,
               impact_score, affected_stocks, related_symbols
        FROM news
        WHERE dividend_detected = TRUE
        ORDER BY published_at DESC
        LIMIT $1
        """,
        limit,
    )

    return {"count": len(items), "dividend_news": items}


@router.get("/news/sources")
async def list_sources():
    """Get all available news sources with article counts."""
    sources = await fetch(
        """
        SELECT source, COUNT(*) as count
        FROM news
        GROUP BY source
        ORDER BY count DESC
        """
    )
    return {"sources": sources}
