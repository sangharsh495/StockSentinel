"""
AI Institutional Research Analyst — synthesizes stock fundamentals, news catalysts,
and corporate action calendar into an institutional analyst research dossier.

Supports:
1. Google Gemini (gemini-2.0-flash-lite / gemini-1.5-flash)
2. Groq (llama-3.1-8b-instant)
3. Deterministic rule-based fallback (100% offline, zero downtime)
"""

import json
import logging
import asyncio
from typing import Dict, Any, Optional
import requests

from app.database import get_pool
from app.config import settings
from app.ml.catalyst_analyzer import catalyst_analyzer

logger = logging.getLogger(__name__)


class AIAnalyst:
    """Generates on-demand institutional research dossiers for any stock."""

    async def generate_dossier(self, symbol: str) -> Dict[str, Any]:
        """Generate comprehensive analyst research dossier for a stock."""
        symbol_upper = symbol.strip().upper()

        pool = await get_pool()
        async with pool.acquire() as conn:
            # 1. Fetch stock data
            stock = await conn.fetchrow(
                """
                SELECT id, symbol, name, exchange, market, sector, industry,
                       current_price, prev_close, day_high, day_low, open_price,
                       volume, market_cap, change_pct, currency, last_updated
                FROM stocks
                WHERE UPPER(symbol) = $1
                ORDER BY market_cap DESC NULLS LAST
                LIMIT 1
                """,
                symbol_upper,
            )

            if not stock:
                return {"error": f"Stock '{symbol_upper}' not found in database", "symbol": symbol_upper}

            # 2. Fetch stock-specific news with impact
            news_items = await conn.fetch(
                """
                SELECT n.title, n.summary, n.source, n.published_at, n.sentiment,
                       nsi.impact_direction, nsi.impact_score, nsi.reason
                FROM news_stock_impact nsi
                JOIN news n ON nsi.news_id = n.id
                WHERE UPPER(nsi.symbol) = $1
                ORDER BY n.published_at DESC
                LIMIT 6
                """,
                symbol_upper,
            )

            # 3. Fetch upcoming dividends
            dividends = await conn.fetch(
                """
                SELECT dividend_type, amount, ex_date, status
                FROM dividends
                WHERE UPPER(symbol) = $1 AND ex_date >= CURRENT_DATE - INTERVAL '30 days'
                ORDER BY ex_date DESC
                LIMIT 3
                """,
                symbol_upper,
            )

        # Build context payload
        context = {
            "symbol": stock["symbol"],
            "name": stock["name"] or stock["symbol"],
            "exchange": stock["exchange"] or "NSE",
            "market": stock["market"] or "IN",
            "sector": stock["sector"] or "General",
            "industry": stock["industry"] or "Diversified",
            "current_price": float(stock["current_price"]) if stock["current_price"] else None,
            "change_pct": float(stock["change_pct"]) if stock["change_pct"] else 0.0,
            "day_high": float(stock["day_high"]) if stock["day_high"] else None,
            "day_low": float(stock["day_low"]) if stock["day_low"] else None,
            "currency": stock["currency"] or "INR",
            "news": [
                {
                    "title": row["title"],
                    "sentiment": row["sentiment"],
                    "impact": row["impact_direction"],
                }
                for row in news_items
            ],
            "dividends": [
                {
                    "type": row["dividend_type"],
                    "amount": float(row["amount"]) if row["amount"] else None,
                    "ex_date": str(row["ex_date"]),
                }
                for row in dividends
            ],
        }

        # Strategy 1: Try Gemini API
        if settings.GEMINI_API_KEY:
            try:
                res = await self._call_gemini(context)
                if res:
                    return res
            except Exception as e:
                logger.warning(f"Gemini analyst generation failed: {e}")

        # Strategy 2: Try Groq API
        if settings.GROQ_API_KEY:
            try:
                res = await self._call_groq(context)
                if res:
                    return res
            except Exception as e:
                logger.warning(f"Groq analyst generation failed: {e}")

        # Strategy 3: Deterministic Rule-Based Fallback (Offline)
        return self._generate_rule_based(context)

    async def _call_gemini(self, ctx: dict) -> Optional[dict]:
        """Generate analysis via Google Gemini API."""
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)

        # Use fast lite model
        model = genai.GenerativeModel("gemini-2.0-flash-lite")

        prompt = f"""You are a senior institutional equity research analyst.
Analyze this company and return a STRICT JSON object with no markdown fences, no ```json, no preface.

Stock Data:
Company: {ctx['name']} ({ctx['symbol']}) | Exchange: {ctx['exchange']}
Price: {ctx['currency']} {ctx['current_price']} (Change: {ctx['change_pct']:+.2f}%)
Sector: {ctx['sector']} | Industry: {ctx['industry']}
Recent News: {json.dumps(ctx['news'][:4])}
Dividends: {json.dumps(ctx['dividends'][:2])}

Generate a concise, high-conviction analyst dossier:
{{
  "symbol": "{ctx['symbol']}",
  "name": "{ctx['name']}",
  "verdict": "STRONG_BUY_MOMENTUM | ACCUMULATE_ON_DIPS | NEUTRAL_CONSOLIDATION | HIGH_VOLATILITY_RISK",
  "conviction_score": 0.85,
  "trend_forecast": "1-2 sentence forecast on expected trend trajectory and key driver",
  "emerging_catalysts": [
    "First emerging growth catalyst or recent operational news point",
    "Second key catalyst or upcoming market trigger"
  ],
  "upcoming_events": "Upcoming corporate action, dividend ex-date or earnings expectation",
  "bull_case": "1 clear sentence stating the primary upside thesis",
  "bear_risk": "1 clear sentence stating the primary downside risk or watch item"
}}"""

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: model.generate_content(prompt))
        text = response.text.strip()

        # Clean markdown
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        data = json.loads(text)
        data["source"] = "Gemini AI"
        return data

    async def _call_groq(self, ctx: dict) -> Optional[dict]:
        """Generate analysis via Groq Chat Completions (Llama 3.1)."""
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json",
        }

        prompt = f"""You are an institutional equity research analyst. Analyze {ctx['name']} ({ctx['symbol']}) and return JSON only.
Price: {ctx['currency']} {ctx['current_price']} ({ctx['change_pct']:+.2f}%), Sector: {ctx['sector']}.
News: {json.dumps(ctx['news'][:3])}
Dividends: {json.dumps(ctx['dividends'][:1])}

Return JSON with exact keys:
{{
  "symbol": "{ctx['symbol']}",
  "name": "{ctx['name']}",
  "verdict": "STRONG_BUY_MOMENTUM" (or ACCUMULATE_ON_DIPS, NEUTRAL_CONSOLIDATION, HIGH_VOLATILITY_RISK),
  "conviction_score": 0.80,
  "trend_forecast": "1-2 sentences on trend trajectory and key driver",
  "emerging_catalysts": ["catalyst 1", "catalyst 2"],
  "upcoming_events": "Upcoming dividend or corporate event",
  "bull_case": "1 sentence bull thesis",
  "bear_risk": "1 sentence primary risk"
}}"""

        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }

        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(
            None,
            lambda: requests.post(url, headers=headers, json=payload, timeout=12),
        )

        if res.status_code == 200:
            content = res.json()["choices"][0]["message"]["content"]
            data = json.loads(content)
            data["source"] = "Groq Llama 3.1"
            return data
        return None

    def _generate_rule_based(self, ctx: dict) -> dict:
        """Deterministic, rule-based analyst engine (works 100% offline)."""
        pct = ctx["change_pct"]
        news_items = ctx["news"]
        divs = ctx["dividends"]

        # Verdict logic
        if pct >= 3.0:
            verdict = "STRONG_BUY_MOMENTUM"
            conviction = 0.85
            trend = f"{ctx['symbol']} exhibits powerful upside momentum with a gain of {pct:+.1f}%. Buyers in firm control."
        elif pct > 0.0:
            verdict = "ACCUMULATE_ON_DIPS"
            conviction = 0.75
            trend = f"Steady positive trajectory (+{pct:.1f}%). Ideal for systematic accumulation on minor pullbacks."
        elif pct <= -3.0:
            verdict = "HIGH_VOLATILITY_RISK"
            conviction = 0.80
            trend = f"Sharp pullback ({pct:+.1f}%). Selling pressure dominates; wait for base confirmation before entry."
        else:
            verdict = "NEUTRAL_CONSOLIDATION"
            conviction = 0.70
            trend = f"Consolidating within recent price range. Key breakout levels will dictate the next weekly directional move."

        # Catalysts
        catalysts = []
        if news_items:
            for item in news_items[:2]:
                catalysts.append(item["title"])
        if not catalysts:
            catalysts.append(f"Market tracking performance across {ctx['sector']} sector dynamics.")
            catalysts.append(f"Technical support and resistance forming near current {ctx['currency']} {ctx['current_price'] or ''} level.")

        # Upcoming events
        if divs:
            div = divs[0]
            upcoming_events = f"Upcoming dividend ({div.get('type', 'Interim')}) ex-date on {div.get('ex_date')}."
        else:
            upcoming_events = "Quarterly earnings results and institutional volume tracking."

        bull_case = f"Strong fundamentals in {ctx['sector']} and consistent business expansion provide solid upside backing."
        bear_risk = f"Broader market volatility and sector-wide profit booking could trigger short-term consolidation."

        return {
            "symbol": ctx["symbol"],
            "name": ctx["name"],
            "verdict": verdict,
            "conviction_score": conviction,
            "trend_forecast": trend,
            "emerging_catalysts": catalysts[:2],
            "upcoming_events": upcoming_events,
            "bull_case": bull_case,
            "bear_risk": bear_risk,
            "source": "StockSentinel Quantitative Rules Engine",
        }


ai_analyst = AIAnalyst()


# ---------------------------------------------------------------------------
# Enhanced Research Report Generator (extends base dossier)
# ---------------------------------------------------------------------------

# Prompt for full research report
FULL_RESEARCH_PROMPT = """You are a senior institutional equity research analyst writing a comprehensive
research note for {name} ({symbol}) listed on {exchange}.

Stock Data:
  Price: {currency} {current_price} (Change: {change_pct:+.2f}%)
  Market Cap: {market_cap_str}
  Sector: {sector} | Industry: {industry}
  Day Range: {day_low} – {day_high}
  Volume: {volume}
  Recent News: {news_summary}
  Dividends: {div_summary}

Generate a STRICT JSON research report (no markdown fences):
{{
  "company_profile": "2-paragraph company description: products, services, subsidiaries, geographic presence",
  "industry_competition": "1-paragraph on sector dynamics, 3 main competitors, market share context, TAM",
  "financial_scorecard": {{
    "revenue_growth": "Description of revenue growth trend (e.g. +18% CAGR)",
    "profit_margins": "EBITDA and PAT margin description",
    "debt_health": "Debt-to-equity ratio assessment",
    "cash_flow": "Operating cash flow health",
    "overall_grade": "A+ through D rating for financial health"
  }},
  "technical_summary": "2 sentences on support/resistance levels, RSI, moving average trend",
  "shareholding_pattern": {{
    "promoter_pct": 55.0,
    "fii_pct": 18.0,
    "dii_pct": 15.0,
    "public_pct": 12.0,
    "commentary": "1 sentence on shareholding quality"
  }},
  "peer_comparison": [
    {{"name": "Peer 1 Name", "pe_ratio": 25.0, "roe_pct": 18.0, "dividend_yield_pct": 1.5}},
    {{"name": "Peer 2 Name", "pe_ratio": 22.0, "roe_pct": 20.0, "dividend_yield_pct": 2.0}},
    {{"name": "Peer 3 Name", "pe_ratio": 28.0, "roe_pct": 15.0, "dividend_yield_pct": 1.0}}
  ],
  "investment_thesis": "3-paragraph thesis: (1) Why invest now (2) Key catalyst/trigger (3) What could go wrong and target price range",
  "research_grade": "A+ through D"
}}

Be specific. Use reasonable industry estimates if exact data unavailable. Return ONLY JSON."""


async def generate_full_research_report(symbol: str) -> Dict[str, Any]:
    """
    Generate an industry-standard equity research report that extends the
    basic dossier with financial scorecard, peer comparison, shareholding,
    and investment thesis.
    """
    symbol_upper = symbol.strip().upper()

    pool = await get_pool()
    async with pool.acquire() as conn:
        stock = await conn.fetchrow(
            """
            SELECT id, symbol, name, exchange, market, sector, industry,
                   current_price, prev_close, day_high, day_low, open_price,
                   volume, market_cap, change_pct, currency
            FROM stocks
            WHERE UPPER(symbol) = $1
            ORDER BY market_cap DESC NULLS LAST
            LIMIT 1
            """,
            symbol_upper,
        )

        if not stock:
            return {"error": f"Stock '{symbol_upper}' not found"}

        # Fetch recent news
        news_items = await conn.fetch(
            """
            SELECT n.title, n.sentiment, nsi.impact_direction
            FROM news_stock_impact nsi
            JOIN news n ON nsi.news_id = n.id
            WHERE UPPER(nsi.symbol) = $1
            ORDER BY n.published_at DESC
            LIMIT 4
            """,
            symbol_upper,
        )

        # Fetch dividends
        divs = await conn.fetch(
            """
            SELECT dividend_type, amount, ex_date
            FROM dividends
            WHERE UPPER(symbol) = $1
            ORDER BY ex_date DESC
            LIMIT 5
            """,
            symbol_upper,
        )

    # Format context
    mcap = stock["market_cap"]
    if mcap:
        if mcap > 1_000_000_000_000:
            mcap_str = f"₹{mcap / 1_000_000_000_000:.1f}T"
        elif mcap > 10_000_000_000:
            mcap_str = f"₹{mcap / 10_000_000:.0f}Cr"
        else:
            mcap_str = f"₹{mcap / 10_000_000:.1f}Cr"
    else:
        mcap_str = "N/A"

    news_summary = "; ".join([f"{n['title']} ({n['sentiment']})" for n in news_items[:3]]) or "No recent news"
    div_summary = "; ".join([
        f"{d['dividend_type']} ₹{d['amount']} ex:{d['ex_date']}"
        for d in divs[:2] if d.get("amount")
    ]) or "No recent dividends"

    ctx = {
        "name": stock["name"] or symbol_upper,
        "symbol": stock["symbol"],
        "exchange": stock["exchange"] or "NSE",
        "sector": stock["sector"] or "General",
        "industry": stock["industry"] or "Diversified",
        "currency": stock["currency"] or "INR",
        "current_price": float(stock["current_price"]) if stock["current_price"] else 0,
        "change_pct": float(stock["change_pct"]) if stock["change_pct"] else 0,
        "day_high": float(stock["day_high"]) if stock["day_high"] else 0,
        "day_low": float(stock["day_low"]) if stock["day_low"] else 0,
        "volume": stock["volume"] or 0,
        "market_cap_str": mcap_str,
        "news_summary": news_summary,
        "div_summary": div_summary,
    }

    prompt = FULL_RESEARCH_PROMPT.format(**ctx)

    # Try Gemini
    report = None
    if settings.GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "temperature": 0.3,
                    "maxOutputTokens": 4096,
                    "responseMimeType": "application/json",
                },
            }
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                report = json.loads(text)
                report["source"] = "Gemini AI"
        except Exception as e:
            logger.warning(f"Gemini research report failed: {e}")

    # Try Groq
    if not report and settings.GROQ_API_KEY:
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 4096,
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
            if resp.status_code == 200:
                text = resp.json()["choices"][0]["message"]["content"]
                report = json.loads(text)
                report["source"] = "Groq Llama 3.1"
        except Exception as e:
            logger.warning(f"Groq research report failed: {e}")

    # Fallback
    if not report:
        pct = ctx["change_pct"]
        if pct >= 2:
            grade = "B+"
        elif pct >= 0:
            grade = "B"
        elif pct >= -2:
            grade = "C+"
        else:
            grade = "C"

        report = {
            "company_profile": f"{ctx['name']} is a {'large-cap' if mcap and mcap > 100_000_000_000 else 'mid-cap'} company in the {ctx['sector']} sector listed on {ctx['exchange']}.",
            "industry_competition": f"Operates in the competitive {ctx['industry']} space. Full competitive analysis requires AI.",
            "financial_scorecard": {
                "revenue_growth": "Data requires AI analysis",
                "profit_margins": "Check quarterly filings",
                "debt_health": "Balance sheet review needed",
                "cash_flow": "Operating cash flow data unavailable",
                "overall_grade": grade,
            },
            "technical_summary": f"Stock at {ctx['currency']} {ctx['current_price']} within day range {ctx['day_low']}-{ctx['day_high']}.",
            "shareholding_pattern": {
                "promoter_pct": None,
                "fii_pct": None,
                "dii_pct": None,
                "public_pct": None,
                "commentary": "Shareholding data requires latest quarterly filings.",
            },
            "peer_comparison": [],
            "investment_thesis": f"Further analysis needed. Current price action shows {pct:+.1f}% movement with {'bullish' if pct > 0 else 'bearish'} bias.",
            "research_grade": grade,
            "source": "StockSentinel Rules Engine",
        }

    # Attach stock metadata
    report["symbol"] = stock["symbol"]
    report["name"] = stock["name"]
    report["exchange"] = stock["exchange"]
    report["market"] = stock["market"]
    report["current_price"] = ctx["current_price"]
    report["change_pct"] = ctx["change_pct"]
    report["currency"] = ctx["currency"]
    report["market_cap"] = mcap_str
    report["sector"] = ctx["sector"]

    # Attach dividend history summary
    report["dividend_history"] = [
        {
            "type": d["dividend_type"],
            "amount": float(d["amount"]) if d["amount"] else None,
            "ex_date": str(d["ex_date"]) if d["ex_date"] else None,
        }
        for d in divs[:5]
    ]

    return report
