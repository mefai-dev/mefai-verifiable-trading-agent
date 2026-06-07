-- MEFAI · sample database schema
--
-- This is the exact shape of the two tables the agent and the strategy skills
-- read. In production they hold the live signal stream and the resolved,
-- labeled outcome of every signal. The production database is intentionally
-- NOT committed (see .gitignore); this schema plus the sample generator in
-- make_sample_db.py let anyone run the whole pipeline locally against a
-- clearly-synthetic book of the same shape.
--
-- ---------------------------------------------------------------------------
-- signals : the live signal stream the fusion layer reads.
--   symbol     feed symbol, e.g. BTCUSDT.P
--   timeframe  the scan timeframe, e.g. 5m / 1h
--   signal     'buy' or 'sell' (the most recent row per symbol/timeframe wins)
--   timestamp  unix seconds when the signal was emitted
--   price      mark price at emission
CREATE TABLE IF NOT EXISTS signals (
  id         INTEGER PRIMARY KEY,
  symbol     TEXT    NOT NULL,
  timeframe  TEXT    NOT NULL,
  signal     TEXT    NOT NULL,
  timestamp  INTEGER NOT NULL,
  price      REAL
);
CREATE INDEX IF NOT EXISTS ix_signals_latest ON signals (symbol, timeframe, id);

-- ---------------------------------------------------------------------------
-- signal_performance : one resolved, labeled outcome per signal. Every number
-- the sizing engine, the TP/SL optimizer and the leaderboard fit comes from
-- this table.
--   symbol            feed symbol, e.g. BTCUSDT.P
--   timeframe         the signal timeframe bucket, e.g. 5m / 1h / 4h / 1d
--   signal_type       'buy' / 'sell' (mapped to long / short direction)
--   status            'completed' once the outcome at all horizons is resolved
--   entry_time        unix seconds at entry (the engine orders by this)
--   entry_price       mark price at entry
--   result_1h/4h/24h  'win' / 'loss' label at each horizon
--   pnl_1h/4h/24h     signed realized pnl percent at each horizon (direction-aware)
--   max_drawdown_pct  worst adverse excursion percent while open (stop hint, MAE)
--   max_profit_pct    best favorable excursion percent while open (MFE)
--   <tp>_hit/_time    barrier touch flag (0/1) and seconds-from-entry for each
--   <sl>_hit/_time    take-profit and stop-loss level (NULL time when not hit).
--                     The TP/SL optimizer sweeps these brackets out of sample.
CREATE TABLE IF NOT EXISTS signal_performance (
  id               INTEGER PRIMARY KEY,
  symbol           TEXT    NOT NULL,
  timeframe        TEXT    NOT NULL,
  signal_type      TEXT,
  status           TEXT    NOT NULL DEFAULT 'completed',
  entry_time       INTEGER,
  entry_price      REAL,
  result_1h        TEXT,
  result_4h        TEXT,
  result_24h       TEXT,
  pnl_1h           REAL,
  pnl_4h           REAL,
  pnl_24h          REAL,
  max_drawdown_pct REAL,
  max_profit_pct   REAL,
  -- take-profit barriers (percent): 0.5 1 1.5 2 3 5 10
  tp_05_hit INTEGER, tp_05_time INTEGER,
  tp_1_hit  INTEGER, tp_1_time  INTEGER,
  tp_15_hit INTEGER, tp_15_time INTEGER,
  tp_2_hit  INTEGER, tp_2_time  INTEGER,
  tp_3_hit  INTEGER, tp_3_time  INTEGER,
  tp_5_hit  INTEGER, tp_5_time  INTEGER,
  tp_10_hit INTEGER, tp_10_time INTEGER,
  -- stop-loss barriers (percent): 0.2 0.3 0.5 0.7 0.9 1 1.5 2 3 4 5 7 10
  sl_02_hit INTEGER, sl_02_time INTEGER,
  sl_03_hit INTEGER, sl_03_time INTEGER,
  sl_05_hit INTEGER, sl_05_time INTEGER,
  sl_07_hit INTEGER, sl_07_time INTEGER,
  sl_09_hit INTEGER, sl_09_time INTEGER,
  sl_1_hit  INTEGER, sl_1_time  INTEGER,
  sl_15_hit INTEGER, sl_15_time INTEGER,
  sl_2_hit  INTEGER, sl_2_time  INTEGER,
  sl_3_hit  INTEGER, sl_3_time  INTEGER,
  sl_4_hit  INTEGER, sl_4_time  INTEGER,
  sl_5_hit  INTEGER, sl_5_time  INTEGER,
  sl_7_hit  INTEGER, sl_7_time  INTEGER,
  sl_10_hit INTEGER, sl_10_time INTEGER
);
CREATE INDEX IF NOT EXISTS ix_sigperf_bucket
  ON signal_performance (symbol, timeframe, status);
CREATE INDEX IF NOT EXISTS ix_sigperf_entry
  ON signal_performance (entry_time);
