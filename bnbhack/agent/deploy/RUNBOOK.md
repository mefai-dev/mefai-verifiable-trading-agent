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

## Resource bounds (7-day unattended)

- equity history is a 1440-point ring; per-cycle close lists snapshot the most
  recent 8 from SQLite, so memory does not grow with run length.
- both units carry `OOMScoreAdjust` so they are not first to be killed under
  memory pressure.
- journald auto-vacuums at its default cap; the loop logs only a few lines per
  cycle, so the journal stays small over a week.
