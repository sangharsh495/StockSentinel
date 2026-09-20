"""
Weekly Movers & Momentum Radar — scans market data, news catalysts, and corporate calendars
to identify stocks positioned for significant moves in the coming 3 to 7 days.
"""

import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone

from app.database import get_pool
from app.ml.catalyst_analyzer import catalyst_analyzer

logger = logging.getLogger(__name__)


class WeeklyMoversEngine:
    """Detects and ranks companies set to move this week."""

    async def get_weekly_movers(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Synthesize multi-factor signals:
        1. High-impact news catalysts (last 72h)
        2. Upcoming dividend ex-dates (next 7 days)
        3. High momentum price changes
        Returns ranked list of mover candidates.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Factor 1: High-impact news from the last 72 hours
            news_rows = await conn.fetch(
                """
                SELECT n.id, n.title, n.published_at, n.summary,
                       nsi.symbol, nsi.impact_direction, nsi.impact_score, nsi.reason,
                       s.id as stock_id, s.name, s.exchange, s.market,
                       s.current_price, s.change_pct, s.currency, s.sector
                FROM news_stock_impact nsi
                JOIN news n ON nsi.news_id = n.id
                JOIN stocks s ON UPPER(nsi.symbol) = UPPER(s.symbol)
                WHERE n.published_at >= NOW() - INTERVAL '72 hours'
                  AND s.is_active = TRUE
                ORDER BY nsi.impact_score DESC, n.published_at DESC
                LIMIT 50
                """
            )

            # Factor 2: Upcoming dividends in the next 7 days
            div_rows = await conn.fetch(
                """
                SELECT d.symbol, d.company_name, d.exchange, d.dividend_type, d.amount, d.ex_date,
                       s.id as stock_id, s.name, s.market, s.current_price, s.change_pct,
                       s.currency, s.sector
                FROM dividends d
                JOIN stocks s ON UPPER(d.symbol) = UPPER(s.symbol)
                WHERE d.ex_date >= CURRENT_DATE
                  AND d.ex_date <= CURRENT_DATE + INTERVAL '7 days'
                  AND s.is_active = TRUE
                ORDER BY d.ex_date ASC, d.amount DESC NULLS LAST
                LIMIT 20
                """
            )

            # Factor 3: Extreme price movers from stocks table (volume/breakout)
            price_mover_rows = await conn.fetch(
                """
                SELECT id as stock_id, symbol, name, exchange, market,
                       current_price, change_pct, volume, currency, sector
                FROM stocks
                WHERE is_active = TRUE
                  AND change_pct IS NOT NULL
                  AND (change_pct >= 4.0 OR change_pct <= -4.0)
                ORDER BY ABS(change_pct) DESC
                LIMIT 25
                """
            )

        candidates = {}  # symbol -> candidate dict

        # Process News Catalysts
        for row in news_rows:
            sym = row["symbol"].upper()
            if sym in candidates:
                continue

            analysis = catalyst_analyzer.analyze_headline(row["title"], row.get("summary") or "")

            expected_trend = analysis["trend_direction"]
            if expected_trend == "NEUTRAL":
                expected_trend = row.get("impact_direction") or "BULLISH"

            candidates[sym] = {
                "stock_id": row["stock_id"],
                "symbol": sym,
                "name": row["name"] or sym,
                "exchange": row["exchange"] or "NSE",
                "market": row["market"] or "IN",
                "current_price": float(row["current_price"]) if row["current_price"] else None,
                "change_pct": float(row["change_pct"]) if row["change_pct"] else 0.0,
                "currency": row["currency"] or "INR",
                "sector": row["sector"] or "General",
                "expected_trend": expected_trend,
                "catalyst_badge": analysis["catalyst_label"],
                "catalyst_headline": row["title"],
                "catalyst_summary": analysis["trend_rationale"],
                "confidence": round(float(row["impact_score"] or 0.8), 2),
                "timeframe": "This Week (1-5 Days)",
                "rank_score": float(row["impact_score"] or 0.8) * 1.5,
            }

        # Process Upcoming Dividends (high retail/institutional buying interest prior to ex-date)
        for row in div_rows:
            sym = row["symbol"].upper()
            days_to_ex = (row["ex_date"] - datetime.now().date()).days if row["ex_date"] else 3
            day_str = f"in {days_to_ex} days" if days_to_ex > 0 else "tomorrow"
            amt_str = f"₹{row['amount']}" if row['amount'] else "Dividend"

            if sym not in candidates:
                candidates[sym] = {
                    "stock_id": row["stock_id"],
                    "symbol": sym,
                    "name": row["name"] or sym,
                    "exchange": row["exchange"] or "NSE",
                    "market": row["market"] or "IN",
                    "current_price": float(row["current_price"]) if row["current_price"] else None,
                    "change_pct": float(row["change_pct"]) if row["change_pct"] else 0.0,
                    "currency": row["currency"] or "INR",
                    "sector": row["sector"] or "Dividend Player",
                    "expected_trend": "BULLISH",
                    "catalyst_badge": "Upcoming Dividend",
                    "catalyst_headline": f"Ex-date {day_str} ({amt_str} per share)",
                    "catalyst_summary": f"Dividend capture buying momentum expected ahead of {row['ex_date']} ex-date.",
                    "confidence": 0.82,
                    "timeframe": f"Until Ex-date ({day_str})",
                    "rank_score": 1.25,
                }
            else:
                # Augment existing candidate
                candidates[sym]["catalyst_summary"] += f" Also has {amt_str} dividend ex-date {day_str}."
                candidates[sym]["rank_score"] += 0.4

        # Process Extreme Price Movers
        for row in price_mover_rows:
            sym = row["symbol"].upper()
            pct = float(row["change_pct"])
            if sym not in candidates:
                trend = "STRONG_BULLISH" if pct > 0 else "BEARISH"
                badge = "Momentum Breakout" if pct > 0 else "Sharp Correction"
                candidates[sym] = {
                    "stock_id": row["stock_id"],
                    "symbol": sym,
                    "name": row["name"] or sym,
                    "exchange": row["exchange"] or "NSE",
                    "market": row["market"] or "IN",
                    "current_price": float(row["current_price"]) if row["current_price"] else None,
                    "change_pct": pct,
                    "currency": row["currency"] or "INR",
                    "sector": row["sector"] or "Active",
                    "expected_trend": trend,
                    "catalyst_badge": badge,
                    "catalyst_headline": f"High momentum move of {pct:+.1f}%",
                    "catalyst_summary": f"Strong volume surge indicates active institutional accumulation/distribution.",
                    "confidence": 0.75,
                    "timeframe": "Next 3-5 Days",
                    "rank_score": min(abs(pct) / 5.0, 1.2),
                }

        # Sort by rank_score descending
        ranked = sorted(candidates.values(), key=lambda x: x.get("rank_score", 0), reverse=True)
        return ranked[:limit]


weekly_movers_engine = WeeklyMoversEngine()
