"""
IPO scraper parsing and IPO model honesty checks.
"""

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.quant.ipo_model import build_frame, evaluate_ipo, walk_forward_ipo  # noqa: E402
from app.scrapers.ipo_history import parse_detail, parse_tracker  # noqa: E402


def _rsc_page(payload: str, body: str = "") -> str:
    return (f"<html><body><script>self.__next_f.push([1,{json.dumps(payload)}])</script>"
            f"{body}</body></html>")


def test_parse_tracker_reads_embedded_rows():
    rows = [{
        "~orderby": "2025-01-19", "IPO": "Laxmi Dental ", "Symbol": "LAXMIDENTL, 544339",
        "Listing Dt": "20-Jan-25", "Size": "&#8377;698.06 Cr", "Sub": "114.14x", "GMP": "&#8377;145",
        "Price": "&#8377;428.00", "~id": 1179, "~URLRewrite_Folder_Name": "/gmp/laxmi-dental-ipo/1179/",
        "~IPO_Category": "IPO", "~str_listing_gain_in_per": 26.64, "~str_closing_gain_in_per": 30.1,
    }, {"~orderby": "x", "IPO": "Some SME", "~id": 5, "~IPO_Category": "SME"}]
    out = parse_tracker(_rsc_page("1:" + json.dumps(rows)))
    assert len(out) == 1
    r = out[0]
    assert r["symbol"] == "LAXMIDENTL" and r["issue_price"] == 428.0 and r["gmp"] == 145.0
    assert r["subscription_x"] == 114.14 and r["listing_gain_pct"] == 26.64
    assert str(r["listing_date"]) == "2025-01-20"


def test_parse_detail_reads_issue_object_and_gmp_trend():
    obj = {"shares_offered_qib": "1", "issue_size_fresh_in_amt": "138", "issue_size_ofs_in_amt": "560",
           "issue_size_in_amt": "698", "pe_ratio": "87.7", "issue_end_dt_json": "2025-01-15",
           "company_sector": "Medical"}
    html = _rsc_page("2:" + json.dumps({"data": obj}), (
        "<table><tr><th>Metric</th><th>Value</th></tr><tr><td>First GMP</td><td>₹155</td></tr>"
        "<tr><td>Latest GMP</td><td>₹145</td></tr><tr><td>Trend Slope</td><td>-3.4</td></tr></table>"))
    d = parse_detail(html)
    assert d["fresh_issue_amt"] == 138 and d["ofs_amt"] == 560 and d["pe_ratio"] == 87.7
    assert str(d["issue_close_date"]) == "2025-01-15" and d["sector"] == "Medical"
    assert d["gmp_first"] == 155 and d["gmp_latest"] == 145 and d["gmp_slope"] == -3.4


def _synthetic_ipos(n=260, seed=0):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2020-01-01")
    rows = []
    for i in range(n):
        price = 100.0
        gmp = rng.normal(15, 20)
        listing = start + pd.Timedelta(days=5 * i)
        rows.append({
            "ig_id": i, "name": f"IPO{i}", "issue_price": price, "gmp": gmp,
            "subscription_x": float(np.exp(rng.normal(2, 1))), "issue_size_cr": 500.0,
            "listing_date": listing.date(), "issue_close_date": (listing - pd.Timedelta(days=3)).date(),
            # truth: listing = GMP% minus a fixed 3-point haircut, plus noise
            "listing_gain_pct": gmp - 3 + rng.normal(0, 4),
        })
    return rows


def test_ipo_heat_uses_only_past_listings():
    rows = _synthetic_ipos(40)
    df = build_frame(rows)
    # the 6th IPO's heat may only use IPOs that listed before its books closed
    i = 6
    close = pd.Timestamp(rows[i]["issue_close_date"])
    past = [r["listing_gain_pct"] for r in rows if pd.Timestamp(r["listing_date"]) < close][-10:]
    assert df.loc[i, "ipo_heat_10"] == np.mean(past)


def test_walk_forward_trains_only_on_already_listed_ipos():
    df = build_frame(_synthetic_ipos())
    oos = walk_forward_ipo(df, min_train=120, step=30)
    assert len(oos) > 0
    m = evaluate_ipo(oos)
    # the model learns the systematic GMP haircut, so it should beat raw GMP
    assert m["model_mae_pct"] < m["gmp_rule_mae_pct"]
