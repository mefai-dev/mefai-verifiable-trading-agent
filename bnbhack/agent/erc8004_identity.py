"""
MEFAI BNB HACK · ERC-8004 identity + ERC-8183 commerce wrapper (twak)

The agent's verifiable identity layer. Wraps the Trust Wallet Agent Kit CLI for:
  - ERC-8004 Identity Registry: mint the agent identity (NFT), point its agentURI
    at the served agent card, write track-record metadata entries, and read state.
  - ERC-8183 Agentic Commerce: the job-escrow lifecycle (create / budget / fund /
    submit / complete / reject / refund / status) for agent-to-agent jobs.

Safety mirrors the spot adapter (bsc_exec):
  - Subprocesses are spawned with an explicit argv list (no shell), reusing
    bsc_exec._run_twak, so a description / address can never be shell-interpreted.
  - The wallet password is delivered to the child via TWAK_WALLET_PASSWORD only,
    never on argv, through the minimal allowlisted env in bsc_exec._child_env.
  - Every state-changing call is dry by default (execute=False) and only signs
    when execute=True AND a password is configured. Reads never sign.

NOTE: the ERC-8004 registry and ERC-8183 contracts have a BSC MAINNET deployment
only (no testnet), so register / set-metadata / job writes spend real mainnet gas
and create permanent records. Treat execute=True here as a mainnet action.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import agent_card
from bsc_exec import (
    CHAIN, EXEC_TIMEOUT, QUOTE_TIMEOUT, CliResult, _resolve_addr,
    _run_twak,
)

logger = logging.getLogger("mefai.bnbhack.erc8004")

# Metadata keys/values are bounded so an oversized entry cannot be pushed to the
# registry (and to keep gas predictable).
_MAX_KEY = 64
_MAX_VALUE = 4096
_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
# A registration URI must be https or ipfs (the schemes the register call accepts).
# No `@` (userinfo) so a credential cannot be smuggled into the agentURI.
_URI_RE = re.compile(r"^(https://|ipfs://)[\w.~:/?#\[\]!$&'()*+,;=%-]{3,2048}$")
# Agent / job ids are decimal token ids.
_ID_RE = re.compile(r"^[0-9]{1,32}$")
# Control characters (incl. NUL/newline) are rejected from any free-text argv
# value so a description / metadata value cannot inject a log line or confuse
# the argv parser.
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _valid_id(v: Any) -> Optional[str]:
    if isinstance(v, int) and v >= 0:
        return str(v)
    if isinstance(v, str) and _ID_RE.match(v.strip()):
        return v.strip()
    return None


def _valid_text(v: Any, max_len: int) -> bool:
    """Free-text argv value: bounded, printable, not a leading-dash that the CLI
    could mistake for a flag."""
    if not isinstance(v, str) or not (0 < len(v) <= max_len):
        return False
    if v.lstrip().startswith("-"):
        return False
    return _CTRL_RE.search(v) is None


# --- read paths (no signing) -----------------------------------------------

async def show_identity(agent_id: Any) -> CliResult:
    """Read the on-record state of an ERC-8004 agent identity. No password."""
    aid = _valid_id(agent_id)
    if aid is None:
        return CliResult(False, error="invalid agent id")
    return await _run_twak(
        ["erc8004", "show", aid, "--chain", CHAIN, "--json"],
        timeout=QUOTE_TIMEOUT, with_password=False)


async def get_metadata(agent_id: Any, key: str) -> CliResult:
    aid = _valid_id(agent_id)
    if aid is None:
        return CliResult(False, error="invalid agent id")
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return CliResult(False, error="invalid metadata key")
    return await _run_twak(
        ["erc8004", "get-metadata", aid, "--key", key, "--chain", CHAIN, "--json"],
        timeout=QUOTE_TIMEOUT, with_password=False)


async def job_status(job_id: Any) -> CliResult:
    jid = _valid_id(job_id)
    if jid is None:
        return CliResult(False, error="invalid job id")
    return await _run_twak(
        ["erc8183", "status", jid, "--chain", CHAIN, "--json"],
        timeout=QUOTE_TIMEOUT, with_password=False)


# --- gated identity writes (mainnet) ---------------------------------------

@dataclass
class WriteOutcome:
    executed: bool
    result: Dict[str, Any] = field(default_factory=dict)
    detail: str = ""


def _dry(detail: str) -> WriteOutcome:
    return WriteOutcome(False, detail=f"dry-run (execute=False): {detail}")


async def register_identity(uri: Optional[str] = None, *,
                            execute: bool = False) -> WriteOutcome:
    """Mint the agent identity, pointing agentURI at the served card by default.
    MAINNET write: dry unless execute=True and a wallet password is configured."""
    target = (uri or agent_card.CARD_URL).strip()
    if not _URI_RE.match(target):
        return WriteOutcome(False, detail=f"refused: agentURI must be https/ipfs "
                                          f"and well-formed (got {target!r})")
    if not execute:
        return _dry(f"would register identity with agentURI {target}")
    ex = await _run_twak(
        ["erc8004", "register", "--uri", target, "--chain", CHAIN, "--json"],
        timeout=EXEC_TIMEOUT, with_password=True)
    if not ex.ok:
        logger.warning("erc8004 register failed: %s", ex.error)
        return WriteOutcome(False, detail=f"register failed: {ex.error}")
    return WriteOutcome(True, result=ex.data, detail="identity registered")


async def set_metadata(agent_id: Any, key: str, value: str, *,
                       execute: bool = False) -> WriteOutcome:
    """Write one metadata entry on the identity. MAINNET write; dry by default."""
    aid = _valid_id(agent_id)
    if aid is None:
        return WriteOutcome(False, detail="invalid agent id")
    if not isinstance(key, str) or not _KEY_RE.match(key):
        return WriteOutcome(False, detail="invalid metadata key")
    if not _valid_text(value, _MAX_VALUE):
        return WriteOutcome(False, detail="invalid metadata value")
    if not execute:
        return _dry(f"would set metadata {key}={value} on agent {aid}")
    ex = await _run_twak(
        ["erc8004", "set-metadata", aid, "--key", key, "--value", value,
         "--chain", CHAIN, "--json"],
        timeout=EXEC_TIMEOUT, with_password=True)
    if not ex.ok:
        logger.warning("erc8004 set-metadata %s failed: %s", key, ex.error)
        return WriteOutcome(False, detail=f"set-metadata {key} failed: {ex.error}")
    return WriteOutcome(True, result=ex.data, detail=f"metadata {key} set")


async def set_all_metadata(agent_id: Any, *,
                           execute: bool = False) -> List[WriteOutcome]:
    """Write the full track-record metadata set (from agent_card.metadata_entries).
    Each entry is an independent MAINNET write; all are dry unless execute=True."""
    out: List[WriteOutcome] = []
    for entry in agent_card.metadata_entries():
        out.append(await set_metadata(agent_id, entry["key"], entry["value"],
                                      execute=execute))
    return out


# --- gated ERC-8183 commerce writes (mainnet) ------------------------------

async def create_job(provider: str, evaluator: str, expires_at: int,
                     description: str, *, execute: bool = False) -> WriteOutcome:
    """Open a job escrow (caller is the client). MAINNET write; dry by default."""
    prov = _resolve_addr(provider)
    evalr = _resolve_addr(evaluator)
    if prov is None:
        return WriteOutcome(False, detail="invalid provider address")
    if evalr is None:
        return WriteOutcome(False, detail="invalid evaluator address")
    if not isinstance(expires_at, int) or expires_at <= int(time.time()):
        return WriteOutcome(False, detail="invalid expiry timestamp (must be future)")
    if not _valid_text(description, 1024):
        return WriteOutcome(False, detail="invalid description")
    args = ["erc8183", "create-job", "--provider", prov, "--evaluator", evalr,
            "--expires-at", str(expires_at), "--description", description,
            "--chain", CHAIN, "--json"]
    if not execute:
        return _dry(f"would create job provider={prov} evaluator={evalr}")
    ex = await _run_twak(args, timeout=EXEC_TIMEOUT, with_password=True)
    if not ex.ok:
        logger.warning("erc8183 create-job failed: %s", ex.error)
        return WriteOutcome(False, detail=f"create-job failed: {ex.error}")
    return WriteOutcome(True, result=ex.data, detail="job created")


async def fund_job(job_id: Any, *, execute: bool = False) -> WriteOutcome:
    """Approve + deposit the budget into escrow (two txs). MAINNET; dry default."""
    jid = _valid_id(job_id)
    if jid is None:
        return WriteOutcome(False, detail="invalid job id")
    if not execute:
        return _dry(f"would fund job {jid}")
    ex = await _run_twak(
        ["erc8183", "fund", jid, "--chain", CHAIN, "--json"],
        timeout=EXEC_TIMEOUT, with_password=True)
    if not ex.ok:
        logger.warning("erc8183 fund failed: %s", ex.error)
        return WriteOutcome(False, detail=f"fund failed: {ex.error}")
    return WriteOutcome(True, result=ex.data, detail="job funded")


async def complete_job(job_id: Any, *, execute: bool = False) -> WriteOutcome:
    """Mark a submitted job complete (evaluator), releasing escrow. MAINNET."""
    jid = _valid_id(job_id)
    if jid is None:
        return WriteOutcome(False, detail="invalid job id")
    if not execute:
        return _dry(f"would complete job {jid}")
    ex = await _run_twak(
        ["erc8183", "complete", jid, "--chain", CHAIN, "--json"],
        timeout=EXEC_TIMEOUT, with_password=True)
    if not ex.ok:
        logger.warning("erc8183 complete failed: %s", ex.error)
        return WriteOutcome(False, detail=f"complete failed: {ex.error}")
    return WriteOutcome(True, result=ex.data, detail="job completed")
