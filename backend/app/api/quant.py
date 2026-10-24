"""
Quant API — tested model predictions, validation reports and news outcomes.

Every response carries `edge_verified` and the model's out-of-sample
accuracy, so the app can show how much to trust each number.
"""

import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.database import fetch, fetchrow

router = APIRouter(prefix="/quant")

STRATEGIES = {"trader": "stock_trader", "swing": "stock_swing", "investor": "stock_investor"}


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


def _trust(run: dict) -> dict:
    """Compact 'how much can I trust this' block for the app."""
    m = _j(run.get("metrics")) or {}
    bt = _j(run.get("backtest")) or {}
    edge = bool(run.get("edge_verified"))
    return {
        "edge_verified": edge,
        "verdict": (
            "Tested edge: the model beat chance on years of unseen data."
            if edge else
            "No proven edge yet: on unseen data this model was close to a coin flip. "
            "Treat its probabilities as near 50/50 context, not a signal."
        ),
        "oos_period": [m.get("oos_start"), m.get("oos_end")],
        "auc": m.get("auc"),
        "accuracy": m.get("accuracy"),
        "accuracy_always_majority": m.get("accuracy_always_majority"),
        "rank_ic_tstat": m.get("rank_ic_tstat"),
        "backtest_cagr_pct": (bt.get("model") or {}).get("cagr_pct"),
        "nifty_cagr_pct": (bt.get("nifty") or {}).get("cagr_pct"),
        "trained_at": run["trained_at"].isoformat() if run.get("trained_at") else None,
        "data_end": str(run["data_end"]) if run.get("data_end") else None,
    }


async def _latest_run(model_key: str) -> Optional[dict]:
    return await fetchrow(
        "SELECT * FROM quant_model_runs WHERE model_key = $1 ORDER BY trained_at DESC LIMIT 1",
        model_key,
    )


@router.get("/picks")
async def picks(
    strategy: str = Query("swing", description="trader (5d), swing (20d) or investor (60d)"),
    limit: int = Query(20, ge=1, le=100),
    min_probability: float = Query(0.0, ge=0, le=1),
):
    """Stocks ranked by tested probability of beating their peers for the chosen strategy."""
    key = STRATEGIES.get(strategy.lower())
    if not key:
        raise HTTPException(400, f"strategy must be one of {list(STRATEGIES)}")
    run = await _latest_run(key)
    if not run:
        return {"strategy": strategy, "status": "not_trained", "picks": []}
    rows = await fetch(
        """
        SELECT p.payload, s.name, s.sector, s.current_price, s.change_pct
        FROM quant_predictions p
        LEFT JOIN stocks s ON UPPER(s.symbol) = p.symbol AND s.exchange = 'NSE'
        WHERE p.model_key = $1 AND p.probability >= $2
        ORDER BY p.rank ASC LIMIT $3
        """,
        key, min_probability, limit,
    )
    out = []
    for r in rows:
        p = _j(r["payload"])
        p.update({"name": r["name"], "sector": r["sector"],
                  "current_price": float(r["current_price"]) if r["current_price"] is not None else None,
                  "change_pct": float(r["change_pct"]) if r["change_pct"] is not None else None})
        out.append(p)
    return {"strategy": strategy, "horizon_days": run["horizon_days"],
            "description": run["description"], "trust": _trust(run), "picks": out}


@router.get("/stock/{symbol}")
async def stock_view(symbol: str):
    """All strategy probabilities for one stock plus its measured news reactions."""
    sym = symbol.upper().strip()
    rows = await fetch(
        """
        SELECT p.model_key, p.payload, r.horizon_days, r.description, r.edge_verified,
               r.metrics, r.backtest, r.trained_at, r.data_end
        FROM quant_predictions p JOIN quant_model_runs r ON r.id = p.run_id
        WHERE p.symbol = $1 AND p.model_key LIKE 'stock_%'
        """,
        sym,
    )
    strategies = {
        r["model_key"].replace("stock_", ""): {
            **_j(r["payload"]), "horizon_days": r["horizon_days"],
            "description": r["description"], "trust": _trust(r),
        }
        for r in rows
    }
    news = await fetch(
        """
        SELECT n.title, n.source, n.published_at, nsi.impact_direction, nsi.impact_score,
               o.abn_1d, o.abn_5d, o.abn_20d
        FROM news_stock_impact nsi
        JOIN news n ON n.id = nsi.news_id
        LEFT JOIN news_outcomes o ON o.news_id = nsi.news_id AND o.symbol = nsi.symbol
        WHERE nsi.symbol = $1
        ORDER BY n.published_at DESC NULLS LAST LIMIT 15
        """,
        sym,
    )
    for n in news:
        for k in ("abn_1d", "abn_5d", "abn_20d"):
            v = n.pop(k, None)
            n[k + "_pct"] = round(v * 100, 2) if v is not None else None
        n["impact_score"] = float(n["impact_score"]) if n.get("impact_score") is not None else None
    return {"symbol": sym, "strategies": strategies, "news_reactions": news}


@router.get("/market-outlook")
async def market_outlook():
    """Chance the Nifty is higher in 5 / 20 trading days, with the model's tested accuracy."""
    out = {}
    for h in (5, 20):
        key = f"market_{h}d"
        run = await _latest_run(key)
        if not run:
            continue
        p = await fetchrow("SELECT payload FROM quant_predictions WHERE model_key = $1", key)
        out[f"{h}d"] = {**(_j(p["payload"]) if p else {}), "trust": _trust(run)}
    return {"status": "ok" if out else "not_trained", "outlook": out}


@router.get("/models")
async def models_report():
    """Full validation report for every model: metrics, calibration, deciles, backtest, folds."""
    rows = await fetch(
        """
        SELECT DISTINCT ON (model_key) * FROM quant_model_runs
        ORDER BY model_key, trained_at DESC
        """
    )
    return {"models": [
        {k: (_j(v) if k in ("metrics", "backtest", "folds") else
             (v.isoformat() if hasattr(v, "isoformat") else v)) for k, v in r.items()}
        for r in rows
    ]}


@router.get("/news-impact")
async def news_impact(
    days: int = Query(180, ge=7, le=730),
    horizon: str = Query("5d", description="1d, 5d or 20d"),
    min_samples: int = Query(10, ge=3, le=500),
):
    """
    Measured outcome of news tags: for each (direction, category), how often
    the stock really moved that way vs the market, with 95% intervals.
    """
    from app.quant.news_events import load_outcomes_frame, summarize, MIN_SAMPLES_FOR_MODEL

    if horizon not in ("1d", "5d", "20d"):
        raise HTTPException(400, "horizon must be 1d, 5d or 20d")
    df = await load_outcomes_frame(days)
    col = f"abn_{horizon}"
    total = int(df[col].notna().sum()) if not df.empty else 0
    news_run = await _latest_run("news_5d")
    return {
        "horizon": horizon, "days": days, "measured_pairs": total,
        "model": {
            "samples_needed": MIN_SAMPLES_FOR_MODEL,
            "status": "trained" if news_run else "collecting_data",
            "trust": _trust(news_run) if news_run else None,
        },
        "groups": summarize(df, col, min_samples) if total else [],
    }
