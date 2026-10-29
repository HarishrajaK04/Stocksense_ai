"""StockSense assistant: uses Claude when ANTHROPIC_API_KEY is set, otherwise a rule-based fallback.

Both modes are grounded in the same context (live quote, indicators, risk, headlines) so
answers cite real numbers rather than guessing.
"""
from __future__ import annotations

import os
import re

from . import analytics, data, news

GLOSSARY = {
    "pe ratio": "P/E (price-to-earnings) = share price / earnings per share. It shows how much investors pay for Rs 1 of annual profit. High P/E can mean high growth expectations or an expensive stock; compare within the same sector.",
    "eps": "EPS (earnings per share) = net profit / number of shares. Rising EPS over several quarters is generally a healthy sign.",
    "market cap": "Market capitalisation = share price x total shares. In India, large-cap usually means the top 100 companies, mid-cap the next 150, small-cap the rest (SEBI classification).",
    "rsi": "RSI (Relative Strength Index, 0-100) measures recent momentum. Above 70 is often called overbought, below 30 oversold - but strong trends can stay extreme for long.",
    "macd": "MACD = 12-day EMA minus 26-day EMA, with a 9-day EMA signal line. MACD crossing above the signal line suggests rising momentum; below suggests fading momentum.",
    "sma": "SMA (simple moving average) is the average closing price over N days. Price above the 50/200-day SMA is commonly read as an uptrend.",
    "ema": "EMA (exponential moving average) is like an SMA but gives more weight to recent prices, so it reacts faster.",
    "sharpe": "Sharpe ratio = (return - risk-free rate) / volatility. Higher means better risk-adjusted return; above 1 is generally considered good.",
    "drawdown": "Drawdown is the fall from a previous peak to a later low. Max drawdown is the worst such fall and shows how painful holding the asset could have been.",
    "volatility": "Volatility is how much returns fluctuate, usually annualised standard deviation of daily returns. Higher volatility = bigger swings = more risk.",
    "beta": "Beta measures sensitivity to the market (NIFTY 50). Beta 1.3 means the stock has historically moved ~30% more than the index.",
    "var": "Value at Risk (95%) is the daily loss that was exceeded only on ~5% of days historically. It is a historical estimate, not a worst case.",
    "nifty": "NIFTY 50 is NSE's benchmark index of 50 large Indian companies across sectors.",
    "sensex": "SENSEX is BSE's benchmark index of 30 large, well-established Indian companies.",
    "dividend yield": "Dividend yield = annual dividend per share / share price. It shows cash income as a percentage of price.",
    "p/b": "P/B (price-to-book) = price / book value per share. Often used for banks and asset-heavy firms.",
    "roe": "ROE (return on equity) = net profit / shareholders' equity. Consistently high ROE suggests efficient use of capital.",
    "support": "Support is a price zone where buying has repeatedly halted declines; resistance is where selling has repeatedly halted rallies.",
    "bull market": "A bull market is a sustained rise in prices (often 20%+ from lows); a bear market is a sustained fall (often 20%+ from highs).",
    "circuit": "Circuit limits are daily price bands (e.g. 5%, 10%, 20%) set by exchanges; trading in that stock halts for the day if the band is hit.",
    "backtest": "A backtest simulates a trading rule on past data. Results can be overfit and ignore slippage, taxes and changing market regimes.",
}

SYSTEM = (
    "You are StockSense AI, a research assistant for Indian equities (NSE/BSE). "
    "Use ONLY the numbers in the provided CONTEXT for prices, indicators, risk and news; if something is missing, say so. "
    "Explain terms plainly. Be concise (under 200 words unless asked). Never promise returns or tell the user to buy/sell; "
    "describe what the data shows and the uncertainty. End with a one-line reminder this is research, not financial advice "
    "only when discussing a specific stock's outlook."
)


def _find_symbol(msg: str) -> str | None:
    m = re.search(r"\$([A-Za-z&\-]{2,15})", msg)
    if m:
        return m.group(1).upper()
    low = msg.lower()
    for s, n in data.STOCKS:
        if re.search(rf"\b{re.escape(s.lower())}\b", low) or n.lower() in low:
            return s
    for alias in ("nifty 50", "nifty", "sensex", "bank nifty", "banknifty"):
        if alias in low:
            return alias.upper()
    return None


def _context(symbol: str | None) -> str:
    parts = []
    if not symbol:
        try:
            for q in data.quotes(list(data.INDICES.values())):
                if "error" not in q:
                    parts.append(f"{q['name']}: {q['price']:.2f} ({q['change_pct']:+.2f}%)")
        except Exception:
            pass
        return "Indices: " + "; ".join(parts) if parts else ""
    try:
        q = data.quote(symbol)
        f2 = lambda v: "n/a" if v is None else f"{v:,.2f}"  # noqa: E731
        parts.append(f"QUOTE {q['symbol']} ({q['name']}): price {q['price']:.2f}, change {q['change_pct']:+.2f}%, "
                     f"day range {f2(q.get('low'))}-{f2(q.get('high'))}, 52w range {f2(q.get('year_low'))}-{f2(q.get('year_high'))}, as of {q['as_of']} ({q['source']})")
        d = data.history(symbol, "1y", "1d")
        ts = analytics.technical_summary(d)
        if ts:
            parts.append("TECHNICALS: " + "; ".join(f"{k}={v}" for k, v in ts.items()))
        rk = analytics.risk_metrics(d)
        parts.append(f"RISK(1y): vol {rk['annualized_volatility']*100:.1f}%, max drawdown {rk['max_drawdown']*100:.1f}%, "
                     f"1d VaR95 {rk['var_95']*100:.2f}%, return {rk['total_return']*100:.1f}%")
    except Exception as e:
        parts.append(f"(price data unavailable: {e})")
    try:
        nw = news.fetch(symbol, 6)
        if nw["items"]:
            parts.append("HEADLINES: " + " | ".join(f"{i['title']} [{i['sentiment']['label']}]" for i in nw["items"][:6]))
    except Exception:
        pass
    return "\n".join(parts)


def _rules(msg: str, symbol: str | None, ctx: str) -> str:
    low = msg.lower()
    for term, text in GLOSSARY.items():
        if re.search(rf"\b{re.escape(term)}\b", low):
            extra = f"\n\nLive data for {symbol}:\n{ctx}" if symbol and ctx else ""
            return text + extra
    if symbol and ctx:
        return f"Here is what the data currently shows for {symbol}:\n\n{ctx}\n\n(Add an ANTHROPIC_API_KEY on the server for fuller conversational analysis. This is research, not financial advice.)"
    if any(w in low for w in ("market", "index", "indices", "today")) and ctx:
        return f"Market snapshot: {ctx}"
    return ("I can explain terms (P/E, RSI, MACD, Sharpe, drawdown...), and pull live prices, indicators, risk and headlines for a stock. "
            "Try: 'How is TCS doing?', 'What is RSI?' or 'Explain max drawdown'.")


def answer(message: str, history: list[dict] | None = None) -> dict:
    symbol = _find_symbol(message)
    ctx = _context(symbol)
    key = os.getenv("ANTHROPIC_API_KEY")
    if key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=key)
            msgs = [{"role": h["role"], "content": h["content"]} for h in (history or [])[-8:] if h.get("role") in ("user", "assistant")]
            msgs.append({"role": "user", "content": f"CONTEXT (live data):\n{ctx or 'none'}\n\nQUESTION: {message}"})
            resp = client.messages.create(model=os.getenv("STOCKSENSE_LLM_MODEL", "claude-haiku-5-5"), max_tokens=700, system=SYSTEM, messages=msgs)
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            return {"reply": text, "mode": "llm", "symbol": symbol}
        except Exception as e:  # fall back gracefully
            return {"reply": _rules(message, symbol, ctx) + f"\n\n(LLM unavailable: {e})", "mode": "rules", "symbol": symbol}
    return {"reply": _rules(message, symbol, ctx), "mode": "rules", "symbol": symbol}
