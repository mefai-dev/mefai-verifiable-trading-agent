/* BNB HACK · the MEFAI whitepaper.
   A full technical paper · the trust problem, the design principles, the decision
   loop, the verifiable layer and how to audit every claim on BNB Chain. House
   style: middle dot as separator, no dash, no comma in visible copy. */

import { Btn, Card, Reveal, Stat, CountUp, shortAddr } from '../ui'
import { apiGet, usePoll } from '../api'
import type { Leaderboard } from '../api'
import { ADDR, AGENT_ID, AGENT_CARD_URL, COMPETITION, GITHUB_URL, TERMINAL_URL, scan, chainOf } from '../config'
import { IconExternal } from '../icons'

/* the decision loop, one card per step */
const FLOW = [
  { n: '01', tone: 'var(--c-primary)', t: 'Gather', d: 'Every MEFAI capability reports a directional reading · signals expert debate whale flow smart money accumulation derivatives risk and the full CoinMarketCap regime.' },
  { n: '02', tone: 'var(--cmc)', t: 'Fuse', d: 'Readings collapse into one conviction score each weighted by its own historical hit rate. Agreement and coverage qualify the call.' },
  { n: '03', tone: 'var(--green)', t: 'Size', d: 'A fractional Kelly engine sizes the position from 181k empirical outcomes then shrinks it to fit the remaining drawdown budget.' },
  { n: '04', tone: '#8b5cf6', t: 'Guard', d: 'A pre trade security solver runs honeypot contract slippage approval preflight and MEV checks. GO or BLOCK gates the spend.' },
  { n: '05', tone: 'var(--c-primary)', t: 'Commit', d: 'The full prediction is hashed and written to the registry before entry so the track record cannot be backfilled.' },
  { n: '06', tone: 'var(--trust)', t: 'Reveal', d: 'After the window the preimage is revealed the hash verified and the keeper records the outcome to the BSC ledger.' },
]

/* whitepaper body. Each item is a paragraph, a bullet list or a sub heading. */
type Block = string | { list: string[] } | { sub: string }
type Section = { id: string; title: string; body: Block[] }

const SECTIONS: Section[] = [
  {
    id: 'abstract', title: 'Abstract',
    body: [
      'MEFAI is an autonomous trading agent built so you never have to trust it on faith. Every prediction is sealed before the outcome is known. Every risk limit is enforced by a contract the agent cannot override. Every resolved result is written to a public ledger on BNB Chain.',
      'The track record is therefore something a stranger can audit rather than a screenshot they must believe. This paper describes the full system. It covers the decision loop that turns market data into one conviction. It covers the sizing engine that bounds risk. It covers the security gate that clears every spend. And it covers the verifiable layer that makes the record impossible to backfill.',
    ],
  },
  {
    id: 'problem', title: 'The trust problem',
    body: [
      'Most trading bots ask for blind faith. They publish a curve and a win rate. They rarely publish a way to check either. A backtest can be cherry picked. A live record can be edited after the fact. A single good week can be framed as a permanent edge.',
      'An agent that trades real money should be held to a higher standard. Its claims should be checkable by anyone. Its risk should be bounded by something stronger than a promise. MEFAI is designed around that standard from the first line.',
    ],
  },
  {
    id: 'principles', title: 'Design principles',
    body: [
      'Four rules shape every part of the system.',
      { list: [
        'Prove before you act. The agent seals each prediction as a hash before entry then reveals it after the window. The past cannot be rewritten.',
        'Risk is enforced not promised. A circuit breaker contract halts trading at the drawdown cap. The agent literally cannot blow past its own limit.',
        'No fabricated numbers. Every figure shown comes from a live endpoint or a verifiable ledger. When a feed is down the surface says so rather than inventing a value.',
        'Open and attributable. The agent carries a verifiable identity. Its signatures are public. The source is open.',
      ] },
    ],
  },
  {
    id: 'overview', title: 'System overview',
    body: [
      'The system has four layers. The intelligence layer reads the market and produces one conviction per asset. The execution layer turns an approved decision into a trade on BNB Chain. The verifiable layer anchors the prediction the risk cap and the result to public contracts. The presentation layer is this terminal where a judge can watch every layer run.',
      'Each layer is independent. The intelligence layer can be inspected without touching funds. The verifiable layer can be audited on a block explorer without trusting the terminal. This separation is what lets a stranger confirm the record end to end.',
    ],
  },
  {
    id: 'loop', title: 'The decision loop',
    body: [
      'Six steps run on every cycle. The same loop powers the live agent cockpit and the strategy skills. Each step is shown below.',
    ],
  },
  {
    id: 'fusion', title: 'Signal fusion and conviction',
    body: [
      'MEFAI does not rely on one indicator. It gathers a directional reading from many capabilities. Signals expert debate whale flow smart money accumulation derivatives risk and the full CoinMarketCap regime each cast a vote.',
      'Those votes do not count equally. Each source earns its weight from its own historical hit rate. A source that has not beaten a coin flip gets no say. A proven engine can never be diluted by an unproven one. The votes collapse into a single conviction score. Agreement across sources and the share of sources that could be read both qualify the call.',
    ],
  },
  {
    id: 'sizing', title: 'Sizing under a drawdown budget',
    body: [
      'Conviction alone is not a position. The sizing engine fits a fractional Kelly stake from the realised win rate and payoff of the relevant cell. It draws on a base of 181k labeled outcomes.',
      'The raw Kelly stake is then shrunk to fit the remaining drawdown budget. If the budget is nearly spent the position is small or zero. A leg only deploys when its empirical edge is positive. This is how the agent compounds while it physically cannot ruin itself.',
    ],
  },
  {
    id: 'security', title: 'The execution security gate',
    body: [
      'Before any spend a security solver runs six checks. It probes for a honeypot. It reads the contract. It models slippage. It inspects the approval. It runs a preflight. It checks for MEV exposure.',
      'The verdict is a simple GO or BLOCK. A blocked plan never reaches the chain. This gate is the same one a Trust Wallet user can run on any token before they sign.',
    ],
  },
  {
    id: 'verifiable', title: 'The verifiable layer',
    body: [
      'Four contracts make the record auditable. The raw address of each is one tap away on the matching explorer below.',
      { sub: 'Commit reveal prediction registry' },
      'Before entry the agent writes the keccak256 hash of the full prediction to the registry. After the window it reveals the preimage. The hash binds the call before the outcome is known so the track record cannot be backfilled.',
      { sub: 'RiskGovernor circuit breaker' },
      'The governor enforces a drawdown cap of 1400 basis points. Breach the budget and the vault halts at the cap before equity can fall through the hard floor. The agent cannot override it.',
      { sub: 'Result ledger' },
      'Thousands of resolved signals are written to a mainnet ledger. The track record becomes something a judge can verify in a block explorer rather than a claim they must accept.',
      { sub: 'ERC-8004 identity' },
      'The agent registers a verifiable identity and metadata on BSC. Its actions are provably attributable to one audited entity rather than an impersonator.',
    ],
  },
  {
    id: 'x402', title: 'The machine payable feed',
    body: [
      'The verified signal feed is served over HTTP 402. Each product binds its exact price with an EIP-3009 authorization to the token and chain charged. A calling agent hits the URL. It receives a 402. It pays the quoted amount. It re requests and gets the signed payload. Agents pay agents for proven alpha with no human in the loop.',
    ],
  },
  {
    id: 'council', title: 'The expert council',
    body: [
      'Six expert agents debate the same asset. Each speaks from its own lens. One reads the technical structure. One reads the verified signal feed. One frames the macro regime. One tracks smart money flow. One runs a machine learning ensemble. One aggregates twelve technical indicators into a composite.',
      'The table resolves to one consensus with a measured agreement level. A visitor can then question the verdict and the desk answers grounded only on the live reading. It never invents prices.',
    ],
  },
  {
    id: 'sponsors', title: 'Sponsor integrations',
    body: [
      'MEFAI is built on three sponsor stacks.',
      { list: [
        'CoinMarketCap Agent Hub. Twelve MCP tools gate global metrics derivatives narratives marketcap technicals and macro events into the regime read.',
        'Trust Wallet Agent Kit. Execution and self custody safety. The approval guard and the security solver both run from this kit.',
        'BNB Chain. The settlement and proof layer. PancakeSwap and ApolloX for execution. The registry governor ledger and identity for verification.',
      ] },
    ],
  },
  {
    id: 'data', title: 'Data and methodology',
    body: [
      'The edge is grounded on a base of 181k labeled outcomes across forty assets. Every signal the agent reads has been resolved against what the market actually did.',
      'This is what lets the sizing engine fit real win rates and payoffs rather than guesses. It is also what lets the leaderboard rank each source by realised expectancy. A win rate near fifty percent is not weak when the reward to risk ratio carries positive expectancy.',
    ],
  },
  {
    id: 'integrity', title: 'Engineering for integrity',
    body: [
      'A verifiable agent is only as honest as the engineering behind it. Several safeguards keep the numbers real and keep the agent from harming itself.',
      { sub: 'Net of cost edge gate' },
      'A signal only sizes a trade when its measured edge clears the full round trip cost. The engine reads the empirical expectancy of the exact cell then subtracts the trading cost. If the net edge does not beat its own error bar the leg is declined. The agent would rather skip a marginal trade than bleed fees on a coin flip.',
      { sub: 'Out of sample backtest' },
      'The strategy is validated on a walk forward simulation. Each cell learns its edge from a training window then is tested on a later window it never saw. Equity is compounded net of cost under the same drawdown budget the live engine uses. The report is built from the labeled outcome base and nothing is fitted on the test window.',
      { sub: 'Position lifecycle safety' },
      'Open positions are tracked in an atomic store that re checks the position cap inside the insert. Peak equity is persisted so a restart cannot reset the drawdown budget. A startup reconcile reads the wallet against the open ledger and flags any orphan without ever signing. The peak only ratchets up.',
      { sub: 'Two sided by direction' },
      'The book is direction aware. A long is expressed directly on PancakeSwap spot. A short cannot borrow on spot so a live short routes through the ApolloX perpetual venue behind an explicit execute flag. In paper mode a short is simulated with an honest label and its profit and loss is signed by direction so the engine earns in falling weeks as well as rising ones. No simulated leg is ever presented as a settled trade.',
      { sub: 'Resilient settlement' },
      'The proof writer rotates across a list of chain endpoints. If one provider stalls the writer fails over to the next that reports the right chain so commit reveal and ledger writes keep flowing through the judged window. An endpoint on the wrong chain is refused rather than trusted.',
      { sub: 'Protected interfaces' },
      'The read surfaces a judge needs stay public so anyone can curl the live agent and its proofs. The expensive market and compute endpoints are gated so off site scripts cannot drain a data quota or spin up work. The live cockpit reads remain open while the costly paths are shielded.',
    ],
  },
  {
    id: 'verify', title: 'Verify it yourself',
    body: [
      'You do not have to take any of this on faith. Four steps confirm the whole system. The contract cards follow.',
    ],
  },
  {
    id: 'roadmap', title: 'Roadmap',
    body: [
      'The full judged loop runs on BSC mainnet. The commit reveal registry, the risk governor, the equity keeper, the result ledger and the identity all live on chain 56 with thousands of resolved signals.',
      'Beyond the contest the plan is to widen the asset universe. To open the machine payable feed to more agents. The verifiable design stays the same at every step.',
    ],
  },
  {
    id: 'conclusion', title: 'Conclusion',
    body: [
      'MEFAI turns a trading record into something you can check. It seals every call before the outcome. It caps its own risk with a contract. It writes every result to a public ledger. The result is an autonomous agent that earns trust by proof rather than by claim.',
      'Open the surfaces in the navigation to watch it run. Open the contracts below to audit it yourself.',
    ],
  },
]

const jump = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })

function Body({ blocks }: { blocks: Block[] }) {
  return <>
    {blocks.map((b, i) => {
      if (typeof b === 'string') return <p key={i} style={{ fontSize: 14.5, lineHeight: 1.75, color: 'var(--c-text-2)', margin: '0 0 14px' }}>{b}</p>
      if ('sub' in b) return <h3 key={i} style={{ fontSize: 16, fontWeight: 800, margin: '20px 0 8px', color: 'var(--c-text)' }}>{b.sub}</h3>
      return <ul key={i} style={{ margin: '0 0 14px', paddingLeft: 0, listStyle: 'none', display: 'grid', gap: 10 }}>
        {b.list.map((li, j) => (
          <li key={j} style={{ display: 'flex', gap: 11, fontSize: 14, lineHeight: 1.7, color: 'var(--c-text-2)' }}>
            <span style={{ flexShrink: 0, marginTop: 9, width: 6, height: 6, borderRadius: 999, background: 'var(--c-primary)' }} />
            <span>{li}</span>
          </li>
        ))}
      </ul>
    })}
  </>
}

export default function Docs({ go }: { go: (p: string) => void }) {
  const { data: lb } = usePoll<Leaderboard>((s) => apiGet('/leaderboard?rank_by=expectancy&min_samples=30&top_n=1', s), 120_000)
  const ov = lb?.overall

  return <div style={{ maxWidth: 1080, margin: '0 auto', padding: '40px 22px 80px' }}>
    {/* title block */}
    <Reveal>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', flexWrap: 'wrap', gap: 14 }}>
        <div>
          <div className="mono" style={{ fontSize: 12, letterSpacing: 2, color: 'var(--c-primary)', textTransform: 'uppercase', marginBottom: 12 }}>{'Whitepaper · v1.0'}</div>
          <h1 style={{ fontSize: 'clamp(30px,4.4vw,50px)', fontWeight: 900, letterSpacing: '-1.2px', margin: 0, lineHeight: 1.05 }}>
            MEFAI · <span className="cp-grad-text">{'the verifiable trading agent'}</span>
          </h1>
          <p style={{ color: 'var(--c-text-2)', maxWidth: 680, marginTop: 14, lineHeight: 1.7, fontSize: 15.5 }}>
            {'An autonomous agent that proves every trade before it happens and cannot breach its own risk cap. This paper walks the full system from the decision loop to the contracts that make the whole record auditable on BNB Chain.'}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Btn variant="ghost" sm onClick={() => go('/compete')}>{'Home'}</Btn>
          <Btn variant="primary" sm href={GITHUB_URL}>{'Source'}</Btn>
        </div>
      </div>
    </Reveal>

    {/* abstract figures */}
    <Reveal delay={80}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))', gap: 12, marginTop: 30 }}>
        <Stat label="Experts in council" value={<CountUp value={6} />} tone="var(--c-primary)" sub="debate and decide" />
        <Stat label="Labeled outcomes" value={<CountUp value={181000} />} tone="var(--cmc)" sub="training base" />
        <Stat label="Resolved signals" value={ov ? <CountUp value={ov.n_resolved} /> : '-'} tone="var(--green)" sub="verified" />
        <Stat label="Chain" value="BNB Chain" tone="var(--trust)" sub="BSC mainnet" />
        {/* Stat label/sub translate centrally via ui.tsx */}
      </div>
    </Reveal>

    {/* table of contents */}
    <Reveal delay={120}>
      <Card style={{ padding: 22, marginTop: 30 }}>
        <div className="mono" style={{ fontSize: 11, letterSpacing: 1.5, color: 'var(--c-muted)', textTransform: 'uppercase', marginBottom: 14 }}>{'Contents'}</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 4 }}>
          {SECTIONS.map((s, i) => (
            <button key={s.id} onClick={() => jump(s.id)} className="cp-toc-row"
              style={{ display: 'flex', alignItems: 'baseline', gap: 10, padding: '7px 8px', background: 'none', border: 0, borderRadius: 8, cursor: 'pointer', textAlign: 'left', width: '100%' }}>
              <span className="mono" style={{ fontSize: 12, fontWeight: 800, color: 'var(--c-primary)', minWidth: 22 }}>{String(i + 1).padStart(2, '0')}</span>
              <span style={{ fontSize: 13.5, color: 'var(--c-text-2)' }}>{s.title}</span>
            </button>
          ))}
        </div>
      </Card>
    </Reveal>

    {/* sections */}
    {SECTIONS.map((s, i) => (
      <section key={s.id} id={s.id} style={{ scrollMarginTop: 84, marginTop: i === 0 ? 46 : 40 }}>
        <Reveal>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginBottom: 16 }}>
            <span className="mono" style={{ fontSize: 16, fontWeight: 900, color: 'var(--c-primary)' }}>{String(i + 1).padStart(2, '0')}</span>
            <h2 style={{ fontSize: 26, fontWeight: 900, letterSpacing: '-.5px', margin: 0 }}>{s.title}</h2>
          </div>
        </Reveal>
        <Reveal delay={60}>
          <div style={{ maxWidth: 760 }}><Body blocks={s.body} /></div>
        </Reveal>

        {/* the decision loop cards */}
        {s.id === 'loop' && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(280px,1fr))', gap: 14, marginTop: 8 }}>
            {FLOW.map((f, j) => (
              <Reveal key={f.n} delay={(j % 3) * 70}>
                <Card glow={f.tone} style={{ padding: 20, height: '100%' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
                    <span className="mono" style={{ fontSize: 26, fontWeight: 900, color: f.tone }}>{f.n}</span>
                    <span style={{ fontSize: 18, fontWeight: 800 }}>{f.t}</span>
                  </div>
                  <p style={{ fontSize: 13.5, lineHeight: 1.6, color: 'var(--c-text-2)', margin: 0 }}>{f.d}</p>
                </Card>
              </Reveal>
            ))}
          </div>
        )}

        {/* verifiable layer contracts */}
        {s.id === 'verifiable' && (
          <Reveal delay={80}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 12, marginTop: 8 }}>
              {[
                ['Prediction registry', ADDR.registry], ['Risk governor', ADDR.governor],
                ['Result ledger', ADDR.ledger], ['ERC-8004 identity', ADDR.erc8004],
              ].map(([label, addr]) => {
                const testnet = chainOf(addr) === 97
                return <a key={label} className="cp-a" href={scan(addr)} target="_blank" rel="noopener noreferrer"
                  style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 13, borderRadius: 12, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span style={{ fontSize: 11, letterSpacing: 1, color: 'var(--c-muted)', textTransform: 'uppercase' }}>{label}</span>
                    <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 700, color: testnet ? 'var(--gold)' : 'var(--green)' }}>{testnet ? 'testnet' : 'mainnet'}</span>
                  </span>
                  <span className="mono" style={{ fontSize: 13, color: 'var(--c-text)', fontWeight: 600 }}>{shortAddr(addr)}</span>
                  <span style={{ fontSize: 11, color: 'var(--c-primary)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>{testnet ? 'testnet BscScan' : 'BscScan'} <IconExternal size={12} /></span>
                </a>
              })}
            </div>
          </Reveal>
        )}

        {/* verification steps and proof links */}
        {s.id === 'verify' && (
          <Reveal delay={80}>
            <Card style={{ padding: 22, marginTop: 8 }}>
              <ol style={{ margin: 0, paddingLeft: 20, fontSize: 14, lineHeight: 1.9, color: 'var(--c-text-2)' }}>
                <li>{'Open the contracts below on the matching explorer and confirm they are verified.'}</li>
                <li>{'Watch the live agent commit a prediction hash then reveal the preimage after the window.'}</li>
                <li>{'Confirm the RiskGovernor cap sits below the hard floor so'} <span className="mono" style={{ color: 'var(--trust)' }}>canTrade()</span> {'halts first.'}</li>
                <li>{'Cross check the leaderboard expectancy against the result ledger.'}</li>
              </ol>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(230px,1fr))', gap: 12, marginTop: 18 }}>
                {[
                  ['Prediction registry', ADDR.registry], ['Risk governor', ADDR.governor],
                  ['Result ledger', ADDR.ledger], ['ERC-8004 identity', ADDR.erc8004],
                ].map(([label, addr]) => {
                  const testnet = chainOf(addr) === 97
                  return <a key={label} className="cp-a" href={scan(addr)} target="_blank" rel="noopener noreferrer"
                    style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 13, borderRadius: 12, background: 'var(--c-panel-2)', border: '1px solid var(--c-line)' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ fontSize: 11, letterSpacing: 1, color: 'var(--c-muted)', textTransform: 'uppercase' }}>{label}</span>
                      <span style={{ marginLeft: 'auto', fontSize: 10, fontWeight: 700, color: testnet ? 'var(--gold)' : 'var(--green)' }}>{testnet ? 'testnet' : 'mainnet'}</span>
                    </span>
                    <span className="mono" style={{ fontSize: 13, color: 'var(--c-text)', fontWeight: 600 }}>{shortAddr(addr)}</span>
                    <span style={{ fontSize: 11, color: 'var(--c-primary)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>{testnet ? 'testnet BscScan' : 'BscScan'} <IconExternal size={12} /></span>
                  </a>
                })}
              </div>
              <div className="mono" style={{ marginTop: 14, fontSize: 11.5, color: 'var(--c-muted)' }}>agentId {shortAddr(AGENT_ID)} · {'mainnet identity'}</div>
            </Card>
          </Reveal>
        )}
      </section>
    ))}

    {/* closing call to action */}
    <Reveal delay={80}>
      <Card glow="var(--c-primary)" style={{ padding: 28, marginTop: 48, textAlign: 'center' }}>
        <h3 style={{ fontSize: 22, fontWeight: 900, margin: 0 }}>{'Explore the system'}</h3>
        <p style={{ color: 'var(--c-text-2)', marginTop: 8, fontSize: 14 }}>{'Registered for'} {COMPETITION}. {'Open source · live terminal and the verifiable BNB Chain proofs.'}</p>
        <div className="cp-cta-btns" style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'center', marginTop: 18 }}>
          <Btn variant="primary" href={GITHUB_URL}>{'Open source'}</Btn>
          <Btn variant="primary" href={TERMINAL_URL}>{'Live terminal'}</Btn>
          <Btn variant="primary" onClick={() => go('/compete/orchestra')}>{'AI Council'}</Btn>
          <Btn variant="primary" href={AGENT_CARD_URL}>{'Agent card'}</Btn>
        </div>
      </Card>
    </Reveal>
  </div>
}
