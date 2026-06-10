# BNB HACK Agent · Operations Runbook

Two systemd units run the autonomous agent unattended:

| Unit | Role | Recovery |
| --- | --- | --- |
| `mefai-bnbhack-loop` | the decision/execute loop | `Restart=always`, `RestartSec=10`, backoff `StartLimitBurst=10/300s` |
| `mefai-bnbhack-watchdog` | hang detector for the loop | reads the loop heartbeat, restarts the loop if it wedges |

`Restart=always` covers a process that exits. The watchdog covers the case a
process stays alive but stops advancing (hung await / stuck socket): it reads
the heartbeat the loop publishes every cycle and restarts the loop once the
heartbeat is stale past the budget, with a cooldown so it never storms.

## Install / enable

```
cp deploy/mefai-bnbhack-loop.service /etc/systemd/system/
cp deploy/mefai-bnbhack-watchdog.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now mefai-bnbhack-loop
systemctl enable --now mefai-bnbhack-watchdog
```

## Health checks

```
systemctl is-active mefai-bnbhack-loop mefai-bnbhack-watchdog
cat state/loop_state.json | python3 -c "import json,sys,time;d=json.load(sys.stdin);print('hb age', round(time.time()-d['heartbeat']), 'cycle', d['cycle'], 'mode', d['mode'])"
cat state/watchdog_status.json     # healthy:true, restarts count, last_restart_ts
journalctl -u mefai-bnbhack-loop -n 50 --no-pager
```

## Restart / resume guarantees

A `systemctl restart mefai-bnbhack-loop` resumes cleanly:

- `peak_equity.json` and `start_equity.json` are reloaded on boot, so the
  drawdown reference survives a restart (the cycle counter resets, peak does not).
- the open ledger lives in SQLite, not memory, so open legs persist.
- on startup the loop runs a one-shot reconcile against the live wallet to
  surface any leg that closed while it was down before the first new decision.
- all state writes are atomic (`tempfile` + `os.replace`), so a crash mid-write
  never leaves a torn file.

To restart the loop without disturbing the watchdog: `systemctl restart mefai-bnbhack-loop`.
To stop everything: `systemctl stop mefai-bnbhack-watchdog mefai-bnbhack-loop`
(stop the watchdog first so it does not restart the loop you just stopped).

## Watchdog tunables (env, all optional)

| Var | Default | Meaning |
| --- | --- | --- |
| `BNBHACK_WD_CHECK_SEC` | 30 | poll interval |
| `BNBHACK_WD_STALE_SEC` | 300 | heartbeat age that counts as wedged |
| `BNBHACK_WD_GRACE_SEC` | 180 | startup grace before the first check |
| `BNBHACK_WD_COOLDOWN_SEC` | 300 | min gap between forced restarts |
| `BNBHACK_WD_ALERT_WEBHOOK` | (unset) | optional POST target for wedge alerts (no secrets in payload) |

## Live-trade broadcast (transparency feed, all optional)

The loop can announce every trade leg it takes (and every close) to a Telegram
chat / channel, so the judged window is observable in real time. It is fully
opt-in: with no bot token configured it is a silent no-op. It signs nothing,
moves no funds, and every message carries only public trade facts (symbol, side,
size, prices, PnL) plus the public BscScan tx link. Set these in the loop's
secrets EnvironmentFile (`secrets/agent-secrets.env` in the service template):

| Var | Default | Meaning |
| --- | --- | --- |
| `BNBHACK_TG_BOT_TOKEN` | (falls back to `TELEGRAM_BOT_TOKEN`) | bot token for the broadcast |
| `BNBHACK_TG_CHAT_ID` | (unset) | target chat / channel id (broadcast is off until set) |
| `BNBHACK_TG_PAPER` | 1 | also announce paper legs (labelled PAPER); 0 = live executed legs only |

## Two-sided execution · live SHORT leg (perp venue, all optional)

A LONG is expressed directly on PancakeSwap spot (`bsc_exec`). A SHORT has no
spot borrow leg, so it routes through the audited USDT-M futures adapter (the
`autotrade/exchange_adapter.py` package deployed next to the agent, Binance
first) via `perp_exec`. This is fully opt-in and **OFF by default**: with the
flag off (or no venue keys) a LIVE short stays an honest no-go and a PAPER short
is simulated · the loop signs nothing, holds no key and moves no funds. ApolloX
is deliberately not wired as a raw leveraged-DEX signer (twak exposes no perp
primitive); the audited CEX futures adapter is the supported, gated venue.

When enabled, the perp venue's account equity (margin + open uPnL) is folded
into mark-to-market equity, so the short leg's risk is VISIBLE to the
RiskGovernor drawdown killswitch (never reported only on the BSC wallet). All
existing gates (drawdown-budget sizer, RiskGovernor halt, the per-leg pre-trade
gate) still apply. Set these in the loop's secrets EnvironmentFile:

| Var | Default | Meaning |
| --- | --- | --- |
| `BNBHACK_EXECUTE_PERP` | (off) | `1` to sign live shorts on the perp venue (requires keys) |
| `BNBHACK_PERP_VENUE` | binance | futures venue (`binance` / `aster`) |
| `BNBHACK_PERP_KEY` | (unset) | venue API key (read here, never logged) |
| `BNBHACK_PERP_SECRET` | (unset) | venue API secret (read here, never logged) |
| `BNBHACK_PERP_QUOTE` | USDT | margin/settlement quote (`USDT` / `USDC`) |
| `BNBHACK_PERP_LEVERAGE` | 1 | leverage pin (1x = notional matches the sizer, no amplification) |
| `BNBHACK_PERP_MARGIN_MODE` | isolated | `isolated` / `cross` |
| `BNBHACK_PERP_TESTNET` | (off) | `1` to use the venue sandbox (Binance only) |

Note: requires `BNBHACK_EXECUTE_TRADES=1` (the live spot flag) for the live
short path to engage; with spot live but perps off, shorts stay paper-only.

## Daily trade floor (qualification guard, live mode only)

If no trade has executed by a late-day UTC hour, the loop places one minimal
clamped trade so the agent never misses a per-day activity rule. The forced leg
relaxes ONLY the selectivity gates (conviction floor, regime stand-aside); the
drawdown-budget sizer, the RiskGovernor halt and the security gate still apply,
so it never trades through a risk stop. Gated on `BNBHACK_EXECUTE_TRADES`: in
paper mode the floor never fires.

| Var | Default | Meaning |
| --- | --- | --- |
| `BNBHACK_DAILY_TRADE_FLOOR` | 1 | enable the floor (live mode only) |
| `BNBHACK_DAILY_MIN_TRADES` | 1 | executed trades required per UTC day |
| `BNBHACK_DAILY_FLOOR_HOUR_UTC` | 21 | hour after which the floor may fire |
| `BNBHACK_DAILY_FLOOR_USD` | 8 | notional clamp for a forced leg |

## Resource bounds (7-day unattended)

- equity history is a 1440-point ring; per-cycle close lists snapshot the most
  recent 8 from SQLite, so memory does not grow with run length.
- both units carry `OOMScoreAdjust` so they are not first to be killed under
  memory pressure.
- journald auto-vacuums at its default cap; the loop logs only a few lines per
  cycle, so the journal stays small over a week.
