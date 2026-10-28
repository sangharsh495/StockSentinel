"""
Persist trainer results to Postgres (quant_model_runs / quant_predictions).
"""

import json
import logging
from datetime import date
from typing import Dict, List

logger = logging.getLogger(__name__)


async def save_results(results: List[Dict]) -> None:
    from app.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for r in results:
                if r.get("status") == "collecting_data":
                    continue
                run_id = await conn.fetchval(
                    """
                    INSERT INTO quant_model_runs (model_key, strategy, horizon_days, description,
                        model_type, data_end, edge_verified, metrics, backtest, folds)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10::jsonb)
                    RETURNING id
                    """,
                    r["model_key"], r.get("strategy"), r.get("horizon_days"), r.get("description"),
                    r.get("model_type"),
                    date.fromisoformat(r["data_end"]) if r.get("data_end") else None,
                    bool(r.get("edge_verified")),
                    json.dumps(r.get("metrics")), json.dumps(r.get("backtest")), json.dumps(r.get("folds")),
                )
                preds = r.get("predictions") or []
                if not preds:
                    continue
                await conn.execute("DELETE FROM quant_predictions WHERE model_key = $1", r["model_key"])
                await conn.executemany(
                    """
                    INSERT INTO quant_predictions (model_key, symbol, run_id, as_of, rank, probability, payload)
                    VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
                    """,
                    [
                        (r["model_key"], p["symbol"], run_id, date.fromisoformat(p["as_of"]),
                         p.get("rank"), p.get("probability"), json.dumps(p))
                        for p in preds
                    ],
                )
            # Keep the last 20 runs per model for history.
            await conn.execute(
                """
                DELETE FROM quant_model_runs WHERE id IN (
                    SELECT id FROM (
                        SELECT id, ROW_NUMBER() OVER (PARTITION BY model_key ORDER BY trained_at DESC) rn
                        FROM quant_model_runs) t
                    WHERE rn > 20)
                """
            )
    logger.info(f"Saved {len(results)} quant model results")
