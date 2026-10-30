"""
Weekly Multibagger Radar run: download fundamentals, train and test the
model zoo, publish the radar, log it, and score earlier radar picks.

    cd backend && python ../scripts/train_multibagger.py              # full run + save to DB
    cd backend && python ../scripts/train_multibagger.py --no-db --bags 1 --out mb.json
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

import pandas as pd  # noqa: E402

from app.quant.fundamentals import load_fundamentals  # noqa: E402
from app.quant.market_data import update_market  # noqa: E402
from app.quant.multibagger import MIN_TURNOVER_LACS, run_multibagger, score_ledger  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("train_multibagger")


def build(args):
    W = update_market(pd.bdate_range(pd.Timestamp.now() - pd.Timedelta(days=15), pd.Timestamp.now()))
    liq = W["TurnoverLacs"].rolling(60, min_periods=40).median()
    ever = liq.resample("ME").last().ge(MIN_TURNOVER_LACS).any()
    symbols = list(ever[ever].index)
    fund = load_fundamentals(symbols, max_fetch=args.max_fetch)
    log.info(f"Fundamentals: {fund['symbol'].nunique()} of {len(symbols)} stocks")
    return W, fund, run_multibagger(W, fund, n_bags=args.bags, refit_months=args.refit_months)


async def main(args):
    W, fund, res = await asyncio.to_thread(build, args)
    m = res["metrics"]
    s = m["honest_stack"]
    log.info(f"Zoo: {m['model_configurations']} configurations, {m['fitted_models']} fitted models, "
             f"{len(m['fdr_survivors'])} pass the false-discovery test")
    log.info(f"Honest stack: top-decile doubling {s.get('top_decile_hit_pct')}% vs base {s.get('avg_base_rate_pct')}% "
             f"(lift {s.get('lift_top_decile')}, t={s.get('newey_west_t')}), edge_verified={res['edge_verified']}")
    results = [res]
    if not args.no_db:
        from app.database import close_pool, create_pool, execute_many, fetch, init_schema
        from app.quant.store import save_results

        await create_pool()
        try:
            await init_schema()
            await execute_many(
                "INSERT INTO multibagger_log (date, symbol, stage, score_percentile) VALUES ($1, $2, $3, $4) "
                "ON CONFLICT DO NOTHING",
                [(date.fromisoformat(p["as_of"]), p["symbol"], p["stage"], p["score_percentile"])
                 for p in res["predictions"]],
            )
            rows = await fetch("SELECT date, symbol, stage FROM multibagger_log")
            card = score_ledger(W, [dict(r) for r in rows])
            results.append({
                "model_key": "multibagger_scorecard", "strategy": "scorecard", "horizon_days": 250,
                "description": "Live track record of the Multibagger Radar: real weekly picks, scored after 6 and 12 months.",
                "model_type": "live_scorecard", "trained_at": datetime.now(timezone.utc).isoformat(),
                "data_end": res["data_end"], "edge_verified": False, "metrics": card,
                "backtest": None, "folds": None, "predictions": [],
            })
            await save_results(results)
        finally:
            await close_pool()
    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1, default=str)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--bags", type=int, default=6, help="bootstrap models per configuration")
    ap.add_argument("--refit-months", type=int, default=6)
    ap.add_argument("--max-fetch", type=int, default=4000, help="max stocks to refresh fundamentals for")
    asyncio.run(main(ap.parse_args()))
