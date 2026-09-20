"""
IPO Researcher Engine — Generates comprehensive AI-powered IPO research reports
using Gemini/Groq with offline fallback.

Report Format:
  1. Company Overview — What does the company do
  2. Business Model — How they make money
  3. Industry Position — Market share, competitors, TAM
  4. Financial Snapshot — Revenue, PAT, margins
  5. Promoter & Management — Key people, holding %
  6. IPO Valuation Assessment — P/E vs industry, GMP analysis
  7. Strengths & Risks — SWOT-style
  8. Reasons to Buy — Concrete bullish arguments
  9. Reasons NOT to Buy — Concrete risks
  10. AI Verdict — SUBSCRIBE / AVOID / RISKY BET
"""

import json
import logging
from typing import Dict, Any, Optional
import requests

from app.database import get_pool
from app.config import settings

logger = logging.getLogger(__name__)

# AI prompt template for IPO research
IPO_RESEARCH_PROMPT = """You are an institutional equity research analyst. Generate a comprehensive IPO research report for the following company.

Company: {company_name}
Market: {market}
Price Band: {price_band}
Lot Size: {lot_size}
Issue Size: {issue_size}
Open Date: {open_date}
Close Date: {close_date}
GMP: {gmp}
Subscription Status: {subscription}

Generate a structured JSON report with these exact keys:
{{
  "company_overview": "2-3 paragraph description of what the company does, main products/services, key subsidiaries",
  "business_model": "How they make money: B2B vs B2C, recurring vs one-time revenue, key revenue streams",
  "industry_position": "Market share, main competitors, total addressable market size, industry growth rate",
  "financial_snapshot": {{
    "revenue_description": "Revenue trend description",
    "profitability": "PAT and margin description",
    "debt_status": "Debt-to-equity and financial health",
    "key_metrics": "P/E, EPS, book value if available"
  }},
  "promoter_management": "Key promoters, management team, promoter holding %, institutional interest",
  "valuation_assessment": "P/E vs industry average, price band analysis, GMP interpretation, fair value estimate",
  "strengths": ["strength 1", "strength 2", "strength 3", "strength 4", "strength 5"],
  "risks": ["risk 1", "risk 2", "risk 3", "risk 4", "risk 5"],
  "reasons_to_buy": ["reason 1", "reason 2", "reason 3", "reason 4"],
  "reasons_not_to_buy": ["reason 1", "reason 2", "reason 3", "reason 4"],
  "verdict": "SUBSCRIBE or AVOID or RISKY_BET",
  "verdict_confidence_pct": 75,
  "verdict_rationale": "2-3 sentence summary of why this verdict"
}}

Be specific and factual. If you don't know actual financials, state reasonable industry estimates.
Return ONLY the JSON object, no markdown or explanation."""


class IPOResearcher:
    """Generates AI-powered comprehensive IPO research reports."""

    async def generate_report(self, ipo_id: int) -> Dict[str, Any]:
        """Generate a full IPO research report by ID."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            ipo = await conn.fetchrow(
                "SELECT * FROM ipos WHERE id = $1", ipo_id
            )

        if not ipo:
            return {"error": f"IPO with id {ipo_id} not found"}

        ipo_data = dict(ipo)
        company_name = ipo_data.get("company_name", "Unknown")

        # Format data for prompt
        price_band = "TBD"
        if ipo_data.get("price_band_low") and ipo_data.get("price_band_high"):
            currency = "₹" if ipo_data.get("market") == "IN" else "$"
            price_band = f"{currency}{ipo_data['price_band_low']} - {currency}{ipo_data['price_band_high']}"

        context = {
            "company_name": company_name,
            "market": ipo_data.get("market", "IN"),
            "price_band": price_band,
            "lot_size": ipo_data.get("lot_size") or "N/A",
            "issue_size": ipo_data.get("issue_size") or "N/A",
            "open_date": str(ipo_data.get("open_date") or "TBD"),
            "close_date": str(ipo_data.get("close_date") or "TBD"),
            "gmp": f"₹{ipo_data['gmp']}" if ipo_data.get("gmp") else "N/A",
            "subscription": json.dumps(ipo_data.get("subscription_status") or {}),
        }

        prompt = IPO_RESEARCH_PROMPT.format(**context)

        # Try Gemini first, then Groq, then fallback
        report = None
        report = await self._try_gemini(prompt)
        if not report:
            report = await self._try_groq(prompt)
        if not report:
            report = self._generate_fallback(ipo_data)

        # Attach IPO metadata
        report["ipo_id"] = ipo_id
        report["company_name"] = company_name
        report["market"] = ipo_data.get("market", "IN")
        report["price_band"] = price_band
        report["lot_size"] = ipo_data.get("lot_size")
        report["issue_size"] = ipo_data.get("issue_size")
        report["open_date"] = str(ipo_data.get("open_date") or "TBD")
        report["close_date"] = str(ipo_data.get("close_date") or "TBD")
        report["listing_date"] = str(ipo_data.get("listing_date") or "TBD")
        report["status"] = ipo_data.get("status", "upcoming")
        report["gmp"] = float(ipo_data["gmp"]) if ipo_data.get("gmp") else None
        report["subscription_status"] = ipo_data.get("subscription_status")

        return report

    async def _try_gemini(self, prompt: str) -> Optional[Dict]:
        """Try generating report via Google Gemini."""
        if not settings.GEMINI_API_KEY:
            return None

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
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
        except Exception as e:
            logger.warning(f"Gemini IPO report failed: {e}")
        return None

    async def _try_groq(self, prompt: str) -> Optional[Dict]:
        """Try generating report via Groq."""
        if not settings.GROQ_API_KEY:
            return None

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
                return json.loads(text)
        except Exception as e:
            logger.warning(f"Groq IPO report failed: {e}")
        return None

    def _generate_fallback(self, ipo_data: dict) -> Dict[str, Any]:
        """Deterministic fallback report when AI is unavailable."""
        name = ipo_data.get("company_name", "Unknown Company")
        market = ipo_data.get("market", "IN")
        gmp = float(ipo_data.get("gmp") or 0)
        price_high = float(ipo_data.get("price_band_high") or 0)

        # Simple heuristic verdict based on GMP
        if gmp > 0 and price_high > 0:
            gmp_pct = (gmp / price_high) * 100
            if gmp_pct > 30:
                verdict = "SUBSCRIBE"
                confidence = 70
                rationale = f"Strong grey market premium of {gmp_pct:.0f}% indicates high retail demand."
            elif gmp_pct > 10:
                verdict = "RISKY_BET"
                confidence = 50
                rationale = f"Moderate GMP of {gmp_pct:.0f}%. Consider fundamentals before applying."
            else:
                verdict = "AVOID"
                confidence = 40
                rationale = f"Weak GMP of {gmp_pct:.0f}%. Market interest is limited."
        else:
            verdict = "RISKY_BET"
            confidence = 35
            rationale = "Insufficient data for a confident recommendation. Research further."

        return {
            "company_overview": f"{name} is a company in the {'Indian' if market == 'IN' else 'US'} market filing for an IPO. Detailed business information requires AI analysis.",
            "business_model": "Business model details unavailable in offline mode. Check the DRHP/prospectus for revenue breakdown.",
            "industry_position": "Industry analysis requires AI. Check sectoral reports for competitive landscape.",
            "financial_snapshot": {
                "revenue_description": "Financial data not available in offline mode",
                "profitability": "Check DRHP for PAT and margin data",
                "debt_status": "Debt metrics unavailable",
                "key_metrics": "P/E and valuation metrics require AI analysis",
            },
            "promoter_management": "Promoter and management details available in the DRHP document.",
            "valuation_assessment": f"Price band assessment: {'GMP suggests positive listing' if gmp > 0 else 'GMP data unavailable'}.",
            "strengths": [
                "IPO provides growth capital for expansion",
                "Public listing improves brand visibility",
                "Institutional investors provide credibility",
            ],
            "risks": [
                "IPO pricing may be at premium valuations",
                "Post-listing volatility is common",
                "Limited public financial history available",
                "Lock-in period expiry may create selling pressure",
            ],
            "reasons_to_buy": [
                "Growth potential in expanding market",
                f"{'Positive GMP indicates listing gains' if gmp > 0 else 'Early entry opportunity'}",
            ],
            "reasons_not_to_buy": [
                "Limited operating history as public company",
                "Valuation may not justify long-term returns",
                "Market conditions may impact listing performance",
            ],
            "verdict": verdict,
            "verdict_confidence_pct": confidence,
            "verdict_rationale": rationale,
            "ai_generated": False,
        }


# Singleton
ipo_researcher = IPOResearcher()
