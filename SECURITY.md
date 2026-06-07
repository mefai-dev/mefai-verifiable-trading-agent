# Security

MEFAI is a trading agent that can move money, so it is built to fail safe. The
default posture is to do nothing irreversible: the agent decides, gates, sizes,
plans and publishes its state but **signs nothing** until an operator explicitly
opts in. Everything below describes how that posture is enforced in code, what
the threat model is, and how to report a problem.

This document covers the public showcase repository. It does not describe the
private production infrastructure (the live signal pipeline, the labeled-outcome
book, operator hosts), which is out of scope and not shipped here.

---

## Safe by default · two flags, two keys

Going live is gated behind **two independent environment flags**, and each still
needs its own key to be present before anything is signed:

| Flag | Unlocks | Without it |
| --- | --- | --- |
| `BNBHACK_EXECUTE_TRADES` | spot swaps on a DEX | trades are simulated in a paper book |
| `BNBHACK_EXECUTE_CHAIN` | verifiable chain writes (commit-reveal + equity anchor) | proofs are computed and logged, never sent |

Both default to `0`. With neither flag set the full pipeline runs end to end and
touches no private key. A flag set without its matching key (`BNBHACK_AGENT_PRIVATE_KEY`,
`BNBHACK_ORACLE_PRIVATE_KEY`) still does not sign: the missing key is treated as
"stay in paper mode," not as an error to push through.

---

## The pre-spend security gate

Every intended spend is run through `tx_security_solver.py` and must return a
`go=True` verdict before `bsc_exec.py` is allowed to sign. The gate folds many
independent checks into one go / block decision. The six core security checks are:

1. **Honeypot / token risk** · buy and sell tax, sell-disabled and self-destruct flags.
2. **Contract scan** · verified source, upgradeable-proxy detection, critical-risk patterns, round-trip loss.
3. **Slippage guard** · derived from the `expected_out` vs `min_out` quote, hard-capped (default 3.0%).
4. **Approval hygiene** · rejects infinite/unlimited approvals and any approval below the exact spend.
5. **Preflight simulation** · an `eth_call` that must not revert; revert payloads returned as call output are caught too.
6. **MEV exposure** · loose slippage that invites sandwiching is flagged.

Three more guards layer on top: **address validation** (every address must match
`0x` + 40 hex and is rejected if it is the zero address), **gas sanity** (a
non-positive or absurd gas price is blocked; a normal cheap BSC price is never
blocked on a ratio alone), and the **RiskGovernor equity-floor authorization**
(no new trade is authorized once equity drops below the bonded floor).

### Design principles enforced in the gate

- **Fail closed.** In strict mode (the default), a security-critical check
  (token risk, contract scan, preflight) that cannot reach its data source while
  a trade is actually intended is treated as a BLOCK, not a silent pass. An
  outage of the analysis stack can never authorize an unvetted trade. A spend
  with no valid token to scan is blocked. A plan with trade intent that no
  security-critical check could verdict is blocked as insufficiently vetted.
- **One FAIL blocks.** A single failing check sets `go=False`. WARN lowers the
  advisory score but does not block. SKIP means the input was absent.
- **No raising.** Every check returns a result and never throws; an adapter that
  cannot answer degrades to SKIP rather than crashing the gate.
- **The score never implies safety for a blocked trade.** A blocked verdict is
  always capped well below any "safe" threshold.

---

## Network boundary · no SSRF surface

The agent talks to exactly two kinds of host and nothing a trade plan can choose:

- A **local trusted proxy** on loopback (`127.0.0.1`) that fronts the analysis
  endpoints. An operator may override the host; a trade plan never can.
- A **fixed allowlist of public BSC JSON-RPC endpoints**. Every RPC call
  re-checks the target host against the allowlist before the request is made, so
  the client cannot be pointed at an attacker-chosen target.

Responses are bounded: a body over 512 KB is refused, calldata over the cap is
not forwarded to the node, and a revert payload is decoded only up to a fixed
length with its claimed length clamped to what is actually present, so a hostile
payload cannot drive a large allocation. Amounts are parsed defensively (int,
decimal string, or `0x` hex) and a value that cannot be parsed makes the
dependent check SKIP rather than guess.

---

## Verifiable layer · circuit breaker and tamper-evidence

- **RiskGovernor** (`contracts/src/RiskGovernor.sol`) is a drawdown kill-switch.
  It records equity against a high-water mark, halts and blocks all trading the
  moment drawdown breaches the bonded budget, enforces keeper-only equity writes
  and owner-only resume, and supports a global pause. Once halted, `canTrade`
  returns false until an explicit resume.
- **CommitRevealPredictionRegistry** (`contracts/src/CommitRevealPredictionRegistry.sol`)
  seals each prediction as a keccak256 commitment before the outcome is known and
  reveals it after, with a deadline that must precede the outcome window. Only the
  committing wallet may commit and reveal; only the oracle may grade an outcome,
  and never twice. This makes the record impossible to backfill.

Both contracts ship with a test suite (`contracts/test/bnbhack.test.ts`, 15
cases) that runs entirely on a local network with no key, no RPC and no funds.

---

## API edge

The cockpit API (`bnbhack/api/backend.py`) treats every request as hostile at the
boundary:

- **API-key auth** on all data endpoints via a constant-time comparison
  (`hmac.compare_digest`); a missing or wrong key returns `401`. Only liveness
  (`/health`), the public agent card and the read-only live `/loop/state`
  snapshot are unauthenticated, so the judged window can be rendered without a key.
- **Per-IP sliding-window rate limit** (`429` on breach). The socket peer is
  authoritative for the limiter; an `X-Forwarded-For` header is honored only from
  a configured trusted-proxy set, so the limiter cannot be dodged by spoofing it.
- **Input bounds and choice validation** on query parameters before any work runs.

In production the key is injected server-side by the reverse proxy, so it is
never present in the browser or in client-shipped code.

---

## Secret hygiene

- No private keys, mnemonics or API keys are committed. `.gitignore` excludes
  `.env`, `*.env*` (except `.env.example`), `*.key`, `*.pem`, `*.keystore`,
  `*.secret` and `*secrets*`.
- `.env.example` ships with **every secret field blank**; it documents shape only.
- The labeled-outcome production database is private and gitignored; the repo
  ships the schema and a clearly-synthetic sample generator instead, so no
  committed number is one a reviewer cannot reproduce from source.
- Public verification anchors (contract addresses, the agent's public wallet, the
  ERC-8004 id) are intentionally shareable and are listed in
  `bnbhack/contracts/DEPLOYMENTS.md`.

---

## Reporting a vulnerability

If you find a security issue, please report it privately rather than opening a
public issue. Open a GitHub Security Advisory on this repository
(Security tab · Report a vulnerability) with:

- a description of the issue and its impact,
- the steps or proof of concept to reproduce it,
- the affected file(s) or endpoint(s).

Please do not exploit the issue beyond what is needed to demonstrate it, and do
not access, modify or exfiltrate data that is not yours. We will acknowledge a
valid report and work on a fix before any public disclosure.

---

## Scope

In scope: the code in this repository · the agent loop, the sizing and security
engines, the API edge, and the Solidity in `bnbhack/contracts/`.

Out of scope: third-party services and RPC providers, the private production
infrastructure, denial-of-service against public RPC endpoints, and any finding
that requires a compromised operator host or a leaked operator key (the trust
model already assumes those are protected off-repo).
