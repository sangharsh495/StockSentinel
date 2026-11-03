"""NSE end-of-day file parsing and the investorgain IPO feed."""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.scrapers.ipo_live import ipo_status, to_row  # noqa: E402
from app.scrapers.nse_prices import parse_bhavcopy  # noqa: E402

BHAV = """SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, DELIV_QTY, DELIV_PER
RELIANCE, EQ, 03-Nov-2026, 1300.00, 1301.00, 1312.00, 1295.50, 1307.00, 1307.90, 1305.10, 9000000, 117459.00, 200000, 5000000, 55.55
RELIANCE, BL, 03-Nov-2026, 1300.00, 1301.00, 1312.00, 1295.50, 1307.00, 1307.90, 1305.10, 10, 1.00, 1, -, -
NEWCO, EQ, 03-Nov-2026, -, 50.00, 52.00, 49.00, 51.00, 51.00, 50.50, 1000, 0.51, 10, 500, 50.00
"""


def test_bhavcopy_keeps_eq_series_and_computes_change():
    rows = {r["symbol"]: r for r in parse_bhavcopy(BHAV)}
    assert set(rows) == {"RELIANCE", "NEWCO"}
    r = rows["RELIANCE"]
    assert r["close"] == 1307.9 and r["volume"] == 9000000 and abs(r["change_pct"] - 0.6077) < 1e-3
    assert rows["NEWCO"]["prev_close"] is None and rows["NEWCO"]["change_pct"] is None


def test_ipo_status_from_dates():
    t = date(2026, 11, 3)
    assert ipo_status(date(2026, 11, 5), date(2026, 11, 7), None, t) == "upcoming"
    assert ipo_status(date(2026, 11, 1), date(2026, 11, 4), None, t) == "open"
    assert ipo_status(date(2026, 10, 28), date(2026, 10, 30), date(2026, 11, 4), t) == "closed"
    assert ipo_status(date(2026, 10, 20), date(2026, 10, 22), date(2026, 10, 27), t) == "listed"


def test_investorgain_row_mapping():
    r = to_row({"name": " M.K.Sons Fine Jewels ", "issue_price": 162.0, "min_order_amount": 14904.0,
                "issue_size_cr": 275.4, "issue_open_date": date(2026, 10, 28), "issue_close_date": date(2026, 10, 30),
                "listing_date": date(2026, 11, 4), "gmp": 11.5, "subscription_x": 5.09, "roe": 30.8, "sector": "Jewellery"})
    assert r["company_name"] == "M.K.Sons Fine Jewels" and r["lot_size"] == 92 and r["issue_size"] == "₹275 Cr"
    assert r["subscription_status"] == {"total": 5.09} and r["details"]["roe"] == 30.8
