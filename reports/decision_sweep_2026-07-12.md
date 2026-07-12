# Decision-point sweep — 2026-07-12

Goal (Kym directive): maximise WIN RATE with increasing precision, measured as the Wilson lower bound (95%), volume reported alongside.

Population: 4676 settled real trades (2340 wins, 50.04% WR) from 2026-06-19 to 2026-07-12; draws excluded. Break-even 52.08% (92% payout). Holdout: median-timestamp split at 2026-06-22 19:16.

**Hypotheses tested: 555** (270 on all trades, 270 on the gated population, 15 pairwise). At p<0.05 expect ~27 false positives by chance — treat every candidate below as a shadow-arm or forward-test hypothesis, never as a proven edge.

Candidate bar: n >= 300, >= 50 trades in each half, WR > break-even in BOTH halves independently, and binomial p < 0.05 overall.

## TIGHTEN candidates — all settled trades

_none_


## TIGHTEN candidates — within go-forward population (flip & ADX>=40, n=582, WR 55.5%)

| rule | n | WR | Wilson-LB | h1 WR (n) | h2 WR (n) | p | trades/day |
|---|---|---|---|---|---|---|---|
| `adx >= 41.171` | 523 | 57.7% | **53.5%** | 60.6% (241) | 55.3% (282) | 0.0053 | 22 |
| `adx >= 42.102` | 465 | 57.8% | **53.3%** | 60.3% (214) | 55.8% (251) | 0.0072 | 20 |
| `dist_atr >= 3.0` | 309 | 58.3% | **52.7%** | 59.3% (140) | 57.4% (169) | 0.0170 | 13 |
| `adx >= 43.328` | 407 | 57.5% | **52.6%** | 60.0% (185) | 55.4% (222) | 0.0161 | 17 |
| `adx >= 44.56` | 350 | 57.7% | **52.5%** | 61.0% (159) | 55.0% (191) | 0.0197 | 15 |
| `gap_at_flip <= 0.224` | 350 | 57.7% | **52.5%** | 57.7% (168) | 57.7% (182) | 0.0197 | 15 |
| `bars_in_trend >= 13.0` | 420 | 57.1% | **52.4%** | 59.7% (211) | 54.5% (209) | 0.0211 | 18 |
| `plus_di >= 11.36` | 524 | 56.5% | **52.2%** | 58.4% (238) | 54.9% (286) | 0.0239 | 22 |
| `bars_in_trend >= 7.0` | 471 | 56.7% | **52.2%** | 58.4% (238) | 54.9% (233) | 0.0251 | 20 |
| `dist_atr >= 2.824` | 349 | 57.3% | **52.1%** | 59.1% (159) | 55.8% (190) | 0.0284 | 15 |
| `atr_bps <= 0.508` | 465 | 56.6% | **52.0%** | 57.3% (211) | 55.9% (254) | 0.0294 | 20 |
| `gap_expansion <= 0.364` | 408 | 56.9% | **52.0%** | 56.7% (194) | 57.0% (214) | 0.0296 | 17 |
| `minus_di >= 15.48` | 349 | 57.0% | **51.8%** | 55.5% (164) | 58.4% (185) | 0.0362 | 15 |
| `atr_bps <= 0.193` | 349 | 57.0% | **51.8%** | 61.2% (134) | 54.4% (215) | 0.0362 | 15 |
| `bb_width_bps <= 2.461` | 349 | 57.0% | **51.8%** | 62.2% (135) | 53.7% (214) | 0.0362 | 15 |


## Pairwise refinements (AND of top gated singles)

| rule | n | WR | Wilson-LB | h1 WR (n) | h2 WR (n) | p | trades/day |
|---|---|---|---|---|---|---|---|
| `adx >= 41.171 AND gap_at_flip <= 0.224` | 319 | 59.9% | **54.4%** | 61.6% (146) | 58.4% (173) | 0.0031 | 14 |
| `adx >= 41.171 AND adx >= 42.102` | 465 | 57.8% | **53.3%** | 60.3% (214) | 55.8% (251) | 0.0072 | 20 |
| `adx >= 41.171 AND adx >= 43.328` | 407 | 57.5% | **52.6%** | 60.0% (185) | 55.4% (222) | 0.0161 | 17 |
| `adx >= 42.102 AND adx >= 43.328` | 407 | 57.5% | **52.6%** | 60.0% (185) | 55.4% (222) | 0.0161 | 17 |
| `adx >= 41.171 AND adx >= 44.56` | 350 | 57.7% | **52.5%** | 61.0% (159) | 55.0% (191) | 0.0197 | 15 |
| `adx >= 42.102 AND adx >= 44.56` | 350 | 57.7% | **52.5%** | 61.0% (159) | 55.0% (191) | 0.0197 | 15 |
| `adx >= 43.328 AND adx >= 44.56` | 350 | 57.7% | **52.5%** | 61.0% (159) | 55.0% (191) | 0.0197 | 15 |


## LOOSEN candidates (volume only — no outcome data exists for skips)

| skip_reason (14d) | count |
|---|---|
| weak_trade_strength: marginal_pair_wr=45.9%/n=61 | 5256 |
| weak_trade_strength: below_required_probability=50.0%<52.1% | 4712 |
| weak_trade_strength: marginal_pair_wr=48.4%/n=62 | 3665 |
| weak_trade_strength: marginal_pair_wr=52.5%/n=202 | 3640 |
| weak_trade_strength: marginal_pair_wr=48.6%/n=35 | 3311 |
| weak_trade_strength: marginal_pair_wr=50.9%/n=175 | 3213 |
| weak_trade_strength: marginal_pair_wr=49.1%/n=55 | 3127 |
| weak_trade_strength: marginal_pair_wr=48.4%/n=64 | 3048 |
| weak_trade_strength: marginal_pair_wr=46.3%/n=67 | 2890 |
| weak_trade_strength: below_required_probability=46.7%<52.1% | 2871 |
| weak_trade_strength: marginal_pair_wr=50.7%/n=148 | 2831 |
| weak_trade_strength: marginal_pair_wr=52.8%/n=72 | 2811 |

**ADX>=40 flips blocked by `marginal_pair_wr` (14d): 10473** — the gate the 2026-07-11 deep dive flagged as inverted (trailing pair WR is non-predictive). These are the prime LOOSEN candidates, but with no shadow outcomes on record the only honest validation is a forward shadow arm.


## Post-cap-removal segment check (since 2026-07-12T08:24Z)

| segment since cap removal | n | wins |
|---|---|---|
| ADX [40,55] | 4 | 1 |
| ADX > 55 | 1 | 0 |


## Shadow-arm recommendations

TIGHTEN candidates are subsets of trades the bot already places, so they need
no shadow code — the live stream validates them for free via segment queries
on decisions.db. LOOSEN candidates need shadow arms (no outcomes exist for
skips). Recommended, in priority order:

1. **[LOOSEN, needs shadow arm] Bypass `marginal_pair_wr` for ADX>=40 flips.**
   Rule: `entry_kind == flip AND adx >= 40 AND skip_reason ~ marginal_pair_wr`.
   10,473 blocked in 14d (~750/day) vs ~22/day traded — a 30x information
   multiplier on exactly the validated-edge population, blocking on a signal
   (trailing pair WR) twice shown to be non-predictive. Highest value per unit
   of risk (shadow = zero stake).
2. **[TIGHTEN, segment-track only] `gap_at_flip <= 0.225 AND adx >= 41`** —
   best validated refinement: 59.9% WR, Wilson-LB 54.4%, h1 61.6% / h2 58.4%,
   p=0.0031, retains ~14 trades/day. Track its live segment; if LB stays above
   BE at n>=300 forward trades, pre-register a gate change.
3. **[TIGHTEN, segment-track only] `dist_atr >= 3.0`** — 58.3% WR, LB 52.7%,
   both halves >= 57%. Consistent with the exhaustion-reversal thesis (flips
   entered far from the SuperTrend band).
4. **[TIGHTEN, segment-track only] `bars_in_trend >= 13`** — 57.1% WR, LB
   52.4%. NOTE: this directly contradicts the live `stale_flip` penalty
   (-0.04 strength for > 8 bars) — same inverted-heuristic pattern as the
   removed flip_adx_exhausted penalty. Flag for Kym: the penalty suppresses a
   segment the data says is BETTER.
5. **[Monitor] higher ADX cuts (>= 42-45)** — the dose-response remains
   monotone in-sample; the running forward test plus the post-cap ADX>55
   segment will answer this without any new machinery.

Caveats: 555 hypotheses at p<0.05 imply ~27 chance survivors; the candidate
bar (both-halves + volume floor) mitigates but does not eliminate this. h1 is
June-heavy and volume has since collapsed (~36 trades/day in July) — forward
segment tracking is the only arbiter that counts. Nested ADX-cut pairs in the
pairwise table are redundant by construction (adx>=a AND adx>=b = the tighter
cut); only the gap_at_flip combination adds information.
