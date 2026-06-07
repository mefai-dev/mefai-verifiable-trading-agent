#!/usr/bin/env python3
"""Meta-Strategy Composer · end-to-end pipeline + portfolio-budget verification.

Chains selection -> bracket -> regime gate -> sizing -> portfolio budget into one
plan, then verifies the account-level invariant: the sum of deployed legs'
worst-case losses stays inside DD_BUDGET_K * R * equity. Read-only and
deterministic. `compose_plan` is the reusable entry point; running the file as a
script also writes output/report.json.
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

AGENT = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "agent"))
sys.path.insert(0, AGENT)

from leaderboard import build_leaderboard  # noqa: E402
from tp_sl_optimizer import optimize, regime_overlay  # noqa: E402
from sizing import (  # noqa: E402
    DD_BUDGET_K, INTERNAL_CAP_RATIO, SizingInput, size_position,
)

EPS = 1e-6


def compose_plan(
    equity: float = 10_000.0,
    current_drawdown: float = 0.04,
    jury_cap: float = 0.20,
    regime_direction: int = 1,
    regime_strength: float = 0.7,
    timeframe: str = "1h",
    signal_type: str = "buy",
    top_n: int = 5,
    min_samples: int = 50,
    since_ts: Optional[int] = None,
) -> dict:
    """Run the full pipeline and return a sized, gated, budgeted plan."""
    internal_cap = INTERNAL_CAP_RATIO * jury_cap
    R = max(0.0, internal_cap - current_drawdown)
    account_budget = DD_BUDGET_K * R * equity

    # 1 · SELECT
    lb = build_leaderboard(group_by="symbol", rank_by="expectancy",
                           min_samples=min_samples, horizon="24h",
                           since_ts=since_ts)
    selected = [e.key for e in lb.entries[:top_n]]

    # 2 + 3 · BRACKET then GATE (only legs the regime deploys survive)
    staged = []
    for symbol in selected:
        res = optimize(symbol=symbol, timeframe=timeframe,
                       signal_type=signal_type, since_ts=since_ts)
        if not res.recommend or res.best_per_risk is None:
            staged.append({"symbol": symbol, "deploy": False,
                           "reason": "no significant edge"})
            continue
        gate = regime_overlay(res, regime_direction=regime_direction,
                              regime_strength=regime_strength)
        if not gate.deploy or gate.bracket is None:
            staged.append({"symbol": symbol, "deploy": False,
                           "reason": gate.reason})
            continue
        staged.append({"symbol": symbol, "deploy": True, "gate": gate,
                       "bracket": gate.bracket, "reason": gate.reason})

    deployed = [s for s in staged if s["deploy"]]
    k = len(deployed)
    # 4 · SIZE · split the account budget equally across deployed legs so the
    # SUM of worst-case losses stays inside the account ceiling.
    per_leg_equity = equity / k if k else 0.0

    legs: List[dict] = []
    portfolio_worst = 0.0
    for s in staged:
        if not s["deploy"]:
            legs.append({"symbol": s["symbol"], "deploy": False,
                         "reason": s["reason"], "worst_case_loss": 0.0})
            continue
        br = s["bracket"]
        gate = s["gate"]
        stop = br.sl / 100.0  # bracket SL percent -> fraction
        sized = size_position(SizingInput(
            symbol=s["symbol"], timeframe=timeframe, equity=per_leg_equity,
            current_drawdown=current_drawdown, jury_cap=jury_cap,
            stop_distance=stop, regime_gate=gate.risk_scale, conviction=1.0,
        ))
        portfolio_worst += sized.worst_case_loss
        legs.append({
            "symbol": s["symbol"], "deploy": True,
            "tp": br.tp, "sl": br.sl, "regime_scale": gate.risk_scale,
            "leverage": round(sized.leverage, 3),
            "notional": round(sized.notional, 2),
            "worst_case_loss": round(sized.worst_case_loss, 4),
            "approved": sized.approved, "reason": s["reason"],
        })

    return {
        "skill": "meta-strategy-composer",
        "equity": equity, "current_drawdown": current_drawdown,
        "jury_cap": jury_cap, "internal_cap": round(internal_cap, 4),
        "drawdown_room_R": round(R, 5),
        "regime": {"direction": regime_direction, "strength": regime_strength},
        "selected": selected, "deployed_legs": k,
        "budget_ceiling": round(account_budget, 4),
        "portfolio_worst_case_loss": round(portfolio_worst, 4),
        "within_budget": portfolio_worst <= account_budget + EPS,
        "legs": legs,
    }


# Sweep a range of account states so the budget invariants are exercised across
# equity, drawdown, regime and leg-count, not at a single point.
SCENARIOS = [
    dict(equity=10_000.0, current_drawdown=0.04, jury_cap=0.20,
         regime_direction=1, regime_strength=0.7, top_n=5,
         timeframe="15m", signal_type="buy"),
    dict(equity=50_000.0, current_drawdown=0.0, jury_cap=0.20,
         regime_direction=1, regime_strength=1.0, top_n=8,
         timeframe="15m", signal_type="buy"),
    dict(equity=5_000.0, current_drawdown=0.10, jury_cap=0.20,
         regime_direction=0, regime_strength=0.0, top_n=6,
         timeframe="15m", signal_type="buy"),
    dict(equity=20_000.0, current_drawdown=0.12, jury_cap=0.20,
         regime_direction=-1, regime_strength=0.5, top_n=4,
         timeframe="15m", signal_type="buy"),
]


def run() -> dict:
    scenarios = []
    all_within = True
    all_legs_ok = True
    any_deployed = False
    for sc in SCENARIOS:
        plan = compose_plan(**sc)
        internal_cap = INTERNAL_CAP_RATIO * sc["jury_cap"]
        R = max(0.0, internal_cap - sc["current_drawdown"])
        k = plan["deployed_legs"]
        # Each deployed leg sizes against equity/k, so its worst-case loss must
        # stay within DD_BUDGET_K * R * (equity/k); the sum of these is the
        # account ceiling. Checking the per-leg bound is the real defense.
        per_leg_budget = DD_BUDGET_K * R * (sc["equity"] / k) if k else 0.0
        legs_within = all(
            leg["worst_case_loss"] <= per_leg_budget + EPS
            for leg in plan["legs"] if leg["deploy"]
        )
        all_within = all_within and plan["within_budget"]
        all_legs_ok = all_legs_ok and legs_within
        if k > 0:
            any_deployed = True
        scenarios.append({
            "inputs": sc, "deployed_legs": k,
            "budget_ceiling": plan["budget_ceiling"],
            "portfolio_worst_case_loss": plan["portfolio_worst_case_loss"],
            "within_budget": plan["within_budget"],
            "per_leg_budget": round(per_leg_budget, 4),
            "legs_within_per_leg_budget": legs_within,
        })

    representative = compose_plan(**SCENARIOS[0])
    return {
        "skill": "meta-strategy-composer",
        "n_scenarios": len(scenarios), "scenarios": scenarios,
        # A run that deploys nothing in every scenario proves nothing, so it is
        # not a pass even though the (empty) budget sum trivially holds.
        "any_scenario_deployed": any_deployed,
        "portfolio_budget_held": all_within,
        "per_leg_budget_held": all_legs_ok,
        "all_checks_ok": all_within and all_legs_ok and any_deployed,
        "representative_plan": representative,
    }


def main() -> int:
    report = run()
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "output")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w") as fh:
        json.dump(report, fh, indent=2)

    rp = report["representative_plan"]
    print(f"scenarios checked     : {report['n_scenarios']}")
    print(f"any scenario deployed : {report['any_scenario_deployed']}")
    print(f"portfolio budget held : {report['portfolio_budget_held']}")
    print(f"per-leg budget held   : {report['per_leg_budget_held']}")
    print(f"representative selected: {rp['selected']}")
    print(f"representative deployed: {rp['deployed_legs']} of {len(rp['legs'])}")
    for leg in rp["legs"]:
        if leg["deploy"]:
            print(f"  {leg['symbol']}: TP{leg['tp']}/SL{leg['sl']} "
                  f"lev {leg['leverage']}x worst {leg['worst_case_loss']}")
        else:
            print(f"  {leg['symbol']}: skip ({leg['reason']})")
    print("PASS" if report["all_checks_ok"] else "FAIL")
    return 0 if report["all_checks_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
