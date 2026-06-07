/* BNB HACK · what we built on BNB Chain.
   Everything verifiable lives on BNB Chain. The result ledger and identity are on
   BSC mainnet; the live judged commit reveal registry and risk governor run on BSC
   testnet for the contest window. Each card shows its chain and the raw address is
   one tap away on the matching explorer. */

import { useState } from 'react'
import { Btn, Chip, Panel, Reveal } from '../ui'
import { apiGet, usePoll } from '../api'
import type { X402Catalog } from '../api'
import { ADDR, GITHUB_URL, scan, chainLabel } from '../config'
import { SponsorHero, FeatureGrid, SponsorSectionHead, PlainContract } from './sponsorKit'
import { SkillCatalog } from './skillCatalog'
import { OmniSignalPanel } from './omniSignal'
import { IconExternal } from '../icons'

const TONE = 'var(--gold)'

/* plain-language explanations of each contract, so a non-developer gets it */
const CONTRACTS: { label: string; plain: string; addr: string }[] = [
  { label: 'Prediction notebook', plain: 'A public notebook where the agent writes down every call (sealed) before the outcome is known then reveals it after. Nobody can edit the past.', addr: ADDR.registry },
  { label: 'Automatic circuit breaker', plain: 'A contract that halts trading the instant losses approach the limit. The agent literally cannot blow past its own risk cap.', addr: ADDR.governor },
  { label: 'Verified scoreboard', plain: 'The result ledger that records thousands of real outcomes to the BSC ledger so the track record is auditable not just a screenshot.', addr: ADDR.ledger },
  { label: 'Agent identity card', plain: 'An ERC-8004 identity proving the agent you talk to is the real audited MEFAI agent and not an impersonator.', addr: ADDR.erc8004 },
  { label: 'Agent wallet', plain: 'The wallet the agent signs its commit and reveal proofs with. Every signature is public and traceable.', addr: ADDR.agent },
  { label: 'Oracle keeper', plain: 'The keeper that records equity to the chain so the circuit breaker always knows the true balance.', addr: ADDR.keeper },
]

export default function BnbChain({ go }: { go: (p: string) => void }) {
  return <div>
    <SponsorHero
      tone={TONE} eyebrow="Built on BNB Chain" go={go}
      title={<>Proof not promises<br />all on <span style={{ color: TONE }}>BNB Chain</span></>}
      blurb="The whole point of MEFAI is that you do not have to trust us. Every prediction every risk limit and every result is anchored to BNB Chain where you can audit it yourself. The result ledger and identity are on BSC mainnet; the live judged commit reveal registry and risk governor run on BSC testnet. Below the contracts in plain language first."
    />

    <SponsorSectionHead tone={TONE} eyebrow="Our flagship capability" title={<>MEFAI Omni Signal · the whole decision chain <span style={{ color: TONE }}>live</span></>}
      sub="The capability we built for this hackathon. Pick an asset and the full pipeline runs live: the CoinMarketCap hub and our signal engine fuse into one conviction the AI council debates it the TP/SL bracket is fit from labeled history the position is sized against the drawdown budget and the Trust Wallet safety gate clears it ending in one verdict." />
    <Reveal>
      <div style={{ maxWidth: 1180, margin: '0 auto', padding: '0 22px 8px' }}>
        <OmniSignalPanel />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow="What we built" title="A trading agent anchored to BNB Chain" />
    <FeatureGrid tone={TONE} items={[
      { t: 'Commit reveal predictions', d: 'Each trade is sealed as a keccak hash on BSC before entry and revealed after so the record is impossible to backfill or fake.' },
      { t: 'Ledger anchored circuit breaker', d: 'A RiskGovernor contract enforces a 1400 bps drawdown cap. Breach the budget and the vault halts at the cap before equity can fall through the hard floor.' },
      { t: 'Verified result ledger', d: 'Thousands of resolved signals are written to a mainnet ledger turning the track record into something a judge can verify in a block explorer.' },
      { t: 'PancakeSwap execution', d: 'The agent executes spot and perps through PancakeSwap and ApolloX on BNB Chain with every spend quoted first and capped to a maximum.' },
      { t: 'ERC-8004 identity', d: 'The agent registers a verifiable identity and metadata on BSC so its actions are provably attributable to one audited entity.' },
      { t: 'x402 machine payable feed', d: 'The verified signal feed is served over HTTP 402 with EIP-3009 payment binding the exact BSC token charged. Agents pay agents for proven alpha.' },
    ]} />

    <SponsorSectionHead tone={TONE} eyebrow="Audit it yourself" title="The contracts in plain words" />
    <section style={{ maxWidth: 1180, margin: '0 auto', padding: '20px 22px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(290px,1fr))', gap: 14 }}>
        {CONTRACTS.map((c, i) => (
          <Reveal key={c.label} delay={(i % 3) * 70}>
            <PlainContract tone={TONE} label={c.label} plain={c.plain} addr={c.addr} scanUrl={scan(c.addr)} chain={chainLabel(c.addr)} />
          </Reveal>
        ))}
      </div>
    </section>

    <SponsorSectionHead tone={TONE} eyebrow="Agents pay agents" title="The machine payable feed live" />
    <Reveal>
      <div style={{ maxWidth: 1040, margin: '0 auto', padding: '0 22px' }}>
        <LiveFeed />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow="See it running" title="Our live BSC intelligence embedded"
      sub="The same BNB Chain tools the agent reads from embedded live from the production terminal. Pick a tool watch it pull live chain data then open it full screen." />
    <Reveal>
      <div style={{ maxWidth: 1320, margin: '0 auto', padding: '0 22px' }}>
        <EmbedViewer />
      </div>
    </Reveal>

    <SponsorSectionHead tone={TONE} eyebrow="The full surface" title="Every MEFAI capability catalogued"
      sub="What we deployed to BNB Chain one card each: the verifiable contracts and the engines that drive them. Every card here is live in the agent today. Tap any card for what it does and what it connects to across the stack." />
    <SkillCatalog group="bnb" tone={TONE} />

    <div style={{ textAlign: 'center', padding: '34px 22px 70px', display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap' }}>
      <Btn variant="amber" onClick={() => go('/compete/agent')}>Watch the live agent</Btn>
      <Btn variant="ghost" href={GITHUB_URL}>Read the source</Btn>
    </div>
  </div>
}

/* ─────────────── live BSC terminal pages, embedded ─────────────── */
const EMBEDS: { label: string; path: string; note: string }[] = [
  { label: 'Address Profiler', path: '/bnb-address-profiler', note: 'Score any BSC wallet: identity net worth behavior counterparty graph and a risk radar all from live chain history.' },
  { label: 'Contract Reader', path: '/bnb-contract-reader', note: 'Read any BSC contract: identity proxy target live state snapshot honeypot probe and a risk radar.' },
  { label: 'Token Holders', path: '/bnb-holder-dist', note: 'Concentration map for any BSC token: supply tiers Lorenz curve top holders and 24h flow.' },
  { label: 'DEX Activity', path: '/bnb-dex-activity', note: 'The live BSC swap firehose top pairs fresh pair radar and whale DEX flow.' },
  { label: 'Network Pulse', path: '/bnb-network-info', note: 'BSC network health: gas ring block health multi endpoint RPC probes and chain TVL.' },
  { label: 'Smart Money Lens', path: '/smart-money', note: 'The proven BSC trader leaderboard with cohorts first movers and Sharpe based skill scoring.' },
]

function EmbedViewer() {
  const [active, setActive] = useState(0)
  const cur = EMBEDS[active]
  return <Panel title="LIVE BSC INTELLIGENCE EMBEDDED" accent={TONE} right="mefai.io terminal">
    <p style={{ fontSize: 12.5, color: 'var(--c-muted)', margin: '0 0 14px', lineHeight: 1.55 }}>
      Each tool below reads BSC live as you watch it. Pick one then open it full screen to drive it yourself.
    </p>
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 14, ['--c-primary' as string]: 'var(--gold)', ['--c-primary-soft' as string]: 'color-mix(in srgb, var(--gold) 14%, transparent)' }}>
      {EMBEDS.map((e, i) => (
        <button key={e.path} onClick={() => setActive(i)} aria-pressed={i === active} className={`cp-pill ${i === active ? 'on' : ''}`}>{e.label}</button>
      ))}
    </div>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
      <span style={{ fontSize: 12.5, color: 'var(--c-text-2)', lineHeight: 1.55, flex: '1 1 320px' }}>{cur.note}</span>
      <a href={cur.path} target="_blank" rel="noopener noreferrer" className="mono" style={{ fontSize: 12, fontWeight: 700, color: 'var(--gold)', textDecoration: 'none', whiteSpace: 'nowrap' }}>
        Open full screen <IconExternal size={12} />
      </a>
    </div>
    <div style={{ borderRadius: 12, overflow: 'hidden', border: '1px solid var(--c-line)', background: 'var(--c-panel-2)', height: 'min(72vh, 760px)' }}>
      <iframe key={cur.path} src={`${cur.path}?mobile=preview`} title={cur.label} loading="lazy" allow="clipboard-write" style={{ width: '100%', height: '100%', border: 0, display: 'block' }} />
    </div>
  </Panel>
}

/* ─────────────── live x402 machine payable feed ─────────────── */
function LiveFeed() {
  const { data, error, loading } = usePoll<X402Catalog>((s) => apiGet('/x402/products', s), 120_000)
  const products = data?.products ?? []
  return <Panel title="X402 VERIFIED SIGNAL FEED" accent={TONE} right={data ? data.network : error ? 'offline' : 'loading'}>
    <p style={{ fontSize: 12.5, color: 'var(--c-muted)', margin: '0 0 14px', lineHeight: 1.55 }}>
      The verified signal feed is served over HTTP 402. Each product binds its exact BSC price via EIP-3009 so another agent
      can pay for proven alpha with one settlement. This catalog is read live from the running service.
    </p>
    {products.length === 0
      ? <div style={{ fontSize: 13, color: 'var(--c-muted)', padding: '14px 0' }}>{error ? 'The feed is unreachable right now.' : loading ? <>Reading the catalog<span className="cp-ellipsis" /></> : 'No products are published right now.'}</div>
      : <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 12 }}>
        {products.map((p) => (
          <div key={p.product_id} style={{ padding: 16, borderRadius: 12, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)', display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
              <span style={{ fontSize: 14.5, fontWeight: 800, color: 'var(--c-text)' }}>{p.title}</span>
              <Chip tone="var(--gold)">HTTP 402</Chip>
            </div>
            <span style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--c-text-2)' }}>{p.description}</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 'auto', paddingTop: 6, flexWrap: 'wrap' }}>
              <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: 'var(--gold)' }}>{p.price_atomic} atomic</span>
              <span style={{ fontSize: 11, color: 'var(--c-muted)' }}>{p.mime_type}</span>
            </div>
          </div>
        ))}
      </div>}
  </Panel>
}
