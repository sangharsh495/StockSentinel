"""
Sentiment Analyzer — classifies news headlines as BULLISH/BEARISH/NEUTRAL using Groq API.
"""

import logging
import asyncio
import json
import requests
from app.database import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


async def analyze_sentiment():
    """
    Fetch unanalyzed news headlines, classify sentiment via Groq Chat Completions API.
    Batches headlines to conserve rate limits.
    """
    if not settings.GROQ_API_KEY:
        logger.warning("GROQ_API_KEY not set — skipping sentiment analysis")
        return 0

    logger.info("Running sentiment analysis on new headlines using Groq...")

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

    logger.info(f"Analyzing sentiment for {len(rows)} headlines using Groq Llama 3")

    count = 0
    batch_size = 10  # Batch 10 headlines per API call

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
        "Content-Type": "application/json"
    }

    # Run loop synchronously/asynchronously inside executor or via standard requests since it's simple
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]

        # Build prompt
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
            # Run the requests call in the default executor to prevent event loop blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, 
                lambda: requests.post(url, headers=headers, json=payload, timeout=15)
            )

            if response.status_code != 200:
                logger.warning(f"Groq API returned status code {response.status_code}: {response.text}")
                continue

            resp_json = response.json()
            choices = resp_json.get("choices", [])
            if not choices:
                continue

            text = choices[0]["message"]["content"].strip()
            
            # Clean up response if it wraps in markdown blocks anyway
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

            # Groq returns standard JSON object, parse it
            data = json.loads(text)
            
            results = []
            if isinstance(data, list):
                results = data
            elif isinstance(data, dict):
                # Check for a nested list first
                for val in data.values():
                    if isinstance(val, list):
                        results = val
                        break
                else:
                    # If it's a dictionary of objects, e.g. {"0": {"sentiment": "BULLISH", "index": 1}}
                    for val in data.values():
                        if isinstance(val, dict) and "sentiment" in val:
                            results.append(val)

            if not results:
                logger.warning(f"Groq did not return valid sentiment entries: {text}")
                continue

            async with pool.acquire() as conn:
                for result in results:
                    idx = result.get("index", 0) - 1
                    if 0 <= idx < len(batch):
                        sentiment = result.get("sentiment", "NEUTRAL").upper()
                        score = result.get("score", 0.5)

                        if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
                            sentiment = "NEUTRAL"

                        await conn.execute(
                            """
                            UPDATE news SET sentiment = $1, sentiment_score = $2
                            WHERE id = $3
                            """,
                            sentiment,
                            min(max(float(score), 0.0), 1.0),
                            batch[idx]["id"],
                        )
                        count += 1

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Groq JSON response: {e}")
        except Exception as e:
            logger.warning(f"Groq API connection error: {e}")

        # Rate limiting: wait 2s between batches
        await asyncio.sleep(2.0)

    logger.info(f"Sentiment analysis complete: {count} headlines classified")
    return count
