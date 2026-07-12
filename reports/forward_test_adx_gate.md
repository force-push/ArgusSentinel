# Forward test: ADX flip gate — pre-registration

**Registered:** 2026-07-11T13:59:20+00:00 (before any test data existed)
**Approved by:** Kym (2026-07-11, "act upon them for testing")
**Basis:** `reports/entry_edges_2026-07-11.md` — full deep dive over 4,636 settled live trades.

## Hypothesis

Flip entries with ADX >= 40 win at a rate above the 52.08% break-even (92% payout).
Historical evidence: 56.8% WR over 544 trades (+$105.68), p=0.015 vs break-even,
monotone dose-response in ADX, stable across median-split halves, pairs, and directions.

## Intervention

`ADX_FLIP_GATE_ENABLED=true`, `ADX_FLIP_GATE_MIN=40` in `.env.config`.
Hard entry filter in `strategy/manager_v2.py::_assess_trade_signal` — non-flip entries
and flips with ADX < 40 are skipped (`adx_flip_gate_*` skip reasons). **No other policy
changed**: all existing gates (marginal_pair_wr, EV gate, martingale L1, stake) stay as-is
so the forward population matches the validated historical population.

## Pre-registered decision rules

| Condition | Verdict |
|---|---|
| n >= 150 settled and WR < 52.1% | KILL early |
| n >= 300, WR >= 54%, binomial p < 0.05 vs 52.08% | PASS — edge confirmed |
| n >= 300, WR < 52.1% | KILL |
| n >= 300, 52.1% <= WR < 54% or p >= 0.05 | INCONCLUSIVE — Kym decides |

Draws excluded from WR; counted in PnL. Expected volume ~25 settled trades/day,
so evaluation size ≈ 12 days.

## Monitoring

`./venv/bin/python scripts/forward_test_status.py` — prints n, WR, PnL, gate-skip count,
and the verdict per the table above. No mid-test threshold changes: if a different ADX
cut looks better mid-run, that is a NEW test, not an edit to this one.

## Known risks (accepted at registration)

- Multiple comparisons in the discovery phase; this test exists to control that.
- W27 historical dip (48.8%, n=80) — edge is not uniform week to week.
- OTC feed is broker-generated; edge may be repriced away at any time.
- The `flip_adx_exhausted` penalty (ADX > 55) still applies and contradicts the
  dose-response data (ADX>50 ran 58.9%); left unchanged for comparability. Revisit
  after this test reads out.
- 2026-07-11T14:16Z: dynamic pair universe activated (DYNAMIC_PAIRS_ENABLED=true,
  8-12 pairs, hourly reselection — see reports/dynamic_pair_selection_2026-07-11.md).
  Pair mix therefore varies during the test. Accepted because within-gate pair
  heterogeneity is statistically absent (chi-square p=0.46) and the historical
  basis population itself rotated pairs. Logged as a covariate, not a violation.
- `data/flip_levers.json` (2026-07-09 state) independently requires
  ADX>=40 for PUT flips, >=15 for CALL flips, and hard-caps flips at ADX<=55 at the
  detection layer. Net effective test band: fresh flips with ADX in [40, 55]. That
  band ran ~56% WR historically, so the hypothesis stands, but the ADX>55 tail
  (strongest historical segment) is excluded by the levers, not by this gate.

## Amendment 1 — 2026-07-12T08:24Z (Kym directive)

`flip_adx_max` in `data/flip_levers.json` raised 55 -> 999 (off). Rationale: the
<=55 cap truncated the strongest dose-response segment (high-ADX flips ran 58.9%
historically). Effective traded band widens from ADX [40, 55] to [40, inf) from
this timestamp.

Impact on the pre-registered verdict: every DecisionRow stamps `adx` and the
active `flip_levers`, so the ORIGINAL test remains scoreable without contamination
by restricting the verdict computation to flips with ADX in [40, 55] across the
whole run. Trades with ADX > 55 (admitted only after this amendment) are tracked
as a separate exploratory segment, not counted toward the pre-registered n=300 /
52.1% kill rule unless Kym decides otherwise.

Note: the hardcoded `flip_adx_exhausted` soft penalty (-0.03 strength for flip
ADX > 55, `strategy/manager_v2.py::_assess_trade_signal`) still applies to the
newly admitted segment — it can suppress borderline-strength entries but is not
a hard block. Left in place pending Kym's decision.

## Amendment 3 — 2026-07-13 (Kym directive)

The `stale_flip` soft penalty removed from `_assess_trade_signal` (was -0.04
strength for flip bars_in_trend > 8). Basis: decision_sweep_2026-07-12 —
bars_in_trend >= 13 flips ran 57.1% (Wilson-LB 52.4%, both halves above
break-even); the penalty suppressed a better-than-average segment (same
inverted-heuristic pattern as the removed flip_adx_exhausted penalty).

Impact on the pre-registered verdict: unlike Amendment 2, this DOES touch the
verdict population — borderline-strength flips with bars_in_trend > 8 inside
ADX [40,55] that previously skipped can now trade, and the sweep says that
segment is above-average, which biases the verdict WR upward from this date.
Mitigation: every row stamps bars_in_trend, so at verdict time the WR will be
reported BOTH ways — full population, and excluding post-2026-07-13 trades
with bars_in_trend > 8 (the composition-neutral view). If the two disagree on
the kill/pass line, the composition-neutral number governs and the widened
population runs as its own follow-on test.

Also same day: the marginal_wr shadow arm activated (SHADOWS_ENABLED=true,
see reports/forward_test_marginal_wr_shadow.md). Shadows never enter this
test's population (shadow=0 filter), so no verdict impact.

## Amendment 2 — 2026-07-12 (Kym directive, same session as Amendment 1)

The `flip_adx_exhausted` soft penalty removed from
`strategy/manager_v2.py::_assess_trade_signal` (was -0.03 strength for flip
ADX > 55). The ADX > 55 exploratory segment now trades with no ADX-related
handicap of any kind. Original-band trades (ADX in [40, 55]) are unaffected —
the penalty never fired below 55 — so the pre-registered verdict population is
unchanged by this amendment.
