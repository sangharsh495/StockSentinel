"""
Stock Screener Engine — Multi-factor ML scoring system that ranks stocks
using a composite research score (0–100) with letter grades (A+ to D).

Scoring Factors (Phase 1 Buffett-Upgraded):
  - Valuation Score (15%): P/E, PEG, margin of safety from stock_ratios
  - Financial Health (15%): ROE, D/E, current ratio from stock_ratios
  - Catalyst Momentum (15%): Recent extreme news catalysts
  - Price Momentum (15%): 5-day trend + volume surge
  - Sentiment Score (10%): Aggregate bullish/bearish news ratio
  - Dividend Signal (10%): Upcoming ex-dates within 30 days
  - Volume Breakout (10%): Current volume vs historical average
  - Market Cap Stability (10%): Large/mid-cap reliability bias
"""

import logging
import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from app.database import get_pool
from app.ml.catalyst_analyzer import catalyst_analyzer

logger = logging.getLogger(__name__)

# Grade thresholds
GRADES = [
    (90, "A+"), (80, "A"), (70, "B+"), (60, "B"),
    (50, "C+"), (40, "C"), (30, "D+"), (0, "D"),
]

ACTIONS = {
    "A+": "Strong Buy", "A": "Strong Buy", "B+": "Buy", "B": "Buy",
    "C+": "Hold", "C": "Hold", "D+": "Avoid", "D": "Avoid",
}


def _score_to_grade(score: float) -> str:
    for threshold, grade in GRADES:
        if score >= threshold:
            return grade
    return "D"


class StockScreener:
    """Ranks stocks using multi-factor composite research scoring."""

    async def screen(
        self,
        sector: Optional[str] = None,
        market: Optional[str] = None,
        min_market_cap: Optional[int] = None,
        min_score: float = 0,
        has_catalyst: bool = False,
        has_dividend: bool = False,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Screen and rank stocks based on multi-factor scoring.
        Returns ranked list with research_score, research_grade, key_reasons, recommended_action.
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Build dynamic WHERE clause
            conditions = ["s.is_active = TRUE"]
            params = []
            idx = 1

            if market:
                conditions.append(f"s.market = ${idx}")
                params.append(market.upper())
                idx += 1

            if sector:
                conditions.append(f"LOWER(s.sector) LIKE ${idx}")
                params.append(f"%{sector.lower()}%")
                idx += 1

            if min_market_cap:
                conditions.append(f"s.market_cap >= ${idx}")
                params.append(min_market_cap)
                idx += 1

            where = " AND ".join(conditions)

            # 1. Fetch candidate stocks (top by market cap for manageable set)
            stocks = await conn.fetch(
                f"""
                SELECT s.id, s.symbol, s.name, s.exchange, s.market, s.sector,
                       s.current_price, s.prev_close, s.change_pct, s.volume,
                       s.market_cap, s.currency, s.last_updated
                FROM stocks s
                WHERE {where}
                  AND s.current_price IS NOT NULL
                  AND s.current_price > 0
                ORDER BY s.market_cap DESC NULLS LAST
                LIMIT 500
                """,
                *params,
            )

            if not stocks:
                return []

            # 2. Batch-fetch catalyst news from last 72h
            symbol_list = [s["symbol"] for s in stocks]
            news_impacts = await conn.fetch(
                """
                SELECT nsi.symbol, nsi.impact_direction, nsi.impact_score,
                       n.title, n.sentiment
                FROM news_stock_impact nsi
                JOIN news n ON nsi.news_id = n.id
                WHERE n.published_at >= NOW() - INTERVAL '72 hours'
                  AND UPPER(nsi.symbol) = ANY($1::text[])
                ORDER BY nsi.impact_score DESC
                """,
                [s.upper() for s in symbol_list],
            )

            # Group news by symbol
            news_by_symbol: Dict[str, list] = {}
            for ni in news_impacts:
                sym = ni["symbol"].upper()
                news_by_symbol.setdefault(sym, []).append(dict(ni))

            # 3. Batch-fetch upcoming dividends (next 30 days)
            upcoming_divs = await conn.fetch(
                """
                SELECT UPPER(symbol) as symbol, amount, ex_date, dividend_type
                FROM dividends
                WHERE ex_date >= CURRENT_DATE
                  AND ex_date <= CURRENT_DATE + INTERVAL '30 days'
                  AND UPPER(symbol) = ANY($1::text[])
                """,
                [s.upper() for s in symbol_list],
            )

            div_by_symbol: Dict[str, list] = {}
            for d in upcoming_divs:
                sym = d["symbol"]
                div_by_symbol.setdefault(sym, []).append(dict(d))

            # 4. Batch-fetch financial ratios (Phase 1: valuation + health)
            ratios_by_symbol: Dict[str, dict] = {}
            try:
                ratios = await conn.fetch(
                    """
                    SELECT symbol, pe_ratio, pb_ratio, peg_ratio, ev_ebitda, forward_pe,
                           roe_pct, roce_pct, net_margin_pct, operating_margin_pct,
                           debt_to_equity, current_ratio, interest_coverage,
                           fcf_yield_pct, revenue_cagr_3y, profit_cagr_3y,
                           dividend_yield_pct, overall_financial_grade
                    FROM stock_ratios
                    WHERE UPPER(symbol) = ANY($1::text[])
                    """,
                    [s.upper() for s in symbol_list],
                )
                for r in ratios:
                    ratios_by_symbol[r["symbol"].upper()] = dict(r)
            except Exception as e:
                logger.debug(f"stock_ratios table not yet available: {e}")

        # 5. Score each stock
        scored = []
        for stock in stocks:
            sym = stock["symbol"].upper()
            score, reasons = self._compute_score(
                stock,
                news_by_symbol.get(sym, []),
                div_by_symbol.get(sym, []),
                ratios_by_symbol.get(sym, {}),
            )

            # Apply filters
            if has_catalyst and not news_by_symbol.get(sym):
                continue
            if has_dividend and not div_by_symbol.get(sym):
                continue
            if score < min_score:
                continue

            grade = _score_to_grade(score)
            scored.append({
                "symbol": stock["symbol"],
                "name": stock["name"],
                "exchange": stock["exchange"],
                "market": stock["market"],
                "sector": stock["sector"],
                "current_price": float(stock["current_price"]) if stock["current_price"] else None,
                "change_pct": float(stock["change_pct"]) if stock["change_pct"] else None,
                "volume": stock["volume"],
                "market_cap": stock["market_cap"],
                "currency": stock["currency"],
                "research_score": round(score, 1),
                "research_grade": grade,
                "recommended_action": ACTIONS.get(grade, "Hold"),
                "key_reasons": reasons[:3],
                "catalyst_count": len(news_by_symbol.get(sym, [])),
                "has_upcoming_dividend": bool(div_by_symbol.get(sym)),
                "financial_grade": ratios_by_symbol.get(sym, {}).get("overall_financial_grade"),
            })

        # Sort by score descending
        scored.sort(key=lambda x: x["research_score"], reverse=True)
        return scored[:limit]

    def _compute_score(
        self, stock: dict, news_items: list, dividends: list, ratios: dict
    ) -> tuple:
        """Compute composite research score (0-100) with weighted factors."""
        reasons = []
        total_score = 0.0

        # --- Factor 1: Valuation Score (15%) [NEW] ---
        val_score = 50.0
        pe = ratios.get("pe_ratio")
        peg = ratios.get("peg_ratio")
        if pe is not None:
            pe_f = float(pe)
            if 0 < pe_f < 12:
                val_score = 90
                reasons.append(f"Attractive valuation (P/E {pe_f:.1f})")
            elif pe_f < 20:
                val_score = 75
            elif pe_f < 30:
                val_score = 55
            elif pe_f < 50:
                val_score = 35
            else:
                val_score = 15
        if peg is not None:
            peg_f = float(peg)
            if 0 < peg_f < 1:
                val_score = min(val_score + 15, 100)
                reasons.append(f"Undervalued vs growth (PEG {peg_f:.2f})")
            elif peg_f < 1.5:
                val_score = min(val_score + 8, 100)
        total_score += val_score * 0.15

        # --- Factor 2: Financial Health (15%) [NEW] ---
        health_score = 50.0
        roe = ratios.get("roe_pct")
        d2e = ratios.get("debt_to_equity")
        cr = ratios.get("current_ratio")
        margin = ratios.get("net_margin_pct")

        if roe is not None:
            roe_f = float(roe)
            if roe_f > 20:
                health_score += 15
            elif roe_f > 12:
                health_score += 8
            elif roe_f < 5:
                health_score -= 10

        if d2e is not None:
            d2e_f = float(d2e)
            d2e_norm = d2e_f / 100 if d2e_f > 5 else d2e_f
            if d2e_norm < 0.3:
                health_score += 15
                reasons.append(f"Low debt (D/E {d2e_norm:.2f})")
            elif d2e_norm < 0.8:
                health_score += 8
            elif d2e_norm > 1.5:
                health_score -= 10

        if margin is not None:
            margin_f = float(margin)
            if margin_f > 15:
                health_score += 10
            elif margin_f > 8:
                health_score += 5

        health_score = max(0, min(100, health_score))
        total_score += health_score * 0.15

        # --- Factor 3: Catalyst Momentum (15%) ---
        catalyst_score = 0.0
        if news_items:
            extreme_count = 0
            for ni in news_items[:10]:
                analysis = catalyst_analyzer.analyze_headline(ni.get("title", ""), "")
                if analysis["is_extreme"]:
                    extreme_count += 1
                imp = float(ni.get("impact_score") or 0)
                catalyst_score += imp * 20

            catalyst_score = min(catalyst_score, 100)

            if extreme_count > 0:
                reasons.append(f"{extreme_count} extreme catalyst(s) in last 72h")
            elif len(news_items) >= 3:
                reasons.append(f"{len(news_items)} news catalysts detected")

        total_score += catalyst_score * 0.15

        # --- Factor 4: Price Momentum (15%) ---
        momentum_score = 50.0
        change_pct = float(stock["change_pct"] or 0)

        if change_pct > 5:
            momentum_score = 95
            reasons.append(f"Strong upward momentum (+{change_pct:.1f}%)")
        elif change_pct > 2:
            momentum_score = 80
            reasons.append(f"Positive momentum (+{change_pct:.1f}%)")
        elif change_pct > 0:
            momentum_score = 65
        elif change_pct > -2:
            momentum_score = 45
        elif change_pct > -5:
            momentum_score = 30
        else:
            momentum_score = 15
            reasons.append(f"Under selling pressure ({change_pct:.1f}%)")

        total_score += momentum_score * 0.15

        # --- Factor 5: Sentiment Score (10%) ---
        sentiment_score = 50.0
        if news_items:
            bullish = sum(1 for n in news_items if n.get("impact_direction") == "BULLISH")
            bearish = sum(1 for n in news_items if n.get("impact_direction") == "BEARISH")
            total_news = len(news_items)
            if total_news > 0:
                bull_ratio = bullish / total_news
                sentiment_score = bull_ratio * 100
                if bull_ratio > 0.7:
                    reasons.append(f"Strong bullish sentiment ({bullish}/{total_news} news)")

        total_score += sentiment_score * 0.10

        # --- Factor 6: Dividend Signal (10%) ---
        div_score = 30.0
        if dividends:
            div_score = 85.0
            amounts = [float(d.get("amount") or 0) for d in dividends if d.get("amount")]
            if amounts:
                total_div = sum(amounts)
                price = float(stock["current_price"] or 1)
                approx_yield = (total_div / price) * 100 if price > 0 else 0
                if approx_yield > 2:
                    div_score = 95
                    reasons.append(f"Dividend ex-date coming (~{approx_yield:.1f}% yield)")
                else:
                    reasons.append(f"Upcoming dividend (₹{total_div:.2f})")

        total_score += div_score * 0.10

        # --- Factor 7: Volume Breakout (10%) ---
        volume_score = 50.0
        vol = stock.get("volume") or 0
        if vol > 0:
            mcap = stock.get("market_cap") or 0
            if mcap > 100_000_000_000:
                expected_vol = 5_000_000
            elif mcap > 10_000_000_000:
                expected_vol = 1_000_000
            else:
                expected_vol = 200_000

            vol_ratio = vol / expected_vol if expected_vol > 0 else 1
            if vol_ratio > 3:
                volume_score = 95
                reasons.append("Unusual volume spike detected")
            elif vol_ratio > 1.5:
                volume_score = 75
            elif vol_ratio > 0.5:
                volume_score = 50
            else:
                volume_score = 25

        total_score += volume_score * 0.10

        # --- Factor 8: Market Cap Stability (10%) ---
        mcap_score = 50.0
        mcap = stock.get("market_cap") or 0
        if mcap > 500_000_000_000:
            mcap_score = 90
        elif mcap > 100_000_000_000:
            mcap_score = 80
        elif mcap > 10_000_000_000:
            mcap_score = 60
        elif mcap > 1_000_000_000:
            mcap_score = 40
        else:
            mcap_score = 20

        total_score += mcap_score * 0.10

        # Ensure within bounds
        total_score = max(0, min(100, total_score))

        # Add fallback reason if none generated
        if not reasons:
            if total_score >= 60:
                reasons.append("Stable fundamentals with balanced profile")
            else:
                reasons.append("Limited catalyst activity")

        return total_score, reasons


# Singleton
stock_screener = StockScreener()

