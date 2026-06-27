"""
Sentiment Analyzer — classifies news headlines as BULLISH/BEARISH/NEUTRAL.

Strategy (designed for 24/7 uptime):
1. Try Groq API (Llama 3.1) for highest accuracy
2. If Groq fails → fall back to local VADER sentiment (zero API calls)
3. VADER is always available, no API key needed
"""

import logging
import asyncio
import json
import requests
from app.database import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local VADER Sentiment (offline fallback — always available)
# ---------------------------------------------------------------------------
def _vader_classify(headline: str) -> tuple[str, float]:
    """
    Classify a single headline using VADER sentiment analysis.
    Returns (sentiment, confidence_score).

    VADER compound score mapping:
      >= +0.15  → BULLISH
      <= -0.15  → BEARISH
      else      → NEUTRAL
    """
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        analyzer = SentimentIntensityAnalyzer()
        scores = analyzer.polarity_scores(headline)
        compound = scores["compound"]

        if compound >= 0.15:
            return "BULLISH", min(abs(compound), 1.0)
        elif compound <= -0.15:
            return "BEARISH", min(abs(compound), 1.0)
        else:
            return "NEUTRAL", 1.0 - abs(compound)
    except Exception:
        return "NEUTRAL", 0.5


def _vader_batch_classify(headlines: list[dict]) -> list[dict]:
    """Classify a batch of headlines using VADER. Returns list of {id, sentiment, score}."""
    results = []
    for item in headlines:
        sentiment, score = _vader_classify(item["title"])
        results.append({
            "id": item["id"],
            "sentiment": sentiment,
            "score": round(score, 4),
        })
    return results


# ---------------------------------------------------------------------------
# Groq API Sentiment (primary — highest accuracy)
# ---------------------------------------------------------------------------
async def _groq_batch_classify(batch: list[dict]) -> list[dict] | None:
    """
    Classify headlines via Groq Chat Completions API (Llama 3.1).
    Returns list of {index, sentiment, score} or None if API fails.
    """
    if not settings.GROQ_API_KEY:
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    headlines_text = "\n".join(
        f"{idx + 1}. {row['title']}" for idx, row in enumerate(batch)
    )

    prompt = f"""You are a financial market sentiment analyzer.

Classify each headline as BULLISH (positive for stocks/market), BEARISH (negative), or NEUTRAL.

Return ONLY a JSON array of objects. Do not write any markdown formatting, do not write ```json, do not write introduction or extra words.
Each object must contain "index" (1-based), "sentiment" (BULLISH/BEARISH/NEUTRAL), and "score" (confidence 0.0-1.0).

Example Response:
[
  {{"index": 1, "sentiment": "BULLISH", "score": 0.85}},
  {{"index": 2, "sentiment": "NEUTRAL", "score": 0.90}}
]

Headlines to analyze:
{headlines_text}"""

    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(
            None,
            lambda: requests.post(url, headers=headers, json=payload, timeout=15)
        )

        if response.status_code != 200:
            logger.warning(f"Groq API returned status code {response.status_code}: {response.text}")
            return None

        resp_json = response.json()
        choices = resp_json.get("choices", [])
        if not choices:
            return None

        text = choices[0]["message"]["content"].strip()

        # Clean up response if it wraps in markdown blocks anyway
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()

        data = json.loads(text)

        results = []
        if isinstance(data, list):
            results = data
        elif isinstance(data, dict):
            for val in data.values():
                if isinstance(val, list):
                    results = val
                    break
            else:
                for val in data.values():
                    if isinstance(val, dict) and "sentiment" in val:
                        results.append(val)

        if not results:
            logger.warning(f"Groq did not return valid sentiment entries: {text}")
            return None

        return results

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse Groq JSON response: {e}")
        return None
    except Exception as e:
        logger.warning(f"Groq API connection error: {e}")
        return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
async def analyze_sentiment():
    """
    Fetch unanalyzed news headlines, classify sentiment.
    Strategy: Groq API first → VADER fallback if Groq fails.
    Guarantees 24/7 operation regardless of API availability.
    """
    logger.info("Running sentiment analysis on new headlines...")

    pool = await get_pool()

    # Get headlines without sentiment
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, title FROM news
            WHERE sentiment IS NULL
            ORDER BY published_at DESC
            LIMIT 50
            """
        )

    if not rows:
        logger.info("No unanalyzed headlines")
        return 0

    headlines = [dict(row) for row in rows]
    logger.info(f"Analyzing sentiment for {len(headlines)} headlines")

    count = 0
    batch_size = 10
    groq_available = bool(settings.GROQ_API_KEY)
    groq_failed = False

    for i in range(0, len(headlines), batch_size):
        batch = headlines[i:i + batch_size]
        classified = []

        # --- Strategy: Try Groq first, fall back to VADER ---
        if groq_available and not groq_failed:
            groq_results = await _groq_batch_classify(batch)

            if groq_results:
                # Map Groq results to our batch
                for result in groq_results:
                    idx = result.get("index", 0) - 1
                    if 0 <= idx < len(batch):
                        sentiment = result.get("sentiment", "NEUTRAL").upper()
                        score = result.get("score", 0.5)
                        if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
                            sentiment = "NEUTRAL"
                        classified.append({
                            "id": batch[idx]["id"],
                            "sentiment": sentiment,
                            "score": min(max(float(score), 0.0), 1.0),
                        })
                logger.debug(f"Groq classified {len(classified)}/{len(batch)} headlines")
            else:
                # Groq failed — switch to VADER for this and remaining batches
                groq_failed = True
                logger.info("Groq API failed — switching to VADER fallback for remaining headlines")

        # --- VADER fallback for anything Groq missed or if Groq failed ---
        classified_ids = {c["id"] for c in classified}
        unclassified = [h for h in batch if h["id"] not in classified_ids]

        if unclassified:
            vader_results = _vader_batch_classify(unclassified)
            classified.extend(vader_results)
            if groq_failed or not groq_available:
                logger.debug(f"VADER classified {len(vader_results)} headlines (fallback)")

        # --- Save to database ---
        async with pool.acquire() as conn:
            for item in classified:
                try:
                    await conn.execute(
                        """
                        UPDATE news SET sentiment = $1, sentiment_score = $2
                        WHERE id = $3
                        """,
                        item["sentiment"],
                        item["score"],
                        item["id"],
                    )
                    count += 1
                except Exception as e:
                    logger.debug(f"Error saving sentiment: {e}")

        # Rate limiting between Groq batches only
        if groq_available and not groq_failed:
            await asyncio.sleep(2.0)

    source = "VADER-only" if (groq_failed or not groq_available) else "Groq+VADER"
    logger.info(f"Sentiment analysis complete ({source}): {count} headlines classified")
    return count
