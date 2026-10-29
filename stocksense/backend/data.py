"""Market-data layer for StockSense AI.

Live data comes from Yahoo Finance through `yfinance` (NSE: SYMBOL.NS, BSE: SYMBOL.BO,
indices: ^NSEI, ^BSESN). Yahoo data for Indian exchanges is typically near-real-time to
~15 min delayed. To use a true real-time feed, replace `quote()` and `history()` with calls
to a broker API (Zerodha Kite, Upstox, Angel One SmartAPI) - the rest of the app only
depends on the shapes returned here.

Set STOCKSENSE_DEMO=1 to use synthetic data (offline development only).
"""
from __future__ import annotations

import hashlib
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None

DEMO = os.getenv("STOCKSENSE_DEMO", "0") == "1"
IST = timezone(timedelta(hours=5, minutes=30))


class DataError(Exception):
    """Raised when market data cannot be retrieved."""


INDICES = {"NIFTY 50": "^NSEI", "SENSEX": "^BSESN", "BANK NIFTY": "^NSEBANK"}

STOCKS = [
    ("RELIANCE", "Reliance Industries"), ("TCS", "Tata Consultancy Services"),
    ("HDFCBANK", "HDFC Bank"), ("ICICIBANK", "ICICI Bank"), ("INFY", "Infosys"),
    ("HINDUNILVR", "Hindustan Unilever"), ("ITC", "ITC"), ("SBIN", "State Bank of India"),
    ("BHARTIARTL", "Bharti Airtel"), ("KOTAKBANK", "Kotak Mahindra Bank"),
    ("LT", "Larsen & Toubro"), ("AXISBANK", "Axis Bank"), ("ASIANPAINT", "Asian Paints"),
    ("MARUTI", "Maruti Suzuki"), ("SUNPHARMA", "Sun Pharma"), ("TITAN", "Titan Company"),
    ("ULTRACEMCO", "UltraTech Cement"), ("WIPRO", "Wipro"), ("HCLTECH", "HCL Technologies"),
    ("NESTLEIND", "Nestle India"), ("BAJFINANCE", "Bajaj Finance"),
    ("BAJAJFINSV", "Bajaj Finserv"), ("TATASTEEL", "Tata Steel"),
    ("POWERGRID", "Power Grid"), ("NTPC", "NTPC"), ("ONGC", "ONGC"),
    ("ADANIENT", "Adani Enterprises"), ("ADANIPORTS", "Adani Ports"),
    ("M&M", "Mahindra & Mahindra"), ("TECHM", "Tech Mahindra"),
    ("COALINDIA", "Coal India"), ("JSWSTEEL", "JSW Steel"), ("INDUSINDBK", "IndusInd Bank"),
    ("DRREDDY", "Dr. Reddy's"), ("CIPLA", "Cipla"), ("EICHERMOT", "Eicher Motors"),
    ("HEROMOTOCO", "Hero MotoCorp"), ("BRITANNIA", "Britannia"), ("GRASIM", "Grasim"),
    ("HINDALCO", "Hindalco"),
]
NAMES = {s: n for s, n in STOCKS}
NAMES.update({"^NSEI": "NIFTY 50", "^BSESN": "SENSEX", "^NSEBANK": "BANK NIFTY"})
ALIASES = {"NIFTY": "^NSEI", "NIFTY50": "^NSEI", "NIFTY 50": "^NSEI", "SENSEX": "^BSESN",
           "BANKNIFTY": "^NSEBANK", "BANK NIFTY": "^NSEBANK"}
MOVERS = [s for s, _ in STOCKS[:20]]

PERIOD_DAYS = {"1d": 1, "5d": 5, "1mo": 22, "3mo": 66, "6mo": 132, "1y": 252,
               "2y": 504, "5y": 1260, "10y": 2520, "max": 2600}
ALLOWED_INTERVALS = {"1m", "2m", "5m", "15m", "30m", "60m", "1d", "1wk", "1mo"}

_CACHE: dict = {}


def _memo(key, ttl, fn):
    hit = _CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


# --------------------------------------------------------------------------- helpers
def normalize(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        raise DataError("Empty symbol")
    if s in ALIASES:
        return ALIASES[s]
    if s.startswith("^") or "." in s:
        return s
    return s + ".NS"


def display_symbol(sym: str) -> str:
    for suf in (".NS", ".BO"):
        if sym.endswith(suf):
            return sym[: -len(suf)]
    return sym


def name_for(sym: str) -> str:
    return NAMES.get(sym) or NAMES.get(display_symbol(sym)) or display_symbol(sym)


def now_ist() -> datetime:
    return datetime.now(IST)


def market_status() -> dict:
    n = now_ist()
    open_t, close_t = n.replace(hour=9, minute=15, second=0, microsecond=0), n.replace(hour=15, minute=30, second=0, microsecond=0)
    is_open = n.weekday() < 5 and open_t <= n <= close_t
    if n.weekday() >= 5:
        text = "Closed - weekend"
    elif n < open_t:
        text = "Pre-open - opens 9:15 IST"
    elif n > close_t:
        text = "Closed - reopens next trading day"
    else:
        text = "Open - trading session"
    return {"open": is_open, "text": text, "time_ist": n.strftime("%d %b %Y, %H:%M:%S IST")}


def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except Exception:
        return None


# --------------------------------------------------------------------------- demo data
def _seed(sym: str) -> int:
    return int(hashlib.md5(sym.encode()).hexdigest()[:8], 16)


def _demo_daily(sym: str, days: int = 2700) -> pd.DataFrame:
    seed = _seed(sym)
    rng = np.random.default_rng(seed)
    end = pd.Timestamp.now(tz=IST).tz_localize(None).normalize()
    idx = pd.bdate_range(end=end, periods=days)
    base = {"^NSEI": 24500, "^BSESN": 80500, "^NSEBANK": 53000}.get(sym, 120 + seed % 2800)
    r = rng.normal(0.0004, 0.013, days)
    path = np.cumsum(r)
    close = base * np.exp(path - path[-1])
    open_ = close * (1 + rng.normal(0, 0.004, days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, days)))
    vol = rng.integers(200_000, 6_000_000, days)
    return pd.DataFrame({"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol}, index=idx)


def _demo_history(sym: str, period: str, interval: str) -> pd.DataFrame:
    daily = _demo_daily(sym)
    n = PERIOD_DAYS.get(period, 252)
    if interval in ("1d", "1wk", "1mo"):
        df = daily.tail(n)
        if interval != "1d":
            key = df.index.to_period("W-FRI" if interval == "1wk" else "M")
            df = df.groupby(key).agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
            df.index = df.index.to_timestamp()
        return df
    step = int(interval.rstrip("m"))
    frames = []
    for date, row in daily.tail(max(1, n)).iterrows():
        times = pd.date_range(date + pd.Timedelta(hours=9, minutes=15), date + pd.Timedelta(hours=15, minutes=29), freq=f"{step}min")
        rng = np.random.default_rng(_seed(sym) + int(date.strftime("%Y%m%d")))
        t = np.linspace(0, 1, len(times))
        noise = np.cumsum(rng.normal(0, row.Close * 0.0006, len(times)))
        path = row.Open + (row.Close - row.Open) * t + (noise - t * noise[-1])
        frames.append(pd.DataFrame({"Open": path, "High": path * 1.0007, "Low": path * 0.9993, "Close": path,
                                    "Volume": rng.integers(1_000, 90_000, len(times))}, index=times))
    return pd.concat(frames)


# --------------------------------------------------------------------------- public API
def history(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    sym = normalize(symbol)
    if period not in PERIOD_DAYS:
        raise DataError(f"Unsupported period '{period}'")
    if interval not in ALLOWED_INTERVALS:
        raise DataError(f"Unsupported interval '{interval}'")
    intraday = interval.endswith("m") and interval != "1mo"
    ttl = 30 if intraday else 300

    def go():
        if DEMO:
            return _demo_history(sym, period, interval)
        if yf is None:
            raise DataError("yfinance is not installed")
        try:
            df = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=True)
        except Exception as e:
            raise DataError(f"Data provider error for {sym}: {e}")
        if df is None or df.empty:
            raise DataError(f"No data returned for {display_symbol(sym)}. Check the symbol (NSE) or try again.")
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        idx = df.index
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("Asia/Kolkata").tz_localize(None)
        if not intraday:
            idx = idx.normalize()
        df.index = idx
        return df

    return _memo(("hist", sym, period, interval), ttl, go).copy()


def quote(symbol: str) -> dict:
    sym = normalize(symbol)

    def go():
        price = prev = op = hi = lo = vol = yh = yl = None
        source = "demo" if DEMO else "yahoo"
        if not DEMO and yf is not None:
            try:
                fi = yf.Ticker(sym).fast_info
                g = lambda k: _f(fi[k]) if k in fi else None  # noqa: E731
                price, prev = g("last_price"), g("previous_close")
                op, hi, lo, vol = g("open"), g("day_high"), g("day_low"), g("last_volume")
                yh, yl = g("year_high"), g("year_low")
            except Exception:
                price = prev = None
        if price is None or prev is None:
            d = history(sym, "5d", "1d")
            if len(d) < 1:
                raise DataError(f"No quote for {display_symbol(sym)}")
            price = float(d["Close"].iloc[-1])
            prev = float(d["Close"].iloc[-2]) if len(d) > 1 else price
            op, hi, lo, vol = (float(d["Open"].iloc[-1]), float(d["High"].iloc[-1]), float(d["Low"].iloc[-1]), float(d["Volume"].iloc[-1]))
            if DEMO:  # tiny jitter so the demo visibly "ticks"
                price *= 1 + math.sin(time.time() / 20 + _seed(sym) % 7) * 0.0008
        if yh is None or yl is None:
            try:
                y = history(sym, "1y", "1d")
                yh, yl = float(y["High"].max()), float(y["Low"].min())
            except DataError:
                pass
        chg = price - prev
        return {
            "symbol": display_symbol(sym), "ticker": sym, "name": name_for(sym), "price": price, "prev_close": prev,
            "change": chg, "change_pct": (chg / prev * 100) if prev else 0.0, "open": op, "high": hi, "low": lo,
            "volume": vol, "year_high": yh, "year_low": yl,
            "as_of": now_ist().strftime("%H:%M:%S IST"), "source": source,
        }

    return _memo(("quote", sym), 10, go)


def quotes(symbols: list[str]) -> list[dict]:
    def one(s):
        try:
            return quote(s)
        except Exception as e:
            return {"symbol": display_symbol(s.upper()), "error": str(e)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        return list(ex.map(one, symbols))


def search(q: str, limit: int = 10) -> list[dict]:
    q = (q or "").strip()
    if not q:
        return []
    ql = q.lower()
    out, seen = [], set()
    ranked = sorted(STOCKS, key=lambda t: (not t[0].lower().startswith(ql), not t[1].lower().startswith(ql)))
    for s, n in ranked:
        if ql in s.lower() or ql in n.lower():
            out.append({"symbol": s, "name": n, "exchange": "NSE"})
            seen.add(s)
    for n, t in INDICES.items():
        if ql in n.lower():
            out.append({"symbol": display_symbol(t), "name": n, "exchange": "Index"})
    if not DEMO and yf is not None and len(out) < limit and hasattr(yf, "Search"):
        try:
            for r in yf.Search(q, max_results=10).quotes:
                sym = r.get("symbol", "")
                if sym.endswith((".NS", ".BO")) and display_symbol(sym) not in seen:
                    out.append({"symbol": sym, "name": r.get("shortname") or r.get("longname") or sym,
                                "exchange": "NSE" if sym.endswith(".NS") else "BSE"})
                    seen.add(display_symbol(sym))
        except Exception:
            pass
    if not out:
        out.append({"symbol": q.upper(), "name": "Try this symbol", "exchange": "NSE"})
    return out[:limit]
