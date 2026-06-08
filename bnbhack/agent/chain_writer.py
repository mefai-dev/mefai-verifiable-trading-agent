"""
MEFAI BNB HACK · Verifiable proof bridge (commit-reveal + RiskGovernor)

The agent's chain-anchored proof layer for the autonomous loop. It wraps two
BSC-testnet contracts so the live judged window is itself un-backfillable:

  - CommitRevealPredictionRegistry: the agent COMMITS a keccak256 seal of a
    prediction (symbol, signal, confidence, entry, target, stop, expiry, salt)
    BEFORE it acts, then REVEALS the plaintext after. The seal binds the call at
    commit time, so a track record cannot be backfit or cherry-picked. Commit and
    reveal are sent from the agent's OWN wallet (self-sovereign authorship); the
    oracle only grades outcomes.
  - RiskGovernor: the drawdown killswitch twin of the local sizer. The keeper
    records equity each cycle; canTrade() is the pre-trade gate that refuses new
    trades once peak-to-trough drawdown breaches the budget.

Safety model (mirrors bsc_exec / erc8004_identity):
  - Reads (canTrade, getVault, getArenaStats, sealOf) never sign and need no key.
  - Every state-changing call is DRY by default (execute=False) and only signs
    when execute=True AND the relevant private key is configured in the env.
  - Keys are read from the environment only, never logged, never returned.
  - The connected chain is pinned to CHAIN_ID; a write refuses to sign if the RPC
    reports a different chain, and gas price / gas limit are hard-capped so a
    misconfigured env cannot drain the wallet in one send.
  - The seal is computed with eth_abi.encode to match the contract's abi.encode
    (NOT solidity_keccak / encodePacked), so a locally computed seal can never
    silently diverge from the ledger recomputation.

This is BSC TESTNET (chain 97) by default; it spends only testnet gas. Switching
to mainnet would require new addresses + an explicit execute and is out of scope
for this module.
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("mefai.bnbhack.chain")

# --- network + addresses (testnet) ------------------------------------------
RPC_URL = os.getenv("BNBHACK_RPC_URL",
                    os.getenv("ARENA_RPC_URL",
                              "https://bsc-testnet-rpc.publicnode.com"))
CHAIN_ID = int(os.getenv("BNBHACK_CHAIN_ID", "97"))
REGISTRY_ADDR = os.getenv("BNBHACK_REGISTRY_TESTNET", "").strip()
GOVERNOR_ADDR = os.getenv("BNBHACK_RISKGOVERNOR_TESTNET", "").strip()

# RPC failover. A single provider hiccup in the judged window must not silently
# stall the commit/reveal/equity proof trail, so we keep an ordered candidate
# list and rotate to a healthy node on failure. The operator can override or
# extend the whole set with BNBHACK_RPC_URLS (comma separated, tried first);
# after that we try the legacy single URL and a small per-chain public fallback.
_PUBLIC_RPCS: Dict[int, Tuple[str, ...]] = {
    97: ("https://bsc-testnet-rpc.publicnode.com",
         "https://data-seed-prebsc-1-s1.bnbchain.org:8545",
         "https://bsc-testnet.public.blastapi.io"),
    56: ("https://bsc-rpc.publicnode.com",
         "https://bsc-dataseed.bnbchain.org",
         "https://bsc-dataseed1.defibit.io"),
}


def _rpc_candidates() -> list:
    """Ordered, de-duplicated RPC URLs to try (env list, legacy URL, fallbacks)."""
    seen, out = set(), []
    raw = os.getenv("BNBHACK_RPC_URLS", "")
    for u in (*raw.split(","), RPC_URL, *_PUBLIC_RPCS.get(CHAIN_ID, ())):
        u = (u or "").strip()
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

# Keys (env only). The agent key authors commits/reveals; the oracle key grades
# outcomes and (as keeper) records equity. Absent key => that path stays dry.
_AGENT_KEY = os.getenv("BNBHACK_AGENT_PRIVATE_KEY", "").strip()
_ORACLE_KEY = os.getenv("BNBHACK_ORACLE_PRIVATE_KEY",
                        os.getenv("ARENA_ORACLE_PRIVATE_KEY", "")).strip()

# Hard ceilings so an env override (or poisoned env) cannot push an unbounded
# gas spend in a single send. The defaults sit well under these caps.
_MAX_GAS_LIMIT = 1_000_000
_MAX_GAS_GWEI = 20.0
GAS_LIMIT = min(int(os.getenv("BNBHACK_GAS_LIMIT", "300000")), _MAX_GAS_LIMIT)
GAS_GWEI = min(float(os.getenv("BNBHACK_GAS_GWEI", "3")), _MAX_GAS_GWEI)
TX_TIMEOUT = 60
PRICE_SCALE = 10000   # uint64 prices carry 4 decimals (price * 1e4)

# A single process-wide lock per signing wallet so concurrent sends cannot reuse
# a nonce. Keyed by the sender address.
_NONCE_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()

# Signal / Outcome enums (must match the Solidity enum ordering).
SIGNAL_BUY, SIGNAL_SELL, SIGNAL_HOLD = 0, 1, 2
OUTCOME_PENDING, OUTCOME_TARGET, OUTCOME_STOP, OUTCOME_EXPIRED = 0, 1, 2, 3

# --- minimal hand-written ABIs (self-contained; no artifact dependency) ------
_REGISTRY_ABI = [
    {"type": "function", "name": "commit", "stateMutability": "nonpayable",
     "inputs": [{"name": "agentId", "type": "bytes32"},
                {"name": "seal", "type": "bytes32"},
                {"name": "expiresAt", "type": "uint40"},
                {"name": "revealDeadline", "type": "uint40"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "reveal", "stateMutability": "nonpayable",
     "inputs": [{"name": "commitId", "type": "uint256"},
                {"name": "agentId", "type": "bytes32"},
                {"name": "symbol", "type": "string"},
                {"name": "signal", "type": "uint8"},
                {"name": "confidence", "type": "uint8"},
                {"name": "entryPrice", "type": "uint64"},
                {"name": "targetPrice", "type": "uint64"},
                {"name": "stopLoss", "type": "uint64"},
                {"name": "expiresAt", "type": "uint40"},
                {"name": "salt", "type": "bytes32"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "registerAgent", "stateMutability": "nonpayable",
     "inputs": [{"name": "name", "type": "string"},
                {"name": "wallet", "type": "address"}],
     "outputs": [{"name": "", "type": "bytes32"}]},
    {"type": "function", "name": "verifyOutcome", "stateMutability": "nonpayable",
     "inputs": [{"name": "predictionId", "type": "uint256"},
                {"name": "outcome", "type": "uint8"},
                {"name": "exitPrice", "type": "uint64"}],
     "outputs": []},
    {"type": "function", "name": "getAgentStats", "stateMutability": "view",
     "inputs": [{"name": "agentId", "type": "bytes32"}],
     "outputs": [{"name": "name", "type": "string"},
                 {"name": "wallet", "type": "address"},
                 {"name": "committed", "type": "uint32"},
                 {"name": "revealed", "type": "uint32"},
                 {"name": "correct", "type": "uint32"},
                 {"name": "wrong", "type": "uint32"},
                 {"name": "streak", "type": "int16"},
                 {"name": "bestStreak", "type": "int16"}]},
    {"type": "function", "name": "getArenaStats", "stateMutability": "view",
     "inputs": [],
     "outputs": [{"name": "totalAgents", "type": "uint256"},
                 {"name": "committed", "type": "uint256"},
                 {"name": "revealed", "type": "uint256"},
                 {"name": "verified", "type": "uint256"},
                 {"name": "pendingReveals", "type": "uint256"},
                 {"name": "pendingOutcomes", "type": "uint256"}]},
    {"type": "event", "name": "Committed", "anonymous": False,
     "inputs": [{"name": "commitId", "type": "uint256", "indexed": True},
                {"name": "agentId", "type": "bytes32", "indexed": True},
                {"name": "seal", "type": "bytes32", "indexed": False},
                {"name": "expiresAt", "type": "uint40", "indexed": False},
                {"name": "revealDeadline", "type": "uint40", "indexed": False}]},
    {"type": "event", "name": "Revealed", "anonymous": False,
     "inputs": [{"name": "commitId", "type": "uint256", "indexed": True},
                {"name": "predictionId", "type": "uint256", "indexed": True},
                {"name": "agentId", "type": "bytes32", "indexed": True},
                {"name": "symbol", "type": "string", "indexed": False},
                {"name": "signal", "type": "uint8", "indexed": False},
                {"name": "entryPrice", "type": "uint64", "indexed": False}]},
]

_GOVERNOR_ABI = [
    {"type": "function", "name": "canTrade", "stateMutability": "view",
     "inputs": [{"name": "agent", "type": "address"}],
     "outputs": [{"name": "ok", "type": "bool"},
                 {"name": "ddBps", "type": "uint256"}]},
    {"type": "function", "name": "drawdownBps", "stateMutability": "view",
     "inputs": [{"name": "agent", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}]},
    {"type": "function", "name": "getVault", "stateMutability": "view",
     "inputs": [{"name": "agent", "type": "address"}],
     "outputs": [{"name": "hwm", "type": "uint256"},
                 {"name": "equity", "type": "uint256"},
                 {"name": "updatedAt", "type": "uint40"},
                 {"name": "halted", "type": "bool"},
                 {"name": "registered", "type": "bool"}]},
    {"type": "function", "name": "registerVault", "stateMutability": "nonpayable",
     "inputs": [{"name": "agent", "type": "address"},
                {"name": "initialEquity", "type": "uint256"}],
     "outputs": []},
    {"type": "function", "name": "recordEquity", "stateMutability": "nonpayable",
     "inputs": [{"name": "agent", "type": "address"},
                {"name": "equity", "type": "uint256"}],
     "outputs": []},
]


# --- helpers ----------------------------------------------------------------

@dataclass
class TxOutcome:
    executed: bool
    ok: bool = False
    tx_hash: str = ""
    value: Any = None
    detail: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


def _dry(detail: str, **extra: Any) -> TxOutcome:
    return TxOutcome(False, ok=False, detail=f"dry-run (execute=False): {detail}",
                     extra=extra)


def new_salt() -> bytes:
    """A fresh 32-byte commitment salt. Keep it private until reveal."""
    return secrets.token_bytes(32)


def to_scaled_price(price: float) -> int:
    """Encode a float price to the contract's uint64 (price * 1e4), clamped."""
    v = int(round(max(0.0, float(price)) * PRICE_SCALE))
    return min(v, (1 << 64) - 1)


def _nonce_lock(addr: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lk = _NONCE_LOCKS.get(addr)
        if lk is None:
            lk = threading.Lock()
            _NONCE_LOCKS[addr] = lk
        return lk


class ChainWriter:
    """Lazy web3 bridge to the commit-reveal registry + RiskGovernor.

    Reads work whenever the contract addresses are configured. Writes need both
    execute=True at the call site and the relevant private key in the env; absent
    either, the call returns a dry outcome and signs nothing.
    """

    def __init__(self) -> None:
        self._w3 = None
        self._registry = None
        self._governor = None
        self._agent_acct = None
        self._oracle_acct = None
        self._chain_ok = False
        self._init = False
        self._candidates: list = []
        self._rpc_idx = -1
        self._rpc_url = ""

    # -- init / accounts -----------------------------------------------------
    @staticmethod
    def _dial(url: str):
        """Open a Web3 to one URL and prove connectivity. Returns (w3, chain_id)
        or (None, None) if the node is unreachable."""
        try:
            from web3 import Web3
            from web3.middleware import ExtraDataToPOAMiddleware
            w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
            return w3, int(w3.eth.chain_id)
        except Exception as exc:
            logger.warning("chain_writer: RPC %s unreachable: %s", url, exc)
            return None, None

    def _bind(self, idx: int, url: str, w3, chain_ok: bool) -> None:
        """Adopt a dialed Web3 as the active provider and (re)bind contracts."""
        from web3 import Web3
        self._w3 = w3
        self._chain_ok = chain_ok
        self._rpc_idx = idx
        self._rpc_url = url
        self._registry = (w3.eth.contract(address=Web3.to_checksum_address(REGISTRY_ADDR),
                                           abi=_REGISTRY_ABI) if REGISTRY_ADDR else None)
        self._governor = (w3.eth.contract(address=Web3.to_checksum_address(GOVERNOR_ADDR),
                                          abi=_GOVERNOR_ABI) if GOVERNOR_ADDR else None)
        self._agent_acct = w3.eth.account.from_key(_AGENT_KEY) if _AGENT_KEY else None
        self._oracle_acct = w3.eth.account.from_key(_ORACLE_KEY) if _ORACLE_KEY else None

    def _ensure(self) -> bool:
        if self._init:
            return self._w3 is not None
        self._init = True
        self._candidates = _rpc_candidates()
        fallback = None  # (idx, url, w3): reachable but wrong chain
        for idx, url in enumerate(self._candidates):
            w3, cid = self._dial(url)
            if w3 is None:
                continue
            if cid == CHAIN_ID:
                self._bind(idx, url, w3, True)
                logger.info("chain_writer: connected RPC[%d] %s (chain %s)", idx, url, cid)
                return True
            if fallback is None:
                fallback = (idx, url, w3)
        if fallback is not None:
            idx, url, w3 = fallback
            self._bind(idx, url, w3, False)
            logger.warning("chain_writer: no RPC on chain %s; using %s (writes refused)",
                           CHAIN_ID, url)
            return True
        logger.warning("chain_writer: no RPC candidate connected (%d tried)",
                       len(self._candidates))
        return False

    def _reconnect(self) -> bool:
        """Rotate to the next reachable chain-matching RPC after a failure."""
        cands = self._candidates or _rpc_candidates()
        n = len(cands)
        if n <= 1:
            return False
        for k in range(1, n + 1):
            idx = (self._rpc_idx + k) % n
            w3, cid = self._dial(cands[idx])
            if w3 is not None and cid == CHAIN_ID:
                self._bind(idx, cands[idx], w3, True)
                logger.warning("chain_writer: rotated to RPC[%d] %s after failure",
                               idx, cands[idx])
                return True
        return False

    @property
    def agent_address(self) -> str:
        self._ensure()
        if self._agent_acct is not None:
            return self._agent_acct.address
        return os.getenv("TWAK_AGENT_WALLET", "").strip()

    def agent_id(self, name: str, wallet: Optional[str] = None) -> str:
        """keccak256(abi.encodePacked(name, wallet)) as the registry computes it."""
        from web3 import Web3
        w = Web3.to_checksum_address(wallet or self.agent_address)
        h = Web3.solidity_keccak(["string", "address"], [name, w]).hex()
        # .hex() may or may not carry a 0x prefix across web3 versions; strip the
        # exact prefix only (never a leading data nibble, which lstrip would eat).
        if h.startswith("0x"):
            h = h[2:]
        return "0x" + h

    def seal_of(self, agent_id_hex: str, symbol: str, signal: int, confidence: int,
                entry: int, target: int, stop: int, expires_at: int,
                salt: bytes) -> bytes:
        """The canonical seal, computed locally with eth_abi.encode to match the
        contract's abi.encode exactly."""
        from eth_abi import encode
        from web3 import Web3
        aid = bytes.fromhex(agent_id_hex[2:] if agent_id_hex.startswith("0x")
                            else agent_id_hex)
        packed = encode(
            ["bytes32", "string", "uint8", "uint8", "uint64", "uint64",
             "uint64", "uint40", "bytes32"],
            [aid, symbol, int(signal), int(confidence), int(entry), int(target),
             int(stop), int(expires_at), salt],
        )
        return Web3.keccak(packed)

    # -- low-level send ------------------------------------------------------
    def _send(self, fn, acct, retries: int = 3) -> TxOutcome:
        w3 = self._w3
        if not self._chain_ok:
            return TxOutcome(False, detail=f"refused: connected chain is not the "
                                           f"expected chain {CHAIN_ID}")
        lock = _nonce_lock(acct.address)
        last_err = ""
        for attempt in range(retries):
            with lock:
                try:
                    nonce = w3.eth.get_transaction_count(acct.address, "pending")
                    tx = fn.build_transaction({
                        "from": acct.address,
                        "nonce": nonce,
                        "gas": GAS_LIMIT,
                        "gasPrice": w3.to_wei(GAS_GWEI, "gwei"),
                        "chainId": CHAIN_ID,
                    })
                    signed = acct.sign_transaction(tx)
                    h = w3.eth.send_raw_transaction(signed.raw_transaction)
                    rcpt = w3.eth.wait_for_transaction_receipt(h, timeout=TX_TIMEOUT)
                    txh = h.hex()
                    if not txh.startswith("0x"):
                        txh = "0x" + txh
                    if rcpt.get("status") != 1:
                        return TxOutcome(True, ok=False, tx_hash=txh,
                                         detail="transaction reverted")
                    return TxOutcome(True, ok=True, tx_hash=txh, value=rcpt)
                except Exception as exc:
                    last_err = str(exc)
                    if "nonce" in last_err.lower() and attempt < retries - 1:
                        time.sleep(0.5)
                        continue
                    # A transient RPC fault (timeout, 5xx, broken pipe) should not
                    # abandon the send: rotate to a healthy node and retry once.
                    if attempt < retries - 1 and self._reconnect():
                        w3 = self._w3
                        continue
                    logger.warning("chain send failed: %s", last_err)
                    # Keep the raw web3 error in the server log only; the returned
                    # detail can surface in the public /loop/state, and a web3
                    # exception string can embed the RPC endpoint host. Return a
                    # generic message so no node/endpoint detail leaks to readers.
                    return TxOutcome(True, ok=False, detail="send failed")
        return TxOutcome(True, ok=False, detail="send failed")

    def _event_arg(self, receipt, event_name: str, arg: str) -> Optional[int]:
        try:
            from web3.logs import DISCARD
            ev = getattr(self._registry.events, event_name)()
            for log in ev.process_receipt(receipt, errors=DISCARD):
                return int(log["args"][arg])
        except Exception as exc:
            logger.warning("event decode failed (%s.%s): %s", event_name, arg, exc)
            return None
        return None

    # -- registry writes (agent-signed) -------------------------------------
    def commit(self, agent_id_hex: str, seal: bytes, expires_at: int,
               reveal_deadline: int, *, execute: bool = False) -> TxOutcome:
        """Commit a sealed prediction from the agent wallet. TESTNET; dry default."""
        if not execute:
            return _dry(f"would commit seal expiring {expires_at}")
        if not self._ensure() or self._registry is None:
            return TxOutcome(False, detail="registry not configured")
        if self._agent_acct is None:
            return TxOutcome(False, detail="agent key not configured (cannot sign)")
        fn = self._registry.functions.commit(
            bytes.fromhex(agent_id_hex[2:] if agent_id_hex.startswith("0x")
                          else agent_id_hex),
            seal, int(expires_at), int(reveal_deadline))
        out = self._send(fn, self._agent_acct)
        if out.ok:
            cid = self._event_arg(out.value, "Committed", "commitId")
            out.extra["commit_id"] = cid
            out.detail = f"committed (commitId={cid})"
        return out

    def reveal(self, commit_id: int, agent_id_hex: str, symbol: str, signal: int,
               confidence: int, entry: int, target: int, stop: int,
               expires_at: int, salt: bytes, *, execute: bool = False) -> TxOutcome:
        """Reveal a previously committed prediction. TESTNET; dry default."""
        if not execute:
            return _dry(f"would reveal commitId {commit_id} for {symbol}")
        if not self._ensure() or self._registry is None:
            return TxOutcome(False, detail="registry not configured")
        if self._agent_acct is None:
            return TxOutcome(False, detail="agent key not configured (cannot sign)")
        fn = self._registry.functions.reveal(
            int(commit_id),
            bytes.fromhex(agent_id_hex[2:] if agent_id_hex.startswith("0x")
                          else agent_id_hex),
            symbol, int(signal), int(confidence), int(entry), int(target),
            int(stop), int(expires_at), salt)
        out = self._send(fn, self._agent_acct)
        if out.ok:
            pid = self._event_arg(out.value, "Revealed", "predictionId")
            out.extra["prediction_id"] = pid
            out.detail = f"revealed (predictionId={pid})"
        return out

    # -- registry / governor writes (oracle/keeper-signed) ------------------
    def verify_outcome(self, prediction_id: int, outcome: int, exit_price: int,
                       *, execute: bool = False) -> TxOutcome:
        if not execute:
            return _dry(f"would verify prediction {prediction_id} outcome {outcome}")
        if not self._ensure() or self._registry is None:
            return TxOutcome(False, detail="registry not configured")
        if self._oracle_acct is None:
            return TxOutcome(False, detail="oracle key not configured (cannot sign)")
        fn = self._registry.functions.verifyOutcome(
            int(prediction_id), int(outcome), int(exit_price))
        return self._send(fn, self._oracle_acct)

    def record_equity(self, equity_units: int, agent: Optional[str] = None,
                      *, execute: bool = False) -> TxOutcome:
        """Keeper pushes the agent's equity to the RiskGovernor (auto-halts on a
        budget breach). Equity is an integer scale (e.g. USD cents)."""
        if not execute:
            return _dry(f"would record equity {equity_units}")
        if not self._ensure() or self._governor is None:
            return TxOutcome(False, detail="governor not configured")
        if self._oracle_acct is None:
            return TxOutcome(False, detail="keeper key not configured (cannot sign)")
        from web3 import Web3
        addr = Web3.to_checksum_address(agent or self.agent_address)
        fn = self._governor.functions.recordEquity(addr, int(equity_units))
        return self._send(fn, self._oracle_acct)

    # -- reads (no gas, no key) ---------------------------------------------
    def can_trade(self, agent: Optional[str] = None) -> Tuple[bool, int, str]:
        """RiskGovernor pre-trade gate: (ok, drawdown_bps, detail). Fails OPEN
        only when the governor is simply not configured (paper mode); a deployed
        governor that says halt is honoured, and a read error against a CONFIGURED
        governor fails CLOSED so a transient RPC fault cannot bypass the halt."""
        if not self._ensure() or self._governor is None:
            return (True, 0, "governor not configured (paper mode)")
        try:
            from web3 import Web3
            addr = Web3.to_checksum_address(agent or self.agent_address)
            ok, dd = self._governor.functions.canTrade(addr).call()
            return (bool(ok), int(dd),
                    "ok" if ok else f"blocked by RiskGovernor (dd {dd}bps)")
        except Exception as exc:
            logger.warning("canTrade read failed: %s", exc)
            return (False, 0, "governor read error (failing closed)")

    def arena_stats(self) -> Dict[str, Any]:
        if not self._ensure() or self._registry is None:
            return {}
        try:
            r = self._registry.functions.getArenaStats().call()
            return {"total_agents": r[0], "committed": r[1], "revealed": r[2],
                    "verified": r[3], "pending_reveals": r[4],
                    "pending_outcomes": r[5]}
        except Exception as exc:
            logger.warning("arena_stats read failed: %s", exc)
            return {}

    def vault(self, agent: Optional[str] = None) -> Dict[str, Any]:
        if not self._ensure() or self._governor is None:
            return {}
        try:
            from web3 import Web3
            addr = Web3.to_checksum_address(agent or self.agent_address)
            r = self._governor.functions.getVault(addr).call()
            return {"hwm": int(r[0]), "equity": int(r[1]), "updated_at": int(r[2]),
                    "halted": bool(r[3]), "registered": bool(r[4])}
        except Exception as exc:
            logger.warning("vault read failed: %s", exc)
            return {}

    # -- explorer links ------------------------------------------------------
    @staticmethod
    def tx_url(tx_hash: str) -> str:
        if not tx_hash:
            return ""
        h = tx_hash if tx_hash.startswith("0x") else f"0x{tx_hash}"
        base = ("https://testnet.bscscan.com" if CHAIN_ID == 97
                else "https://bscscan.com")
        return f"{base}/tx/{h}"


# Module-level singleton (lazy; safe to import even with no keys/addresses).
_writer: Optional[ChainWriter] = None


def get_writer() -> ChainWriter:
    global _writer
    if _writer is None:
        _writer = ChainWriter()
    return _writer
