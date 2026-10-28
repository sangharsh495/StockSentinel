"""
IPO history scraper — past mainboard IPOs with GMP, subscription, deal
structure, financials and the real listing-day result.

Source: investorgain.com public pages (robots.txt allows crawling).
The year pages embed every IPO as JSON; each IPO's own page embeds its
issue details and GMP trend. We fetch politely (one request at a time,
with a delay) and cache, so each IPO page is only downloaded once.
"""

import json
import logging
import os
import re
import time
from datetime import date, datetime
from typing import Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://www.investorgain.com"
TRACKER = BASE + "/report/ipo-gmp-performance-tracker/377/ipo/?year={year}"
UA = "Mozilla/5.0 (compatible; StockSentinel/1.0; personal research app)"
CACHE_DIR = os.environ.get(
    "IPO_CACHE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".quant_cache", "ipo"),
)
DELAY_S = 1.5


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def rsc_text(html: str) -> str:
    """Concatenate the Next.js data chunks embedded in the page."""
    parts = re.findall(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', html)
    out = []
    for p in parts:
        try:
            out.append(json.loads(p))
        except ValueError:
            continue
    return "".join(out)


def _num(v) -> Optional[float]:
    if v is None:
        return None
    s = re.sub(r"<[^>]+>", "", str(v)).replace("&#8377;", "").replace("₹", "").replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group()) if m else None


def _date(v) -> Optional[date]:
    if not v:
        return None
    s = str(v)
    for fmt in ("%d-%b-%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:10] if fmt == "%Y-%m-%d" else s, fmt).date()
        except ValueError:
            continue
    return None


def parse_tracker(html: str) -> List[Dict]:
    """All IPO rows embedded in a year page (including later 'pages')."""
    t = rsc_text(html)
    dec = json.JSONDecoder()
    rows, seen = [], set()
    for m in re.finditer(r'\[\{"~orderby"', t):
        try:
            arr, _ = dec.raw_decode(t[m.start():])
        except ValueError:
            continue
        for r in arr:
            rid = r.get("~id")
            if rid in seen or r.get("~IPO_Category", "IPO") != "IPO":
                continue
            seen.add(rid)
            rows.append({
                "ig_id": int(rid),
                "name": (r.get("IPO") or "").strip(),
                "symbol": (r.get("Symbol") or "").split(",")[0].strip() or None,
                "listing_date": _date(r.get("Listing Dt")),
                "issue_size_cr": _num(r.get("Size")),
                "subscription_x": _num(r.get("Sub")),
                "gmp": _num(r.get("GMP")),
                "issue_price": _num(r.get("Price")),
                "listing_gain_pct": r.get("~str_listing_gain_in_per"),
                "listing_close_gain_pct": r.get("~str_closing_gain_in_per"),
                "url": BASE + r["~URLRewrite_Folder_Name"] if r.get("~URLRewrite_Folder_Name") else None,
            })
    return rows


DETAIL_FIELDS = {
    "issue_open_date": "issue_open_dt_json", "issue_close_date": "issue_end_dt_json",
    "fresh_issue_amt": "issue_size_fresh_in_amt", "ofs_amt": "issue_size_ofs_in_amt",
    "total_issue_amt": "issue_size_in_amt", "pe_ratio": "pe_ratio", "post_pe_ratio": "post_pe_ratio",
    "price_to_book": "price_to_book_value", "roe": "kpi_roe", "roce": "kpi_roce",
    "debt_equity": "kpi_debt_equity", "pat_margin": "kpi_pat_margin", "market_cap_cr": "market_cap",
    "promoter_pre": "promoter_shareholding_pre_issue", "promoter_post": "promoter_shareholding_post_issue",
    "anchor_shares": "shares_offered_anchor_investor", "retail_shares": "shares_offered_rii",
    "qib_shares": "shares_offered_qib_with_anchor", "total_shares": "shares_offered_total",
    "min_order_amount": "min_order_amount", "incorporated": "company_incorporation",
    "lead_managers": "lead_managers",
}


def _find_issue_object(t: str) -> Optional[Dict]:
    dec = json.JSONDecoder()
    i = t.find('"shares_offered_qib"')
    if i < 0:
        return None
    st = i
    for _ in range(40):
        st = t.rfind("{", 0, st)
        if st < 0:
            return None
        try:
            o, _ = dec.raw_decode(t[st:])
            if isinstance(o, dict) and "shares_offered_qib" in o:
                return o
        except ValueError:
            continue
    return None


def parse_detail(html: str) -> Dict:
    t = rsc_text(html)
    o = _find_issue_object(t) or {}
    d: Dict = {}
    for k, src in DETAIL_FIELDS.items():
        v = o.get(src)
        if k in ("issue_open_date", "issue_close_date"):
            d[k] = _date(v)
        elif k == "lead_managers":
            d[k] = v or None
        else:
            d[k] = _num(v)
    d["sector"] = o.get("company_sector") or None

    # GMP trend summary table (first/latest GMP, sessions up/down, slope)
    soup = BeautifulSoup(html, "lxml")
    for tb in soup.find_all("table"):
        cells = [[c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])] for r in tb.find_all("tr")]
        if cells and cells[0][:2] == ["Metric", "Value"]:
            m = {r[0]: r[1] for r in cells[1:] if len(r) >= 2}
            d["gmp_first"] = _num(m.get("First GMP"))
            d["gmp_latest"] = _num(m.get("Latest GMP"))
            d["gmp_range"] = _num(m.get("GMP Range"))
            d["gmp_pos_sessions_pct"] = _num(m.get("Positive Sessions"))
            d["gmp_neg_sessions_pct"] = _num(m.get("Negative Sessions"))
            d["gmp_slope"] = _num(m.get("Trend Slope"))
            break
    return d


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------
def _get(client: httpx.Client, url: str) -> Optional[str]:
    for attempt in range(3):
        try:
            r = client.get(url)
            if r.status_code == 200:
                return r.text
            logger.warning(f"{url} -> HTTP {r.status_code}")
        except httpx.HTTPError as e:
            logger.warning(f"{url} failed: {e}")
        time.sleep(2 ** (attempt + 1))
    return None


def _cached(path: str, fetch, max_age_h: Optional[float]) -> Optional[str]:
    if os.path.exists(path) and (max_age_h is None or (time.time() - os.path.getmtime(path)) / 3600 < max_age_h):
        with open(path, encoding="utf-8") as f:
            return f.read()
    html = fetch()
    if html:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
    return html


def scrape_history(start_year: int = 2019, end_year: Optional[int] = None,
                   skip_ids: Optional[set] = None) -> List[Dict]:
    """
    Every listed mainboard IPO from start_year with detail fields merged in.
    skip_ids: IPOs already stored (their detail pages are not re-fetched).
    """
    end_year = end_year or date.today().year
    skip_ids = skip_ids or set()
    out: List[Dict] = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        for y in range(start_year, end_year + 1):
            # Past years never change; the current year is refreshed daily.
            age = None if y < date.today().year else 12
            html = _cached(os.path.join(CACHE_DIR, f"tracker_{y}.html"),
                           lambda: (time.sleep(DELAY_S), _get(client, TRACKER.format(year=y)))[1], age)
            rows = parse_tracker(html) if html else []
            logger.info(f"IPO tracker {y}: {len(rows)} mainboard IPOs")
            for r in rows:
                if r["ig_id"] in skip_ids or not r["url"] or r["listing_gain_pct"] is None:
                    continue
                dh = _cached(os.path.join(CACHE_DIR, f"ipo_{r['ig_id']}.html"),
                             lambda: (time.sleep(DELAY_S), _get(client, r["url"]))[1], None)
                if dh:
                    r.update(parse_detail(dh))
                out.append(r)
    return out


def scrape_current() -> List[Dict]:
    """Upcoming/open IPOs from the live GMP page, with details, for scoring."""
    out = []
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as client:
        html = _get(client, BASE + "/report/ipo-gmp-live/331/")
        if not html:
            return out
        t = rsc_text(html)
        dec = json.JSONDecoder()
        seen = set()
        for m in re.finditer(r'\[\{"~', t):
            try:
                arr, _ = dec.raw_decode(t[m.start():])
            except ValueError:
                continue
            for r in arr:
                if not isinstance(r, dict) or "~id" not in r or r["~id"] in seen:
                    continue
                if (r.get("~IPO_Category") or "IPO") != "IPO" or not r.get("~urlrewrite_folder_name"):
                    continue
                seen.add(r["~id"])
                row = {
                    "ig_id": int(r["~id"]),
                    "name": (r.get("~ipo_name") or re.sub(r"<[^>]+>", " ", r.get("Name") or "")).strip(),
                    "issue_open_date": _date(r.get("~Srt_Open")),
                    "issue_close_date": _date(r.get("~Srt_Close")),
                    "listing_date": _date(r.get("~Str_Listing")),
                    "gmp": _num(r.get("GMP")), "issue_price": _num(r.get("Price (₹)") or r.get("Price")),
                    "issue_size_cr": _num(r.get("IPO Size")), "subscription_x": _num(r.get("Sub")),
                    "url": BASE + r["~urlrewrite_folder_name"],
                }
                time.sleep(DELAY_S)
                dh = _get(client, row["url"])
                if dh:
                    row.update(parse_detail(dh))
                out.append(row)
    return out
