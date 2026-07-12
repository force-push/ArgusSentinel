# Forward test: marginal_wr shadow arm — pre-registration

**Registered:** 2026-07-13 (before any shadow data existed; arm enabled same day)
**Approved by:** Kym (2026-07-13, "Please do 1 and 2")
**Basis:** `reports/decision_sweep_2026-07-12.md` LOOSEN #1;
`reports/entry_edges_2026-07-11.md` (marginal_pair_wr gate flagged as inverted).
**Feature spec:** `FEATURE_SHADOW_ARMS.md`.

## Hypothesis

ADX>=40 flip entries blocked ONLY by the `marginal_pair_wr` strength penalty
win at a rate above the 52.08% break-even (92% payout) — i.e. the gate blocks
winners. Basis: trailing pair WR is twice-demonstrated non-predictive
(regresses to mean), while the blocked population is exactly the validated
edge population (flip & ADX>=40 ran 56.8%, n=544). ~750 such skips/day were
observed in the 14d pre-registration window.

## Intervention

`SHADOWS_ENABLED=true` + `SHADOW_MARGINAL_WR_ENABLED=true` (2026-07-13).
Shadow trades (`shadow_kind="marginal_wr"`, demo balance, no effect on
strategy stats/risk/martingale) placed for skips where the ONLY qualitative
penalty is marginal_pair_wr (`StrategyManagerV2._mwr_shadow_eligible`),
capped at `SHADOW_MARGINAL_WR_HOURLY_CAP=20/h` (≤480/day). **No live trading
policy changed by this arm**: real entries still respect the marginal_pair_wr
penalty while the arm collects counterfactuals.

## Pre-registered decision rules

Draws excluded from WR. Population: settled `shadow_kind='marginal_wr'` rows.

| Condition | Verdict |
|---|---|
| n >= 150 settled and WR < 50% | KILL early — gate is protective, keep it |
| n >= 300, WR >= 54%, binomial p < 0.05 vs 52.08% | PASS — propose retiring marginal_pair_wr for gated flips (as its own pre-registered LIVE test) |
| n >= 300, WR < 52.1% | FAIL — gate stays, deep-dive suspicion retired |
| n >= 300, 52.1% <= WR < 54% or p >= 0.05 | INCONCLUSIVE — Kym decides |

Expected volume: cap-bound, likely 100-400 settled/day depending on how often
eligible skips cluster → evaluation size reached in ~1-3 days of runtime.

## Monitoring

Query (also used by heartbeat checks):
`sqlite3 data/decisions.db "SELECT COUNT(*), SUM(outcome='win'), SUM(outcome='loss') FROM decisions WHERE shadow=1 AND shadow_kind='marginal_wr' AND outcome IN ('win','loss');"`

## Known risks (accepted at registration)

- Simultaneous change: the `stale_flip` penalty was removed the same day
  (see forward_test_adx_gate.md Amendment 3). Eligibility requires
  marginal_pair_wr to be the ONLY penalty, and stale_flip's removal makes
  some previously-confounded skips newly eligible — the arm's population is
  defined by the post-removal penalty set. Acceptable: the hypothesis is
  about the marginal_pair_wr gate as it operates NOW.
- Hourly cap sampling is time-based (first-come), not random; if edge varies
  by hour this biases toward high-activity hours. Recorded, not corrected.
- Shadows use `select_expiry` (5s) at demo stake; results transfer to live
  only within the same expiry/payout regime.
- OTC feed is broker-generated; the gate's counterfactual value may shift
  with feed regime at any time.
