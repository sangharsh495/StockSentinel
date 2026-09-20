"""
Catalyst & Extreme News Classifier — extracts market-moving corporate events:
1. CONTRACT_WIN: Order wins, capacity expansion, project tenders.
2. DIVIDEND_BONUS: Dividends, bonus shares, stock splits, buybacks.
3. EARNINGS_CATALYST: Quarterly/annual results, revenue surge, profit jumps.
4. LEGAL_REGULATORY: SEBI/SEC actions, court/NCLT rulings, government policies, patents.
5. DEAL_MERGER: Acquisitions, joint ventures, stake purchases, promoter actions.
6. MANAGEMENT_CHANGE: CEO/leadership changes, board approvals.

Calculates an Extreme Impact Score (0.0 to 1.0) and assigns a directional trend prediction.
Works 100% offline using high-performance regex heuristics + VADER sentiment.
"""

import re
import logging
from typing import Optional, Dict, Any, List
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

logger = logging.getLogger(__name__)

_vader = SentimentIntensityAnalyzer()

# ---------------------------------------------------------------------------
# Catalyst Regex Patterns & Scoring Weights
# ---------------------------------------------------------------------------
CATALYST_RULES = [
    {
        "type": "CONTRACT_WIN",
        "label": "Order Win / Expansion",
        "base_impact": 0.85,
        "default_direction": "BULLISH",
        "patterns": [
            re.compile(r"\b(?:bags|wins|secures|awarded|bags order|order win|receives order|contract worth|order of rs|deal worth)\b", re.IGNORECASE),
            re.compile(r"\b(?:capacity expansion|new plant|capex|commissions plant|manufacturing facility|greenfield)\b", re.IGNORECASE),
            re.compile(r"\b(?:defense order|railway order|power project|infrastructure project|export order)\b", re.IGNORECASE),
        ],
    },
    {
        "type": "DIVIDEND_BONUS",
        "label": "Dividend / Bonus / Split",
        "base_impact": 0.80,
        "default_direction": "BULLISH",
        "patterns": [
            re.compile(r"\b(?:dividend|interim dividend|final dividend|special dividend|record date|ex-dividend|ex date)\b", re.IGNORECASE),
            re.compile(r"\b(?:bonus issue|bonus shares|stock split|share split|sub-division of shares)\b", re.IGNORECASE),
            re.compile(r"\b(?:share buyback|buyback of shares|tender offer)\b", re.IGNORECASE),
        ],
    },
    {
        "type": "EARNINGS_CATALYST",
        "label": "Financial Results / Earnings",
        "base_impact": 0.80,
        "default_direction": "NEUTRAL",  # Determined by VADER / sentiment words
        "patterns": [
            re.compile(r"\b(?:q[1-4]|quarterly results|net profit|pat|revenue|ebitda|operating profit|q[1-4] profit)\b", re.IGNORECASE),
            re.compile(r"\b(?:profit surges|profit jumps|profit rises|profit soars|revenue up|strong earnings)\b", re.IGNORECASE),
            re.compile(r"\b(?:profit drops|net loss|loss widens|profit falls|revenue declines|margin pressure)\b", re.IGNORECASE),
            re.compile(r"\b(?:beats estimates|misses estimates|earnings beat|guidance hike|guidance cut)\b", re.IGNORECASE),
        ],
    },
    {
        "type": "LEGAL_REGULATORY",
        "label": "Legal / Regulatory / Govt",
        "base_impact": 0.88,
        "default_direction": "BEARISH",  # Regulatory often brings volatility/risk
        "patterns": [
            re.compile(r"\b(?:sebi|sec|ed raid|cbi|income tax raid|tax demand|show cause notice|penalty|fined)\b", re.IGNORECASE),
            re.compile(r"\b(?:nclt|insolvency|bankruptcy|lawsuit|supreme court|high court|stay order|patent litigation)\b", re.IGNORECASE),
            re.compile(r"\b(?:usfda|483 observations|warning letter|import alert|fda approval)\b", re.IGNORECASE),
            re.compile(r"\b(?:pli scheme|anti-dumping duty|customs duty|export duty|subsidies|govt approval)\b", re.IGNORECASE),
        ],
    },
    {
        "type": "DEAL_MERGER",
        "label": "M&A / Strategic Stake",
        "base_impact": 0.82,
        "default_direction": "BULLISH",
        "patterns": [
            re.compile(r"\b(?:acquires|acquisition|takeover|merger|buys stake|picks stake|strategic alliance|joint venture)\b", re.IGNORECASE),
            re.compile(r"\b(?:promoter buys|promoter sells|block deal|bulk deal|pe fund investment|fii buying)\b", re.IGNORECASE),
            re.compile(r"\b(?:divestment|stake sale|subsidiary sale|hive off)\b", re.IGNORECASE),
        ],
    },
    {
        "type": "MANAGEMENT_CHANGE",
        "label": "Management / Governance",
        "base_impact": 0.70,
        "default_direction": "NEUTRAL",
        "patterns": [
            re.compile(r"\b(?:appoints md|appoints ceo|resigns|steps down|board approves|management change|auditor resigns)\b", re.IGNORECASE),
            re.compile(r"\b(?:fraud|investigation|whistleblower|audit qualified)\b", re.IGNORECASE),
        ],
    },
]

# Additional extreme market impact words
STRONG_BULLISH_KEYWORDS = [
    "multibagger", "record profit", "massive order", "landmark deal",
    "blockbuster", "breakout", "skyrockets", "fda approval", "debt free",
    "doubles profit", "all-time high", "all time high", "mega deal",
]

STRONG_BEARISH_KEYWORDS = [
    "fraud", "scam", "bankruptcy", "default", "liquidation",
    "cbi probe", "ed probe", "sebi ban", "warning letter", "suspension",
    "insolvency", "delisting", "catastrophic", "massive loss",
]


class CatalystAnalyzer:
    """Detects corporate catalysts and projects market trend direction."""

    @staticmethod
    def analyze_headline(title: str, summary: str = "") -> Dict[str, Any]:
        """
        Analyze a headline and summary to detect:
        - catalyst_type: One of CATALYST_RULES types or 'GENERAL_NEWS'
        - catalyst_label: Human readable badge text
        - is_extreme: True if impact >= 0.75
        - impact_score: 0.0 to 1.0
        - trend_direction: 'STRONG_BULLISH', 'BULLISH', 'NEUTRAL', 'BEARISH', 'STRONG_BEARISH'
        - trend_rationale: 1-sentence analytical reason
        """
        text = f"{title} {summary}".strip()
        text_lower = text.lower()

        # 1. Check for catalyst match
        detected_catalyst = None
        for rule in CATALYST_RULES:
            for pattern in rule["patterns"]:
                if pattern.search(text):
                    detected_catalyst = rule
                    break
            if detected_catalyst:
                break

        # 2. VADER sentiment
        vader_scores = _vader.polarity_scores(text)
        compound = vader_scores["compound"]

        # 3. Check for extreme sentiment modifiers
        has_strong_bull = any(k in text_lower for k in STRONG_BULLISH_KEYWORDS)
        has_strong_bear = any(k in text_lower for k in STRONG_BEARISH_KEYWORDS)

        # 4. Determine Impact Score
        if detected_catalyst:
            impact_score = detected_catalyst["base_impact"]
            catalyst_type = detected_catalyst["type"]
            catalyst_label = detected_catalyst["label"]
        else:
            impact_score = round(min(abs(compound) * 0.7, 0.65), 2)
            catalyst_type = "GENERAL_NEWS"
            catalyst_label = "Market News"

        if has_strong_bull or has_strong_bear:
            impact_score = min(impact_score + 0.15, 0.98)

        # 5. Trend Direction Classification
        if has_strong_bull or compound >= 0.55:
            trend_direction = "STRONG_BULLISH"
        elif compound >= 0.15:
            trend_direction = "BULLISH"
        elif has_strong_bear or compound <= -0.55:
            trend_direction = "STRONG_BEARISH"
        elif compound <= -0.15:
            trend_direction = "BEARISH"
        else:
            # Fall back to catalyst default if neutral
            if detected_catalyst and detected_catalyst["default_direction"] != "NEUTRAL":
                trend_direction = detected_catalyst["default_direction"]
            else:
                trend_direction = "NEUTRAL"

        # Special overrides
        if "dividend" in text_lower and trend_direction in ("NEUTRAL", "BEARISH") and not has_strong_bear:
            trend_direction = "BULLISH"

        if any(w in text_lower for w in ["ed probe", "sebi notice", "loss widens", "penalty"]):
            trend_direction = "BEARISH"

        # 6. Rationale generation
        if trend_direction in ("STRONG_BULLISH", "BULLISH"):
            rationale = f"Positive catalyst: {catalyst_label} expected to drive buying momentum."
        elif trend_direction in ("STRONG_BEARISH", "BEARISH"):
            rationale = f"Negative headwind: {catalyst_label} creates risk of downward selling pressure."
        else:
            rationale = f"{catalyst_label} event under market observation; consolidation likely."

        is_extreme = impact_score >= 0.75

        return {
            "catalyst_type": catalyst_type,
            "catalyst_label": catalyst_label,
            "is_extreme": is_extreme,
            "impact_score": round(impact_score, 2),
            "trend_direction": trend_direction,
            "trend_rationale": rationale,
        }


# Singleton instance
catalyst_analyzer = CatalystAnalyzer()
