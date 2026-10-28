"""
Train, test and publish StockSentinel's quant models.

    cd backend && python ../scripts/train_quant.py               # train + save to DB
    cd backend && python ../scripts/train_quant.py --no-db --out report.json

Runs walk-forward validation and backtests for every model, then saves
metrics + today's predictions to Postgres (DATABASE_URL). Designed to run
in GitHub Actions after market close, because Render's free CPU is too
slow for training.
"""

import argparse
import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from app.quant.trainer import run_all  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("train_quant")


def summary_line(r):
    m = r.get("metrics") or {}
    if r.get("model_key") == "ipo_listing" and m:
        return (f"ipo_listing      edge_verified={r.get('edge_verified')!s:<5} IPOs={m.get('oos_ipos')} "
                f"MAE model={m.get('model_mae_pct')} vs GMP rule={m.get('gmp_rule_mae_pct')} "
                f"AUC model={m.get('model_auc_positive_listing')} vs GMP={m.get('gmp_rule_auc_positive_listing')}")
    bt = (r.get("backtest") or {}).get("model") or {}
    return (f"{r['model_key']:<16} edge_verified={r.get('edge_verified')!s:<5} "
            f"AUC={m.get('auc')} acc={m.get('accuracy')} (majority {m.get('accuracy_always_majority')}) "
            f"IC_t={m.get('rank_ic_tstat')} backtest_CAGR={bt.get('cagr_pct')}")


async def scanner_scorecard(results):
    """Save tonight's scanner picks, then score every earlier pick whose 5 days have passed."""
    from datetime import date, datetime, timezone
    import pandas as pd
    from app.database import execute_many, fetch
    from app.quant.market_data import update_market
    from app.quant.scanner import score_past_picks

    scan = next((r for r in results if r.get("model_key") == "market_scanner"), None)
    if not scan:
        return None
    await execute_many(
        "INSERT INTO scanner_log (date, symbol, category) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        [(date.fromisoformat(p["as_of"]), p["symbol"], p["category"]) for p in scan["predictions"]],
    )
    rows = await fetch("SELECT date, symbol, category FROM scanner_log")
    W = update_market(pd.DatetimeIndex([]))          # cached: no download
    card = score_past_picks(W, rows)
    log.info(f"Scanner scorecard: {card.get('scored_picks')} scored, right {card.get('right_pct_all')}%")
    return {
        "model_key": "scanner_scorecard", "strategy": "scorecard", "horizon_days": 5,
        "description": "Live track record of the nightly watchlist: real picks, scored 5 trading days later.",
        "model_type": "live_scorecard", "trained_at": datetime.now(timezone.utc).isoformat(),
        "data_end": scan.get("data_end"), "edge_verified": False, "metrics": card,
        "backtest": None, "folds": None, "predictions": [],
    }


async def main(args):
    results = await asyncio.to_thread(run_all, args.strategies, args.period, not args.no_ipo)

    if not args.no_db:
        from app.database import close_pool, create_pool, init_schema
        from app.quant.news_events import load_outcomes_frame, train_news_model, update_news_outcomes
        from app.quant.store import save_results

        await create_pool()
        try:
            # Create any missing tables (safe to repeat: every statement is IF NOT EXISTS)
            await init_schema()
            try:
                await update_news_outcomes()
                news = train_news_model(await load_outcomes_frame(365))
                log.info(f"News model: {news.get('status')} ({news.get('samples')} samples)")
                if news.get("status") == "trained":
                    results.append(news)
            except Exception as e:  # news tables may be empty on a fresh DB
                log.warning(f"News model step skipped: {e}")
            try:
                card = await scanner_scorecard(results)
                if card:
                    results.append(card)
            except Exception as e:
                log.warning(f"Scanner scorecard skipped: {e}")
            await save_results(results)
        finally:
            await close_pool()

    for r in results:
        log.info(summary_line(r))
    if args.out:
        with open(args.out, "w") as f:
            json.dump(results, f, indent=1, default=str)
        log.info(f"Report written to {args.out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true", help="don't write to the database")
    ap.add_argument("--out", help="write the full JSON report here")
    ap.add_argument("--period", default="10y")
    ap.add_argument("--no-ipo", action="store_true", help="skip the IPO scrape and model")
    ap.add_argument("--strategies", nargs="*", choices=["trader", "swing", "investor"])
    asyncio.run(main(ap.parse_args()))
