"""
News Ranker Engine — Assigns a Market Impact Rating (1–10) to every news article
and produces daily Top-10 ranked lists with archive support.

Rating Scale:
  9–10: Extreme — Mergers, major order wins, regulatory bans, earnings shocks
  7–8:  High — Dividends, management changes, sector policy shifts
  5–6:  Medium — Quarterly results in-line, analyst upgrades/downgrades
  3–4:  Low — General commentary, minor operational updates
  1–2:  Noise — Rehashed articles, opinion pieces, market wraps
"""

import logging
import re
from typing import List, Dict, Any, Optional
from datetime import date, datetime

from app.database import get_pool, fetch
from app.ml.catalyst_analyzer import catalyst_analyzer

logger = logging.getLogger(__name__)

# Keywords for impact level detection
EXTREME_KEYWORDS = [
    r'\bmerger\b', r'\bacquisition\b', r'\btakeover\b', r'\bbuyout\b',
    r'\bban\b', r'\bsebi.*order\b', r'\bfraud\b', r'\bscam\b',
    r'\bearnings.*shock\b', r'\bprofit.*surge\b', r'\bprofit.*crash\b',
    r'\border.*win\b', r'\b\d+.*crore.*order\b', r'\b\d+.*billion.*deal\b',
    r'\bdelisting\b', r'\binsolvency\b', r'\bbankrupt\b',
    r'\brbi.*action\b', r'\bsebi.*penalty\b',
]

HIGH_KEYWORDS = [
    r'\bdividend\b', r'\bbonus\b', r'\bstock.*split\b', r'\bbuyback\b',
    r'\bceo.*resign\b', r'\bmd.*appoint\b', r'\bmanagement.*change\b',
    r'\bsector.*policy\b', r'\bgov.*subsidy\b', r'\btariff\b',
    r'\bupgrade\b', r'\bdowngrade\b', r'\btarget.*price\b',
    r'\bquarterly.*result\b', r'\bq[1-4].*result\b',
    r'\bfii.*bought\b', r'\bdii.*sold\b', r'\bblock.*deal\b',
]

MEDIUM_KEYWORDS = [
    r'\bquarterly\b', r'\bresults?\b', r'\banalyst\b', r'\bforecast\b',
    r'\bguidance\b', r'\boutlook\b', r'\bexpansion\b', r'\blaunch\b',
    r'\bpartnership\b', r'\bcollaboration\b', r'\bagreement\b',
]

NOISE_KEYWORDS = [
    r'\bmarket.*wrap\b', r'\bmarket.*today\b', r'\bopinion\b',
    r'\b(top|best).*stocks?\b', r'\bshould.*buy\b', r'\bshould.*sell\b',
    r'\btips?\b', r'\bpicks?\b', r'\bmultibagger\b',
]


class NewsRanker:
    """Assigns market impact ratings (1-10) to news articles."""

    def rate_article(self, title: str, summary: str = "") -> Dict[str, Any]:
        """
        Rate a single news article on a 1-10 impact scale.
        Returns rating, reason, and whether action is required.
        """
        combined = f"{title} {summary}".lower()

        # Check for extreme impact (9-10)
        for pattern in EXTREME_KEYWORDS:
            if re.search(pattern, combined, re.IGNORECASE):
                # Use catalyst analyzer for more precision
                analysis = catalyst_analyzer.analyze_headline(title, summary)
                if analysis["is_extreme"]:
                    return {
                        "rating": 10,
                        "rating_reason": f"Extreme market event: {analysis['catalyst_type'].replace('_', ' ').title()}",
                        "action_required": True,
                        "impact_level": "EXTREME",
                    }
                return {
                    "rating": 9,
                    "rating_reason": f"Major catalyst detected: {analysis['catalyst_type'].replace('_', ' ').title()}",
                    "action_required": True,
                    "impact_level": "EXTREME",
                }

        # Check for high impact (7-8)
        high_matches = sum(1 for p in HIGH_KEYWORDS if re.search(p, combined, re.IGNORECASE))
        if high_matches >= 2:
            analysis = catalyst_analyzer.analyze_headline(title, summary)
            return {
                "rating": 8,
                "rating_reason": f"High-impact: Multiple catalysts ({analysis['catalyst_type'].replace('_', ' ').title()})",
                "action_required": True,
                "impact_level": "HIGH",
            }
        elif high_matches == 1:
            analysis = catalyst_analyzer.analyze_headline(title, summary)
            return {
                "rating": 7,
                "rating_reason": f"Notable catalyst: {analysis['catalyst_type'].replace('_', ' ').title()}",
                "action_required": False,
                "impact_level": "HIGH",
            }

        # Check for noise first (1-2) before medium
        noise_matches = sum(1 for p in NOISE_KEYWORDS if re.search(p, combined, re.IGNORECASE))
        if noise_matches >= 2:
            return {
                "rating": 1,
                "rating_reason": "Noise: Rehashed opinion or generic market wrap",
                "action_required": False,
                "impact_level": "NOISE",
            }
        elif noise_matches == 1:
            return {
                "rating": 2,
                "rating_reason": "Low relevance: General market commentary",
                "action_required": False,
                "impact_level": "NOISE",
            }

        # Check for medium impact (5-6)
        med_matches = sum(1 for p in MEDIUM_KEYWORDS if re.search(p, combined, re.IGNORECASE))
        if med_matches >= 2:
            return {
                "rating": 6,
                "rating_reason": "Moderate: Corporate event or analyst activity",
                "action_required": False,
                "impact_level": "MEDIUM",
            }
        elif med_matches == 1:
            return {
                "rating": 5,
                "rating_reason": "Standard corporate or sector update",
                "action_required": False,
                "impact_level": "MEDIUM",
            }

        # Default: Low impact (3-4)
        # Use sentiment/impact score from DB if available
        return {
            "rating": 4,
            "rating_reason": "Minor operational or market update",
            "action_required": False,
            "impact_level": "LOW",
        }

    async def get_daily_top_10(
        self, target_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get the top 10 rated news for a specific date.
        If no date given, uses today.
        """
        if target_date:
            date_filter = target_date
        else:
            date_filter = str(date.today())

        # Fetch all news from that day
        rows = await fetch(
            """
            SELECT id, title, url, source, published_at, sentiment,
                   sentiment_score, impact_score, affected_stocks,
                   dividend_detected, summary, related_symbols
            FROM news
            WHERE DATE(published_at) = $1::date
            ORDER BY published_at DESC
            LIMIT 200
            """,
            date_filter,
        )

        # Rate each article
        rated = []
        for r in rows:
            rating_data = self.rate_article(r["title"], r.get("summary") or "")

            # Boost rating with DB impact score if available
            db_impact = float(r.get("impact_score") or 0)
            if db_impact > 0.7 and rating_data["rating"] < 8:
                rating_data["rating"] = max(rating_data["rating"], 8)
                rating_data["rating_reason"] = f"ML-boosted: High computed impact ({db_impact:.2f})"

            item = dict(r)
            # Convert non-serializable types
            if item.get("published_at"):
                item["published_at"] = str(item["published_at"])
            if item.get("related_symbols") and isinstance(item["related_symbols"], list):
                item["related_symbols"] = item["related_symbols"]

            item.update(rating_data)
            rated.append(item)

        # Sort by rating descending, then by impact_score
        rated.sort(key=lambda x: (x["rating"], float(x.get("impact_score") or 0)), reverse=True)

        top_10 = rated[:10]

        return {
            "date": date_filter,
            "total_news_today": len(rows),
            "top_10_count": len(top_10),
            "top_10": top_10,
        }

    async def get_archive(self, days: int = 7) -> Dict[str, Any]:
        """Get daily top-10 for the last N days."""
        archive = []
        today = date.today()

        for i in range(days):
            target = str(today - __import__("datetime").timedelta(days=i))
            daily = await self.get_daily_top_10(target)
            if daily["top_10"]:
                archive.append(daily)

        return {
            "days_requested": days,
            "days_with_data": len(archive),
            "archive": archive,
        }


# Singleton
news_ranker = NewsRanker()
