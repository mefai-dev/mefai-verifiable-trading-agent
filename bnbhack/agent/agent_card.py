"""
MEFAI BNB HACK · ERC-8004 agent registration card (single source of truth)

The agent's public identity document, in the ERC-8004 registration-v1 shape. The
backend serves it read-only at a stable https URL, and that same URL is what the
ERC-8004 register call points its agentURI at, so the minted identity and the
served card never drift. Building it here (not inline in the backend) keeps the
card and the register/metadata wrapper reading from one place.

Nothing here signs or moves funds: it only assembles a JSON document from public
addresses and endpoints, all overridable via the service environment.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

# Public competition + proof addresses. These are public BSC addresses, safe to
# embed; each is overridable from the environment for a different deployment.
AGENT_WALLET = os.getenv(
    "TWAK_AGENT_WALLET", "0xD5df700Ed5355f0c778159592a072B8773faE1CC")
# ERC-8004 Identity Registry on BSC mainnet (the only known deployment).
ERC8004_REGISTRY = os.getenv(
    "ERC8004_REGISTRY_ADDRESS", "0x8004A169FB4a3325136EB29fA0ceB6D2e539a432")
# Proof anchors: the result ledger and the commit-reveal protocol, all on BSC mainnet.
MAINNET_LEDGER = os.getenv(
    "MEFAI_MAINNET_LEDGER", "0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744")
REGISTRY = os.getenv(
    "BNBHACK_REGISTRY_ADDRESS", "0xcA9499a2d20cFAa98f9Bc3b2F1386A70f51c2FEB")
GOVERNOR = os.getenv(
    "BNBHACK_RISKGOVERNOR_ADDRESS", "0xf679DD2Fe68Bd8e67838efB2740285E491Fa00b2")

# Public service endpoints (the cockpit and the machine-payable feed).
SITE = os.getenv("MEFAI_SITE", "https://mefai.io")
COCKPIT_URL = os.getenv("MEFAI_COCKPIT_URL", f"{SITE}/terminal/bnbhack-agent")
LEADERBOARD_URL = os.getenv("MEFAI_LEADERBOARD_URL", f"{SITE}/bnbhack-api/leaderboard")
X402_URL = os.getenv("MEFAI_X402_URL", f"{SITE}/bnbhack-x402/products")
CARD_URL = os.getenv("MEFAI_AGENT_CARD_URL", f"{SITE}/bnbhack-api/agent-card")
LOGO_URL = os.getenv("MEFAI_LOGO_URL", f"{SITE}/mefailogo.png")

# The minted agent id, surfaced once known so the served card reflects the live
# identity (a strict ERC-8004 consumer resolves registrations[].agentId).
AGENT_ID = os.getenv("BNBHACK_AGENT_ID", "").strip() or None

# Endpoint URLs are env-overridable, so validate them at import: a malformed
# override must fail loudly here rather than ship a broken card.
_HTTPS_RE = re.compile(r"^https://[\w.~:/?#\[\]@!$&'()*+,;=%-]{3,2048}$")


def _check_url(name: str, value: str) -> str:
    if not _HTTPS_RE.match(value):
        raise ValueError(f"agent_card: {name} must be a well-formed https URL "
                         f"(got {value!r})")
    return value


for _n, _v in (("SITE", SITE), ("COCKPIT_URL", COCKPIT_URL),
               ("LEADERBOARD_URL", LEADERBOARD_URL), ("X402_URL", X402_URL),
               ("CARD_URL", CARD_URL), ("LOGO_URL", LOGO_URL)):
    _check_url(_n, _v)


def _valid_agent_id(v: Optional[str]) -> Optional[str]:
    if v and re.match(r"^[0-9]{1,32}$", v):
        return v
    return None


AGENT_NAME = "MEFAI Verifiable Autonomous Trader"
AGENT_DESCRIPTION = (
    "An autonomous BNB Chain trading agent that proves every prediction before "
    "it acts and cannot breach its own risk cap. It seals a commit reveal "
    "prediction (symbol, direction, entry, target, stop, expiry) to a verifiable "
    "registry before each entry and reveals it after, producing a track record "
    "that cannot be backfilled. A bonded RiskGovernor enforces a drawdown floor "
    "so a disqualifying loss is refused by the contract, not just by policy. "
    "Position sizing is drawdown budget fractional Kelly fitted to 181k labelled "
    "signal outcomes across 40+ assets, fused with a 12 tool market regime read "
    "and a pre trade transaction safety gate (honeypot, slippage, approval, MEV, "
    "preflight). Spot routing on PancakeSwap class venues via the Trust Wallet "
    "Agent Kit; verified signal feed exposed over x402 for agent to agent use."
)

# OASF skill + domain taxonomy (same vocabulary other ERC-8004 agents publish).
SKILLS: List[str] = [
    "financial_services/trading/strategy_execution",
    "financial_services/trading/risk_management",
    "financial_services/market_analysis/technical_analysis",
    "evaluation_and_monitoring/performance_evaluation",
    "agent_orchestration/decision_fusion",
]
DOMAINS: List[str] = [
    "financial_services/trading",
    "technology/blockchain",
    "technology/artificial_intelligence",
]


def _eip155(addr: str, chain_id: int = 56) -> str:
    return f"eip155:{chain_id}:{addr}"


def build_agent_card() -> Dict[str, Any]:
    """Assemble the ERC-8004 registration-v1 document for this agent."""
    return {
        "type": "https://eips.ethereum.org/EIPS/eip-8004#registration-v1",
        "name": AGENT_NAME,
        "description": AGENT_DESCRIPTION,
        "image": LOGO_URL,
        "services": [
            {"name": "web", "endpoint": COCKPIT_URL},
            {"name": "agentWallet", "endpoint": _eip155(AGENT_WALLET)},
            {"name": "leaderboard", "endpoint": LEADERBOARD_URL},
            {"name": "x402", "endpoint": X402_URL},
            {
                "name": "OASF",
                "endpoint": "https://github.com/agntcy/oasf/",
                "version": "0.8.0",
                "skills": SKILLS,
                "domains": DOMAINS,
            },
        ],
        "registrations": [
            {"agentId": _valid_agent_id(AGENT_ID),
             "agentRegistry": _eip155(ERC8004_REGISTRY)},
        ],
        "active": True,
        "x402Support": True,
        "supportedTrust": ["reputation", "crypto-economic"],
        # Non-standard extension fields live under a single x-* namespace so a
        # strict registration-v1 validator (additionalProperties:false) accepts
        # the card. Proof anchors: the mainnet result ledger and the verified
        # mainnet commit-reveal registry + risk governor.
        "x-mefai": {
            "track": "BNBHACK-T1",
            "proofs": {
                "resultLedger": _eip155(MAINNET_LEDGER),
                "predictionRegistry": _eip155(REGISTRY),
                "riskGovernor": _eip155(GOVERNOR),
            },
        },
    }


# Metadata key/value entries written to the identity AFTER mint (setMetadata), so
# the track record is queryable from the registry itself, not only the card URL.
def metadata_entries() -> List[Dict[str, str]]:
    return [
        {"key": "resultLedger", "value": _eip155(MAINNET_LEDGER)},
        {"key": "predictionRegistry", "value": _eip155(REGISTRY)},
        {"key": "riskGovernor", "value": _eip155(GOVERNOR)},
        {"key": "leaderboard", "value": LEADERBOARD_URL},
        {"key": "x402", "value": X402_URL},
        {"key": "track", "value": "BNBHACK-T1"},
    ]
