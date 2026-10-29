"""Analytics: indicators, risk metrics, strategy backtesting and ML forecasting."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

RISK_FREE = 0.07  # annual, approx. Indian 10y G-sec yield
TRADING_DAYS = 252


def _clean(arr):
    return [None if (x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))) else float(x) for x in arr]


def _dates(idx, intraday=False):
    fmt = "%Y-%m-%d %H:%M" if intraday else "%Y-%m-%d"
    return [d.strftime(fmt) for d in idx]


def _is_intraday(df: pd.DataFrame) -> bool:
    return len(df) > 1 and (df.index[1] - df.index[0]) < pd.Timedelta(hours=20)


# --------------------------------------------------------------------------- indicators
def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up, dn = d.clip(lower=0), -d.clip(upper=0)
    ru, rd = up.ewm(alpha=1 / n, adjust=False).mean(), dn.ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + ru / rd.replace(0, np.nan))
    out[rd == 0] = 100.0
    return out


def macd(close: pd.Series):
    line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    sig = line.ewm(span=9, adjust=False).mean()
    return line, sig


def history_payload(df: pd.DataFrame) -> dict:
    c = df["Close"].astype(float)
    m, s = macd(c)
    intr = _is_intraday(df)
    return {
        "dates": _dates(df.index, intr),
        "open": _clean(df["Open"]), "high": _clean(df["High"]), "low": _clean(df["Low"]),
        "close": _clean(c), "volume": _clean(df["Volume"]),
        "sma20": _clean(c.rolling(20).mean()), "sma50": _clean(c.rolling(50).mean()),
        "rsi": _clean(rsi(c)), "macd": _clean(m), "macd_signal": _clean(s),
    }


def technical_summary(df: pd.DataFrame) -> dict:
    c = df["Close"].astype(float)
    out = {}
    if len(c) < 30:
        return out
    r = float(rsi(c).iloc[-1])
    out["rsi"] = round(r, 1)
    out["rsi_view"] = "overbought (>70)" if r > 70 else "oversold (<30)" if r < 30 else "neutral (30-70)"
    sma50 = c.rolling(50).mean().iloc[-1]
    if not np.isnan(sma50):
        out["trend"] = "above 50-day average (uptrend bias)" if c.iloc[-1] > sma50 else "below 50-day average (downtrend bias)"
    m, s = macd(c)
    out["macd_view"] = "MACD above signal (bullish momentum)" if m.iloc[-1] > s.iloc[-1] else "MACD below signal (bearish momentum)"
    return out


# --------------------------------------------------------------------------- risk
def _max_drawdown(equity: pd.Series) -> float:
    return float((equity / equity.cummax() - 1).min())


def risk_metrics(df: pd.DataFrame, bench: pd.DataFrame | None = None) -> dict:
    c = df["Close"].astype(float)
    r = c.pct_change().dropna()
    if len(r) < 30:
        raise ValueError("Need at least ~30 daily observations for risk analysis")
    n = len(r)
    total = float(c.iloc[-1] / c.iloc[0] - 1)
    ann_ret = float((1 + total) ** (TRADING_DAYS / n) - 1)
    vol = float(r.std() * math.sqrt(TRADING_DAYS))
    downside = r[r < 0].std() * math.sqrt(TRADING_DAYS)
    equity = (1 + r).cumprod()
    dd = equity / equity.cummax() - 1
    q05 = float(np.percentile(r, 5))
    beta = None
    if bench is not None and len(bench) > 30:
        b = bench["Close"].astype(float).pct_change().dropna()
        j = pd.concat([r.rename("a"), b.rename("b")], axis=1).dropna()
        if len(j) > 30 and j["b"].var() > 0:
            beta = float(j["a"].cov(j["b"]) / j["b"].var())
    hist, edges = np.histogram(r * 100, bins=30)
    rolling = (r.rolling(30).std() * math.sqrt(TRADING_DAYS) * 100)
    level = "Low" if vol < 0.18 else "Moderate" if vol < 0.30 else "High" if vol < 0.45 else "Very high"
    return {
        "observations": n, "total_return": total, "annualized_return": ann_ret, "annualized_volatility": vol,
        "sharpe": (ann_ret - RISK_FREE) / vol if vol else None,
        "sortino": (ann_ret - RISK_FREE) / float(downside) if downside and not np.isnan(downside) else None,
        "max_drawdown": float(dd.min()), "var_95": -q05, "cvar_95": float(-r[r <= q05].mean()),
        "beta": beta, "best_day": float(r.max()), "worst_day": float(r.min()),
        "positive_days_pct": float((r > 0).mean()), "risk_level": level,
        "drawdown": {"dates": _dates(dd.index), "values": _clean(dd * 100)},
        "rolling_vol": {"dates": _dates(rolling.index), "values": _clean(rolling)},
        "histogram": {"labels": [f"{(edges[i] + edges[i + 1]) / 2:.1f}" for i in range(len(hist))], "counts": [int(x) for x in hist]},
    }


# --------------------------------------------------------------------------- backtesting
def _signal(close: pd.Series, strategy: str, p: dict) -> pd.Series:
    if strategy == "buy_hold":
        return pd.Series(1.0, index=close.index)
    if strategy == "sma_cross":
        fast, slow = int(p.get("fast", 20)), int(p.get("slow", 50))
        if fast >= slow:
            raise ValueError("Fast window must be smaller than slow window")
        f, s = close.rolling(fast).mean(), close.rolling(slow).mean()
        sig = (f > s).astype(float)
        sig[s.isna()] = 0.0
        return sig
    if strategy == "rsi_reversion":
        lo, hi, n = float(p.get("buy_below", 30)), float(p.get("sell_above", 70)), int(p.get("period", 14))
        r = rsi(close, n).values
        pos, out = 0.0, []
        for v in r:
            if not np.isnan(v):
                if v < lo:
                    pos = 1.0
                elif v > hi:
                    pos = 0.0
            out.append(pos)
        return pd.Series(out, index=close.index)
    if strategy == "breakout":
        n_in, n_out = int(p.get("entry", 20)), int(p.get("exit", 10))
        up, dn = close.shift(1).rolling(n_in).max(), close.shift(1).rolling(n_out).min()
        pos, out = 0.0, []
        for c, u, d in zip(close.values, up.values, dn.values):
            if not np.isnan(u) and c > u:
                pos = 1.0
            elif not np.isnan(d) and c < d:
                pos = 0.0
            out.append(pos)
        return pd.Series(out, index=close.index)
    raise ValueError(f"Unknown strategy '{strategy}'")


def _perf(equity: pd.Series, rets: pd.Series) -> dict:
    years = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    tot = float(equity.iloc[-1] / equity.iloc[0] - 1)
    vol = float(rets.std() * math.sqrt(TRADING_DAYS))
    ann = float(rets.mean() * TRADING_DAYS)
    return {"total_return": tot, "cagr": float((1 + tot) ** (1 / years) - 1) if tot > -1 else -1.0,
            "volatility": vol, "sharpe": (ann - RISK_FREE) / vol if vol else None, "max_drawdown": _max_drawdown(equity)}


def backtest(df: pd.DataFrame, strategy: str, params: dict, capital: float = 100000.0, cost_bps: float = 10.0) -> dict:
    close = df["Close"].astype(float)
    if len(close) < 60:
        raise ValueError("Not enough history to backtest (need >= 60 daily bars)")
    sig = _signal(close, strategy, params or {})
    pos = sig.shift(1).fillna(0.0)  # trade on next bar: no look-ahead
    ret = close.pct_change().fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.iloc[0])
    strat_ret = pos * ret - turnover * cost_bps / 10000.0
    equity = capital * (1 + strat_ret).cumprod()
    bh = capital * (1 + ret).cumprod()

    trades, entry_px, entry_dt = [], None, None
    cost_frac = 2 * cost_bps / 10000.0
    prev = 0.0
    for dt, p, px in zip(close.index, pos.values, close.values):
        if p == 1.0 and prev == 0.0:
            entry_px, entry_dt = px, dt
        elif p == 0.0 and prev == 1.0 and entry_px:
            trades.append({"entry": dt_s(entry_dt), "exit": dt_s(dt), "entry_price": float(entry_px), "exit_price": float(px),
                           "return_pct": float((px / entry_px - 1 - cost_frac) * 100), "status": "closed"})
            entry_px = None
        prev = p
    if entry_px:
        px = close.iloc[-1]
        trades.append({"entry": dt_s(entry_dt), "exit": dt_s(close.index[-1]), "entry_price": float(entry_px), "exit_price": float(px),
                       "return_pct": float((px / entry_px - 1 - cost_frac / 2) * 100), "status": "open"})
    closed = [t for t in trades if t["status"] == "closed"]
    wins = [t for t in closed if t["return_pct"] > 0]
    metrics = _perf(equity, strat_ret)
    metrics.update({"trades": len(trades), "win_rate": (len(wins) / len(closed)) if closed else None,
                    "time_in_market": float(pos.mean()),
                    "avg_trade_pct": float(np.mean([t["return_pct"] for t in closed])) if closed else None,
                    "final_value": float(equity.iloc[-1])})
    bh_metrics = _perf(bh, ret)
    bh_metrics["final_value"] = float(bh.iloc[-1])
    return {
        "dates": _dates(close.index), "equity": _clean(equity), "buy_hold": _clean(bh),
        "buy_markers": [t["entry"] for t in trades],
        "sell_markers": [t["exit"] for t in closed],
        "metrics": metrics, "buy_hold_metrics": bh_metrics, "trades": trades[-50:][::-1],
        "assumptions": f"Signals act on the next daily bar; {cost_bps:g} bps cost per side; long-only, fully invested when in position; no slippage, taxes or liquidity limits.",
    }


def dt_s(d):
    return d if isinstance(d, str) else d.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- forecasting
def _features(close: pd.Series) -> pd.DataFrame:
    r = np.log(close).diff()
    return pd.DataFrame({
        "r1": r, "r2": r.shift(1), "r3": r.shift(2), "r5": r.rolling(5).mean(), "r10": r.rolling(10).mean(),
        "vol10": r.rolling(10).std(), "vol20": r.rolling(20).std(),
        "ma5": close / close.rolling(5).mean() - 1, "ma20": close / close.rolling(20).mean() - 1,
        "ma50": close / close.rolling(50).mean() - 1, "rsi": rsi(close) / 100.0,
    })


def _make_model(name: str):
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if name == "ridge":
        return make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    if name == "random_forest":
        return RandomForestRegressor(n_estimators=200, max_depth=5, min_samples_leaf=10, n_jobs=-1, random_state=42)
    if name == "gradient_boosting":
        return GradientBoostingRegressor(n_estimators=150, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=42)
    raise ValueError(f"Unknown model '{name}'")


def forecast(df: pd.DataFrame, model_name: str = "ridge", horizon: int = 10) -> dict:
    close = df["Close"].astype(float).copy()
    close = close[~close.index.duplicated()]
    if len(close) < 250:
        raise ValueError("Need at least ~250 daily bars (use a 2y+ period) to train and validate a model")
    horizon = max(1, min(int(horizon), 30))
    feats = _features(close)
    target = np.log(close).diff().shift(-1)
    full = pd.concat([feats, target.rename("y")], axis=1).dropna()
    X, y = full.drop(columns="y"), full["y"]
    split = int(len(full) * 0.8)
    Xtr, Xte, ytr, yte = X.iloc[:split], X.iloc[split:], y.iloc[:split], y.iloc[split:]

    model = _make_model(model_name)
    model.fit(Xtr, ytr)
    pred = pd.Series(model.predict(Xte), index=Xte.index)

    px_t = close.reindex(Xte.index)
    actual_next = px_t * np.exp(yte)
    pred_next = px_t * np.exp(pred)
    naive_next = px_t
    mape = lambda a, b: float(np.mean(np.abs((a - b) / a)) * 100)  # noqa: E731
    rmse = lambda a, b: float(np.sqrt(np.mean((a - b) ** 2)))  # noqa: E731
    majority_up = float((ytr > 0).mean() >= 0.5)
    base_dir = float(((yte > 0).astype(float) == majority_up).mean())
    metrics = {
        "model": {"rmse_return": rmse(yte, pred), "mae_return": float(np.mean(np.abs(yte - pred))),
                  "price_mape_pct": mape(actual_next, pred_next),
                  "directional_accuracy": float(((pred > 0) == (yte > 0)).mean())},
        "naive_baseline": {"rmse_return": rmse(yte, 0 * yte), "mae_return": float(np.mean(np.abs(yte))),
                           "price_mape_pct": mape(actual_next, naive_next), "directional_accuracy": base_dir},
        "train_rows": int(len(Xtr)), "test_rows": int(len(Xte)),
    }
    m, b = metrics["model"], metrics["naive_baseline"]
    metrics["beats_naive_rmse"] = bool(m["rmse_return"] < b["rmse_return"])
    metrics["beats_naive_direction"] = bool(m["directional_accuracy"] > b["directional_accuracy"])

    # Refit on everything and roll forward recursively
    final = _make_model(model_name)
    final.fit(X, y)
    resid_sd = float(np.std(yte - pred))
    series = close.copy()
    last_dt = series.index[-1]
    fdates = pd.bdate_range(last_dt + pd.Timedelta(days=1), periods=horizon)
    f_vals, lo, hi = [], [], []
    for k, dt in enumerate(fdates, start=1):
        row = _features(series).iloc[[-1]]
        r_hat = float(final.predict(row)[0])
        new_px = float(series.iloc[-1] * math.exp(r_hat))
        series.loc[dt] = new_px
        f_vals.append(new_px)
        band = 1.96 * resid_sd * math.sqrt(k)
        lo.append(new_px * math.exp(-band))
        hi.append(new_px * math.exp(band))

    tail = close.tail(120)
    test_tail = pred_next.tail(60)
    return {
        "history": {"dates": _dates(tail.index), "close": _clean(tail)},
        "test_predictions": {"dates": _dates(test_tail.index + pd.Timedelta(days=0)), "predicted_close_next_day": _clean(test_tail),
                             "actual_close_next_day": _clean(actual_next.reindex(test_tail.index))},
        "forecast": {"dates": _dates(fdates), "values": _clean(f_vals), "lower": _clean(lo), "upper": _clean(hi)},
        "metrics": metrics, "last_close": float(close.iloc[-1]),
        "expected_change_pct": float((f_vals[-1] / close.iloc[-1] - 1) * 100),
        "disclaimer": "Daily stock returns are close to random. Treat this as an educational experiment, not a trading signal. Bands widen with horizon and are approximate.",
    }
