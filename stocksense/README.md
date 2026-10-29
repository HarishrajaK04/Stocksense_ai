# StockSense AI

AI-powered Indian stock market intelligence platform: FastAPI backend + single-page dashboard.
A research tool, **not** investment advice.

## Features
Market Overview, Market Explorer (search, charts, SMA/volume, compare), News & Sentiment, AI Chatbot,
Forecast Lab (Ridge / Random Forest / Gradient Boosting with honest baseline comparison),
Model Intelligence, Strategy Lab (backtests), Risk Center, Watchlist, Settings.

## Run locally (Python 3.11-3.13 recommended; very new versions may lack prebuilt packages)
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
# open http://localhost:8000
```
The backend serves the dashboard too, so this single command runs everything.

Optional:
- `ANTHROPIC_API_KEY=...` enables the LLM chatbot (otherwise a rule-based assistant is used). Model: `STOCKSENSE_LLM_MODEL` (default `claude-haiku-5-5`).
- `STOCKSENSE_DEMO=1` uses synthetic data for offline development. The UI shows a demo banner.

## How "real time" works here
- Quotes come from Yahoo Finance via `yfinance` (NSE `SYMBOL.NS`, indices `^NSEI`, `^BSESN`). For Indian exchanges this is
  usually near-real-time but can be delayed up to ~15 minutes. Quotes are cached for 10 s, intraday charts for 30 s.
- The dashboard auto-refreshes the Overview and Watchlist (default every 30 s; change it in Settings).
- For tick-by-tick data you need a broker feed (Zerodha Kite Connect, Upstox, Angel One SmartAPI - Angel's is free with an account).
  Swap the bodies of `quote()` and `history()` in `backend/data.py`; nothing else changes.

## Deploy (public URL)
**Option A - one service (simplest).** Push this folder to GitHub, create a Render *Web Service* from the repo
(`render.yaml` is included). Render gives you `https://<name>.onrender.com` serving both API and dashboard.
Free instances sleep when idle, so the first request can take ~30 s.

**Option B - split.** Host `frontend/` on Netlify/Vercel/GitHub Pages and the API on Render/Railway. Then set
`window.STOCKSENSE_API = "https://your-api..."` in `frontend/index.html` (or in Settings) and restrict
`CORS_ORIGINS` on the backend to your frontend URL.

## Project layout
```
backend/  main.py (API) | data.py (market data) | news.py | sentiment.py | analytics.py (indicators, risk, backtest, forecast) | chatbot.py
frontend/ index.html | styles.css | app.js (Chart.js)
```

## Honest notes
- Forecasting daily stock prices is hard; the lab reports out-of-sample error next to a naive baseline so you can see when a model adds nothing.
- Backtests assume next-bar execution and a flat per-side cost; no slippage, taxes or liquidity limits.
- Sentiment is a transparent lexicon on headlines only. Swap in FinBERT behind `sentiment.score()` for more nuance.
- Yahoo data is unofficial and may break or be inaccurate; verify with your broker before acting.
