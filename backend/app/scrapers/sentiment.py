"""
Sentiment Analyzer — classifies news headlines as BULLISH/BEARISH/NEUTRAL using Gemini API.
"""

import logging
import asyncio
import json
from app.database import get_pool
from app.config import settings

logger = logging.getLogger(__name__)


async def analyze_sentiment():
    """
    Fetch unanalyzed news headlines, classify sentiment via Gemini API.
    Batches 5 headlines per API call to conserve the free tier quota.
    """
    if not settings.GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set — skipping sentiment analysis")
        return 0

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

    logger.info(f"Analyzing sentiment for {len(rows)} headlines")

    try:
        import google.generativeai as genai

        genai.configure(api_key=settings.GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")

        count = 0
        batch_size = settings.GEMINI_BATCH_SIZE

        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]

            # Build the prompt with multiple headlines
            headlines_text = "\n".join(
                f"{idx + 1}. {row['title']}" for idx, row in enumerate(batch)
            )

            prompt = f"""You are a financial market sentiment analyzer.

Classify each headline as BULLISH (positive for stocks/market), BEARISH (negative), or NEUTRAL.

Return ONLY a JSON array with objects containing "index" (1-based), "sentiment" (BULLISH/BEARISH/NEUTRAL), and "score" (confidence 0.0-1.0).

Headlines:
{headlines_text}

Response (JSON array only, no markdown):"""

            try:
                response = model.generate_content(prompt)
                text = response.text.strip()

                # Clean up response — remove markdown code blocks if present
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text.rsplit("```", 1)[0]
                text = text.strip()

                results = json.loads(text)

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
                logger.warning(f"Gemini returned non-JSON response: {e}")
                # Fallback: try to classify individually
                for row in batch:
                    try:
                        simple_prompt = f'Classify this financial headline as BULLISH, BEARISH, or NEUTRAL. Reply with ONE word only.\n\nHeadline: "{row["title"]}"'
                        resp = model.generate_content(simple_prompt)
                        word = resp.text.strip().upper()
                        if word in ("BULLISH", "BEARISH", "NEUTRAL"):
                            async with pool.acquire() as conn:
                                await conn.execute(
                                    "UPDATE news SET sentiment = $1, sentiment_score = 0.7 WHERE id = $2",
                                    word, row["id"],
                                )
                                count += 1
                    except Exception:
                        pass

            except Exception as e:
                logger.warning(f"Gemini API error: {e}")

            # Rate limit: respect free tier
            await asyncio.sleep(60 / settings.GEMINI_RPM_LIMIT)

        logger.info(f"Sentiment analysis complete: {count} headlines classified")
        return count

    except ImportError:
        logger.error("google-generativeai not installed")
        return 0
    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return 0
