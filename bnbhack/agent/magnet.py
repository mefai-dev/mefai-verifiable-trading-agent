"""Liquidation-magnet exit targets for the position manager.

The MEFAI proxy serves per-symbol liquidation clusters: price levels with the
strongest "magnet" that tends to pull price toward them (leveraged positions get
liquidated there, so price sweeps the level). For an open RUNNER (the half left
after the TP1 scale-out) the agent exits at the nearest sizable magnet in the
trade's favour instead of a trailing stop or a fixed second target: for a long,
the nearest magnet ABOVE the mark; for a short, the nearest magnet BELOW it.

Read-only HTTP to the local proxy; fully fail-safe (returns None on anything,
and the caller then keeps the 24h time stop as the backstop). Cached per symbol
so a per-cycle check costs nothing. Nothing here trades, signs, or writes.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

# The MEFAI proxy's per-symbol liquidation-cluster endpoint (localhost in prod).
_URL = os.getenv("BNBHACK_MAGNET_URL", "http://127.0.0.1:8210/liq-clusters")
_TTL = float(os.getenv("BNBHACK_MAGNET_TTL", "45"))           # match proxy cache
# A magnet must sit at least MIN and at most MAX away from the mark to be a valid
# runner target: closer than MIN is noise already inside the TP1 band, further
# than MAX is too far to reach inside the holding horizon.
_MIN_DIST = float(os.getenv("BNBHACK_MAGNET_MIN_DIST_PCT", "0.5")) / 100.0
_MAX_DIST = float(os.getenv("BNBHACK_MAGNET_MAX_DIST_PCT", "12")) / 100.0

_cache: Dict[str, Tuple[float, List[dict]]] = {}


def _perp(symbol: str) -> str:
    s = (symbol or "").upper().strip()
    return s[:-2] if s.endswith(".P") else s


def _clusters(symbol: str) -> List[dict]:
    sym = _perp(symbol)
    now = time.time()
    c = _cache.get(sym)
    if c and now - c[0] < _TTL:
        return c[1]
    try:
        url = f"{_URL}?symbol={sym}"
        req = urllib.request.Request(url, headers={"User-Agent": "MEFAI-Agent"})
        with urllib.request.urlopen(req, timeout=6) as r:
            d = json.loads(r.read())
        cl = [x for x in (d.get("clusters") or [])
              if isinstance(x, dict) and x.get("price")]
        _cache[sym] = (now, cl)
        return cl
    except Exception:
        return c[1] if c else []


def magnet_target(symbol: str, direction: int, mark: float) -> Optional[float]:
    """Nearest sizable liquidation magnet in the trade's favour (above the mark
    for a long, below for a short), between MIN and MAX distance. Price sweeps the
    closest magnet first, so the nearest favourable level is the runner's target.
    Returns None when there is no qualifying magnet or on any error, so the caller
    falls back to the time stop."""
    try:
        mark = float(mark)
    except (TypeError, ValueError):
        return None
    if mark <= 0 or direction == 0:
        return None
    best: Optional[Tuple[float, float]] = None  # (abs_dist_frac, price)
    for c in _clusters(symbol):
        try:
            px = float(c["price"])
        except (TypeError, ValueError, KeyError):
            continue
        if px <= 0:
            continue
        d = (px - mark) / mark            # signed distance from mark
        fav = d if direction > 0 else -d  # favourable distance (>0 = in profit)
        if _MIN_DIST <= fav <= _MAX_DIST and (best is None or fav < best[0]):
            best = (fav, px)
    return best[1] if best else None
