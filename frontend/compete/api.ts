/* Shared backend client for the BNB HACK sub-site.
   All reads hit the same hardened edge the terminal cockpit uses:
     /bnbhack-api/*  → FastAPI (port 8401) over the audited pure modules
     /svc/trade-chat → grounded AI assistant (model key stays server-side)
   No secrets ever touch the client. */

import { useCallback, useEffect, useRef, useState } from 'react'

const API = '/bnbhack-api'

/* ─────────────── shared response cache ───────────────
   Every "Built with" page now renders its skills always open, so dozens of
   live panels mount at once. A short in-memory TTL cache with in-flight dedup
   keeps that from hammering the backend or tripping provider rate limits: the
   same endpoint requested by many panels resolves to one round trip, and a
   repeat within the window reuses the last good payload. Errors are never
   cached, so a transient failure retries on the next tick. Consumer abort
   signals are intentionally not threaded into the shared fetch, because one
   panel unmounting must not cancel the response other panels are waiting on;
   the hooks already guard against setting state after unmount. */
const CACHE_TTL = 60_000
type CacheEntry = { at: number; promise: Promise<unknown> }
const _cache = new Map<string, CacheEntry>()
function memo<T>(key: string, run: () => Promise<T>, ttl = CACHE_TTL): Promise<T> {
  const hit = _cache.get(key)
  if (hit && Date.now() - hit.at < ttl) return hit.promise as Promise<T>
  let promise: Promise<T>
  promise = run().catch((e) => {
    if (_cache.get(key)?.promise === promise) _cache.delete(key)
    throw e
  })
  _cache.set(key, { at: Date.now(), promise })
  return promise
}

/* Shared fetch with a hard wall-clock cap. A slow or hung edge must not leave
   an always-open panel spinning forever: after the cap the request aborts and
   the memo entry clears, so the panel shows its honest error/fallback view and
   the next poll retries. Consumer abort signals are deliberately not threaded
   in (see cache note); this only bounds the shared round trip. */
const FETCH_TIMEOUT = 15_000
async function timedFetch(input: string, init?: RequestInit, timeout = FETCH_TIMEOUT): Promise<Response> {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeout)
  try {
    return await fetch(input, { ...init, signal: ctrl.signal })
  } finally {
    clearTimeout(t)
  }
}

export async function apiGet<T>(path: string, _signal?: AbortSignal): Promise<T> {
  return memo<T>(`GET ${path}`, async () => {
    const r = await timedFetch(`${API}${path}`, { cache: 'no-store' })
    if (!r.ok) throw new Error(`${r.status}`)
    return r.json() as Promise<T>
  })
}
export async function apiPost<T>(path: string, body: unknown, _signal?: AbortSignal): Promise<T> {
  return memo<T>(`POST ${path} ${JSON.stringify(body)}`, async () => {
    const r = await timedFetch(`${API}${path}`, {
      method: 'POST', cache: 'no-store',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!r.ok) throw new Error(`${r.status}`)
    return r.json() as Promise<T>
  })
}

/* ─────────────── types ─────────────── */
export type EntityStats = {
  key: string; kind: string; n_total: number; n_resolved: number; n_pending: number
  wins: number; losses: number; win_rate: number; expectancy: number
  realized_pnl: number; avg_drawdown: number; worst_drawdown: number
  brier: number; brier_skill: number; last_entry_ts: number
}
export type Leaderboard = { group_by: string; horizon: string; rank_by: string; since_ts: number | null; qualified: number; below_threshold: number; overall: EntityStats; entries: EntityStats[] }
export type SourceContribution = { name: string; direction: number; strength: number; hit_rate: number | null; weight: number; weight_pct: number; contribution: number; available: boolean; detail?: string }
export type Uvii = { key: string; kind: string; score: number; pnl_score: number; skill_score: number; discipline_score: number; integrity_score: number; uptime_score: number; n_resolved: number }
export type UviiIndex = { group_by: string; horizon: string; global_index: Uvii; entities: Uvii[] }
export type FusionResult = { direction: number; label: string; conviction: number; net: number; agreement: number; coverage: number; n_sources: number; sources: SourceContribution[]; transcript: string[]; ts: number }
export type SizingResult = { approved: boolean; symbol: string; timeframe: string; equity: number; internal_cap: number; drawdown_room_R: number; win_rate: number; payoff: number; full_kelly: number; risk_budget_rho: number; stop_distance: number; notional: number; leverage: number; margin: number; worst_case_loss: number; reasons?: string[] }
export type CheckResult = { name: string; status: string; detail: string; data: Record<string, unknown> }
export type SecurityVerdict = { go: boolean; score: number; checks: CheckResult[]; blockers: string[]; warnings: string[]; detail: string }
export type GridCell = { tp: number; sl: number; rr: number; n: number; win_rate: number; payoff: number; expectancy: number; expectancy_per_risk: number; total_return: number }
export type RegimeDecision = { deploy: boolean; bracket: GridCell | null; risk_scale: number; alignment: number; reason: string }
export type TpSl = { symbol: string | null; timeframe: string | null; signal_type: string | null; horizon: string; n_total: number; min_samples: number; recommend: boolean; note: string; best: GridCell | null; best_per_risk: GridCell | null; regime?: RegimeDecision }
export type X402Product = { product_id: string; title: string; description: string; price_atomic: string; mime_type: string }
export type X402Catalog = { products: X402Product[]; network: string }
export type CmcGate = { tool: string; data: any }

export type LoopDecision = {
  symbol: string; action: string; direction: number; conviction: number; agreement: number; coverage: number
  entry: number; target: number; stop: number; leverage: number; win_rate: number; payoff: number
  reasons: string[]; security: Record<string, any>; proof: Record<string, any>
}
export type LoopProof = { symbol: string; signal: number; confidence: number; status: string; committed_ts: number; commit_tx: string; reveal_tx: string; prediction_id: number | null }
export type LoopPosition = {
  symbol: string; entry: number; mark: number; target: number; stop: number
  size_usd: number; qty: number; unrealized_usd: number; unrealized_pct: number
  tp1_done?: boolean; rungs_filled?: number; rungs_total?: number; realized_partial_usd?: number
  opened_ts: number; open_tx: string
}
export type LoopClose = { symbol: string; reason: string; exit: number; pnl_usd: number; pnl_pct: number; closed_ts: number }
export type LoopPositions = { open: LoopPosition[]; open_count: number; unrealized_usd: number; realized_usd: number; closes: LoopClose[] }
export type LoopCycleClose = { symbol: string; reason: string; exit_price: number; pnl_usd: number; pnl_pct: number; executed: boolean; partial?: boolean; detail: string }
export type LoopState = {
  ts: number; heartbeat: number; cycle: number; uptime_s: number; mode: string
  agent: { name: string; wallet: string; chain_address: string; agent_id: string }
  equity: number; peak_equity: number; drawdown: number; jury_cap: number; internal_cap: number
  governor: { ok: boolean; dd_bps: number; detail: string; record: string }
  config: { watchlist: string[]; timeframe: string; interval: number; conviction_min: number; include_cmc: boolean; max_positions?: number; ladder_rungs?: number; regime_filter?: boolean; max_hold_sec?: number; roundtrip_cost_pct?: number }
  reveals: { symbol: string; detail: string; tx: string }[]
  decisions: LoopDecision[]
  proofs: LoopProof[]
  positions?: LoopPositions
  cycle_closes?: LoopCycleClose[]
}
export type LoopEnvelope = { available: boolean; state?: LoopState; reason?: string }

/* ─────────────── recent verified signals (entered trades + outcomes) ─────────────── */
export type ResolvedSignal = {
  symbol: string; timeframe: string; direction: string
  entry_price: number; entry_time: number
  pnl: number; result: string; drawdown: number; max_profit: number; horizon: string
}
export type RecentSignals = { horizon: string; count: number; signals: ResolvedSignal[] }
export async function fetchRecentSignals(limit = 24, symbols?: string[], signal?: AbortSignal): Promise<RecentSignals> {
  const q = new URLSearchParams({ limit: String(limit) })
  if (symbols && symbols.length) q.set('symbols', symbols.join(','))
  return apiGet<RecentSignals>(`/signals/recent?${q.toString()}`, signal)
}

/* ─────────────── multi AI expert debate (mefai-engine, no auth) ─────────────── */
export type DebateKeyData = {
  entry?: number; target?: number; stoploss?: number
  risk_reward?: number; composite_score?: number; [k: string]: unknown
}
export type DebateExpert = {
  name: string; id: string; signal: string; score?: number; confidence: number
  reasons?: string[]; paragraph?: string; summary?: string
  key_data?: DebateKeyData; [k: string]: unknown
}
export type DebateResponse = { to: string; stance: string; text: string }
export type DebateExchange = { expert: string; signal: string; responses: DebateResponse[] }
export type DebateConsensus = {
  signal: string; confidence: number; agreement_pct?: number
  summary?: string; risk_note?: string; learning_note?: string
  action?: string; reason?: string
  agreeing_experts?: string[]; expert_weights?: Record<string, number>
  entry?: number; price_target?: number; stop_loss?: number
}
export type DebateLearning = {
  accuracy: number; total_predictions: number; correct: number
  partial?: number; wrong: number; streak: number; weight: number
}
export type DebateTrackRecord = { total: number; correct: number; accuracy: number }
export type DebateResult = {
  symbol?: string; price?: number; experts: DebateExpert[]; consensus: DebateConsensus
  debate?: DebateExchange[]; track_record?: DebateTrackRecord
  learning?: Record<string, DebateLearning>
  data_feeds?: Record<string, unknown>; weights?: Record<string, number>
}
/* symbols the engine supports use the BTC/USDT slash form */
export const DEBATE_SYMBOLS = ['BTC/USDT', 'ETH/USDT', 'BNB/USDT', 'SOL/USDT', 'XRP/USDT', 'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'LINK/USDT', 'ARB/USDT']

export async function fetchDebate(symbol: string, _signal?: AbortSignal): Promise<DebateResult> {
  return memo<DebateResult>(`debate ${symbol}`, async () => {
    const r = await timedFetch(`/svc/api/skills/expert-debate?symbol=${encodeURIComponent(symbol)}`, { cache: 'no-store' }, 45_000)
    if (!r.ok) throw new Error(`${r.status}`)
    return r.json() as Promise<DebateResult>
  }, 120_000)
}

/* ─────────────── CoinMarketCap live surface (same hardened edge the main
   terminal uses; CoinGecko global + the audited CMC intelligence skill) ─────────────── */
export type CmcGlobal = {
  total_market_cap_usd: number; total_volume_usd: number
  btc_dominance: number; eth_dominance: number
  active_cryptocurrencies: number; markets: number; mcap_change_24h: number
}
export async function fetchCmcGlobal(_signal?: AbortSignal): Promise<CmcGlobal> {
  return memo<CmcGlobal>('cmc-global', async () => {
    const r = await timedFetch('/superbsc/api/coingecko/global', { cache: 'no-store' })
    if (!r.ok) throw new Error(`${r.status}`)
    const d = (await r.json())?.data ?? {}
    const cap = d.market_cap_percentage ?? {}
    return {
      total_market_cap_usd: d.total_market_cap?.usd ?? 0,
      total_volume_usd: d.total_volume?.usd ?? 0,
      btc_dominance: cap.btc ?? 0,
      eth_dominance: cap.eth ?? 0,
      active_cryptocurrencies: d.active_cryptocurrencies ?? 0,
      markets: d.markets ?? 0,
      mcap_change_24h: d.market_cap_change_percentage_24h_usd ?? 0,
    }
  })
}

export type CmcToken = {
  cmc_id: number; rank: number; symbol: string; name: string; slug: string
  price: number; change_1h: number; change_24h: number; change_7d: number
  volume_24h: number; market_cap: number; contract_chain: string | null
  mefai_score: number; verdict: string; verdict_color: string; verdict_reason: string
  has_anomaly: boolean; mefai_audited: boolean; ecosystems: string[]
}
export type CmcSummary = {
  total_tokens: number; avg_score: number; strong_buy: number; buy: number
  neutral: number; weak: number; avoid: number; anomaly_count: number
  chain_distribution: Record<string, number>
}
export type CmcIntel = { tokens: CmcToken[]; total: number; returned: number; market_summary: CmcSummary; cache_age_seconds: number }
export async function fetchCmcIntel(limit = 60, _signal?: AbortSignal): Promise<CmcIntel> {
  return memo<CmcIntel>(`cmc-intel ${limit}`, async () => {
    const r = await timedFetch(`/svc/api/skills/cmc/intelligence?limit=${limit}`, { cache: 'no-store' })
    if (!r.ok) throw new Error(`${r.status}`)
    return r.json() as Promise<CmcIntel>
  })
}

/* ─────────────── live taker order flow (real Binance spot tape, key-free) ───────────────
   Aggregated trades carry `m` = isBuyerMaker: m=false is an aggressive taker BUY,
   m=true is an aggressive taker SELL. Summed over the window this is the real
   buy versus sell pressure, not an estimate. The depth read gives the resting
   book imbalance. Both are crypto spot only; we never fabricate a stock tape. */
type RawAggTrade = { p: string; q: string; m: boolean; T: number }
type RawDepth = { bids: [string, string][]; asks: [string, string][] }
export type OrderFlow = {
  symbol: string
  buyVol: number; sellVol: number; buyTrades: number; sellTrades: number
  takerBuyRatio: number; netDelta: number; lastPrice: number; trades: number
  bidDepth: number; askDepth: number; bookImbalance: number
}

export async function fetchOrderFlow(symbol: string, signal?: AbortSignal): Promise<OrderFlow> {
  const sym = symbol.toUpperCase()
  const [aggRes, depthRes] = await Promise.all([
    fetch(`/superbsc/api/spot/aggTrades?symbol=${sym}&limit=1000`, { cache: 'no-store', signal }),
    fetch(`/superbsc/api/spot/depth?symbol=${sym}&limit=100`, { cache: 'no-store', signal }),
  ])
  if (!aggRes.ok) throw new Error(`${aggRes.status}`)
  const agg = (await aggRes.json()) as RawAggTrade[]
  let buyVol = 0, sellVol = 0, buyTrades = 0, sellTrades = 0, lastPrice = 0
  for (const t of agg) {
    const p = Number(t.p), q = Number(t.q)
    if (!Number.isFinite(p) || !Number.isFinite(q)) continue
    lastPrice = p
    const notional = p * q
    if (t.m) { sellVol += notional; sellTrades++ } else { buyVol += notional; buyTrades++ }
  }
  const tot = buyVol + sellVol
  let bidDepth = 0, askDepth = 0
  if (depthRes.ok) {
    const d = (await depthRes.json()) as RawDepth
    for (const [p, q] of d.bids ?? []) bidDepth += Number(p) * Number(q)
    for (const [p, q] of d.asks ?? []) askDepth += Number(p) * Number(q)
  }
  const book = bidDepth + askDepth
  return {
    symbol: sym, buyVol, sellVol, buyTrades, sellTrades,
    takerBuyRatio: tot > 0 ? buyVol / tot : 0.5,
    netDelta: buyVol - sellVol, lastPrice, trades: agg.length,
    bidDepth, askDepth, bookImbalance: book > 0 ? bidDepth / book : 0.5,
  }
}

/* ─────────────── wallet approval guard (live, Moralis-backed allowance scan) ───────────────
   MEFAI's own wallet safety check, the same scan the terminal runs before the
   agent ever asks Trust Wallet to sign. It reads every live ERC-20 allowance a
   wallet has granted on BSC, flags unlimited approvals and possible-spam tokens,
   and ranks each by the USD it puts at risk. Real chain data, no fabrication.
   The compete site is read only; revoke runs in the full terminal with the
   visitor's own connected Trust Wallet. */
type RawApproval = {
  token: string; tokenSymbol: string | null; possibleSpam: boolean
  currentBalanceFormatted: string; usdAtRisk: number | null
  spender: string; spenderLabel: string | null; spenderEntity: string | null
  allowance: string; allowanceFormatted: string
}
type RawApprovals = { chain: string; address: string; count: number; approvals: RawApproval[]; error?: string }

export type ApprovalSeverity = 'high' | 'medium' | 'low'
export type WalletApproval = {
  token: string; symbol: string; spender: string; spenderLabel: string | null
  allowanceFormatted: string; unlimited: boolean; possibleSpam: boolean
  usdAtRisk: number | null; severity: ApprovalSeverity
}
export type WalletGuard = {
  address: string; scanned: number; risky: number; unlimited: number
  spam: number; usdAtRisk: number; approvals: WalletApproval[]
}

const MAX_UINT256 = (1n << 256n) - 1n
const UNLIMITED_FLOOR = MAX_UINT256 - (1n << 32n)
const SEV_RANK: Record<ApprovalSeverity, number> = { high: 3, medium: 2, low: 1 }

export async function fetchWalletGuard(address: string, signal?: AbortSignal): Promise<WalletGuard> {
  const addr = address.trim()
  const r = await fetch(`/mefai-proxy/wallet-approvals?address=${addr}&chain=bsc`, { cache: 'no-store', signal })
  if (!r.ok) throw new Error(`${r.status}`)
  const body = (await r.json()) as RawApprovals
  if (body.error) throw new Error(body.error)
  const out: WalletApproval[] = []
  let risky = 0, unlimitedN = 0, spamN = 0, usdAtRisk = 0
  for (const a of body.approvals ?? []) {
    let allowanceBig = 0n
    try { allowanceBig = BigInt(a.allowance || '0') } catch { allowanceBig = 0n }
    if (allowanceBig === 0n) continue
    const unlimited = allowanceBig >= UNLIMITED_FLOOR
    const usd = typeof a.usdAtRisk === 'number' && Number.isFinite(a.usdAtRisk) ? a.usdAtRisk : null
    let severity: ApprovalSeverity = 'low'
    if (a.possibleSpam) severity = 'high'
    else if (unlimited && usd !== null && usd > 0) severity = 'high'
    else if (unlimited) severity = 'medium'
    if (severity === 'high') risky++
    if (unlimited) unlimitedN++
    if (a.possibleSpam) spamN++
    if (usd !== null) usdAtRisk += usd
    out.push({
      token: a.token, symbol: a.tokenSymbol || 'TOKEN', spender: a.spender,
      spenderLabel: a.spenderEntity || a.spenderLabel || null,
      allowanceFormatted: unlimited ? 'UNLIMITED' : `${a.allowanceFormatted ?? ''}`,
      unlimited, possibleSpam: a.possibleSpam, usdAtRisk: usd, severity,
    })
  }
  out.sort((x, y) => SEV_RANK[y.severity] - SEV_RANK[x.severity] || (y.usdAtRisk ?? 0) - (x.usdAtRisk ?? 0))
  return { address: addr, scanned: out.length, risky, unlimited: unlimitedN, spam: spamN, usdAtRisk, approvals: out }
}

/* ─────────────── Arena (shared roster of competing MEFAI agents) ─────────────── */
export type ArenaAgent = {
  agent_id: string; name: string; agent_type: string
  total_predictions: number; correct: number; wrong: number; pending: number
  accuracy_pct: number; streak: number; total_pnl_pct: number; rank: number
}
export type ArenaPrediction = {
  agent_name: string; agent_type: string; wallet_address?: string
  symbol: string; signal: string; confidence: number
  entry_price: number; target_price: number; stop_loss: number
  timestamp: string; expires_at: number; outcome: string
  tx_hash: string; bscscan_url: string; copied_from?: string | null
}
export async function fetchArenaLeaderboard(_signal?: AbortSignal): Promise<{ agents: ArenaAgent[] }> {
  return memo<{ agents: ArenaAgent[] }>('arena-leaderboard', async () => {
    const r = await timedFetch('/svc/api/skills/arena/leaderboard', { cache: 'no-store' })
    if (!r.ok) throw new Error(`${r.status}`)
    return r.json() as Promise<{ agents: ArenaAgent[] }>
  })
}
export async function fetchArenaPredictions(status = 'pending', limit = 12, _signal?: AbortSignal): Promise<{ predictions: ArenaPrediction[] }> {
  return memo<{ predictions: ArenaPrediction[] }>(`arena-pred ${status} ${limit}`, async () => {
    const r = await timedFetch(`/svc/api/skills/arena/predictions?status=${encodeURIComponent(status)}&limit=${limit}`, { cache: 'no-store' })
    if (!r.ok) throw new Error(`${r.status}`)
    return r.json() as Promise<{ predictions: ArenaPrediction[] }>
  })
}

/* ─────────────── agent decision pipeline (nginx injects the data key) ───────────────
   Every endpoint here is the same audited read the live agent runs. The browser
   never sees a key: the /bnbhack-api edge injects it server-side. Real output only,
   never fabricated; callers fall back to an honest schema when a feed is down. */
export async function fetchFusion(symbol: string, timeframe = '4h', signal?: AbortSignal): Promise<FusionResult> {
  return apiPost<FusionResult>('/fusion', { symbol, timeframe, include_cmc: true }, signal)
}
export type SizingArgs = {
  symbol: string; timeframe?: string; equity: number; conviction?: number
  current_drawdown?: number; stop_distance?: number; horizon?: string
}
export async function fetchSizing(args: SizingArgs, signal?: AbortSignal): Promise<SizingResult> {
  return apiPost<SizingResult>('/sizing', { timeframe: '4h', ...args }, signal)
}
export async function fetchTpSl(symbol: string, timeframe = '1h', minSamples = 12, signal?: AbortSignal): Promise<TpSl> {
  // Backend symbol pattern is ^[A-Za-z0-9._]{1,20}$ (no slash), e.g. BNB/USDT -> BNBUSDT.
  const sym = symbol.replace(/\//g, '')
  return apiGet<TpSl>(`/tp-sl?symbol=${encodeURIComponent(sym)}&timeframe=${timeframe}&min_samples=${minSamples}`, signal)
}
export async function fetchLeaderboard(groupBy = 'symbol', rankBy = 'expectancy', horizon = '24h', topN = 8, signal?: AbortSignal): Promise<Leaderboard> {
  return apiGet<Leaderboard>(`/leaderboard?group_by=${groupBy}&rank_by=${rankBy}&horizon=${horizon}&min_samples=20&top_n=${topN}`, signal)
}
export async function fetchUvii(groupBy = 'symbol', horizon = '24h', topN = 8, signal?: AbortSignal): Promise<UviiIndex> {
  return apiGet<UviiIndex>(`/uvii?group_by=${groupBy}&horizon=${horizon}&min_samples=20&top_n=${topN}`, signal)
}
export async function fetchLoopState(signal?: AbortSignal): Promise<LoopEnvelope> {
  return apiGet<LoopEnvelope>('/loop/state', signal)
}
export type SecurityPlan = {
  token?: string; router?: string; chain_id?: number; slippage_bps?: number
  approval_amount?: number; trade_amount?: number; equity?: number; equity_floor?: number; strict?: boolean
}
export async function fetchSecurity(plan: SecurityPlan, signal?: AbortSignal): Promise<SecurityVerdict> {
  return apiPost<SecurityVerdict>('/security/evaluate', { chain_id: 56, strict: true, ...plan }, signal)
}
export async function fetchX402Products(signal?: AbortSignal): Promise<X402Catalog> {
  return apiGet<X402Catalog>('/x402/products', signal)
}
/* allowlisted CMC MCP gate passthrough: global-metrics, derivatives, narratives,
   marketcap-ta, macro-events. Returns { tool, data } with the raw hub payload. */
export async function fetchCmcGate(tool: string, signal?: AbortSignal): Promise<CmcGate> {
  return apiGet<CmcGate>(`/cmc/${encodeURIComponent(tool)}`, signal)
}

/* ─────────────── polling hook ─────────────── */
export function usePoll<T>(fn: (signal: AbortSignal) => Promise<T>, intervalMs: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(true)
  const fnRef = useRef(fn)
  fnRef.current = fn
  useEffect(() => {
    let alive = true
    const ctrl = new AbortController()
    setLoading(true); setData(null); setError(false)
    const tick = async () => {
      try {
        const d = await fnRef.current(ctrl.signal)
        if (alive) { setData(d); setError(false); setLoading(false) }
      } catch {
        if (alive) { setError(true); setLoading(false) }
      }
    }
    tick()
    const t = setInterval(tick, intervalMs)
    return () => { alive = false; ctrl.abort(); clearInterval(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, loading }
}

/* ─────────────── AI "why this trade" (SSE stream) ─────────────── */
export async function streamTradeChat(
  messages: { role: 'user' | 'assistant'; content: string }[],
  onText: (full: string) => void,
  signal?: AbortSignal,
): Promise<string> {
  const resp = await fetch('/svc/trade-chat', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }), signal, cache: 'no-store',
  })
  if (!resp.ok || !resp.body) throw new Error(resp.status === 429 ? 'busy' : 'unavailable')
  const reader = resp.body.getReader()
  const dec = new TextDecoder()
  let buf = '', acc = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let nl
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (!line.startsWith('data:')) continue
      const p = line.slice(5).trim()
      if (!p) continue
      try { const o = JSON.parse(p); if (o.type === 'text' && o.text) { acc += o.text; onText(acc) } } catch { /* partial */ }
    }
  }
  return acc
}
