"""Lightweight, transparent finance-headline sentiment (lexicon + rules).

No model download needed, so it runs on free hosting. It is deliberately simple and
explainable; see /api/models for its documented limitations.
"""
from __future__ import annotations

import math
import re

PHRASES = {
    "52-week high": 2.5, "all-time high": 2.5, "record high": 2.5, "beats estimates": 2.5,
    "tops estimates": 2.5, "above estimates": 2.0, "misses estimates": -2.5, "below estimates": -2.0,
    "profit warning": -3.0, "rating upgrade": 2.5, "rating downgrade": -2.5, "stake sale": -1.0,
    "buyback": 1.5, "order win": 2.0, "net profit rises": 2.5, "net profit falls": -2.5,
    "52-week low": -2.5, "all-time low": -2.5, "short seller": -2.0, "sebi probe": -2.5,
    "fraud": -3.0, "default": -2.5, "debt-laden": -2.0, "block deal": -0.5,
}
POS = {
    "surge": 2.5, "surges": 2.5, "soar": 2.5, "soars": 2.5, "rally": 2.2, "rallies": 2.2, "jump": 2.0,
    "jumps": 2.0, "gain": 1.8, "gains": 1.8, "rise": 1.5, "rises": 1.5, "climb": 1.6, "climbs": 1.6,
    "up": 0.8, "higher": 1.2, "record": 1.5, "strong": 1.8, "robust": 1.8, "growth": 1.6, "profit": 1.4,
    "upgrade": 2.2, "upgrades": 2.2, "outperform": 2.2, "bullish": 2.5, "buy": 1.5, "beat": 1.8, "beats": 1.8,
    "positive": 1.6, "optimism": 1.8, "recovery": 1.6, "rebound": 1.8, "expands": 1.4, "wins": 1.8,
    "boost": 1.7, "boosts": 1.7, "dividend": 1.2, "approval": 1.4, "approved": 1.4, "milestone": 1.2,
    "top": 0.8, "best": 1.4, "launches": 0.8, "acquires": 0.8, "hike": 0.6,
}
NEG = {
    "plunge": -2.8, "plunges": -2.8, "crash": -3.0, "crashes": -3.0, "tumble": -2.5, "tumbles": -2.5,
    "slump": -2.5, "slumps": -2.5, "fall": -1.8, "falls": -1.8, "drop": -1.8, "drops": -1.8,
    "decline": -1.8, "declines": -1.8, "slip": -1.4, "slips": -1.4, "down": -0.8, "lower": -1.2,
    "weak": -1.8, "loss": -2.0, "losses": -2.0, "cut": -1.3, "cuts": -1.3, "downgrade": -2.2,
    "downgrades": -2.2, "underperform": -2.2, "bearish": -2.5, "sell": -1.5, "selloff": -2.5,
    "sell-off": -2.5, "miss": -1.8, "misses": -1.8, "negative": -1.6, "fear": -1.8, "fears": -1.8,
    "concern": -1.3, "concerns": -1.3, "risk": -1.0, "risks": -1.0, "probe": -1.8, "penalty": -2.0,
    "fine": -1.2, "layoffs": -2.0, "lawsuit": -1.8, "volatile": -0.8, "pressure": -1.2, "worst": -2.0,
    "warning": -1.8, "halt": -1.5, "scam": -3.0, "slowdown": -1.8, "inflation": -0.6, "recession": -2.4,
}
NEGATORS = {"not", "no", "never", "without", "fails", "failed", "unlikely", "hardly"}
BOOSTERS = {"sharply": 1.3, "significantly": 1.3, "massive": 1.3, "huge": 1.3, "steep": 1.3, "slightly": 0.7,
            "marginally": 0.7, "marginal": 0.7, "modest": 0.7}
THRESHOLD = 0.15


def score(text: str) -> dict:
    """Return {'score': -1..1, 'label': positive|negative|neutral}."""
    t = (text or "").lower()
    total = 0.0
    for ph, w in PHRASES.items():
        if ph in t:
            total += w
            t = t.replace(ph, " ")
    words = re.findall(r"[a-z][a-z\-']*", t)
    for i, w in enumerate(words):
        val = POS.get(w) or NEG.get(w)
        if not val:
            continue
        window = words[max(0, i - 3):i]
        for b in window:
            if b in BOOSTERS:
                val *= BOOSTERS[b]
        if any(n in window for n in NEGATORS):
            val *= -0.7
        total += val
    norm = total / math.sqrt(total * total + 15)  # VADER-style squashing to (-1, 1)
    label = "positive" if norm >= THRESHOLD else "negative" if norm <= -THRESHOLD else "neutral"
    return {"score": round(norm, 3), "label": label}


def summarize(items: list[dict]) -> dict:
    n = len(items)
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for it in items:
        counts[it["sentiment"]["label"]] += 1
    avg = sum(it["sentiment"]["score"] for it in items) / n if n else 0.0
    label = "positive" if avg >= 0.08 else "negative" if avg <= -0.08 else "neutral"
    return {**counts, "total": n, "avg_score": round(avg, 3), "label": label}
