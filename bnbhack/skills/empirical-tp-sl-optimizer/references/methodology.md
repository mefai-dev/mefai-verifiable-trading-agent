# Empirical TP/SL Optimizer · methodology

## Data model

Every labeled signal records, for a fixed ladder of take-profit and stop-loss
levels, whether each barrier was touched and HOW MANY SECONDS AFTER ENTRY. That
lets any `(TP, SL)` bracket be replayed exactly without re-simulating price.

- TP ladder: 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0 percent
- SL ladder: 0.2, 0.3, 0.5, 0.7, 0.9, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0 percent
- The grid is the full TP x SL cross product (91 cells).

## Resolving one trade under (TP=t, SL=s)

1. TP touched and SL not -> WIN, return `+t`.
2. SL touched and TP not -> LOSS, return `-s`.
3. Both touched -> compare recorded touch seconds; earlier wins. Same second is a
   TIE, charged as a loss `-s` (we cannot prove intrabar order, so we assume the
   stop filled first: pessimistic and risk-honest).
4. Neither touched -> the path stayed inside the band, so close at the realized
   horizon PnL CLAMPED into `(-s, +t)`. The clamp keeps the open return consistent
   with "no barrier hit" and stops a wide stop from importing out-of-band gains.

A trade whose horizon PnL is NULL (still open) is unresolved and dropped, counted
per cell as `n_unresolved`.

## Horizon by timeframe

When neither barrier is hit, the trade closes at the horizon PnL matched to its
timeframe: 1m-30m on the 1h column, 1h on 4h, 4h/1d on 24h.

## Cell statistics

For each cell over its resolved population: `win_rate`, `avg_win`, `avg_loss`,
`payoff = avg_win/|avg_loss|` (clamped at 50), `expectancy` (mean signed return),
`expectancy_stderr` (standard error of the mean), `expectancy_per_risk =
expectancy / sl` (R-multiple per unit risk), and the descriptive
barrier/tie/open termination counts.

All return statistics bucket by realized return SIGN over the SAME resolved
population, so win_rate, avg_win/avg_loss, payoff and expectancy reconcile.

## Recommendation rule

- `best` = max raw expectancy among cells with `n >= min_samples`. Kept for
  reference only; it drifts toward the widest stop.
- `best_per_risk` = max expectancy-per-unit-risk among eligible cells. This is the
  risk-honest pick.
- `recommend = True` only when `best_per_risk` has positive expectancy that also
  clears one standard error (a light t > 1 significance gate). A near-zero edge
  inside the noise band is never advertised.

## Live forward window

`since_ts` (unix seconds) restricts the slice to signals entered at or after that
time. Set it to the submission-lock time to measure on fresh outcomes that cannot
be backfilled, which is the only honest way to claim a live result.

## Caveats

- Selection effect: only `status='completed'` rows are read.
- Pooling (None filters) mixes directions and regimes; prefer a tight slice.
- The grid is the same data the recommendation is chosen on, so a single run is a
  hypothesis. Confirm on a disjoint `since_ts` window before trusting it.
