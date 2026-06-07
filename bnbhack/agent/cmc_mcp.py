"""
MEFAI BNB HACK · CMC Agent Hub MCP client

Async wrapper over the CoinMarketCap Data MCP endpoint (mcp.coinmarketcap.com/mcp).
Exposes all 12 CMC tools used across Track 1 (live cockpit), Track 2 (strategy
skills) and Track 3 (verifiable leaderboard / data-lineage).

Design rules:
  * Server-side key ONLY. The key is read from the environment and never logged,
    never returned to a caller, never echoed in an error.
  * Round-robin key pool with quota-aware cooldown (reuses the same key set the
    rest of the platform ships with, comma-separated in CMC_API_KEYS).
  * TTL cache per (tool, args) with a single-flight lock so a burst of callers
    collapses into one upstream request instead of a stampede.
  * Bounded retries with exponential backoff; a 429 rotates to the next key.
  * Handles both application/json and text/event-stream (MCP streamable) bodies.

This module performs READ-ONLY market-data lookups. It never signs, never spends,
never writes on-chain.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("mefai.bnbhack.cmc_mcp")

# Only these hosts may receive the API key. An operator may point the client at
# a different CMC host via env, but never at an arbitrary host (key exfil guard).
_ALLOWED_HOSTS = frozenset({"mcp.coinmarketcap.com"})


def _resolve_endpoint() -> str:
    url = os.environ.get(
        "CMC_MCP_ENDPOINT", "https://mcp.coinmarketcap.com/mcp"
    ).strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
        logger.warning("CMC_MCP_ENDPOINT host not allowed; using default endpoint")
        return "https://mcp.coinmarketcap.com/mcp"
    return url


MCP_ENDPOINT = _resolve_endpoint()


def _key_fingerprint(key: str) -> str:
    """Stable, non-reversible tag for log lines (never log the key itself)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


# Sentinel distinguishing "cache empty" from "cached a legitimate None result".
_MISS = object()

# --- tuning -----------------------------------------------------------------
_HTTP_TIMEOUT = 30.0          # seconds per upstream request
_MAX_RETRIES = 3              # transient-error retries (network / 5xx)
_MAX_ROTATIONS = 6           # key rotations on 429 before giving up
_BACKOFF_BASE = 0.6          # seconds, exponential
_MIN_INTERVAL = 0.20         # seconds between upstream calls (global throttle)
_RATE_COOLDOWN = 120         # seconds a key is parked after a 429 (transient)
_CACHE_MAX = 2048            # max distinct cache entries before LRU eviction

# Per-tool cache TTL (seconds). Fast-moving data short, slow data long.
_TTL_DEFAULT = 60
_TTL_BY_TOOL: Dict[str, int] = {
    "get_crypto_quotes_latest": 30,
    "get_crypto_technical_analysis": 120,
    "get_crypto_marketcap_technical_analysis": 300,
    "get_global_metrics_latest": 120,
    "get_global_crypto_derivatives_metrics": 60,
    "trending_crypto_narratives": 600,
    "get_crypto_metrics": 600,
    "get_crypto_latest_news": 300,
    "get_upcoming_macro_events": 1800,
    "search_cryptos": 3600,
    "search_crypto_info": 3600,
    "get_crypto_info": 3600,
}

# The canonical 12-tool surface. Used to validate calls and to drive the
# data-lineage panel on every page.
CMC_TOOLS: Tuple[str, ...] = tuple(_TTL_BY_TOOL.keys())
assert len(CMC_TOOLS) == 12, f"expected 12 CMC tools, found {len(CMC_TOOLS)}"


def _now() -> float:
    return time.time()


def _load_keys() -> List[str]:
    """MCP-specific key first, then the shared platform pool, then single."""
    for var in ("CMC_MCP_API_KEYS", "CMC_API_KEYS"):
        raw = os.environ.get(var, "").strip()
        if raw:
            keys = [k.strip() for k in raw.split(",") if k.strip()]
            if keys:
                return keys
    single = os.environ.get("CMC_MCP_API_KEY", "").strip() or os.environ.get(
        "CMC_API_KEY", ""
    ).strip()
    return [single] if single else []


class _KeyPool:
    """Round-robin key pool. A key hit with 429/over-quota is parked until the
    next UTC month rollover (CMC quotas reset monthly)."""

    def __init__(self, keys: List[str]) -> None:
        self._keys = keys
        self._skip_until: Dict[str, float] = {}
        self._idx = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _next_month_ts() -> float:
        now = datetime.now(timezone.utc)
        year = now.year + (1 if now.month == 12 else 0)
        month = 1 if now.month == 12 else now.month + 1
        return datetime(year, month, 1, tzinfo=timezone.utc).timestamp()

    def _available(self, key: str) -> bool:
        return _now() >= self._skip_until.get(key, 0.0)

    async def next_key(self) -> Optional[str]:
        async with self._lock:
            n = len(self._keys)
            if n == 0:
                return None
            for _ in range(n):
                key = self._keys[self._idx % n]
                self._idx = (self._idx + 1) % n
                if self._available(key):
                    return key
            return None  # all parked

    async def park(self, key: str, seconds: float) -> None:
        """Park a key for a bounded window (transient 429 / short rate limit)."""
        async with self._lock:
            self._skip_until[key] = _now() + max(1.0, seconds)
        logger.warning(
            "CMC MCP key %s parked %.0fs (rate limited)",
            _key_fingerprint(key),
            seconds,
        )

    async def mark_exhausted(self, key: str) -> None:
        """Park a key until the next UTC month (explicit monthly quota burn)."""
        async with self._lock:
            self._skip_until[key] = self._next_month_ts()
        logger.warning(
            "CMC MCP key %s parked until month rollover (quota)",
            _key_fingerprint(key),
        )

    def has_keys(self) -> bool:
        return len(self._keys) > 0

    def key_count(self) -> int:
        return len(self._keys)


@dataclass
class _CacheEntry:
    value: Any = _MISS
    expires_at: float = 0.0
    last_used: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def fresh(self) -> bool:
        return self.value is not _MISS and _now() < self.expires_at


class CmcMcpError(RuntimeError):
    """Raised when an MCP call cannot be satisfied (no keys, upstream error)."""


class CmcMcpClient:
    """Async, cached, rate-limited client for the CMC Data MCP endpoint."""

    def __init__(self, keys: Optional[List[str]] = None) -> None:
        self._pool = _KeyPool(keys if keys is not None else _load_keys())
        self._cache: Dict[str, _CacheEntry] = {}
        self._cache_guard = asyncio.Lock()
        self._client: Optional[httpx.AsyncClient] = None
        self._client_guard = asyncio.Lock()
        self._last_call = 0.0
        self._throttle = asyncio.Lock()
        self._req_id = itertools.count(1)

    # -- lifecycle ----------------------------------------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            async with self._client_guard:
                if self._client is None or self._client.is_closed:
                    self._client = httpx.AsyncClient(
                        timeout=_HTTP_TIMEOUT,
                        headers={
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream",
                            "User-Agent": "MEFAI-Agent/1.0",
                        },
                        limits=httpx.Limits(
                            max_connections=8, max_keepalive_connections=4
                        ),
                    )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def available(self) -> bool:
        return self._pool.has_keys()

    # -- cache helpers ------------------------------------------------------
    @staticmethod
    def _cache_key(tool: str, args: Dict[str, Any]) -> str:
        return tool + "|" + json.dumps(args, sort_keys=True, separators=(",", ":"))

    async def _entry(self, key: str) -> _CacheEntry:
        async with self._cache_guard:
            entry = self._cache.get(key)
            if entry is None:
                self._evict_locked()
                entry = _CacheEntry()
                self._cache[key] = entry
            entry.last_used = _now()
            return entry

    def _evict_locked(self) -> None:
        """Drop expired entries first; if still over the cap, drop LRU.
        Caller must hold _cache_guard."""
        if len(self._cache) < _CACHE_MAX:
            return
        now = _now()
        stale = [
            k
            for k, e in self._cache.items()
            if e.value is not _MISS and now >= e.expires_at
        ]
        for k in stale:
            self._cache.pop(k, None)
        if len(self._cache) < _CACHE_MAX:
            return
        # Still full: evict least-recently-used down to 90% of the cap.
        ordered = sorted(self._cache.items(), key=lambda kv: kv[1].last_used)
        target = int(_CACHE_MAX * 0.9)
        for k, _e in ordered[: len(self._cache) - target]:
            self._cache.pop(k, None)

    # -- HTTP / throttle ----------------------------------------------------
    async def _throttle_wait(self) -> None:
        async with self._throttle:
            delta = _now() - self._last_call
            if delta < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - delta)
            self._last_call = _now()

    @staticmethod
    def _parse_body(resp: httpx.Response) -> Dict[str, Any]:
        """MCP returns either a JSON object or an SSE stream of `data:` lines.
        Return the JSON-RPC envelope dict."""
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "text/event-stream" in ctype:
            payload: Optional[Dict[str, Any]] = None
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if not chunk or chunk == "[DONE]":
                        continue
                    try:
                        payload = json.loads(chunk)
                    except json.JSONDecodeError:
                        continue
            if payload is None:
                raise CmcMcpError("empty SSE body from MCP")
            return payload
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise CmcMcpError("non-JSON MCP body") from exc

    @staticmethod
    def _unwrap_result(env: Dict[str, Any]) -> Any:
        """Pull tool output out of a JSON-RPC result envelope.
        MCP tool calls return result.content[] (text blocks) and/or
        result.structuredContent."""
        if "error" in env and env["error"]:
            err = env["error"]
            msg = err.get("message") if isinstance(err, dict) else str(err)
            raise CmcMcpError(f"MCP error: {msg}")
        result = env.get("result", env)
        if isinstance(result, dict):
            if "structuredContent" in result and result["structuredContent"] is not None:
                return result["structuredContent"]
            content = result.get("content")
            if isinstance(content, list):
                texts: List[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                joined = "\n".join(t for t in texts if t)
                if joined:
                    try:
                        return json.loads(joined)
                    except json.JSONDecodeError:
                        return joined
            return result
        return result

    async def _rpc(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """One JSON-RPC call with key rotation + retry/backoff."""
        if not self._pool.has_keys():
            raise CmcMcpError("no CMC MCP API key configured")
        client = await self._get_client()
        body = {
            "jsonrpc": "2.0",
            "id": next(self._req_id),
            "method": method,
            "params": params,
        }
        last_exc: Optional[Exception] = None
        # Two independent budgets: transient retries (network / 5xx) and key
        # rotations (429). A 429 never charges the transient-retry budget, so a
        # few parked keys cannot spuriously fail a call that a healthy key serves.
        attempt = 0
        rotations = 0
        while attempt < _MAX_RETRIES and rotations < _MAX_ROTATIONS:
            key = await self._pool.next_key()
            if key is None:
                raise CmcMcpError("all CMC MCP keys are rate limited")
            await self._throttle_wait()
            try:
                resp = await client.post(
                    MCP_ENDPOINT, json=body, headers={"X-CMC-MCP-API-KEY": key}
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                attempt += 1
                await asyncio.sleep(_BACKOFF_BASE * (2 ** attempt))
                continue
            if resp.status_code == 429:
                await self._pool.park(key, _RATE_COOLDOWN)
                last_exc = CmcMcpError("429 rate limited")
                rotations += 1
                continue
            if resp.status_code >= 500:
                last_exc = CmcMcpError(f"upstream {resp.status_code}")
                attempt += 1
                await asyncio.sleep(_BACKOFF_BASE * (2 ** attempt))
                continue
            if resp.status_code >= 400:
                # 4xx (other than 429) is not retryable; surface a safe message.
                raise CmcMcpError(f"MCP request rejected ({resp.status_code})")
            return self._parse_body(resp)
        raise CmcMcpError(f"MCP call failed after retries: {last_exc}")

    # -- public generic call ------------------------------------------------
    async def call(
        self,
        tool: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        ttl: Optional[int] = None,
        force: bool = False,
    ) -> Any:
        """Call a CMC tool by name with TTL caching + single-flight."""
        if tool not in CMC_TOOLS:
            raise CmcMcpError(f"unknown CMC tool: {tool}")
        args = {k: v for k, v in (arguments or {}).items() if v is not None}
        ckey = self._cache_key(tool, args)
        ttl = _TTL_BY_TOOL.get(tool, _TTL_DEFAULT) if ttl is None else ttl
        entry = await self._entry(ckey)

        if not force and entry.fresh():
            return entry.value

        deadline_before = entry.expires_at
        async with entry.lock:
            # Re-check after acquiring the single-flight lock. A concurrent caller
            # (including a concurrent force=True) that just refreshed within this
            # window collapses the stampede into one upstream call.
            if entry.fresh() and (not force or entry.expires_at > deadline_before):
                return entry.value
            env = await self._rpc(
                "tools/call", {"name": tool, "arguments": args}
            )
            value = self._unwrap_result(env)
            entry.value = value
            entry.expires_at = _now() + ttl
            entry.last_used = _now()
            return value

    async def list_tools(self) -> List[Dict[str, Any]]:
        env = await self._rpc("tools/list", {})
        result = env.get("result", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return tools

    # -- 12 typed wrappers --------------------------------------------------
    async def quotes_latest(self, crypto_id: str) -> Any:
        return await self.call("get_crypto_quotes_latest", {"id": str(crypto_id)})

    async def technical_analysis(
        self, crypto_id: str, include_fields: Optional[str] = None
    ) -> Any:
        args: Dict[str, Any] = {"id": str(crypto_id)}
        if include_fields:
            args["includeFields"] = include_fields
        return await self.call("get_crypto_technical_analysis", args)

    async def marketcap_technical_analysis(self) -> Any:
        return await self.call("get_crypto_marketcap_technical_analysis", {})

    async def global_metrics_latest(self) -> Any:
        return await self.call("get_global_metrics_latest", {})

    async def derivatives_metrics(self) -> Any:
        return await self.call("get_global_crypto_derivatives_metrics", {})

    async def trending_narratives(self) -> Any:
        return await self.call("trending_crypto_narratives", {})

    async def crypto_metrics(self, crypto_id: str) -> Any:
        return await self.call("get_crypto_metrics", {"id": str(crypto_id)})

    async def latest_news(self, crypto_id: str, limit: int = 10) -> Any:
        return await self.call(
            "get_crypto_latest_news",
            {"id": str(crypto_id), "limit": max(1, min(int(limit), 50))},
        )

    async def upcoming_macro_events(self) -> Any:
        return await self.call("get_upcoming_macro_events", {})

    async def search_cryptos(self, query: str, limit: int = 3) -> Any:
        return await self.call(
            "search_cryptos",
            {"query": str(query)[:64], "limit": max(1, min(int(limit), 5))},
        )

    async def search_crypto_info(self, crypto_id: str, prompt: str) -> Any:
        return await self.call(
            "search_crypto_info", {"id": str(crypto_id), "prompt": str(prompt)[:256]}
        )

    async def crypto_info(self, crypto_id: str) -> Any:
        return await self.call("get_crypto_info", {"id": str(crypto_id)})


# Process-wide singleton (the backend creates one and shares it across routes).
_singleton: Optional[CmcMcpClient] = None
_singleton_lock = asyncio.Lock()


async def get_client() -> CmcMcpClient:
    global _singleton
    if _singleton is None:
        async with _singleton_lock:
            if _singleton is None:
                _singleton = CmcMcpClient()
    return _singleton
