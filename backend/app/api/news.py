"""
News API — latest news with sentiment, sentiment summary.
"""

from fastapi import APIRouter, Query
from typing import Optional
from app.database import fetch, fetchrow

router = APIRouter()


@router.get("/news")
async def list_news(
    sentiment: Optional[str] = Query(None, description="BULLISH, BEARISH, NEUTRAL"),
    source: Optional[str] = Query(None, description="Filter by source"),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """Get latest news with optional sentiment/source filter."""
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

    where = " AND ".join(conditions)

    news_items = await fetch(
        f"""
        SELECT id, title, url, source, published_at, sentiment,
               sentiment_score, related_symbols, category, created_at
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
