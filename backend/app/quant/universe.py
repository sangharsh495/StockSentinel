"""
Stock universe used for training and backtesting.

Large, liquid NSE names (roughly the Nifty 100). Using today's list for
past years adds survivorship bias, so backtests are always compared
against an equal-weight portfolio of this same list, not only the Nifty.
"""

NIFTY_INDEX = "^NSEI"
VIX_INDEX = "^INDIAVIX"

UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "BHARTIARTL", "ITC",
    "SBIN", "LT", "HINDUNILVR", "KOTAKBANK", "AXISBANK", "BAJFINANCE",
    "MARUTI", "HCLTECH", "SUNPHARMA", "M&M", "TITAN", "ASIANPAINT",
    "ULTRACEMCO", "NTPC", "POWERGRID", "ONGC", "TATASTEEL", "WIPRO",
    "NESTLEIND", "ADANIENT", "ADANIPORTS", "JSWSTEEL", "COALINDIA",
    "BAJAJFINSV", "TECHM", "GRASIM", "HINDALCO", "DRREDDY", "CIPLA",
    "BRITANNIA", "EICHERMOT", "HEROMOTOCO", "APOLLOHOSP", "DIVISLAB", "BPCL",
    "INDUSINDBK", "TATACONSUM", "SBILIFE", "HDFCLIFE", "BAJAJ-AUTO",
    "SHRIRAMFIN", "TRENT", "BEL", "HAL", "DLF", "PIDILITIND", "SIEMENS",
    "GODREJCP", "DABUR", "HAVELLS", "AMBUJACEM", "SHREECEM", "VEDL", "IOC",
    "GAIL", "TATAPOWER", "BANKBARODA", "PNB", "CANBK", "CHOLAFIN", "ICICIGI",
    "ICICIPRULI", "MARICO", "COLPAL", "BERGEPAINT", "TORNTPHARM", "LUPIN",
    "AUROPHARMA", "ZYDUSLIFE", "MOTHERSON", "BOSCHLTD", "TVSMOTOR", "ABB",
    "INDIGO", "NAUKRI", "LTIM", "PERSISTENT", "MPHASIS", "COFORGE", "SRF",
    "PIIND", "UPL", "JINDALSTEL", "SAIL", "NMDC", "HINDPETRO", "PETRONET",
    "IRCTC", "BHEL", "RECLTD", "PFC", "MUTHOOTFIN", "DMART",
]


def yf_ticker(symbol: str) -> str:
    return f"{symbol}.NS"
