# PBO / CSCV (B3)

**Status: NOT COMPUTED — required inputs were not preserved.**

## Why

PBO (Probability of Backtest Overfitting) via CSCV (Combinatorially Symmetric
Cross-Validation, Bailey et al. 2017) needs the **per-period return series of
every trial strategy** from the parameter sweep, not just the winner. It splits
each trial's return series into S time segments, combinatorially assigns them to
in-sample and out-of-sample, and measures how often the in-sample-best config
underperforms the median out-of-sample.

Our parameter sweep (`src/param_sweep.py`) writes only **summary statistics per
config** (`sweep_results_*.csv`: Sharpe, win rate, P&L, etc.). It does not
persist each config's daily or per-trade return series. Without those series
CSCV cannot be assembled, so PBO is a genuine gap.

Per the directive: we did **not** re-run the sweep solely to produce PBO, since
it is not worth the time before the reviewer call (and re-running is also
currently blocked by the deauthorized data keys).

## What deflated Sharpe already covers, and what PBO would add

DSR (computed, see `dsr_sensitivity.csv`) haircuts the winner's Sharpe for the
number of trials. PBO answers a different question: the probability that the
selection process itself is overfit, i.e. that the chosen config is not
genuinely better than the field out-of-sample. They are complementary; DSR is
present, PBO is absent.

## How to add it later (one-time change, then reproducible)

1. Modify `src/param_sweep.py` to also dump each config's daily return series
   (e.g. `validation/sweep_returns/<config_key>.csv`).
2. Implement CSCV with S=8 segments (~50 lines; the CRAN `pbo` package is a
   reference implementation).
3. Report the PBO value, the performance-degradation slope, and whether the
   in-sample-optimal config shows stochastic dominance out-of-sample. Save to
   this file.
