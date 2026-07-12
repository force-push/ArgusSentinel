# Feature: Shadow-arm expansion (win-rate program phase 3)

**Date:** 2026-07-13 · **Status:** built, DORMANT — awaiting Kym enable decision
**Origin:** `reports/decision_sweep_2026-07-12.md` (LOOSEN section) · **Commit:** eeb9609

## Problem

The decision sweep found that the biggest win-rate opportunity is not
tightening the traded population but testing what current gates *block*:
`marginal_pair_wr` alone blocked **10,473 ADX≥40 flips in 14 days (~750/day)**
versus ~22/day traded — and skipped setups have no outcomes, so no amount of
historical analysis can say whether those blocks were correct. The gate's
signal (trailing pair WR) has twice been shown non-predictive (regresses to
mean), so the suspicion is it blocks winners. Shadow trades (demo, no-stake
impact on strategy stats) are the only honest way to collect counterfactuals.

## Requirements

1. **Isolate one gate per arm.** A shadow row is only useful if exactly one
   gate separates it from a real trade. The `marginal_wr` arm therefore fires
   only when: entry_kind=flip AND ADX≥40 AND `marginal_pair_wr` is among the
   strength penalties AND no other qualitative penalty (stale_flip,
   weak_flip_gap_expansion, rsi_extreme_against_entry, soft_direction_wr) is
   present. Implemented: `StrategyManagerV2._mwr_shadow_eligible`.
2. **Bounded volume.** Eligible skips run ~750/day; unbounded shadowing is what
   bloated decisions.db to 781MB before the 2026-06-23 purge. Hourly cap via
   `SHADOW_MARGINAL_WR_HOURLY_CAP` (default 20/h ⇒ ≤480/day worst case).
3. **Layered kill-switches (all must be true to fire):**
   - `SHADOWS_ENABLED` master (currently `false`, deliberate 2026-06-23 decision)
   - `SHADOW_MARGINAL_WR_ENABLED` (new, default `false`)
   - `trade_mode != LIVE` (hard guard inherited from `_place_single_shadow`)
4. **Attribution.** Rows carry `shadow_kind="marginal_wr"` and
   `would_skip_reason=<the full weak_trade_strength reason>` so analysis can
   join back to the exact blocking penalty values.
5. **Zero effect on live policy.** Shadows never touch the tracker, risk
   budget, martingale state, or concurrency slots (existing infra guarantee).

## Verdict criteria (pre-registered when enabled)

Same framework as `reports/forward_test_adx_gate.md`: at n≥300 settled shadow
outcomes — WR ≥ 54% and binomial p<0.05 vs 52.08% ⇒ propose retiring
`marginal_pair_wr` for gated flips (as its own pre-registered live test);
WR < 52.1% ⇒ the gate stays and the deep-dive suspicion is retired.

## Enable checklist (Kym's call — reverses the 2026-06-23 shadow kill)

1. `SHADOWS_ENABLED=true`, `SHADOW_MARGINAL_WR_ENABLED=true` in `.env.config`
   (no restart needed only for lever-file keys; .env changes need a restart).
2. Confirm decisions.db growth acceptable (≤480 rows/day at default cap).
3. Add a pre-registration section to a new report before the first row lands.

## Future arms (build the same way, one gate per arm)

- `below_required_probability` blocks (4,712+2,871 in 14d) — second-largest.
- Expiry-duration arms (`SHADOW_EXPIRY_SECONDS`, e.g. [30,60]) once tick
  capture has ≥2 weeks of data to design against — see the sweep's timing gap.
