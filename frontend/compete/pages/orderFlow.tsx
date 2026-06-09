/* BNB HACK · live taker order flow + tokenized stocks context.
   Who is buying and who is selling, read from the real Binance spot tape
   (aggregated trades carry the taker side) and the resting book. This is the
   same pressure read that feeds the agent's order flow input. Crypto spot only:
   a free, real stock tape does not exist, so the stocks panel stays an honest
   context card and never fabricates a stock order flow. */

import { useState } from 'react'
import { Panel, Stat, Chip, CoinLogo, CountUp, fmtUsd } from '../ui'
import { usePoll, fetchOrderFlow } from '../api'
import type { OrderFlow } from '../api'

const TONE = 'var(--cmc)'
const SYMBOLS = ['BTC', 'ETH', 'BNB', 'SOL', 'XRP', 'DOGE']

function pressureVerdict(r: number): { label: string; tone: string } {
  if (r >= 0.57) return { label: 'Buyers in control', tone: 'var(--green)' }
  if (r >= 0.52) return { label: 'Buyers leaning', tone: 'var(--green)' }
  if (r <= 0.43) return { label: 'Sellers in control', tone: 'var(--red)' }
  if (r <= 0.48) return { label: 'Sellers leaning', tone: 'var(--red)' }
  return { label: 'Balanced tape', tone: 'var(--gold)' }
}

export function OrderFlowPanel() {
  const [sym, setSym] = useState('BTC')
  const { data } = usePoll<OrderFlow>((s) => fetchOrderFlow(`${sym}USDT`, s), 6_000, [sym])
  const ratio = data?.takerBuyRatio ?? 0.5
  const buyPct = Math.round(ratio * 100)
  const v = pressureVerdict(ratio)
  const net = data?.netDelta ?? 0
  const bookPct = Math.round((data?.bookImbalance ?? 0.5) * 100)

  return <Panel title="TAKER ORDER FLOW · WHO IS BUYING" accent="#3861FB"
    right={data ? `${data.trades} ${'prints · live'}` : 'reading the tape'}
    help={<>{'Aggregated trades carry the taker side: an aggressive market buy lifts the offer an aggressive market sell hits the bid. Summed over the last N prints this is the real buy versus sell pressure not an estimate. The book read sums the top 100 resting levels on each side. Binance spot no key no fabrication.'}</>}>
    <div style={{ display: 'flex', gap: 7, flexWrap: 'wrap', marginBottom: 16 }}>
      {SYMBOLS.map((s) => (
        <button key={s} className={`cp-pill ${sym === s ? 'on' : ''}`} onClick={() => setSym(s)}>
          <CoinLogo symbol={s} size={16} />{s}
        </button>
      ))}
    </div>

    {/* pressure split bar */}
    <div style={{ marginBottom: 6, display: 'flex', justifyContent: 'space-between', fontSize: 12, fontWeight: 700 }}>
      <span style={{ color: 'var(--green)' }}>{'Taker buys'} {buyPct}%</span>
      <Chip tone={v.tone} solid>{v.label}</Chip>
      <span style={{ color: 'var(--red)' }}>{100 - buyPct}% {'sells'}</span>
    </div>
    <div style={{ display: 'flex', height: 14, borderRadius: 999, overflow: 'hidden', background: 'var(--c-fill-2)' }}>
      <div style={{ width: `${buyPct}%`, background: 'linear-gradient(90deg, var(--green), color-mix(in srgb, var(--green) 60%, transparent))', transition: 'width .6s cubic-bezier(.2,.7,.2,1)' }} />
      <div style={{ width: `${100 - buyPct}%`, background: 'linear-gradient(90deg, color-mix(in srgb, var(--red) 60%, transparent), var(--red))', transition: 'width .6s cubic-bezier(.2,.7,.2,1)' }} />
    </div>

    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 10, marginTop: 18 }}>
      <Stat label="Taker buy volume" value={data ? fmtUsd(data.buyVol) : '-'} tone="var(--green)" sub={`${data?.buyTrades ?? 0} ${'buys'}`} />
      <Stat label="Taker sell volume" value={data ? fmtUsd(data.sellVol) : '-'} tone="var(--red)" sub={`${data?.sellTrades ?? 0} ${'sells'}`} />
      <Stat label="Net delta" value={data ? `${net >= 0 ? '+' : '-'}${fmtUsd(Math.abs(net))}` : '-'} tone={net >= 0 ? 'var(--green)' : 'var(--red)'} sub="buys minus sells" />
      <Stat label="Last price" value={data ? <CountUp value={data.lastPrice} decimals={data.lastPrice >= 100 ? 2 : 4} prefix="$" /> : '-'} tone={TONE} sub={`${sym} ${'spot'}`} />
      <Stat label="Resting bids" value={data ? fmtUsd(data.bidDepth) : '-'} tone="var(--green)" sub="top 100 levels" />
      <Stat label="Resting asks" value={data ? fmtUsd(data.askDepth) : '-'} tone="var(--red)" sub="top 100 levels" />
    </div>

    <div style={{ marginTop: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11.5, color: 'var(--c-text-2)', marginBottom: 5 }}>
        <span>{'Book imbalance · bid side'} {bookPct}%</span>
        <span className="mono" style={{ color: bookPct >= 50 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>{bookPct >= 50 ? 'bid heavy' : 'ask heavy'}</span>
      </div>
      <div style={{ display: 'flex', height: 8, borderRadius: 999, overflow: 'hidden', background: 'var(--c-fill-2)' }}>
        <div style={{ width: `${bookPct}%`, background: 'var(--green)', transition: 'width .6s' }} />
        <div style={{ width: `${100 - bookPct}%`, background: 'var(--red)', transition: 'width .6s' }} />
      </div>
    </div>

    <div style={{ fontSize: 11, color: 'var(--c-muted-2)', marginTop: 14, lineHeight: 1.55 }}>
      {'Real Binance spot tape · aggressive taker side per print · refreshed live. This exact read feeds the agent\'s order flow input alongside the CoinMarketCap derivatives view.'}
    </div>
  </Panel>
}

/* ─────────────── tokenized stocks · honest context, no fabricated tape ─────────────── */
const STOCK_FACTS: { t: string; d: string }[] = [
  { t: 'Tokenized US stocks on BNB Chain', d: 'Binance brought equities back in 2026 as bStocks tokenized US stocks issued through Ondo and settled on BNB Chain. The same chain MEFAI anchors its proofs to is now where tokenized equity lives.' },
  { t: 'Stock tracking perps', d: 'Stock tracking perpetuals let an agent take leveraged equity exposure without leaving the venue. The agent\u2019s perps adapter and risk governor already cover this shape of instrument.' },
  { t: 'One conviction engine more assets', d: 'The fusion sizing and TP/SL skills are asset agnostic. As tokenized equities mature on BNB Chain the same verifiable engine extends to them with no change to the proof flow.' },
  { t: 'Why no live stock order flow here', d: 'A real free stock order flow tape does not exist: tick and quote data for equities is a paid feed. We will not fabricate one. The order flow above is the real crypto spot tape and that integrity is the point.' },
]

export function TokenizedStocksPanel() {
  return <Panel title="TOKENIZED STOCKS ON BNB CHAIN · WHERE THIS GOES NEXT" accent="#3861FB"
    help={<>{'This is a context card not a live data feed. Binance relaunched equities in 2026 as tokenized US stocks (bStocks via Ondo) settled on BNB Chain. We show where the verifiable engine extends without inventing numbers a free data source cannot honestly provide.'}</>}>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(240px,1fr))', gap: 12 }}>
      {STOCK_FACTS.map((f) => (
        <div key={f.t} style={{ padding: 15, borderRadius: 12, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)' }}>
          <span style={{ display: 'block', width: 24, height: 3.5, borderRadius: 999, background: TONE, marginBottom: 11 }} />
          <h4 style={{ fontSize: 14.5, fontWeight: 800, margin: '0 0 7px' }}>{f.t}</h4>
          <p style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--c-text-2)', margin: 0 }}>{f.d}</p>
        </div>
      ))}
    </div>
  </Panel>
}
