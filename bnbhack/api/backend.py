"""
MEFAI BNB HACK · agent backend (FastAPI)

The hardened HTTP layer that exposes the audited pure agent modules over a small,
read-only API for the three competition pages and for machine-to-machine x402
buyers. It owns NO trading logic of its own: every endpoint is a thin, validated
wrapper around a module under bnbhack/agent that has already been audited
independently. The backend's whole job is the boundary: input bounds, per-IP rate
limiting, read-only database access, server-side key custody, generic errors, and
a single place that pins db_path so a client can never point a query at another
file.

What it serves (the read side plus the x402 commerce edge):
  GET  /health                  liveness, unauthenticated
  GET  /leaderboard             verified ranking (leaderboard.build_leaderboard)
  GET  /uvii                    unified index (leaderboard.build_uvii_index)
  GET  /tp-sl                   bracket optimizer (symbol required; + optional
                                live regime overlay)
  POST /fusion                  omni-signal fusion (gather_readings + fuse)
  POST /sizing                  drawdown-budget Kelly sizing (size_position)
  POST /compose                 meta-strategy composer (full pipeline plan)
  POST /security/evaluate       pre-trade security gate (evaluate_trade)
  GET  /cmc/{tool}              allowlisted CMC MCP gate passthrough
  GET  /x402/products           x402 feed catalog
  POST /x402/feed/{product_id}  x402 payment-gated verified feed (serve_feed)

The autonomous trade loop is live in production and writes its results to the
on-chain oracle (chain 56); this backend stays the read-only/commerce boundary in
front of those audited modules. Secrets and deployer settings come only from the
environment (the systemd EnvironmentFile); nothing sensitive is ever taken from a
request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from threading import Lock
from typing import Any, Deque, Dict, Iterable, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# Make the audited agent modules importable regardless of where the service is
# launched from (self-locating, no hardcoded absolute path leaked into code).
_AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
if _AGENT not in sys.path:
    sys.path.insert(0, _AGENT)

import agent_card  # noqa: E402
import bsc_exec  # noqa: E402
import erc8004_identity  # noqa: E402
import x402_feed  # noqa: E402
from fusion_core import fuse  # noqa: E402
from fusion_providers import gather_readings  # noqa: E402
from leaderboard import (  # noqa: E402
    DEFAULT_DB_PATH, HORIZON_CHOICES, build_leaderboard, build_uvii_index,
    recent_resolved,
)
from sizing import SizingInput, size_position  # noqa: E402
from tp_sl_optimizer import optimize, regime_overlay  # noqa: E402
from tx_security_solver import TradePlan, evaluate_trade  # noqa: E402

# The Meta-Strategy Composer is the one Track 2 skill that fuses the other four
# (select -> bracket -> regime gate -> size -> portfolio budget) into a single
# plan. Loading its compose_plan by file under a unique module name means the
# LIVE endpoint runs the exact same audited function the reproducible backtest
# report hashes, with no logic duplicated into this boundary layer.
import importlib.util as _ilu  # noqa: E402


def _load_compose_plan():
    path = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "skills",
        "meta-strategy-composer", "backtest", "backtest.py"))
    spec = _ilu.spec_from_file_location("mefai_meta_composer", path)
    mod = _ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.compose_plan


compose_plan = _load_compose_plan()  # noqa: E402

log = logging.getLogger("bnbhack.backend")

# --- configuration (environment only) --------------------------------------

# Optional shared key. When set, the cockpit/data endpoints require it (injected
# server-side by the nginx proxy, never seen by the browser). When unset the
# service runs open for local development and logs one warning. The x402 feed and
# /health are intentionally never key-gated: payment is the gate for the feed.
API_KEY = os.getenv("BNBHACK_API_KEY", "").strip()

# CORS origins allowed to call the data endpoints from a browser.
_DEFAULT_ORIGINS = "https://mefai.io,https://www.mefai.io"
_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("BNBHACK_ALLOWED_ORIGINS",
                                 _DEFAULT_ORIGINS).split(",") if o.strip()
]
# An all-blank override would silently drop CORS entirely; fall back to the
# safe defaults rather than leave the browser surface misconfigured.
if not _ALLOWED_ORIGINS:
    _ALLOWED_ORIGINS = [o.strip() for o in _DEFAULT_ORIGINS.split(",") if o.strip()]

# x402 deployer settings (the payment recipient + asset are the deployer's, never
# the client's). Defaults are inert placeholders so the catalog is browsable; a
# real deployment sets BNBHACK_X402_PAYTO / _ASSET to live BSC addresses.
_X402_PAYTO = os.getenv("BNBHACK_X402_PAYTO", "0x" + "00" * 19 + "01")
_X402_ASSET = os.getenv(
    "BNBHACK_X402_ASSET", "0x55d398326f99059fF775485246999027B3197955")
_X402_NETWORK = os.getenv("BNBHACK_X402_NETWORK", "bsc")
_X402_ASSET_NAME = os.getenv("BNBHACK_X402_ASSET_NAME", "BSC-USD")
_X402_ASSET_VERSION = os.getenv("BNBHACK_X402_ASSET_VERSION", "1")
# Require an actual settled on-chain payment before serving the feed. Off by
# default until the facilitator (twak) is wired; on a paid deployment set it true.
_X402_REQUIRE_SETTLEMENT = os.getenv("BNBHACK_X402_REQUIRE_SETTLEMENT", "") == "1"

# Per-IP rate limit (sliding window).
_RL_MAX = int(os.getenv("BNBHACK_RATE_MAX", "60"))
_RL_WINDOW = float(os.getenv("BNBHACK_RATE_WINDOW", "60"))
_MAX_BODY_BYTES = 64 * 1024

# Only these direct peers are allowed to set the client IP via X-Forwarded-For.
# In production this is the nginx loopback; anything else is keyed by its real
# socket address so a client cannot spoof XFF to escape the per-IP limiter.
_TRUSTED_PROXIES = {
    p.strip() for p in os.getenv(
        "BNBHACK_TRUSTED_PROXIES", "127.0.0.1,::1").split(",") if p.strip()
}

# Read-only record. The path is pinned here from the same default the agent
# modules use; it is NEVER taken from a request, so no caller can repoint a query.
_DB_PATH = os.getenv("MEFAI_SIGNAL_DB", DEFAULT_DB_PATH)

# The autonomous loop publishes its live snapshot here (atomic write). The backend
# only ever reads it; the path is pinned, never request-derived.
_LOOP_STATE_PATH = os.getenv(
    "BNBHACK_LOOP_STATE", os.path.join(_AGENT, "state", "loop_state.json"))
_LOOP_STATE_MAX_BYTES = 256 * 1024

# The reproducible Track 2 backtest index written by skills/run_backtests.py.
# The backend only reads it; the path is pinned, never request-derived.
_SKILLS_DIR = os.path.normpath(os.path.join(_AGENT, "..", "skills"))
_BACKTEST_REPORTS_PATH = os.getenv(
    "BNBHACK_BACKTEST_REPORTS",
    os.path.join(_SKILLS_DIR, "BACKTEST_REPORTS.json"))
_BACKTEST_REPORTS_MAX_BYTES = 512 * 1024

_TF_CHOICES = ("1m", "5m", "15m", "30m", "1h", "4h", "1d")
_SIDE_CHOICES = ("buy", "sell")
_SYMBOL_PATTERN = r"^[A-Za-z0-9._]{1,20}$"
_ADDR_PATTERN = r"^0x[0-9a-fA-F]{40}$"

# Allowlist of no-argument CMC MCP gate tools the cockpit may read. Keeping it to
# fixed, argument-free gates avoids passing any client text into the MCP call.
_CMC_GATES = {
    "global-metrics": "global_metrics_latest",
    "derivatives": "derivatives_metrics",
    "narratives": "trending_narratives",
    "marketcap-ta": "marketcap_technical_analysis",
    "macro-events": "upcoming_macro_events",
    "news": "latest_news",
}
# Bitcoin's CMC id, used as the market-wide proxy for the parameterised
# latest-news tool so the news gate reads with no caller input.
_CMC_NEWS_PROXY_ID = "1"


# --- rate limiter -----------------------------------------------------------

class _RateLimiter:
    """In-memory sliding-window limiter keyed by client IP. A single process
    guard; behind nginx the proxy also enforces a zone, so this is defense in
    depth, not the only line."""

    def __init__(self, max_req: int, window: float) -> None:
        self._max = max(1, max_req)
        self._window = max(1.0, window)
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, now: Optional[float] = None) -> bool:
        now_s = time.time() if now is None else now
        cutoff = now_s - self._window
        with self._lock:
            dq = self._hits[key]
            while dq and dq[0] < cutoff:
                dq.popleft()
            if len(self._hits) > 8192:
                # Sweep every bucket whose window has fully expired so the map
                # cannot grow without bound under IP churn (spoofed or real).
                for k in [k for k, d in self._hits.items()
                          if not d or d[-1] < cutoff]:
                    self._hits.pop(k, None)
                dq = self._hits[key]
            if len(dq) >= self._max:
                return False
            dq.append(now_s)
            return True


_limiter = _RateLimiter(_RL_MAX, _RL_WINDOW)


# --- TTL cache for heavy DB scans -------------------------------------------

# The leaderboard / UVII / TP-SL optimizers each scan the labeled-outcome record
# synchronously; an unfiltered TP-SL pass can take tens of seconds. Running them
# inline on the event loop would stall every other request for that whole time.
# We offload each call to a worker thread and memoize the serialized result for a
# short TTL so repeated cockpit polls (and x402 buyers) reuse one scan instead of
# recomputing it. The cache is keyed by the full argument tuple; it never holds
# request-derived paths and is bounded by sweeping expired entries on each read.
# Floored at 1s: a <= 0 TTL would make every entry instantly stale (cache off,
# every poll re-scans) and sweep-evict on each read, defeating the purpose.
_HEAVY_TTL = max(1.0, float(os.getenv("BNBHACK_HEAVY_TTL", "30")))
_heavy_cache: Dict[Any, tuple[float, Any]] = {}
_heavy_lock = Lock()


async def _cached_thread(key: Any, fn, *args, **kwargs) -> Any:
    """Return fn(*args, **kwargs) from cache if fresh, else run it off the event
    loop in a worker thread and memoize the result for _HEAVY_TTL seconds."""
    now = time.time()
    with _heavy_lock:
        hit = _heavy_cache.get(key)
        if hit is not None and now - hit[0] < _HEAVY_TTL:
            return hit[1]
    result = await asyncio.to_thread(fn, *args, **kwargs)
    with _heavy_lock:
        # Sweep expired entries so the map cannot grow without bound, then store.
        for k in [k for k, (ts, _) in _heavy_cache.items()
                  if now - ts >= _HEAVY_TTL]:
            _heavy_cache.pop(k, None)
        _heavy_cache[key] = (now, result)
    return result


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    # Honor X-Forwarded-For only from a trusted front proxy; otherwise the real
    # socket peer is authoritative so XFF cannot be spoofed to dodge the limiter.
    if peer in _TRUSTED_PROXIES:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip() or peer
    return peer


# --- app + middleware -------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not API_KEY:
        log.warning("BNBHACK_API_KEY is not set; data endpoints run unauthenticated")
    if not os.path.exists(_DB_PATH):
        log.warning("signal record not found at the configured path")
    yield
    # Close the shared CMC client if it was created.
    try:
        import cmc_mcp
        client = getattr(cmc_mcp, "_singleton", None)
        if client is not None:
            await client.aclose()
    except Exception:
        pass


app = FastAPI(title="MEFAI BNB HACK Agent Backend", version="1.0.0",
              lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-PAYMENT"],
    expose_headers=["X-PAYMENT-RESPONSE"],
    max_age=600,
)


@app.middleware("http")
async def _guard(request: Request, call_next):
    # Body-size cap (defends the POST endpoints before any parsing). A declared
    # Content-Length is rejected fast; for chunked or unset-length bodies we
    # measure while reading and abort early so memory stays bounded either way.
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > _MAX_BODY_BYTES:
                return JSONResponse({"error": "request body too large"}, status_code=413)
        except ValueError:
            return JSONResponse({"error": "bad content-length"}, status_code=400)
    elif request.method in ("POST", "PUT", "PATCH"):
        size = 0
        chunks = []
        async for chunk in request.stream():
            size += len(chunk)
            if size > _MAX_BODY_BYTES:
                return JSONResponse({"error": "request body too large"}, status_code=413)
            chunks.append(chunk)
        body = b"".join(chunks)

        async def _replay():  # re-feed the buffered body to the route handler
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = _replay
    # Per-IP rate limit (skip only liveness).
    if request.url.path != "/health":
        if not _limiter.allow(_client_ip(request)):
            return JSONResponse({"error": "rate limit exceeded"}, status_code=429)
    try:
        return await call_next(request)
    except HTTPException:
        raise
    except Exception:
        # Never leak internals (paths, stack traces, keys) to a caller.
        log.exception("unhandled error on %s", request.url.path)
        return JSONResponse({"error": "internal error"}, status_code=500)


def require_key(x_api_key: str = Header(default="")) -> None:
    """Gate the data/cockpit endpoints. No-op when no key is configured."""
    if not API_KEY:
        return
    import hmac
    if not x_api_key or not hmac.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="unauthorized")


# --- serialization ----------------------------------------------------------

def _ser(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _ser(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_ser(v) for v in obj]
    return obj


# --- request models ---------------------------------------------------------

class FusionBody(BaseModel):
    symbol: str = Field(..., pattern=_SYMBOL_PATTERN)
    timeframe: str = Field("1h")
    include_cmc: bool = True


class SizingBody(BaseModel):
    symbol: str = Field(..., pattern=_SYMBOL_PATTERN)
    timeframe: str = Field("1h")
    equity: float = Field(..., gt=0, le=1e9)
    current_drawdown: float = Field(0.0, ge=0.0, le=0.99)
    stop_distance: Optional[float] = Field(None, gt=0.0, le=0.9)
    horizon: str = Field("24h")
    jury_cap: float = Field(0.20, gt=0.0, le=0.9)
    regime_gate: float = Field(1.0, ge=0.0, le=1.0)
    venue_max_leverage: Optional[float] = Field(None, ge=1.0, le=125.0)
    conviction: float = Field(1.0, ge=0.0, le=1.0)


class ComposeBody(BaseModel):
    equity: float = Field(10000.0, gt=0, le=1e9)
    current_drawdown: float = Field(0.04, ge=0.0, le=0.99)
    jury_cap: float = Field(0.20, gt=0.0, le=0.9)
    regime_direction: int = Field(1, ge=-1, le=1)
    regime_strength: float = Field(0.7, ge=0.0, le=1.0)
    timeframe: str = Field("1h")
    signal_type: str = Field("buy")
    top_n: int = Field(5, ge=1, le=12)
    min_samples: int = Field(50, ge=1, le=10000)


class SecurityBody(BaseModel):
    token: Optional[str] = Field(None, pattern=_ADDR_PATTERN)
    router: Optional[str] = Field(None, pattern=_ADDR_PATTERN)
    chain_id: int = Field(56, ge=1, le=2_000_000_000)
    expected_out: Optional[int] = Field(None, ge=0)
    min_out: Optional[int] = Field(None, ge=0)
    slippage_bps: Optional[int] = Field(None, ge=0, le=10_000)
    approval_amount: Optional[int] = Field(None, ge=0)
    trade_amount: Optional[int] = Field(None, ge=0)
    gas_price_wei: Optional[int] = Field(None, ge=0)
    gas_limit: Optional[int] = Field(None, ge=0, le=100_000_000)
    equity: Optional[float] = Field(None, ge=0, le=1e12)
    equity_floor: Optional[float] = Field(None, ge=0, le=1e12)
    strict: bool = True


# Read-only execution preview: quote a real PancakeSwap-class route + run the
# full pre-trade security gate, never signing. Symbols are restricted to the
# audited BSC token map and the amount is bounded so the public endpoint cannot
# be used to fan arbitrary RPC traffic. execute is never honoured here.
class SwapPreviewBody(BaseModel):
    from_token: str = Field(..., pattern=r"^[A-Za-z]{2,8}$")
    to_token: str = Field(..., pattern=r"^[A-Za-z]{2,8}$")
    amount: float = Field(..., gt=0, le=250)
    slippage_pct: float = Field(1.0, ge=0.05, le=3.0)
    equity: float = Field(10000.0, gt=0, le=1e9)
    equity_floor: float = Field(8600.0, ge=0, le=1e9)


# --- endpoints --------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    return {"ok": True, "service": "bnbhack-backend", "record": os.path.exists(_DB_PATH)}


@app.get("/agent-card")
async def agent_card_endpoint() -> Dict[str, Any]:
    """The ERC-8004 registration-v1 identity document. Public and unauthenticated:
    the minted identity's agentURI points here, so it must resolve without a key.
    Static assembly only; no subprocess, no record access, no signing."""
    return agent_card.build_agent_card()


@app.get("/agent/identity", dependencies=[Depends(require_key)])
async def agent_identity() -> Dict[str, Any]:
    """The ERC-8004 identity + ERC-8183 commerce server template, surfaced live.

    This proves the agent is a runnable BNB AI Agent SDK server, not a static
    card. The registry coordinates and the agent card are live; the full identity
    and job lifecycle is exposed as honest dry-run previews produced by the exact
    code path that would run (erc8004_identity), so every command shape is real
    while nothing signs or spends. Minting the identity and funding a job are
    BSC mainnet writes, kept behind execute=True (a gated final-go action), so
    this read-only surface never moves funds."""
    minted = agent_card.AGENT_ID
    identity: Optional[Dict[str, Any]] = None
    if minted:
        # If the identity is already minted, read its live on-record state.
        try:
            r = await erc8004_identity.show_identity(minted)
            identity = _ser(r)
        except Exception:
            log.exception("erc8004 show_identity failed")
            identity = None

    # Honest dry-run previews from the real lifecycle code (execute=False never
    # spawns the signer; it returns the exact action that would be broadcast).
    register = await erc8004_identity.register_identity(execute=False)
    set_meta = await erc8004_identity.set_all_metadata(minted or 0, execute=False)
    create = await erc8004_identity.create_job(
        agent_card.AGENT_WALLET, agent_card.AGENT_WALLET,
        int(time.time()) + 86_400,
        "Deliver a verified BNB Chain trade signal with reveal proof",
        execute=False)
    fund = await erc8004_identity.fund_job(1, execute=False)
    complete = await erc8004_identity.complete_job(1, execute=False)

    return {
        "card": agent_card.build_agent_card(),
        "registry": {
            "contract": agent_card.ERC8004_REGISTRY,
            "chain_id": 56,
            "agent_wallet": agent_card.AGENT_WALLET,
            "agent_id": minted,
            "minted": bool(minted),
        },
        "identity": identity,
        "metadata": agent_card.metadata_entries(),
        "lifecycle": {
            "erc8004": {
                "register": _ser(register),
                "set_metadata": [_ser(o) for o in set_meta],
            },
            "erc8183": {
                "create_job": _ser(create),
                "fund_job": _ser(fund),
                "complete_job": _ser(complete),
            },
        },
        "note": ("ERC-8004 identity and ERC-8183 job escrow are BSC mainnet "
                 "writes. The lifecycle above is a live dry-run from the agent "
                 "server template; minting and funding execute only on a gated "
                 "final-go and never from this read-only surface."),
        "source": "MEFAI ERC-8004 identity + ERC-8183 agentic-commerce server template",
    }


@app.get("/loop/state")
async def loop_state() -> JSONResponse:
    """The autonomous loop's live snapshot (decisions, governor, proofs). Public
    and unauthenticated so the cockpit can render the judged window in real time.
    Read-only: serves the loop-published JSON verbatim, never writes or signs. The
    published file carries no secrets (no salts, no keys) by construction."""
    try:
        if not os.path.exists(_LOOP_STATE_PATH):
            return JSONResponse({"available": False, "reason": "loop not started"},
                                status_code=200)
        if os.path.getsize(_LOOP_STATE_PATH) > _LOOP_STATE_MAX_BYTES:
            return JSONResponse({"available": False, "reason": "state too large"},
                                status_code=200)
        with open(_LOOP_STATE_PATH, "r") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning("loop state read failed: %s", exc)
        return JSONResponse({"available": False, "reason": "state unreadable"},
                            status_code=200)
    return JSONResponse({"available": True, "state": data}, status_code=200)


@app.get("/backtest/reports")
async def backtest_reports() -> JSONResponse:
    """The reproducible Track 2 backtest index: per-skill PASS/FAIL plus dataset
    and code fingerprints and a repository-stable repro_digest. Public and
    read-only; serves the artifact written by skills/run_backtests.py verbatim.
    It carries no secrets. A judge regenerates the artifact from the public
    repo (pinned sample dataset + seeded RNG) and compares the digest."""
    try:
        if not os.path.exists(_BACKTEST_REPORTS_PATH):
            return JSONResponse({"available": False, "reason": "not generated"},
                                status_code=200)
        if os.path.getsize(_BACKTEST_REPORTS_PATH) > _BACKTEST_REPORTS_MAX_BYTES:
            return JSONResponse({"available": False, "reason": "report too large"},
                                status_code=200)
        with open(_BACKTEST_REPORTS_PATH, "r") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning("backtest reports read failed: %s", exc)
        return JSONResponse({"available": False, "reason": "report unreadable"},
                            status_code=200)
    return JSONResponse({"available": True, "index": data}, status_code=200)


@app.get("/backtest/report/{skill}")
async def backtest_report_detail(skill: str) -> JSONResponse:
    """Per-skill backtest manifest (dataset + code fingerprints, content hash,
    the backtest's own report payload and stdout tail). Public and read-only.
    The skill name is matched against a strict pattern and confined to the
    skills directory, so it can never escape into an arbitrary path."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", skill):
        raise HTTPException(status_code=422, detail="invalid skill")
    path = os.path.normpath(
        os.path.join(_SKILLS_DIR, skill, "output", "report.manifest.json"))
    if not path.startswith(_SKILLS_DIR + os.sep) or not os.path.exists(path):
        return JSONResponse({"available": False, "reason": "not found"},
                            status_code=200)
    try:
        if os.path.getsize(path) > _BACKTEST_REPORTS_MAX_BYTES:
            return JSONResponse({"available": False, "reason": "report too large"},
                                status_code=200)
        with open(path, "r") as f:
            data = json.load(f)
    except Exception as exc:
        log.warning("backtest manifest read failed: %s", exc)
        return JSONResponse({"available": False, "reason": "report unreadable"},
                            status_code=200)
    return JSONResponse({"available": True, "manifest": data}, status_code=200)


def _validate_choice(value: str, choices: Iterable[str], name: str) -> str:
    if value not in choices:
        raise HTTPException(status_code=422, detail=f"invalid {name}")
    return value


@app.get("/leaderboard", dependencies=[Depends(require_key)])
async def leaderboard(
    group_by: str = Query("symbol"),
    rank_by: str = Query("expectancy"),
    horizon: str = Query("24h"),
    min_samples: int = Query(30, ge=1, le=100_000),
    top_n: int = Query(20, ge=1, le=200),
    since_ts: Optional[int] = Query(None, ge=0, le=4_102_444_800),
) -> Dict[str, Any]:
    _validate_choice(group_by, ("symbol", "timeframe", "signal_type"), "group_by")
    _validate_choice(rank_by, ("expectancy", "pnl", "win_rate", "skill"), "rank_by")
    _validate_choice(horizon, HORIZON_CHOICES, "horizon")
    lb = await _cached_thread(
        ("lb", group_by, rank_by, horizon, min_samples, since_ts),
        build_leaderboard, group_by=group_by, rank_by=rank_by, horizon=horizon,
        min_samples=min_samples, since_ts=since_ts, db_path=_DB_PATH)
    return {
        "group_by": lb.group_by, "horizon": lb.horizon, "rank_by": rank_by,
        "since_ts": lb.since_ts, "qualified": len(lb.entries),
        "below_threshold": lb.below_threshold,
        "overall": _ser(lb.overall),
        "entries": [_ser(e) for e in lb.entries[:top_n]],
    }


@app.get("/signals/recent", dependencies=[Depends(require_key)])
async def signals_recent(
    limit: int = Query(20, ge=1, le=200),
    symbols: Optional[str] = Query(None, max_length=400),
    timeframe: Optional[str] = Query(None, max_length=8),
    horizon: str = Query("24h"),
) -> Dict[str, Any]:
    """Most recent VERIFIED MEFAI signals with their realized win/loss outcome.

    Powers the cockpit's "the trades the agent enters, and how they resolved"
    view: each entry is a real signal whose result was recorded after the fact.
    Read-only over the verified record. `symbols` is a comma list (bare or .P)."""
    _validate_choice(horizon, HORIZON_CHOICES, "horizon")
    sym_list: Optional[List[str]] = None
    if symbols:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()][:25]
        for s in sym_list:
            if not re.match(_SYMBOL_PATTERN, s):
                raise HTTPException(status_code=422, detail="invalid symbols")
    tf = timeframe.strip() if timeframe else None
    if tf is not None and not re.match(r"^[0-9]{1,3}[mhdw]$", tf):
        raise HTTPException(status_code=422, detail="invalid timeframe")
    rows = recent_resolved(limit=limit, symbols=sym_list, timeframe=tf,
                           horizon=horizon, db_path=_DB_PATH)
    return {"horizon": horizon, "count": len(rows),
            "signals": [_ser(r) for r in rows]}


@app.get("/uvii", dependencies=[Depends(require_key)])
async def uvii(
    group_by: str = Query("symbol"),
    horizon: str = Query("24h"),
    min_samples: int = Query(30, ge=1, le=100_000),
    top_n: int = Query(20, ge=1, le=200),
    since_ts: Optional[int] = Query(None, ge=0, le=4_102_444_800),
) -> Dict[str, Any]:
    _validate_choice(group_by, ("symbol", "timeframe", "signal_type"), "group_by")
    _validate_choice(horizon, HORIZON_CHOICES, "horizon")
    idx = await _cached_thread(
        ("uvii", group_by, horizon, min_samples, since_ts),
        build_uvii_index, group_by=group_by, horizon=horizon,
        min_samples=min_samples, since_ts=since_ts, db_path=_DB_PATH)
    return {
        "group_by": idx.group_by, "horizon": idx.horizon, "since_ts": idx.since_ts,
        "global_index": _ser(idx.global_index),
        "entities": [_ser(u) for u in idx.entities[:top_n]],
    }


@app.get("/tp-sl", dependencies=[Depends(require_key)])
async def tp_sl(
    # symbol is required: a symbol-less call would pool the entire
    # signal_performance table (a heavy unbounded scan that can hang a bare
    # GET /tp-sl). Query(...) makes FastAPI reject the missing/empty case with
    # a 422 before any database work runs.
    symbol: str = Query(..., min_length=1, pattern=_SYMBOL_PATTERN),
    timeframe: Optional[str] = Query(None),
    signal_type: Optional[str] = Query(None),
    since_ts: Optional[int] = Query(None, ge=0, le=4_102_444_800),
    min_samples: int = Query(30, ge=1, le=100_000),
    regime_direction: Optional[int] = Query(None, ge=-1, le=1),
    regime_strength: float = Query(0.0, ge=0.0, le=1.0),
) -> Dict[str, Any]:
    if timeframe is not None:
        _validate_choice(timeframe, _TF_CHOICES, "timeframe")
    if signal_type is not None:
        _validate_choice(signal_type, _SIDE_CHOICES, "signal_type")
    res = await _cached_thread(
        ("tpsl", symbol, timeframe, signal_type, since_ts, min_samples),
        optimize, symbol=symbol, timeframe=timeframe, signal_type=signal_type,
        since_ts=since_ts, min_samples=min_samples, db_path=_DB_PATH)
    out: Dict[str, Any] = {
        "symbol": res.symbol, "timeframe": res.timeframe,
        "signal_type": res.signal_type, "horizon": res.horizon,
        "since_ts": res.since_ts, "n_total": res.n_total,
        "min_samples": res.min_samples, "recommend": res.recommend,
        "note": res.note,
        "best": _ser(res.best), "best_per_risk": _ser(res.best_per_risk),
    }
    if regime_direction is not None:
        gate = regime_overlay(res, regime_direction=regime_direction,
                              regime_strength=regime_strength)
        out["regime"] = _ser(gate)
    return out


@app.post("/fusion", dependencies=[Depends(require_key)])
async def fusion(body: FusionBody) -> Dict[str, Any]:
    _validate_choice(body.timeframe, _TF_CHOICES, "timeframe")
    readings = await gather_readings(body.symbol, body.timeframe,
                                     include_cmc=body.include_cmc)
    result = fuse(readings)
    return _ser(result)


@app.post("/sizing", dependencies=[Depends(require_key)])
async def sizing(body: SizingBody) -> Dict[str, Any]:
    _validate_choice(body.timeframe, _TF_CHOICES, "timeframe")
    kwargs = dict(
        symbol=body.symbol, timeframe=body.timeframe, equity=body.equity,
        current_drawdown=body.current_drawdown, stop_distance=body.stop_distance,
        horizon=body.horizon, jury_cap=body.jury_cap,
        regime_gate=body.regime_gate, conviction=body.conviction,
    )
    if body.venue_max_leverage is not None:
        kwargs["venue_max_leverage"] = body.venue_max_leverage
    result = size_position(SizingInput(**kwargs))
    return _ser(result)


@app.post("/compose", dependencies=[Depends(require_key)])
async def compose(body: ComposeBody) -> Dict[str, Any]:
    """Meta-Strategy Composer · the full pipeline as one plan. Runs the exact
    audited compose_plan (select -> bracket -> regime gate -> size -> portfolio
    budget) the reproducible backtest hashes. Read-only and deterministic for a
    given account state; offloaded to a thread because selection + bracket each
    scan the resolved-outcome record."""
    _validate_choice(body.timeframe, _TF_CHOICES, "timeframe")
    _validate_choice(body.signal_type, ("buy", "sell"), "signal_type")
    plan = await asyncio.to_thread(
        compose_plan, equity=body.equity,
        current_drawdown=body.current_drawdown, jury_cap=body.jury_cap,
        regime_direction=body.regime_direction,
        regime_strength=body.regime_strength, timeframe=body.timeframe,
        signal_type=body.signal_type, top_n=body.top_n,
        min_samples=body.min_samples)
    return _ser(plan)


@app.post("/security/evaluate", dependencies=[Depends(require_key)])
async def security_evaluate(body: SecurityBody) -> Dict[str, Any]:
    plan = TradePlan(
        token=body.token, router=body.router, chain_id=body.chain_id,
        expected_out=body.expected_out, min_out=body.min_out,
        slippage_bps=body.slippage_bps, approval_amount=body.approval_amount,
        trade_amount=body.trade_amount, gas_price_wei=body.gas_price_wei,
        gas_limit=body.gas_limit, equity=body.equity,
        equity_floor=body.equity_floor,
    )
    verdict = await evaluate_trade(plan, strict=body.strict)
    return _ser(verdict)


@app.post("/twak/swap-preview", dependencies=[Depends(require_key)])
async def twak_swap_preview(body: SwapPreviewBody) -> Dict[str, Any]:
    """Real execution pipeline up to the signing boundary: quote a live route via
    twak, then run the full pre-trade security gate. execute is forced False, so
    no key is touched and no funds move; the sign + broadcast step is always the
    user's own self-custody wallet. Returns the quote, the gate verdict and the
    honest sign boundary so the page can show the exact chain the agent runs."""
    src_sym = body.from_token.strip().upper()
    dst_sym = body.to_token.strip().upper()
    if src_sym == dst_sym:
        raise HTTPException(status_code=400, detail="source and destination are the same token")
    # Resolve each symbol to its audited BSC address so the route quotes for every
    # listed token (the CLI resolves only a few symbols by name, but resolves any
    # token by address). Unknown symbols are rejected before any network use.
    src_addr = bsc_exec._resolve_token(src_sym)
    dst_addr = bsc_exec._resolve_token(dst_sym)
    if src_addr is None or dst_addr is None:
        raise HTTPException(status_code=400, detail="unsupported token symbol")
    try:
        outcome = await bsc_exec.swap(
            body.amount, src_addr, dst_addr, body.slippage_pct,
            execute=False, equity=body.equity, equity_floor=body.equity_floor,
            approx_usd=body.amount if src_sym in bsc_exec._USD_STABLES else None,
        )
    except Exception:
        log.exception("swap preview failed")
        raise HTTPException(status_code=502, detail="quote engine unavailable")
    return {
        "go": outcome.go,
        "executed": outcome.executed,
        "quote": outcome.quote or {},
        "verdict": _ser(outcome.verdict) if outcome.verdict else None,
        "detail": outcome.detail,
        "sign_boundary": {
            "signed": False,
            "custody": "self",
            "note": "The route and the gate are live; the sign and broadcast step is "
                    "always performed by the user's own self-custody wallet. No key is "
                    "held server side and no funds move in this preview.",
        },
        "route": {
            "from_token": body.from_token.strip().upper(),
            "to_token": body.to_token.strip().upper(),
            "amount": body.amount,
            "slippage_pct": body.slippage_pct,
            "chain_id": bsc_exec.CHAIN_ID,
        },
        "source": "twak live quote + MEFAI pre-trade security gate",
    }


@app.get("/cmc/{tool}", dependencies=[Depends(require_key)])
async def cmc_gate(tool: str = Path(...)) -> Dict[str, Any]:
    method = _CMC_GATES.get(tool)
    if method is None:
        raise HTTPException(status_code=404, detail="unknown cmc gate")
    try:
        import cmc_mcp
        client = await cmc_mcp.get_client()
        if tool == "news":
            data = await client.latest_news(_CMC_NEWS_PROXY_ID, 10)
        else:
            data = await getattr(client, method)()
    except Exception:
        log.exception("cmc gate %s failed", tool)
        raise HTTPException(status_code=502, detail="cmc gate unavailable")
    return {"tool": tool, "data": data}


# --- x402 verified feed -----------------------------------------------------

_nonce_store = x402_feed.NonceStore()


def _x402_cfg() -> "x402_feed.RequirementsConfig":
    return x402_feed.RequirementsConfig(
        pay_to=_X402_PAYTO, asset=_X402_ASSET, network=_X402_NETWORK,
        asset_name=_X402_ASSET_NAME, asset_version=_X402_ASSET_VERSION,
    )


@app.get("/x402/products")
async def x402_products() -> Dict[str, Any]:
    return {"products": x402_feed.list_products(), "network": _X402_NETWORK}


@app.post("/x402/feed/{product_id}")
async def x402_feed_endpoint(
    request: Request,
    product_id: str = Path(...),
    group_by: str = Query("symbol"),
    rank_by: str = Query("expectancy"),
    horizon: str = Query("24h"),
    top_n: int = Query(10, ge=1, le=100),
    since_ts: Optional[int] = Query(None, ge=0, le=4_102_444_800),
) -> JSONResponse:
    cfg = _x402_cfg()
    x_payment = request.headers.get("x-payment")
    feed_params = {"group_by": group_by, "rank_by": rank_by,
                   "horizon": horizon, "top_n": top_n, "since_ts": since_ts}
    try:
        resp = x402_feed.serve_feed(
            product_id, x_payment, cfg=cfg, feed_params=feed_params,
            nonce_store=_nonce_store, require_settlement=_X402_REQUIRE_SETTLEMENT,
            db_path=_DB_PATH)
    except x402_feed.X402Error as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse(content=_ser(resp.body), status_code=resp.status,
                        headers=resp.headers)


@app.get("/x402/roundtrip/{product_id}")
async def x402_roundtrip(product_id: str = Path(...)) -> Dict[str, Any]:
    """Run the full 402 -> sign -> verify -> 200 handshake against MEFAI's own
    feed end to end and return a step-by-step transcript. The buyer is an
    ephemeral key signing a real EIP-3009 authorization; verification is real,
    on-chain settlement is deferred (no funds move). Read-only and public."""
    cfg = _x402_cfg()
    try:
        result = await asyncio.to_thread(
            x402_feed.demo_roundtrip, product_id, cfg,
            feed_params={"group_by": "symbol", "rank_by": "expectancy",
                         "horizon": "24h", "top_n": 5},
            db_path=_DB_PATH)
    except x402_feed.X402Error as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return _ser(result)


# CoinMarketCap's upstream x402 gateway. Fixed, published endpoint (never a
# caller-supplied URL, so no SSRF surface). The metered tools and the published
# price/network below are CMC's own facts; the probe below reports the real HTTP
# response without ever inventing payment terms.
_CMC_X402_GATEWAY = "https://mcp.coinmarketcap.com/x402/mcp"
_CMC_X402_TOOLS = [
    "dex/search", "cryptocurrency/quotes/latest",
    "cryptocurrency/listings/latest", "dex/pairs/quotes/latest",
]
# A paid tool used only to elicit the live 402 challenge (no payment sent, so no
# data is consumed and no funds move). The tool name is fixed, never client-set.
_CMC_X402_PROBE_TOOL = "trending_crypto_narratives"


def _probe_cmc_x402() -> Dict[str, Any]:
    """POST a JSON-RPC tools/call to CMC's x402 MCP gateway with no payment header
    to elicit the genuine HTTP 402 challenge, then base64-decode the standard
    `payment-required` header into its x402 accepts terms. No payment is sent so
    nothing is consumed; the result is reported verbatim or honestly on failure."""
    import urllib.error
    import urllib.request
    probe: Dict[str, Any] = {"reached": False, "http_status": None,
                             "is_402": False, "accepts": None, "resource": None,
                             "note": ""}
    body = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": _CMC_X402_PROBE_TOOL, "arguments": {}},
    }).encode("utf-8")
    req = urllib.request.Request(
        _CMC_X402_GATEWAY, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream",
                 "User-Agent": "MEFAI-x402-probe"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            probe["reached"] = True
            probe["http_status"] = resp.status
            probe["note"] = "gateway reachable; tool returned a payload"
    except urllib.error.HTTPError as exc:
        probe["reached"] = True
        probe["http_status"] = exc.code
        if exc.code == 402:
            probe["is_402"] = True
            probe["note"] = "live 402 payment-required challenge received"
            try:
                err_body = json.loads(exc.read(4096).decode("utf-8"))
                probe["resource"] = err_body.get("resource")
            except Exception:
                pass
            enc = exc.headers.get("payment-required") if exc.headers else None
            if enc:
                try:
                    import base64
                    decoded = json.loads(
                        base64.b64decode(enc[:8192]).decode("utf-8"))
                    accepts = decoded.get("accepts")
                    if isinstance(accepts, list):
                        probe["accepts"] = accepts[:8]
                except Exception:
                    pass
        else:
            probe["note"] = f"gateway reachable; returned HTTP {exc.code}"
    except Exception:
        probe["note"] = "gateway not reachable from this host right now"
    return probe


@app.get("/x402/cmc-challenge")
async def x402_cmc_challenge() -> Dict[str, Any]:
    """Live probe of CMC's upstream x402 gateway. Calls a paid tool with no
    payment to surface the genuine 402 challenge (Base USDC 0.01, BSC options),
    decoded verbatim from the gateway's `payment-required` header."""
    probe = await asyncio.to_thread(_probe_cmc_x402)
    return {
        "gateway": _CMC_X402_GATEWAY,
        "network": "base",
        "chain_id": 8453,
        "price_human": 0.01,
        "asset_symbol": "USDC",
        "tools": _CMC_X402_TOOLS,
        "probe_tool": _CMC_X402_PROBE_TOOL,
        "probe": probe,
        "source": "CoinMarketCap x402 gateway · live 402 challenge",
    }
