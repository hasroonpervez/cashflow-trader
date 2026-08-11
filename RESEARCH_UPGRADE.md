# Research Upgrade: Validated Signals (Aug 2026)

Surgical, additive upgrade from the Aug 2026 research program (backtest rounds 1-3
+ 20-agent adversarially-verified quant lab). **No existing file was modified.**
New files: `modules/validated_signals.py`, `tests/test_validated_signals.py` (12 tests, all passing).

## What the research proved (provenance for every rule)

| Finding | Evidence | Consequence in code |
|---|---|---|
| TSLA ORB-30 long is the champion day signal | +16.6%/4mo, PF 1.89, positive both halves (86 sessions, 5m) | `orb30_signal()` |
| SMA20-reclaim swing edge is real and replicates | n=413/18mo/34 syms, +125.9bps/trade, 95% CI [+0.8,+271.8] fully above 0 | `swing_pullback_signal()` |
| Pink Diamond does NOT predict drops | 1,022 fires → +1.8% avg fwd 5d; pink exits cut winners everywhere | `PINK_DIAMOND_STATUS`, `pink_diamond_caution()` (tighten, never sell) |
| Blue confluence as entry = regime beta | t=2.98 full sample, NEGATIVE second half, all 12 configs | `blue_diamond_rank()` (watchlist ranker, not trigger) |
| Gap-chasing loses | all configs negative; gaps fade | gap-skip built into `orb30_signal()` |
| Compression ≠ direction | ~44% upward resolution both timeframes | compression intentionally NOT exposed as a signal |
| Old `TA.vwap` invalid intraday | cumulative from first bar, never resets | `session_vwap()` (session-anchored) |
| Full-sample t-stats lie | the Blue Diamond v2 autopsy | `promotion_gate()`, CI>0 + split-half + n≥100 |

## The Diamonds v3 mental model
- **Blue Diamond = a state, not a trade.** `blue_diamond_rank()` scores trend health
  0-6 and reports `setup_state`. When you see `in_pullback` on a high score, you
  KNOW what to wait for: the reclaim close (`swing_pullback_signal` fires it).
- **Pink Diamond = tighten, never sell.** `pink_diamond_caution()` returns
  caution 0/1/2 with an explicit new stop level. Winners are left to run; the
  raised stop harvests the gain if the reversal actually comes.

## Integration (suggested, minimal)
```python
from modules.validated_signals import (
    blue_diamond_rank, pink_diamond_caution,
    swing_pullback_signal, orb30_signal, promotion_gate,
)
# 1. Watchlist tab: rank names by blue_diamond_rank(df_daily)["blue_score"]
# 2. Signal tab: show swing_pullback_signal(df_daily) when it fires
# 3. Position view: show pink_diamond_caution(df_daily)["action"] for holdings
# 4. Any new strategy idea: require promotion_gate(returns)["pass"] before trusting it
```
Existing `detect_diamonds` UI can stay for continuity, recommend relabeling pink
as "caution flag" per `PINK_DIAMOND_STATUS`.

## Verified against real data before delivery
- ORB fired 4 of the last 10 real TSLA sessions (expected ~half).
- Blue ranker on the real 34-name universe (2026-08-04 close): ANET/BMNR/SEPN
  scored 5/6 `in_pullback`: a live, actionable watchlist.
- `promotion_gate` reproduced the round-3 swing result exactly on the real 413
  trades: pass=True, CI [0.8, 271.8], halves +189.9/+62.2 bps.

Research reports live in the vault: Trading-App/Notes (2026-08-04/05 entries).
