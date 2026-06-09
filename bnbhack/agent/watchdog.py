#!/usr/bin/env python3
"""MEFAI BNB HACK · loop watchdog + heartbeat alert.

The autonomous loop publishes a fresh `heartbeat` timestamp into its state file
on every cycle (see loop.py). systemd `Restart=always` already brings the loop
back if the process exits, but a process can also wedge while still alive (a
hung network read, a stuck await) and never advance the heartbeat. This watchdog
is a small, fully decoupled supervisor: if the watchdog itself breaks the trading
loop is untouched, and if the loop wedges the watchdog notices the stale
heartbeat and restarts it, then records the event so the operator sees it.

It reads only the public state file and shells out to `systemctl restart`; it
holds no signing secrets and makes no trade decisions.

Env:
  BNBHACK_LOOP_STATE        state file path (default matches loop.py)
  BNBHACK_WD_CHECK_SEC      poll cadence in seconds (default 30)
  BNBHACK_WD_STALE_SEC      heartbeat age that counts as wedged (default 300)
  BNBHACK_WD_GRACE_SEC      startup grace before the first verdict (default 180)
  BNBHACK_WD_COOLDOWN_SEC   minimum gap between restarts (default 300)
  BNBHACK_WD_SERVICE        unit to restart (default mefai-bnbhack-loop)
  BNBHACK_WD_ALERT_WEBHOOK  optional URL for a POST alert (no body secrets)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger("bnbhack.watchdog")

_AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = Path(os.getenv(
    "BNBHACK_LOOP_STATE", os.path.join(_AGENT_DIR, "state", "loop_state.json")))
STATUS_PATH = STATE_PATH.parent / "watchdog_status.json"

CHECK_SEC = float(os.getenv("BNBHACK_WD_CHECK_SEC", "30"))
STALE_SEC = float(os.getenv("BNBHACK_WD_STALE_SEC", "300"))
GRACE_SEC = float(os.getenv("BNBHACK_WD_GRACE_SEC", "180"))
COOLDOWN_SEC = float(os.getenv("BNBHACK_WD_COOLDOWN_SEC", "300"))
SERVICE = os.getenv("BNBHACK_WD_SERVICE", "mefai-bnbhack-loop")
ALERT_WEBHOOK = os.getenv("BNBHACK_WD_ALERT_WEBHOOK", "").strip()


def _read_heartbeat() -> "float | None":
    """Return the loop's last heartbeat epoch, or None if unreadable."""
    try:
        with open(STATE_PATH, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("state read failed: %s", exc)
        return None
    hb = data.get("heartbeat")
    return float(hb) if isinstance(hb, (int, float)) else None


def _write_status(status: dict) -> None:
    """Publish the watchdog's own view so the operator can see it is alive."""
    try:
        tmp = STATUS_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(status, f, separators=(",", ":"))
        os.replace(tmp, STATUS_PATH)
    except Exception as exc:
        logger.warning("status publish failed: %s", exc)


def _alert(event: str, detail: dict) -> None:
    """Best-effort alert: always to the journal, and to a webhook if configured.
    The payload carries only operational metadata, never any secret."""
    logger.error("ALERT %s %s", event, detail)
    if not ALERT_WEBHOOK:
        return
    try:
        body = json.dumps({"source": "bnbhack-watchdog",
                           "event": event, **detail}).encode()
        req = urllib.request.Request(
            ALERT_WEBHOOK, data=body,
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=8).read(1)
    except Exception as exc:
        logger.warning("alert webhook failed: %s", exc)


def _restart() -> bool:
    """Restart the loop unit. Returns True if systemctl reported success."""
    try:
        out = subprocess.run(["systemctl", "restart", SERVICE],
                             capture_output=True, text=True, timeout=60)
    except Exception as exc:
        logger.error("restart invocation failed: %s", exc)
        return False
    if out.returncode != 0:
        logger.error("restart returned %d: %s", out.returncode,
                     (out.stderr or "").strip())
        return False
    return True


def main() -> None:
    logging.basicConfig(
        level=os.getenv("BNBHACK_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logger.info("watchdog start service=%s stale=%.0fs check=%.0fs cooldown=%.0fs",
                SERVICE, STALE_SEC, CHECK_SEC, COOLDOWN_SEC)
    started = time.time()
    last_restart = 0.0
    restarts = 0
    while True:
        now = time.time()
        hb = _read_heartbeat()
        age = (now - hb) if hb is not None else None
        wedged = (
            # past the startup grace window, and either no heartbeat at all or a
            # heartbeat that has not advanced within the stale budget
            now - started > GRACE_SEC
            and (age is None or age > STALE_SEC)
        )
        status = {
            "ts": int(now),
            "service": SERVICE,
            "heartbeat": int(hb) if hb else None,
            "heartbeat_age_sec": int(age) if age is not None else None,
            "stale_limit_sec": int(STALE_SEC),
            "healthy": not wedged,
            "restarts": restarts,
            "last_restart_ts": int(last_restart) if last_restart else None,
        }
        _write_status(status)

        if wedged and (now - last_restart) > COOLDOWN_SEC:
            detail = {"heartbeat_age_sec": int(age) if age is not None else None,
                      "stale_limit_sec": int(STALE_SEC), "service": SERVICE}
            _alert("loop_wedged_restarting", detail)
            if _restart():
                restarts += 1
                last_restart = now
                # give the freshly started loop room to publish before re-judging
                started = now
        elif wedged:
            logger.warning("loop still stale (age=%ss) but inside restart "
                           "cooldown", int(age) if age is not None else "n/a")

        time.sleep(CHECK_SEC)


if __name__ == "__main__":
    main()
