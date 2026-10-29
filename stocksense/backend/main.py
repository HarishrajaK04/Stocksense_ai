"""StockSense AI - FastAPI backend (also serves the dashboard from ../frontend)."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics, chatbot, data, news

app = FastAPI(title="StockSense AI", version="1.0.0")
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except data.DataError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ------------------------------------------------------------------ market
@app.get("/api/health")
def health():
    return {"ok": True, "demo": data.DEMO, "market": data.market_status(), "llm": bool(os.getenv("ANTHROPIC_API_KEY"))}


@app.get("/api/stocks")
def stocks():
    return [{"symbol": s, "name": n} for s, n in data.STOCKS]


@app.get("/api/overview")
def overview():
    idx = data.quotes(list(data.INDICES.values()))
    movers = data.quotes(data.MOVERS)
    ok = [m for m in movers if "error" not in m]
    adv = sum(1 for m in ok if m["change_pct"] > 0)
    dec = sum(1 for m in ok if m["change_pct"] < 0)
    summary = {"advancers": adv, "decliners": dec, "unchanged": len(ok) - adv - dec, "sample": len(ok)}
    if ok:
        g, l = max(ok, key=lambda m: m["change_pct"]), min(ok, key=lambda m: m["change_pct"])
        summary.update(top_gainer={"symbol": g["symbol"], "change_pct": g["change_pct"]},
                       top_loser={"symbol": l["symbol"], "change_pct": l["change_pct"]})
    nifty = next((q for q in idx if q.get("symbol") == "^NSEI" or q.get("ticker") == "^NSEI"), None)
    if nifty and "error" not in nifty:
        tone = "higher" if nifty["change_pct"] > 0.1 else "lower" if nifty["change_pct"] < -0.1 else "flat"
        summary["text"] = (f"NIFTY 50 is trading {tone} at {nifty['price']:,.2f} ({nifty['change_pct']:+.2f}%). "
                           f"Among {len(ok)} large caps tracked, {adv} are up and {dec} are down.")
    source = next((q.get("source") for q in idx if "source" in q), "n/a")
    return {"market": data.market_status(), "indices": idx, "movers": movers, "summary": summary, "source": source}


@app.get("/api/quote/{symbol}")
def get_quote(symbol: str):
    return _guard(data.quote, symbol)


@app.get("/api/quotes")
def get_quotes(symbols: str = Query(..., description="comma separated")):
    syms = [s for s in (x.strip() for x in symbols.split(",")) if s][:40]
    return data.quotes(syms)


@app.get("/api/search")
def search(q: str = ""):
    return data.search(q)


@app.get("/api/history/{symbol}")
def get_history(symbol: str, period: str = "1y", interval: str = "1d"):
    df = _guard(data.history, symbol, period, interval)
    return {"symbol": data.display_symbol(data.normalize(symbol)), "name": data.name_for(data.normalize(symbol)),
            "period": period, "interval": interval, **analytics.history_payload(df), "technical": analytics.technical_summary(df)}


@app.get("/api/compare")
def compare(symbols: str, period: str = "1y"):
    syms = [s.strip() for s in symbols.split(",") if s.strip()][:6]
    if len(syms) < 2:
        raise HTTPException(422, "Provide at least two symbols")
    import pandas as pd

    frames, names = {}, {}
    for s in syms:
        df = _guard(data.history, s, period, "1d")
        key = data.display_symbol(data.normalize(s))
        frames[key] = df["Close"].astype(float)
        names[key] = data.name_for(data.normalize(s))
    joined = pd.concat(frames, axis=1).dropna()
    if len(joined) < 5:
        raise HTTPException(422, "Not enough overlapping history")
    rebased = joined / joined.iloc[0] * 100
    stats = [{"symbol": k, "name": names[k], "return_pct": float(rebased[k].iloc[-1] - 100),
              "volatility_pct": float(joined[k].pct_change().std() * (252 ** 0.5) * 100)} for k in rebased.columns]
    return {"dates": [d.strftime("%Y-%m-%d") for d in rebased.index],
            "series": {k: analytics._clean(rebased[k]) for k in rebased.columns}, "stats": stats}


# ------------------------------------------------------------------ news / chat
@app.get("/api/news")
def get_news(symbol: str | None = None, limit: int = 25, extra: str = ""):
    return news.fetch(symbol or None, max(1, min(limit, 50)), extra[:80])


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[dict] = []


@app.post("/api/chat")
def chat(body: ChatIn):
    return chatbot.answer(body.message, body.history)


# ------------------------------------------------------------------ labs
class ForecastIn(BaseModel):
    symbol: str
    model: str = "ridge"
    horizon: int = 10
    period: str = "5y"


@app.post("/api/forecast")
def run_forecast(b: ForecastIn):
    df = _guard(data.history, b.symbol, b.period, "1d")
    out = _guard(analytics.forecast, df, b.model, b.horizon)
    out["symbol"] = data.display_symbol(data.normalize(b.symbol))
    out["model_name"] = b.model
    return out


class BacktestIn(BaseModel):
    symbol: str
    strategy: str = "sma_cross"
    params: dict = {}
    period: str = "5y"
    capital: float = Field(100000, gt=0)
    cost_bps: float = Field(10, ge=0, le=500)


@app.post("/api/backtest")
def run_backtest(b: BacktestIn):
    df = _guard(data.history, b.symbol, b.period, "1d")
    out = _guard(analytics.backtest, df, b.strategy, b.params, b.capital, b.cost_bps)
    out["symbol"] = data.display_symbol(data.normalize(b.symbol))
    return out


@app.get("/api/risk/{symbol}")
def risk(symbol: str, period: str = "5y"):
    df = _guard(data.history, symbol, period, "1d")
    try:
        bench = data.history("^NSEI", period, "1d")
    except data.DataError:
        bench = None
    out = _guard(analytics.risk_metrics, df, bench)
    out["symbol"] = data.display_symbol(data.normalize(symbol))
    return out


# ------------------------------------------------------------------ model docs
@app.get("/api/models")
def models():
    return {
        "models": [
            {"name": "Ridge regression", "id": "ridge", "what": "Linear model on standardised features with L2 regularisation. Predicts next-day log return.", "pros": "Fast, stable, hard to overfit.", "cons": "Cannot capture non-linear patterns."},
            {"name": "Random forest", "id": "random_forest", "what": "200 shallow decision trees averaged. Same features and target.", "pros": "Captures non-linear interactions.", "cons": "Can overfit noise; no extrapolation beyond seen ranges."},
            {"name": "Gradient boosting", "id": "gradient_boosting", "what": "Small boosted trees (depth 2) built sequentially on residual errors.", "pros": "Often the strongest tabular learner.", "cons": "Sensitive to hyper-parameters; slower."},
        ],
        "features": ["1/2/3-day lagged log returns", "5 and 10-day mean returns", "10 and 20-day volatility", "Price vs 5/20/50-day averages", "RSI(14)"],
        "validation": "Chronological split: first 80% of history trains the model, last 20% tests it (no shuffling, no look-ahead). Final multi-day forecast refits on all data and rolls forward recursively; bands use test-set residual spread scaled by sqrt(days).",
        "metrics": [
            {"name": "RMSE / MAE (return)", "meaning": "Average size of next-day return errors. Lower is better. Compared against a naive 'no change' baseline."},
            {"name": "Price MAPE", "meaning": "Mean absolute % error of next-day price vs actual."},
            {"name": "Directional accuracy", "meaning": "How often the model got up/down right. ~50% is coin-flip; compared to a majority-class baseline."},
            {"name": "Sharpe / Sortino", "meaning": "Return per unit of total / downside risk, above a 7% risk-free rate."},
            {"name": "Max drawdown, VaR 95%, CVaR 95%", "meaning": "Worst peak-to-trough fall; loss exceeded on 5% of days; average loss on those days."},
        ],
        "sentiment": {"method": "Transparent finance lexicon (~150 weighted terms and phrases) with negation and intensifier handling, squashed to a -1..+1 score. Labels: positive >= 0.15, negative <= -0.15, otherwise neutral.",
                      "limits": "Headline-only, English-only, no sarcasm or context understanding. Upgrading path: swap in a FinBERT model behind the same function."},
        "limitations": [
            "Short-horizon stock returns are very noisy - most models barely beat a naive baseline, and that is a normal, honest result.",
            "Past performance, backtests and historical risk do not guarantee future results.",
            "Backtests ignore slippage, taxes, liquidity and survivorship bias beyond the stated cost assumption.",
            "Data comes from Yahoo Finance and may be delayed or occasionally wrong; verify with your broker before acting.",
            "StockSense AI is a research and education tool, not investment advice.",
        ],
    }


# ------------------------------------------------------------------ frontend
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND.exists():  # mounted last so /api/* routes take precedence
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
