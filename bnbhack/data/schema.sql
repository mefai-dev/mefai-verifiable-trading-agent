-- MEFAI · signal_performance schema
--
-- This is the exact shape of the labeled-outcome table the sizing engine and
-- the leaderboard read from. In production it holds the resolved record of
-- every signal the agent has emitted (each row is one signal whose later price
-- action has been measured at the 1h, 4h and 24h horizons). The production
-- database is intentionally NOT committed (see .gitignore); this schema plus
-- the sample generator in make_sample_db.py let anyone run the engine locally
-- against a clearly-synthetic book of the same shape.
--
-- Column meaning (every number the engine fits comes from these):
--   symbol            feed symbol, e.g. BTCUSDT.P
--   timeframe         the signal timeframe bucket, e.g. 1h / 4h / 1d
--   status            'completed' once the outcome at all horizons is resolved
--   result_1h/4h/24h  'win' / 'loss' label at each horizon
--   pnl_1h/4h/24h     signed realized pnl percent at each horizon (direction-aware)
--   max_drawdown_pct  worst adverse excursion percent while the signal was open
--                     (used as the empirical stop-distance hint)

CREATE TABLE IF NOT EXISTS signal_performance (
  id               INTEGER PRIMARY KEY,
  symbol           TEXT    NOT NULL,
  timeframe        TEXT    NOT NULL,
  status           TEXT    NOT NULL DEFAULT 'completed',
  created_ts       INTEGER,
  resolved_ts      INTEGER,
  result_1h        TEXT,
  result_4h        TEXT,
  result_24h       TEXT,
  pnl_1h           REAL,
  pnl_4h           REAL,
  pnl_24h          REAL,
  max_drawdown_pct REAL
);

CREATE INDEX IF NOT EXISTS ix_sigperf_bucket
  ON signal_performance (symbol, timeframe, status);
