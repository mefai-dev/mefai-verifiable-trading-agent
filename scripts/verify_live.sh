#!/usr/bin/env bash
#
# verify_live.sh · one-click reproducibility check for the verifiable chain
# ─────────────────────────────────────────────────────────────────────────
# This script proves the agent is real and live without trusting a single
# screenshot. It reads the running cockpit edge and the public BNB Chain RPCs
# and confirms, end to end:
#
#   signal fusion -> conviction -> sizing -> security gate -> commit-reveal
#   -> result ledger -> RiskGovernor cap -> leaderboard / UVII
#
# Every value comes from a live endpoint or a public chain read. Nothing here
# needs a key, a wallet or any funds: the cockpit edge injects its own data key
# server-side, and the contract checks use key-free JSON-RPC `eth_getCode`.
#
# Usage:
#   bash scripts/verify_live.sh                 # check the public deployment
#   MEFAI_API_BASE=http://127.0.0.1:8401 \
#     bash scripts/verify_live.sh               # check a local cockpit
#
# Requires: bash, curl, python3 (all standard). This script itself reads the
# live endpoints and the public RPC with stdlib only, so it needs NO extra pip
# packages. The agent's on-chain paths (bnbhack/agent/chain_writer.py) do need
# `web3` (pip install -r requirements.txt); this script reports its absence as a
# plain note below rather than failing, since it does not import web3 itself.

set -u

API_BASE="${MEFAI_API_BASE:-https://mefai.io/bnbhack-api}"
# The public edge gates every path except /loop/state and /agent-card behind a
# same-origin Referer. A browser sends this for free; curl must set it by hand.
REFERER="${MEFAI_REFERER:-https://mefai.io/compete/protocol}"

# Public, key-free BNB Chain JSON-RPC endpoints (only used to read contract code).
RPC_MAINNET="${MEFAI_RPC_MAINNET:-https://bsc-dataseed.binance.org}"

# Verified deployments (see bnbhack/contracts/DEPLOYMENTS.md).
LEDGER="0x77511fEFF4c0CA8bD5aeA8d64dC6a8dAe88C0744"   # mainnet result ledger
ERC8004="0x8004A169FB4a3325136EB29fA0ceB6D2e539a432"  # mainnet ERC-8004 identity registry
AGENT_WALLET="0xD5df700Ed5355f0c778159592a072B8773faE1CC"
REGISTRY="0xcA9499a2d20cFAa98f9Bc3b2F1386A70f51c2FEB"  # mainnet commit-reveal registry
GOVERNOR="0xFACBc0a9b5a7dd34BfD0B91e1102dF4E72b9e43f"  # mainnet RiskGovernor (maxDrawdownBps 1400)

PASS=0
FAIL=0
green() { printf '\033[32m%s\033[0m' "$1"; }
red()   { printf '\033[31m%s\033[0m' "$1"; }
dim()   { printf '\033[2m%s\033[0m' "$1"; }

ok()   { PASS=$((PASS+1)); printf '  [%s] %s\n' "$(green PASS)" "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$(dim "$2")"; }
bad()  { FAIL=$((FAIL+1)); printf '  [%s] %s\n' "$(red FAIL)" "$1"; [ -n "${2:-}" ] && printf '        %s\n' "$(dim "$2")"; }
head_() { printf '\n%s\n' "$1"; }

# api_get PATH        -> body on stdout (with Referer)
api_get() { curl -fsS --max-time 25 -H "Referer: $REFERER" "$API_BASE$1" 2>/dev/null; }
# api_post PATH JSON  -> body on stdout (with Referer)
api_post() { curl -fsS --max-time 25 -H "Referer: $REFERER" -H "Content-Type: application/json" -X POST -d "$2" "$API_BASE$1" 2>/dev/null; }

# jget '<json>' '<py-expr over d>' -> prints the expression, or nothing on error
jget() { printf '%s' "$1" | python3 -c "import sys,json
try:
    d=json.load(sys.stdin)
    print(eval(sys.argv[1]))
except Exception:
    pass" "$2" 2>/dev/null; }

# code_size RPC ADDR -> byte length of deployed bytecode (0 if none / unreachable)
code_size() {
  local body
  body=$(curl -fsS --max-time 20 -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"eth_getCode\",\"params\":[\"$2\",\"latest\"]}" \
    "$1" 2>/dev/null)
  printf '%s' "$body" | python3 -c "import sys,json
try:
    c=json.load(sys.stdin).get('result','0x')
    print(max(0,(len(c)-2)//2))
except Exception:
    print(0)" 2>/dev/null
}

printf '%s\n' "════════════════════════════════════════════════════════════════"
printf '  MEFAI · verifiable trading agent · live reproducibility check\n'
printf '  edge : %s\n' "$API_BASE"
printf '%s\n' "════════════════════════════════════════════════════════════════"

# Optional dependency note: this script needs no pip packages, but the agent's
# on-chain writer needs web3. Surface a clear message instead of a later
# traceback if a user goes on to run those paths in this same environment.
if ! python3 -c "import web3" 2>/dev/null; then
  printf '  %s python web3 is not installed (fine for this script). For the\n' "$(dim 'note:')"
  printf '        on-chain agent paths run: pip install -r requirements.txt\n'
fi

# ── 1. Autonomous loop (public, no Referer needed) ──────────────────────────
head_ "1 · Autonomous loop · GET /loop/state"
LOOP=$(curl -fsS --max-time 25 "$API_BASE/loop/state" 2>/dev/null)
if [ -z "$LOOP" ]; then
  bad "loop state unreachable" "$API_BASE/loop/state returned nothing"
else
  AVAIL=$(jget "$LOOP" "d.get('available')")
  EQ=$(jget "$LOOP" "d['state']['equity']")
  CY=$(jget "$LOOP" "d['state']['cycle']")
  GOV=$(jget "$LOOP" "d['state']['governor']['ok']")
  NPROOF=$(jget "$LOOP" "len(d['state']['proofs'])")
  MODE=$(jget "$LOOP" "d['state']['mode']")
  if [ "$AVAIL" = "True" ]; then
    ok "agent loop is live (mode=$MODE, cycle=$CY)" "equity=\$$EQ · governor.ok=$GOV · commit proofs=$NPROOF"
  else
    bad "agent loop reports unavailable" "$(jget "$LOOP" "d.get('reason')")"
  fi
fi

# ── 2. Signal fusion -> conviction ──────────────────────────────────────────
head_ "2 · Signal fusion -> conviction · POST /fusion"
FUS=$(api_post "/fusion" '{"symbol":"BNB","timeframe":"4h","include_cmc":true}')
LBL=$(jget "$FUS" "d.get('label')")
CONV=$(jget "$FUS" "round(float(d.get('conviction',0)),2)")
NS=$(jget "$FUS" "d.get('n_sources')")
if [ -n "$LBL" ] && [ -n "$NS" ]; then
  ok "fusion resolved BNB to one conviction" "label=$LBL · conviction=$CONV · sources blended=$NS"
else
  bad "fusion did not return a conviction"
fi

# ── 3. Drawdown-budgeted sizing ─────────────────────────────────────────────
head_ "3 · Drawdown-budgeted sizing · POST /sizing"
SZ=$(api_post "/sizing" '{"symbol":"BNB","timeframe":"4h","equity":1000,"conviction":0.7,"current_drawdown":0.0}')
APPR=$(jget "$SZ" "d.get('approved')")
NOT=$(jget "$SZ" "round(float(d.get('notional',0)),2)")
WCL=$(jget "$SZ" "round(float(d.get('worst_case_loss',0)),2)")
if [ -n "$APPR" ]; then
  ok "sizing fit real win-rate/payoff under the equity floor" "approved=$APPR · notional=\$$NOT · worst-case loss=\$$WCL"
else
  bad "sizing did not return a decision"
fi

# ── 4. TP/SL brackets from labeled history ─────────────────────────────────
head_ "4 · Empirical TP/SL · GET /tp-sl"
TP=$(api_get "/tp-sl?symbol=BNBUSDT&timeframe=1h&min_samples=12")
NT=$(jget "$TP" "d.get('n_total')")
REC=$(jget "$TP" "d.get('recommend')")
if [ -n "$NT" ]; then
  ok "TP/SL grid built from labeled outcomes" "samples=$NT · recommend=$REC"
else
  bad "TP/SL endpoint returned no grid"
fi

# ── 5. Pre-spend security gate ──────────────────────────────────────────────
head_ "5 · Security gate (6+ checks) · POST /security/evaluate"
SEC=$(api_post "/security/evaluate" '{"chain_id":56,"strict":true,"token":"0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c","trade_amount":50,"equity":1000,"slippage_bps":100}')
NCHK=$(jget "$SEC" "len(d.get('checks',[]))")
GO=$(jget "$SEC" "d.get('go')")
if [ -n "$NCHK" ] && [ "$NCHK" -ge 6 ] 2>/dev/null; then
  ok "security gate ran its go/no-go checks" "checks=$NCHK · verdict go=$GO (fail-closed)"
else
  bad "security gate did not return its checks"
fi

# ── 6. x402 machine-payable feed ────────────────────────────────────────────
head_ "6 · x402 machine-payable feed · GET /x402/products"
X4=$(api_get "/x402/products")
NPROD=$(jget "$X4" "len(d.get('products',[]))")
NET=$(jget "$X4" "d.get('network')")
if [ -n "$NPROD" ] && [ "$NPROD" -ge 1 ] 2>/dev/null; then
  ok "x402 product catalog is served" "network=$NET · products=$NPROD"
else
  bad "x402 catalog was empty or unreachable"
fi

# ── 7. Realized expectancy leaderboard ──────────────────────────────────────
head_ "7 · Realized expectancy · GET /leaderboard"
LB=$(api_get "/leaderboard?group_by=symbol&rank_by=expectancy&horizon=24h&min_samples=20&top_n=8")
QUAL=$(jget "$LB" "d.get('qualified')")
NENT=$(jget "$LB" "len(d.get('entries',[]))")
if [ -n "$QUAL" ]; then
  ok "leaderboard ranks sources by realized expectancy" "qualified cells=$QUAL · ranked entries=$NENT"
else
  bad "leaderboard returned no ranking"
fi

# ── 8. Unified Verifiable Intelligence Index ────────────────────────────────
head_ "8 · Unified Verifiable Intelligence Index · GET /uvii"
UV=$(api_get "/uvii?group_by=symbol&horizon=24h&min_samples=20&top_n=8")
SCORE=$(jget "$UV" "round(float(d['global_index']['score']),2)")
NRES=$(jget "$UV" "d['global_index']['n_resolved']")
INTEG=$(jget "$UV" "round(float(d['global_index']['integrity_score']),2)")
if [ -n "$SCORE" ]; then
  ok "UVII computed over the resolved record" "index=$SCORE · resolved outcomes=$NRES · integrity=$INTEG"
else
  bad "UVII did not return an index"
fi

# ── 9. Verifiable layer · contracts carry deployed code ────────────────────
head_ "9 · Verifiable layer · public chain reads (eth_getCode, no key)"
chk_code() { # name addr rpc explorer
  local sz; sz=$(code_size "$3" "$2")
  if [ "${sz:-0}" -gt 0 ] 2>/dev/null; then
    ok "$1 has deployed bytecode (${sz} bytes)" "$4/address/$2"
  else
    bad "$1 returned no code (RPC may be rate-limited; retry or open the explorer)" "$4/address/$2"
  fi
}
chk_code "Result ledger (mainnet)"        "$LEDGER"   "$RPC_MAINNET" "https://bscscan.com"
chk_code "ERC-8004 identity (mainnet)"    "$ERC8004"  "$RPC_MAINNET" "https://bscscan.com"
chk_code "Commit-reveal registry (mainnet)" "$REGISTRY" "$RPC_MAINNET" "https://bscscan.com"
chk_code "RiskGovernor (mainnet)"         "$GOVERNOR" "$RPC_MAINNET" "https://bscscan.com"
printf '        %s\n' "$(dim "agent wallet holding the identity: $AGENT_WALLET")"

# ── summary ─────────────────────────────────────────────────────────────────
printf '\n%s\n' "════════════════════════════════════════════════════════════════"
if [ "$FAIL" -eq 0 ]; then
  printf '  %s · %d checks confirmed live, 0 failed\n' "$(green 'VERIFIED')" "$PASS"
  printf '  %s\n' "$(dim 'The full decision chain and the verifiable layer are live and real.')"
  printf '%s\n' "════════════════════════════════════════════════════════════════"
  exit 0
else
  printf '  %s · %d passed, %d failed\n' "$(red 'INCOMPLETE')" "$PASS" "$FAIL"
  printf '  %s\n' "$(dim 'A failed cockpit check usually means the edge is between deploys;')"
  printf '  %s\n' "$(dim 'a failed chain check usually means the public RPC rate-limited the read.')"
  printf '  %s\n' "$(dim 'Open the explorer links above to confirm any contract by hand.')"
  printf '%s\n' "════════════════════════════════════════════════════════════════"
  exit 1
fi
