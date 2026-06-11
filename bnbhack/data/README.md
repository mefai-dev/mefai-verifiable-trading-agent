# Data

The agent fits its win rates, payoffs and stop hints from a table of **labeled
outcomes** called `signal_performance`. Every row is one signal whose later
price action has been measured at the 1h, 4h and 24h horizons and stamped
`win` or `loss`. The sizing engine and the leaderboard read only this table.

## The production book is not committed

The real book (195k labeled outcomes across forty assets) is live account data.
It is excluded by `.gitignore` and is **not** in this repository. That keeps the
record honest: nobody can hand-edit a committed file and call it a track record.

## Run the engine locally against a synthetic sample

`make_sample_db.py` writes a **clearly synthetic** database of the exact same
shape into `data/signal.db`, so the loop, the `/sizing` endpoint and the
backtests all run without the production book:

```bash
python3 bnbhack/data/make_sample_db.py            # default 400 rows per bucket
python3 bnbhack/data/make_sample_db.py --rows 800 # larger sample
```

The sample is seeded and reproducible. It ships **twenty illustrative symbols**
of the same shape as the private book's forty assets, which is enough to exercise
every engine path and reproduce every figure in this repo. Its numbers are drawn
from fixed per-symbol parameters purely to exercise the engine. **They are
illustrative only and must never be read as results.**

## Schema

See [`schema.sql`](schema.sql) for the full table definition and a description
of every column the engine reads.
