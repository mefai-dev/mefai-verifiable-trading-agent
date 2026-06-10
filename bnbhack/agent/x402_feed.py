"""
MEFAI BNB HACK · x402 Verified-Signal Feed

This is the Track 3 agentic-commerce layer: it sells access to MEFAI's verified
signal record over the x402 HTTP-402 micropayment protocol. The product on offer
is the same trustless leaderboard / UVII index that the verifiable-protocol page
shows, but gated behind a stablecoin payment so other agents can buy the feed
machine-to-machine.

The module is the PURE protocol core (no HTTP server, no key custody). It:

  1. publishes a catalog of purchasable feed products,
  2. builds the x402 "402 Payment Required" payment-requirements body,
  3. verifies a client's X-PAYMENT header by recovering the EIP-3009
     TransferWithAuthorization signature and checking every field against the
     requirements (amount, recipient, asset, chain, time window, replay),
  4. hands a verified payment to a Settler and returns the verified feed payload.

The on-chain SETTLEMENT step (broadcasting transferWithAuthorization) is performed
by an x402 facilitator with a funded relayer; that integration runs through the
Trust Wallet agent kit and is supplied as an injected Settler. Until it is wired
the default VerifyOnlySettler proves the payment is cryptographically valid and
marks settlement as deferred, so the feed core is fully testable offline.

Read-only over signal.db: the feed builders only read the verified record; this
module never writes the database, never holds a private key, and never broadcasts
a transaction itself.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from eth_account import Account
from eth_account.messages import encode_typed_data

from leaderboard import (
    DEFAULT_DB_PATH,
    HORIZON_CHOICES,
    build_leaderboard,
    build_uvii_index,
)

X402_VERSION = 1
SCHEME_EXACT = "exact"

# Networks this feed accepts payment on, mapped to their EIP-712 chainId. The
# chainId is taken from THIS map (keyed by the requirements' network), never from
# the client payload, so a signature is bound to the chain we actually require.
NETWORK_CHAIN_ID = {
    "bsc": 56,
    "bsc-testnet": 97,
    "opbnb": 204,
    "opbnb-testnet": 5611,
}

# Bound on the decoded X-PAYMENT header so a hostile client cannot force a large
# base64/JSON allocation before any field is even validated.
MAX_PAYMENT_HEADER_BYTES = 8192

DEFAULT_MAX_TIMEOUT_SECONDS = 120
# Reject authorizations whose validity window is implausibly far in the future;
# the server only ever honors a payment inside [validAfter, validBefore].
MAX_VALID_WINDOW_SECONDS = 3600

_HEX = set("0123456789abcdefABCDEF")
_RANK_CHOICES = ("expectancy", "pnl", "win_rate", "skill")
_GROUP_CHOICES = ("symbol", "timeframe", "signal_type")
_MAX_TOP_N = 100
_MAX_MIN_SAMPLES = 100000


class X402Error(Exception):
    """A malformed request or payment header. Carries an x402 error string."""


# --- small safe parsers ----------------------------------------------------

def _now() -> float:
    return time.time()


def _is_hex(s: str) -> bool:
    return bool(s) and all(c in _HEX for c in s)


def _norm_address(value, field_name: str) -> str:
    """Validate a 20-byte hex address and return it lowercased for comparison."""
    s = str(value or "")
    if s[:2].lower() != "0x" or len(s) != 42 or not _is_hex(s[2:]):
        raise X402Error(f"invalid address: {field_name}")
    low = s.lower()
    if low == "0x" + "00" * 20:
        raise X402Error(f"zero address: {field_name}")
    return low


def _parse_uint(value, field_name: str) -> int:
    """Parse a non-negative integer given as a decimal string or int.

    x402 carries amounts and timestamps as decimal strings; floats, signs,
    underscores and non-decimal text are rejected so nothing silently coerces.
    """
    if isinstance(value, bool):
        raise X402Error(f"invalid uint: {field_name}")
    if isinstance(value, int):
        v = value
    elif isinstance(value, str):
        s = value.strip()
        if not s.isdigit():
            raise X402Error(f"invalid uint: {field_name}")
        v = int(s)
    else:
        raise X402Error(f"invalid uint: {field_name}")
    if v < 0 or v >= (1 << 256):
        raise X402Error(f"uint out of range: {field_name}")
    return v


def _parse_bytes32(value, field_name: str) -> bytes:
    s = str(value or "")
    if s[:2].lower() == "0x":
        s = s[2:]
    if len(s) != 64 or not _is_hex(s):
        raise X402Error(f"invalid bytes32: {field_name}")
    return bytes.fromhex(s)


def _parse_signature(value) -> bytes:
    s = str(value or "")
    if s[:2].lower() == "0x":
        s = s[2:]
    if len(s) != 130 or not _is_hex(s):
        raise X402Error("invalid signature")
    return bytes.fromhex(s)


def _as_str(value, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise X402Error(f"missing field: {field_name}")
    return value


# --- feed product catalog --------------------------------------------------

@dataclass(frozen=True)
class FeedProduct:
    product_id: str
    title: str
    description: str
    price_atomic: str          # atomic units of the configured asset (string)
    mime_type: str = "application/json"


# Default prices are quoted in atomic units of an 18-decimal stablecoin (BSC USDT
# is 18 decimals): 0.01 and 0.05 units. The asset itself is supplied per request
# by the deployer (payment_requirements.asset), so the same catalog works for any
# 18-decimal token; a different-decimal asset must restate the price.
_CATALOG: Dict[str, FeedProduct] = {
    "verified-leaderboard": FeedProduct(
        product_id="verified-leaderboard",
        title="MEFAI Verified Signal Leaderboard",
        description="Ranked entities by verified realized outcomes from the "
                    "labeled signal record.",
        price_atomic="10000000000000000",
    ),
    "uvii-index": FeedProduct(
        product_id="uvii-index",
        title="MEFAI Unified Verifiable Intelligence Index",
        description="Per-entity UVII trust scores plus the single global MEFAI "
                    "index over the whole verified record.",
        price_atomic="50000000000000000",
    ),
}


def list_products() -> List[Dict]:
    return [
        {"product_id": p.product_id, "title": p.title,
         "description": p.description, "price_atomic": p.price_atomic,
         "mime_type": p.mime_type}
        for p in _CATALOG.values()
    ]


def get_product(product_id) -> FeedProduct:
    p = _CATALOG.get(str(product_id))
    if p is None:
        raise X402Error(f"unknown product: {product_id!r}")
    return p


# --- payment requirements (the 402 body) -----------------------------------

@dataclass
class RequirementsConfig:
    """Deployer-controlled payment settings (NOT taken from the client)."""
    pay_to: str
    asset: str
    network: str = "bsc"
    resource: str = "https://mefai.io/bnbhack-x402/feed"
    asset_name: str = "USD Coin"       # EIP-712 domain name of the asset
    asset_version: str = "2"           # EIP-712 domain version of the asset
    max_timeout_seconds: int = DEFAULT_MAX_TIMEOUT_SECONDS


def payment_requirements(product_id: str, cfg: RequirementsConfig) -> Dict:
    """Build the x402 PaymentRequirements ("accepts" entry) for one product."""
    product = get_product(product_id)
    if cfg.network not in NETWORK_CHAIN_ID:
        raise X402Error(f"unsupported network: {cfg.network!r}")
    pay_to = _norm_address(cfg.pay_to, "payTo")
    asset = _norm_address(cfg.asset, "asset")
    # Price must be a clean positive integer string.
    if _parse_uint(product.price_atomic, "price") <= 0:
        raise X402Error("product price must be positive")
    try:
        timeout = max(1, min(int(cfg.max_timeout_seconds), MAX_VALID_WINDOW_SECONDS))
    except (TypeError, ValueError):
        timeout = DEFAULT_MAX_TIMEOUT_SECONDS
    return {
        "scheme": SCHEME_EXACT,
        "network": cfg.network,
        "maxAmountRequired": product.price_atomic,
        "resource": cfg.resource,
        "description": product.description,
        "mimeType": product.mime_type,
        "payTo": pay_to,
        "maxTimeoutSeconds": timeout,
        "asset": asset,
        "extra": {"name": cfg.asset_name, "version": cfg.asset_version},
    }


def make_402(product_id: str, cfg: RequirementsConfig,
             error: str = "X-PAYMENT header required") -> Dict:
    """The full HTTP 402 response body a server returns when payment is missing
    or invalid: the x402 version, an error string, and the accepted terms."""
    return {
        "x402Version": X402_VERSION,
        "error": error,
        "accepts": [payment_requirements(product_id, cfg)],
    }


# --- X-PAYMENT decode + verify ---------------------------------------------

@dataclass
class PaymentAuthorization:
    payer: str                 # authorization.from, lowercased
    to: str                    # authorization.to, lowercased
    value: int
    valid_after: int
    valid_before: int
    nonce: bytes               # 32 bytes
    nonce_hex: str             # 0x-prefixed, lowercased
    signature: bytes           # 65 bytes
    network: str


def decode_payment_header(x_payment_b64: str) -> Dict:
    """Decode the standard-base64 X-PAYMENT header into its JSON object, bounded."""
    s = str(x_payment_b64 or "")
    if not s:
        raise X402Error("empty X-PAYMENT header")
    if len(s) > MAX_PAYMENT_HEADER_BYTES:
        raise X402Error("X-PAYMENT header too large")
    try:
        raw = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError):
        raise X402Error("X-PAYMENT is not valid base64")
    if len(raw) > MAX_PAYMENT_HEADER_BYTES:
        raise X402Error("X-PAYMENT payload too large")
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        # RecursionError covers a deeply nested JSON payload crafted to blow the
        # parser stack; it must read as a malformed header, not a server error.
        raise X402Error("X-PAYMENT is not valid JSON")
    if not isinstance(obj, dict):
        raise X402Error("X-PAYMENT must be a JSON object")
    return obj


def _extract_authorization(payment: Dict) -> PaymentAuthorization:
    """Validate the structural shape of an x402 'exact' EVM payment payload."""
    if payment.get("x402Version") != X402_VERSION:
        raise X402Error("unsupported x402Version")
    if payment.get("scheme") != SCHEME_EXACT:
        raise X402Error("unsupported scheme")
    network = _as_str(payment.get("network"), "network")
    payload = payment.get("payload")
    if not isinstance(payload, dict):
        raise X402Error("missing payload")
    auth = payload.get("authorization")
    if not isinstance(auth, dict):
        raise X402Error("missing authorization")
    nonce = _parse_bytes32(auth.get("nonce"), "nonce")
    return PaymentAuthorization(
        payer=_norm_address(auth.get("from"), "from"),
        to=_norm_address(auth.get("to"), "to"),
        value=_parse_uint(auth.get("value"), "value"),
        valid_after=_parse_uint(auth.get("validAfter"), "validAfter"),
        valid_before=_parse_uint(auth.get("validBefore"), "validBefore"),
        nonce=nonce,
        nonce_hex="0x" + nonce.hex(),
        signature=_parse_signature(payload.get("signature")),
        network=network,
    )


def _recover_signer(req: Dict, auth: PaymentAuthorization) -> Optional[str]:
    """Recover the EIP-3009 TransferWithAuthorization signer.

    The EIP-712 domain is built from the REQUIREMENTS (asset, chainId from the
    network we require, name/version from the asset's domain), not from the client
    payload, so a signature is cryptographically bound to the exact token and
    chain we are charging on. Returns the lowercased signer or None on failure.
    """
    chain_id = NETWORK_CHAIN_ID.get(req["network"])
    if chain_id is None:
        return None
    extra = req.get("extra") or {}
    full_message = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "primaryType": "TransferWithAuthorization",
        "domain": {
            "name": str(extra.get("name", "")),
            "version": str(extra.get("version", "")),
            "chainId": chain_id,
            "verifyingContract": req["asset"],
        },
        "message": {
            "from": auth.payer,
            "to": auth.to,
            "value": auth.value,
            "validAfter": auth.valid_after,
            "validBefore": auth.valid_before,
            "nonce": auth.nonce,
        },
    }
    try:
        signable = encode_typed_data(full_message=full_message)
        recovered = Account.recover_message(signable, signature=auth.signature)
    except Exception:
        # A bad signature / malformed structured data must read as "not verified",
        # never as a server error that could be probed.
        return None
    return recovered.lower()


@dataclass
class VerifyResult:
    valid: bool
    code: str                 # machine-readable reason
    reason: str               # human-readable reason
    payer: str = ""
    value_atomic: str = "0"
    network: str = ""
    nonce_hex: str = ""


def verify_payment(payment: Dict, requirements: Dict, *,
                   now: Optional[float] = None,
                   nonce_store: Optional["NonceStore"] = None) -> VerifyResult:
    """Verify an x402 'exact' payment against the published requirements.

    Checks, in order: structural shape, network match, recipient match, amount
    sufficiency, time window, replay (via nonce_store), then the EIP-3009
    signature recovery binding the signer to authorization.from. Never raises on
    a bad client payload; returns a non-valid VerifyResult instead.
    """
    now_s = _now() if now is None else now
    try:
        auth = _extract_authorization(payment)
    except X402Error as exc:
        return VerifyResult(False, "malformed", str(exc))

    if auth.network != requirements.get("network"):
        return VerifyResult(False, "network_mismatch",
                            "payment network does not match requirements",
                            payer=auth.payer, network=auth.network)

    pay_to = str(requirements.get("payTo", "")).lower()
    if auth.to != pay_to:
        return VerifyResult(False, "recipient_mismatch",
                            "payment recipient does not match payTo",
                            payer=auth.payer, network=auth.network)

    try:
        required = _parse_uint(requirements.get("maxAmountRequired"), "maxAmountRequired")
    except X402Error as exc:
        return VerifyResult(False, "bad_requirements", str(exc))
    if auth.value < required:
        return VerifyResult(False, "insufficient_amount",
                            "payment value is below the required amount",
                            payer=auth.payer, value_atomic=str(auth.value),
                            network=auth.network)

    if auth.valid_after > now_s:
        return VerifyResult(False, "not_yet_valid",
                            "authorization is not valid yet",
                            payer=auth.payer, network=auth.network)
    if auth.valid_before <= now_s:
        return VerifyResult(False, "expired",
                            "authorization has expired",
                            payer=auth.payer, network=auth.network)
    if auth.valid_before - now_s > MAX_VALID_WINDOW_SECONDS:
        return VerifyResult(False, "window_too_long",
                            "authorization validity window is too long",
                            payer=auth.payer, network=auth.network)

    if nonce_store is not None and nonce_store.seen(auth.payer, auth.nonce_hex):
        return VerifyResult(False, "replay",
                            "authorization nonce already used",
                            payer=auth.payer, nonce_hex=auth.nonce_hex,
                            network=auth.network)

    signer = _recover_signer(requirements, auth)
    if signer is None:
        return VerifyResult(False, "bad_signature",
                            "signature could not be recovered",
                            payer=auth.payer, network=auth.network)
    if signer != auth.payer:
        return VerifyResult(False, "signer_mismatch",
                            "recovered signer does not match authorization.from",
                            payer=auth.payer, network=auth.network)

    return VerifyResult(True, "ok", "payment verified", payer=auth.payer,
                        value_atomic=str(auth.value), network=auth.network,
                        nonce_hex=auth.nonce_hex)


# --- replay protection ------------------------------------------------------

class NonceStore:
    """In-memory single-use guard keyed by (payer, nonce).

    An EIP-3009 authorization nonce is single-use on-chain; this mirrors that off
    the chain so the same authorization cannot redeem the feed twice before the
    facilitator settles it. claim() is the atomic check-and-set used on the serve
    path: within one process it closes the read-then-write race between concurrent
    requests carrying the same authorization. Cross-process durability (multiple
    workers) is the deployer's responsibility: back this with a SQLite UNIQUE
    constraint or shared store exposing the same claim()/seen() interface. Entries
    expire at the authorization validBefore.
    """

    def __init__(self) -> None:
        self._seen: Dict[Tuple[str, str], int] = {}

    @staticmethod
    def _key(payer: str, nonce_hex: str) -> Tuple[str, str]:
        return (str(payer).lower(), str(nonce_hex).lower())

    def _prune(self, now_s: float) -> None:
        # Drop expired entries whenever the table is non-trivial so it cannot grow
        # without bound under sustained load (every entry expires by validBefore).
        if len(self._seen) < 1024:
            return
        dead = [k for k, exp in self._seen.items() if exp <= now_s]
        for k in dead:
            self._seen.pop(k, None)

    def seen(self, payer: str, nonce_hex: str) -> bool:
        return self._key(payer, nonce_hex) in self._seen

    def mark(self, payer: str, nonce_hex: str, expires_at: int,
             now: Optional[float] = None) -> None:
        now_s = _now() if now is None else now
        self._prune(now_s)
        self._seen[self._key(payer, nonce_hex)] = int(expires_at)

    def claim(self, payer: str, nonce_hex: str, expires_at: int,
              now: Optional[float] = None) -> bool:
        """Atomically reserve a nonce. Returns True if newly reserved, False if it
        was already used (replay). This single dict read+write has no intervening
        yield, so two concurrent same-nonce requests cannot both win it."""
        now_s = _now() if now is None else now
        self._prune(now_s)
        key = self._key(payer, nonce_hex)
        if key in self._seen:
            return False
        self._seen[key] = int(expires_at)
        return True


# --- settlement -------------------------------------------------------------

@dataclass
class SettlementResult:
    settled: bool
    deferred: bool
    network: str
    payer: str
    tx_hash: Optional[str] = None
    reason: str = ""


class VerifyOnlySettler:
    """Default settler: the payment is cryptographically verified but the on-chain
    broadcast (transferWithAuthorization) is deferred to an x402 facilitator with
    a funded relayer, supplied through the Trust Wallet agent kit. It performs no
    network call and holds no key."""

    def settle(self, payment: Dict, requirements: Dict,
               verify: VerifyResult) -> SettlementResult:
        return SettlementResult(
            settled=False, deferred=True,
            network=str(requirements.get("network", "")),
            payer=verify.payer,
            reason="settlement deferred to x402 facilitator",
        )


# A live settler conforms to this shape: settle(payment, requirements, verify) ->
# SettlementResult. The server layer injects a facilitator-backed implementation.
Settler = Callable[[Dict, Dict, VerifyResult], SettlementResult]


def _encode_payment_response(settle: SettlementResult) -> str:
    body = {
        "success": settle.settled,
        "deferred": settle.deferred,
        "network": settle.network,
        "payer": settle.payer,
        "transaction": settle.tx_hash,
    }
    return base64.b64encode(json.dumps(body).encode("utf-8")).decode("ascii")


# --- feed builders ----------------------------------------------------------

def _entity_dict(e) -> Dict:
    return {
        "key": e.key, "kind": e.kind, "n_resolved": e.n_resolved,
        "win_rate": round(e.win_rate, 4), "expectancy": round(e.expectancy, 4),
        "realized_pnl": round(e.realized_pnl, 4),
        "avg_drawdown": round(e.avg_drawdown, 4),
        "brier_skill": round(e.brier_skill, 4),
    }


def _uvii_dict(u) -> Dict:
    return {
        "key": u.key, "kind": u.kind, "score": round(u.score, 2),
        "pnl_score": round(u.pnl_score, 2), "skill_score": round(u.skill_score, 2),
        "discipline_score": round(u.discipline_score, 2),
        "integrity_score": round(u.integrity_score, 2),
        "uptime_score": round(u.uptime_score, 2),
        "n_resolved": u.n_resolved,
    }


@dataclass
class FeedParams:
    group_by: str = "symbol"
    rank_by: str = "expectancy"
    horizon: str = "24h"
    top_n: int = 10
    min_samples: int = 30
    since_ts: Optional[int] = None


def _coerce_feed_params(raw: Optional[Dict]) -> FeedParams:
    """Validate caller feed parameters against fixed whitelists. db_path is NOT
    accepted here; the server pins it to the configured read-only record."""
    raw = raw or {}
    if not isinstance(raw, dict):
        raise X402Error("feed params must be an object")
    group_by = str(raw.get("group_by", "symbol"))
    if group_by not in _GROUP_CHOICES:
        raise X402Error("invalid group_by")
    rank_by = str(raw.get("rank_by", "expectancy"))
    if rank_by not in _RANK_CHOICES:
        raise X402Error("invalid rank_by")
    horizon = str(raw.get("horizon", "24h"))
    if horizon not in HORIZON_CHOICES:
        raise X402Error("invalid horizon")
    try:
        top_n = int(raw.get("top_n", 10))
    except (TypeError, ValueError):
        raise X402Error("invalid top_n")
    top_n = max(1, min(top_n, _MAX_TOP_N))
    try:
        min_samples = int(raw.get("min_samples", 30))
    except (TypeError, ValueError):
        raise X402Error("invalid min_samples")
    min_samples = max(1, min(min_samples, _MAX_MIN_SAMPLES))
    since = raw.get("since_ts")
    if since is not None:
        try:
            since = int(since)
        except (TypeError, ValueError):
            raise X402Error("invalid since_ts")
        if since < 0:
            raise X402Error("invalid since_ts")
    return FeedParams(group_by=group_by, rank_by=rank_by, horizon=horizon,
                      top_n=top_n, min_samples=min_samples, since_ts=since)


def build_feed(product_id: str, params: FeedParams,
               db_path: str = DEFAULT_DB_PATH) -> Dict:
    """Build the verified-feed payload for a product. Read-only over signal.db."""
    if product_id == "verified-leaderboard":
        lb = build_leaderboard(group_by=params.group_by, rank_by=params.rank_by,
                               horizon=params.horizon,
                               min_samples=params.min_samples,
                               since_ts=params.since_ts, db_path=db_path)
        return {
            "product": product_id, "group_by": lb.group_by,
            "horizon": lb.horizon, "rank_by": params.rank_by,
            "since_ts": lb.since_ts, "qualified": len(lb.entries),
            "below_threshold": lb.below_threshold,
            "overall": _entity_dict(lb.overall),
            "ranked": [_entity_dict(e) for e in lb.entries[:params.top_n]],
        }
    if product_id == "uvii-index":
        idx = build_uvii_index(group_by=params.group_by, horizon=params.horizon,
                               min_samples=params.min_samples,
                               since_ts=params.since_ts, db_path=db_path)
        return {
            "product": product_id, "group_by": idx.group_by,
            "horizon": idx.horizon, "since_ts": idx.since_ts,
            "global_index": _uvii_dict(idx.global_index),
            "entities": [_uvii_dict(u) for u in idx.entities[:params.top_n]],
        }
    raise X402Error(f"unknown product: {product_id!r}")


# --- orchestrator -----------------------------------------------------------

@dataclass
class FeedResponse:
    status: int               # HTTP status (402 = payment required, 200 = served)
    body: Dict
    headers: Dict[str, str] = field(default_factory=dict)


def serve_feed(product_id: str, x_payment_b64: Optional[str], *,
               cfg: RequirementsConfig,
               feed_params: Optional[Dict] = None,
               now: Optional[float] = None,
               nonce_store: Optional[NonceStore] = None,
               settler: Optional[Settler] = None,
               require_settlement: bool = False,
               db_path: str = DEFAULT_DB_PATH) -> FeedResponse:
    """Run the full x402 flow for one feed request and return a FeedResponse.

    No X-PAYMENT -> 402 with payment requirements. A present header is decoded and
    verified; on any failure a 402 is returned with the reason and the terms. On
    success the (single-use) nonce is marked, the payment is settled (or settlement
    is recorded as deferred), and the verified feed payload is returned with an
    X-PAYMENT-RESPONSE header. With require_settlement=True a non-settled payment
    is refused; the default (False) serves the feed on cryptographic verification
    while settlement completes asynchronously through the facilitator.
    """
    now_s = _now() if now is None else now
    # Validate the product/config up front so an unknown product is a clean error,
    # not a 402 advertising nothing.
    get_product(product_id)
    params = _coerce_feed_params(feed_params)

    if not x_payment_b64:
        return FeedResponse(402, make_402(product_id, cfg))

    try:
        payment = decode_payment_header(x_payment_b64)
    except X402Error as exc:
        return FeedResponse(402, make_402(product_id, cfg, error=str(exc)))

    requirements = payment_requirements(product_id, cfg)
    vr = verify_payment(payment, requirements, now=now_s, nonce_store=nonce_store)
    if not vr.valid:
        return FeedResponse(402, make_402(product_id, cfg, error=vr.reason))

    # The authorization is valid and single-use: atomically claim the nonce before
    # serving so a concurrent replay of the same authorization cannot redeem the
    # feed twice within this process. Losing the claim race reads as a replay.
    if nonce_store is not None:
        try:
            valid_before = _parse_uint(
                payment.get("payload", {}).get("authorization", {}).get("validBefore"),
                "validBefore")
        except X402Error:
            valid_before = int(now_s + MAX_VALID_WINDOW_SECONDS)
        if not nonce_store.claim(vr.payer, vr.nonce_hex,
                                 expires_at=valid_before, now=now_s):
            return FeedResponse(402, make_402(
                product_id, cfg, error="authorization nonce already used"))

    settle_fn = settler or VerifyOnlySettler().settle
    try:
        settle = settle_fn(payment, requirements, vr)
    except Exception:
        settle = SettlementResult(settled=False, deferred=True,
                                  network=vr.network, payer=vr.payer,
                                  reason="settlement error")
    if require_settlement and not settle.settled:
        return FeedResponse(402, make_402(
            product_id, cfg, error="payment not settled: " + settle.reason))

    body = build_feed(product_id, params, db_path=db_path)
    body["payment"] = {
        "payer": vr.payer, "value_atomic": vr.value_atomic,
        "network": vr.network, "settled": settle.settled,
        "settlement_deferred": settle.deferred,
        "tx_hash": settle.tx_hash,
    }
    headers = {"X-PAYMENT-RESPONSE": _encode_payment_response(settle)}
    return FeedResponse(200, body, headers)


# --- built-in self-check ----------------------------------------------------

def _sign_authorization(req: Dict, *, value: int, valid_after: int,
                        valid_before: int, nonce: bytes, key) -> Dict:
    """Test helper: produce a signed x402 'exact' payment for given requirements."""
    acct = Account.from_key(key)
    chain_id = NETWORK_CHAIN_ID[req["network"]]
    full_message = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ],
        },
        "primaryType": "TransferWithAuthorization",
        "domain": {
            "name": req["extra"]["name"], "version": req["extra"]["version"],
            "chainId": chain_id, "verifyingContract": req["asset"],
        },
        "message": {
            "from": acct.address, "to": req["payTo"], "value": value,
            "validAfter": valid_after, "validBefore": valid_before, "nonce": nonce,
        },
    }
    signable = encode_typed_data(full_message=full_message)
    sig = Account.sign_message(signable, acct.key)
    return {
        "x402Version": X402_VERSION, "scheme": SCHEME_EXACT,
        "network": req["network"],
        "payload": {
            "signature": "0x" + sig.signature.hex(),
            "authorization": {
                "from": acct.address, "to": req["payTo"], "value": str(value),
                "validAfter": str(valid_after), "validBefore": str(valid_before),
                "nonce": "0x" + nonce.hex(),
            },
        },
    }


def _b64(payment: Dict) -> str:
    return base64.b64encode(json.dumps(payment).encode("utf-8")).decode("ascii")


def demo_roundtrip(product_id: str, cfg: RequirementsConfig, *,
                   now: Optional[float] = None,
                   feed_params: Optional[Dict] = None,
                   db_path: str = DEFAULT_DB_PATH) -> Dict:
    """Run the full 402 -> sign -> verify -> 200 handshake end to end and return a
    step-by-step transcript of the real protocol artifacts.

    The buyer here is a freshly generated ephemeral key that signs a genuine
    EIP-3009 TransferWithAuthorization for the exact published price. Every
    cryptographic step is real: the signature is recovered server-side and the
    recovered signer is checked against authorization.from before the feed is
    served. Only the on-chain SETTLEMENT (broadcasting the authorization) is
    deferred to an x402 facilitator with a funded relayer, exactly as
    VerifyOnlySettler documents. No real funds move and no key is held; this is a
    self-contained proof that the payment core verifies a real signed payment.
    """
    now_s = _now() if now is None else now
    product = get_product(product_id)
    req = payment_requirements(product_id, cfg)
    price = int(req["maxAmountRequired"])

    # Step 1: the server's 402 challenge (the published payment terms).
    challenge = serve_feed(product_id, None, cfg=cfg, now=now_s, db_path=db_path)

    # Step 2: an ephemeral buyer signs an EIP-3009 authorization for the exact
    # price, valid for a short window, with a single-use random nonce.
    acct = Account.create()
    nonce = os.urandom(32)
    valid_before = int(now_s + 60)
    payment = _sign_authorization(req, value=price, valid_after=0,
                                  valid_before=valid_before, nonce=nonce,
                                  key=acct.key)
    sig = payment["payload"]["signature"]

    # Step 3: the server verifies the signature and binds it to the payer.
    vr = verify_payment(payment, req, now=now_s)

    # Step 4: the verified payment redeems the feed (single-use nonce claimed).
    store = NonceStore()
    served = serve_feed(product_id, _b64(payment), cfg=cfg, now=now_s,
                        nonce_store=store, feed_params=feed_params,
                        db_path=db_path)
    pay_resp = None
    enc = served.headers.get("X-PAYMENT-RESPONSE")
    if enc:
        try:
            pay_resp = json.loads(base64.b64decode(enc).decode("utf-8"))
        except (binascii.Error, ValueError, UnicodeDecodeError):
            pay_resp = None
    served_payment = served.body.get("payment") if served.status == 200 else None

    return {
        "product": {
            "product_id": product.product_id, "title": product.title,
            "description": product.description,
            "price_atomic": product.price_atomic, "mime_type": product.mime_type,
        },
        "terms": {
            "network": cfg.network,
            "chain_id": NETWORK_CHAIN_ID.get(cfg.network),
            "asset": req["asset"], "pay_to": req["payTo"],
            "asset_name": req["extra"]["name"],
            "asset_version": req["extra"]["version"],
            "max_amount_required": req["maxAmountRequired"],
            "resource": req["resource"],
            "max_timeout_seconds": req["maxTimeoutSeconds"],
        },
        "steps": [
            {"n": 1, "name": "challenge",
             "title": "402 Payment Required",
             "status": challenge.status,
             "detail": "Server returns the published x402 payment terms.",
             "accepts": challenge.body.get("accepts", [])},
            {"n": 2, "name": "sign",
             "title": "EIP-3009 signed authorization",
             "detail": "Ephemeral buyer signs TransferWithAuthorization for the "
                       "exact price.",
             "payer": acct.address,
             "value_atomic": str(price),
             "nonce": "0x" + nonce.hex(),
             "valid_before": valid_before,
             "signature": sig},
            {"n": 3, "name": "verify",
             "title": "Signature recovered and bound to payer",
             "detail": "Server recovers the signer and checks it equals "
                       "authorization.from.",
             "valid": vr.valid, "code": vr.code, "reason": vr.reason,
             "recovered_payer": vr.payer,
             "network": vr.network},
            {"n": 4, "name": "serve",
             "title": "200 OK · verified feed served",
             "status": served.status,
             "detail": "Payment verified, single-use nonce claimed, feed returned.",
             "payload_keys": sorted(served.body.keys()) if served.status == 200 else [],
             "payment": served_payment,
             "payment_response": pay_resp},
        ],
        "settlement": {
            "settled": bool(pay_resp and pay_resp.get("success")),
            "deferred": bool(pay_resp and pay_resp.get("deferred", True)),
            "note": "Cryptographic verification is real and complete; the "
                    "settlement transaction is deferred to an x402 facilitator "
                    "with a funded relayer (no funds move in this proof).",
        },
        "ephemeral_signer": True,
        "verified": bool(vr.valid and served.status == 200),
    }


def consume_feed(product_id: str, cfg: RequirementsConfig, *,
                 now: Optional[float] = None,
                 feed_params: Optional[Dict] = None,
                 db_path: str = DEFAULT_DB_PATH) -> Dict:
    """Buyer-side primitive: natively consume one x402 feed end to end and return
    a compact result the autonomous loop can publish.

    This is the same real protocol as ``demo_roundtrip`` (402 challenge -> ephemeral
    EIP-3009 signed authorization for the exact price -> server-side signature
    recovery and verification -> 200 verified feed), trimmed to the fields a
    consumer cares about. No key is held and no funds move: settlement stays
    deferred to an x402 facilitator (VerifyOnlySettler), so this is a genuine
    machine-to-machine purchase whose settlement leg is the only deferred step.

    Returns ``{ok, product_id, price_atomic, network, chain_id, payer, verified,
    settled, settlement_deferred, feed}`` where ``feed`` is the compact verified
    payload (global index / overall plus the top entities). On any error returns
    ``{ok: False, error: <str>}`` and never raises."""
    try:
        now_s = _now() if now is None else now
        req = payment_requirements(product_id, cfg)
        price = int(req["maxAmountRequired"])
        # An ephemeral buyer signs a real authorization for the exact price with a
        # single-use random nonce, valid for a short window.
        acct = Account.create()
        nonce = os.urandom(32)
        valid_before = int(now_s + 60)
        payment = _sign_authorization(req, value=price, valid_after=0,
                                      valid_before=valid_before, nonce=nonce,
                                      key=acct.key)
        vr = verify_payment(payment, req, now=now_s)
        store = NonceStore()
        served = serve_feed(product_id, _b64(payment), cfg=cfg, now=now_s,
                            nonce_store=store, feed_params=feed_params,
                            db_path=db_path)
        verified = bool(vr.valid and served.status == 200)
        feed: Dict = {}
        pay = {}
        if served.status == 200:
            pay = served.body.get("payment", {}) or {}
            if product_id == "uvii-index":
                feed = {"global_index": served.body.get("global_index"),
                        "entities": served.body.get("entities", [])}
            else:
                feed = {"overall": served.body.get("overall"),
                        "qualified": served.body.get("qualified"),
                        "ranked": served.body.get("ranked", [])}
        return {
            "ok": verified,
            "product_id": product_id,
            "price_atomic": req["maxAmountRequired"],
            "network": cfg.network,
            "chain_id": NETWORK_CHAIN_ID.get(cfg.network),
            "asset": req["asset"],
            "pay_to": req["payTo"],
            "payer": vr.payer,
            "verified": verified,
            "settled": bool(pay.get("settled")),
            "settlement_deferred": bool(pay.get("settlement_deferred", True)),
            "feed": feed,
        }
    except Exception as exc:  # a feed purchase must never crash the loop
        # Publish only the error type, never the raw message (it can embed a
        # local path); the full exception stays in the process logs.
        return {"ok": False, "error": type(exc).__name__, "product_id": product_id}


def _selftest() -> int:
    cfg = RequirementsConfig(
        pay_to="0x" + "ab" * 20,
        asset="0x55d398326f99059fF775485246999027B3197955",
        network="bsc", asset_name="BSC-USD", asset_version="1")
    req = payment_requirements("verified-leaderboard", cfg)
    price = int(req["maxAmountRequired"])
    acct = Account.create()
    now = 1_900_000_000.0
    nonce = b"\x11" * 32

    checks: List[Tuple[str, bool]] = []

    good = _sign_authorization(req, value=price, valid_after=0,
                               valid_before=int(now + 60), nonce=nonce,
                               key=acct.key)
    vr = verify_payment(good, req, now=now)
    checks.append(("valid payment verifies", vr.valid and vr.code == "ok"))

    # tamper: lower the value after signing -> below the floor, rejected before
    # signature recovery (proves the amount-floor check).
    tampered = json.loads(json.dumps(good))
    tampered["payload"]["authorization"]["value"] = str(price - 1)
    vr_t = verify_payment(tampered, req, now=now)
    checks.append(("tampered-low amount rejected",
                   not vr_t.valid and vr_t.code == "insufficient_amount"))

    # tamper: raise the value after signing (still passes the floor) -> the amount
    # is in the signed body, so recovery yields a different signer: signer_mismatch.
    # This proves the signature binds the amount, not just the floor check.
    tampered_up = json.loads(json.dumps(good))
    tampered_up["payload"]["authorization"]["value"] = str(price + 1)
    vr_tu = verify_payment(tampered_up, req, now=now)
    checks.append(("tampered-high amount rejected",
                   not vr_tu.valid and vr_tu.code == "signer_mismatch"))

    # wrong recipient
    wrong_to = json.loads(json.dumps(good))
    wrong_to["payload"]["authorization"]["to"] = "0x" + "cd" * 20
    vr_w = verify_payment(wrong_to, req, now=now)
    checks.append(("wrong recipient rejected",
                   not vr_w.valid and vr_w.code in ("recipient_mismatch",
                                                    "signer_mismatch")))

    # expired
    expired = _sign_authorization(req, value=price, valid_after=0,
                                  valid_before=int(now - 1), nonce=b"\x22" * 32,
                                  key=acct.key)
    vr_e = verify_payment(expired, req, now=now)
    checks.append(("expired rejected", not vr_e.valid and vr_e.code == "expired"))

    # not yet valid
    future = _sign_authorization(req, value=price, valid_after=int(now + 100),
                                 valid_before=int(now + 200), nonce=b"\x33" * 32,
                                 key=acct.key)
    vr_f = verify_payment(future, req, now=now)
    checks.append(("not-yet-valid rejected",
                   not vr_f.valid and vr_f.code == "not_yet_valid"))

    # replay
    store = NonceStore()
    vr1 = verify_payment(good, req, now=now, nonce_store=store)
    store.mark(vr1.payer, vr1.nonce_hex, expires_at=int(now + 60), now=now)
    vr2 = verify_payment(good, req, now=now, nonce_store=store)
    checks.append(("replay rejected",
                   vr1.valid and not vr2.valid and vr2.code == "replay"))

    # forged signature (signed by a different key) -> signer mismatch
    other = Account.create()
    forged = _sign_authorization(req, value=price, valid_after=0,
                                 valid_before=int(now + 60), nonce=b"\x44" * 32,
                                 key=other.key)
    forged["payload"]["authorization"]["from"] = acct.address
    vr_forge = verify_payment(forged, req, now=now)
    checks.append(("forged signer rejected",
                   not vr_forge.valid and vr_forge.code == "signer_mismatch"))

    # garbage header decode
    bad_decode = True
    for junk in ["", "not base64!!", _b64({"x402Version": 2}),
                 base64.b64encode(b"x" * (MAX_PAYMENT_HEADER_BYTES + 10)).decode()]:
        try:
            obj = decode_payment_header(junk)
            verify_payment(obj if isinstance(obj, dict) else {}, req, now=now)
        except X402Error:
            continue
        except Exception:
            bad_decode = False
    checks.append(("garbage headers safe", bad_decode))

    # full serve flow: no payment -> 402, valid payment -> 200
    no_pay = serve_feed("verified-leaderboard", None, cfg=cfg, now=now)
    paid = serve_feed("verified-leaderboard", _b64(good), cfg=cfg, now=now,
                      nonce_store=NonceStore(),
                      feed_params={"group_by": "symbol", "top_n": 5})
    checks.append(("402 without payment", no_pay.status == 402
                   and no_pay.body.get("accepts")))
    checks.append(("200 with valid payment",
                   paid.status == 200 and "ranked" in paid.body
                   and "X-PAYMENT-RESPONSE" in paid.headers))

    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
