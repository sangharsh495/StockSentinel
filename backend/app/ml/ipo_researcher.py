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
            report = self._generate_fallback(ipo_data, await self._model_view(company_name))

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
        report["price_band_low"] = float(ipo_data["price_band_low"]) if ipo_data.get("price_band_low") else None
        report["price_band_high"] = float(ipo_data["price_band_high"]) if ipo_data.get("price_band_high") else None
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

    @staticmethod
    def _norm(name: str) -> str:
        import re
        n = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
        drop = {"ltd", "limited", "ipo", "pvt", "private", "the", "india", "co", "company", "sme"}
        return " ".join(w for w in n.split() if w not in drop)

    async def _model_view(self, company_name: str) -> Optional[Dict[str, Any]]:
        """The tested IPO listing model's prediction for this company, if it has one."""
        try:
            async with (await get_pool()).acquire() as conn:
                rows = await conn.fetch("SELECT payload FROM quant_predictions WHERE model_key = 'ipo_listing'")
        except Exception:
            return None
        target = self._norm(company_name)
        if not target:
            return None
        for r in rows:
            p = json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"]
            other = self._norm(p.get("name", ""))
            if other and (other == target or other in target or target in other):
                return p
        return None

    def _generate_fallback(self, ipo_data: dict, model: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Report built from our own data and the tested IPO model, used when no AI key is configured."""
        name = ipo_data.get("company_name", "Unknown Company")
        cur = "₹" if ipo_data.get("market", "IN") == "IN" else "$"
        gmp = float(ipo_data.get("gmp") or 0)
        low = float(ipo_data.get("price_band_low") or 0)
        high = float(ipo_data.get("price_band_high") or 0)
        gmp_pct = gmp / high * 100 if gmp and high else None
        sub = ipo_data.get("subscription_status") or {}
        if isinstance(sub, str):
            try:
                sub = json.loads(sub)
            except ValueError:
                sub = {}
        total_x = None
        for k in ("total", "overall", "Total"):
            try:
                total_x = float(sub.get(k)) if sub.get(k) is not None else None
            except (TypeError, ValueError):
                total_x = None
            if total_x is not None:
                break
        if model and model.get("subscription_x") is not None:
            total_x = model["subscription_x"]

        prob = (model or {}).get("probability")
        exp = (model or {}).get("expected_gain_pct")
        rng = (model or {}).get("expected_range_pct") or [None, None]
        track = (model or {}).get("track_record_at_this_confidence") or {}

        if prob is not None and exp is not None:
            if prob >= 0.75 and exp > 0:
                verdict = "SUBSCRIBE"
            elif prob < 0.5 or exp < 0:
                verdict = "AVOID"
            else:
                verdict = "RISKY_BET"
            confidence = int(round(prob * 100))
            rationale = (f"Tested IPO model: expected listing gain {exp:+.1f}%"
                         + (f" (likely range {rng[0]:+.0f}% to {rng[1]:+.0f}%)" if rng[0] is not None else "")
                         + f", {prob * 100:.0f}% chance of listing above the issue price.")
            if track.get("ipos"):
                rationale += (f" Past IPOs at this confidence: {track['listed_positive_pct']:.0f}% listed positive "
                              f"({track['ipos']} IPOs).")
        elif gmp_pct is not None:
            verdict = "SUBSCRIBE" if gmp_pct > 30 else "RISKY_BET" if gmp_pct > 10 else "AVOID"
            confidence = 60 if gmp_pct > 30 else 45 if gmp_pct > 10 else 35
            rationale = (f"Grey market premium is {gmp_pct:.0f}% of the issue price. The tested IPO model has no "
                         "estimate for this issue yet, so this is the GMP signal alone.")
        else:
            verdict, confidence = "RISKY_BET", 30
            rationale = "No GMP and no model estimate yet: not enough data for a confident call."

        facts = [f"Price band {cur}{low:,.0f} - {cur}{high:,.0f}" if high else "Price band not announced yet"]
        if ipo_data.get("lot_size"):
            facts.append(f"lot of {ipo_data['lot_size']} shares")
        if ipo_data.get("issue_size"):
            facts.append(f"issue size {ipo_data['issue_size']}")
        dates = f"bidding {ipo_data.get('open_date') or 'TBD'} to {ipo_data.get('close_date') or 'TBD'}"

        buy, avoid = [], []
        if gmp_pct is not None:
            (buy if gmp_pct > 10 else avoid).append(f"Grey market premium {gmp_pct:+.0f}% of the issue price")
        if total_x is not None:
            (buy if total_x >= 10 else avoid).append(f"Subscribed {total_x:.1f}x overall")
        if prob is not None:
            (buy if prob >= 0.6 else avoid).append(f"Model: {prob * 100:.0f}% chance of a positive listing")
        if (model or {}).get("gmp_check") == "disagree":
            avoid.append("GMP sources disagree: treat the premium with caution")
        if model and not model.get("subscription_known"):
            avoid.append("Bidding not started: estimate rests on GMP only")
        if not buy:
            buy.append("No strong positive signal yet")
        if not avoid:
            avoid.append("Listing gains are never guaranteed; markets can turn before listing day")

        no_ai = "Company description needs the AI write-up (not configured) or the offer document (DRHP on sebi.gov.in)."
        return {
            "company_overview": f"{name}: {', '.join(facts)}; {dates}. {no_ai}",
            "business_model": "Read the 'Our Business' section of the DRHP on sebi.gov.in for how the company earns money.",
            "industry_position": "See the 'Industry Overview' section of the DRHP for competitors and market size.",
            "financial_snapshot": {
                "revenue_description": "Revenue and profit history are in the DRHP's 'Financial Information' section",
                "profitability": f"GMP {cur}{gmp:,.0f}" + (f" ({gmp_pct:+.1f}% of the issue price)" if gmp_pct is not None else ""),
                "debt_status": f"Subscription {total_x:.1f}x overall" if total_x is not None else "Subscription data not out yet",
                "key_metrics": (f"Model expected listing gain {exp:+.1f}%, chance positive {prob * 100:.0f}%"
                                if prob is not None and exp is not None else "No model estimate for this issue yet"),
            },
            "promoter_management": "Promoters and management are listed in the DRHP.",
            "valuation_assessment": rationale,
            "strengths": buy,
            "risks": avoid,
            "reasons_to_buy": buy,
            "reasons_not_to_buy": avoid,
            "verdict": verdict,
            "verdict_confidence_pct": confidence,
            "verdict_rationale": rationale,
            "source": "model_and_data" if model else "data_only",
        }


# Singleton
ipo_researcher = IPOResearcher()
