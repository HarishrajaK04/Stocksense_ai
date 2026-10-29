"""Financial news retrieval (Google News RSS) + sentiment tagging."""
from __future__ import annotations

import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from . import data, sentiment

try:
    import feedparser
except Exception:  # pragma: no cover
    feedparser = None

_CACHE: dict = {}
TTL = 300

DEMO_HEADLINES = [
    ("Nifty surges as banking stocks rally on strong earnings", "Demo Wire"),
    ("Sensex falls sharply amid global selloff fears", "Demo Wire"),
    ("Analysts upgrade IT sector outlook after robust deal wins", "Demo Wire"),
    ("Rupee slips as crude prices climb; inflation concerns weigh", "Demo Wire"),
    ("FIIs turn net buyers as markets stay range-bound", "Demo Wire"),
    ("Auto sales beat estimates, festive demand boosts volumes", "Demo Wire"),
]


def _query(symbol: str | None, extra: str = "") -> str:
    if symbol:
        sym = data.normalize(symbol)
        base = f"{data.name_for(sym)} share price NSE"
    else:
        base = "Indian stock market Nifty Sensex"
    return f"{base} {extra}".strip()


def fetch(symbol: str | None = None, limit: int = 25, extra: str = "") -> dict:
    q = _query(symbol, extra)
    key = (q, limit)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]

    items: list[dict] = []
    error = None
    if data.DEMO:
        for title, src in DEMO_HEADLINES:
            items.append({"title": title, "source": src, "link": "#", "published": datetime.now().strftime("%d %b %Y"),
                          "sentiment": sentiment.score(title)})
    elif feedparser is None:
        error = "feedparser is not installed"
    else:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            feed = feedparser.parse(url, agent="StockSenseAI/1.0")
            for e in feed.entries[: limit * 2]:
                title = e.get("title", "").strip()
                src = (e.get("source") or {}).get("title", "")
                if " - " in title:
                    head, _, tail = title.rpartition(" - ")
                    title, src = head, src or tail
                try:
                    pub = parsedate_to_datetime(e.get("published", ""))
                    ts = pub.timestamp()
                    published = pub.astimezone(data.IST).strftime("%d %b %Y, %H:%M")
                except Exception:
                    ts, published = 0, e.get("published", "")
                items.append({"title": title, "source": src, "link": e.get("link", "#"), "published": published,
                              "_ts": ts, "sentiment": sentiment.score(title)})
            items.sort(key=lambda x: x.get("_ts", 0), reverse=True)
            seen, dedup = set(), []
            for it in items:
                k = it["title"].lower()[:60]
                if k not in seen:
                    seen.add(k)
                    dedup.append(it)
            items = dedup[:limit]
            for it in items:
                it.pop("_ts", None)
            if not items:
                error = "No headlines returned (network blocked or no recent news)."
        except Exception as ex:
            error = f"News fetch failed: {ex}"

    out = {"query": q, "items": items, "summary": sentiment.summarize(items), "error": error,
           "source": "demo" if data.DEMO else "google-news-rss"}
    if items:
        _CACHE[key] = (time.time(), out)
    return out
