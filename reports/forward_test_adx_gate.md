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
- `data/flip_levers.json` (uncommitted 2026-07-09 state) independently requires
  ADX>=40 for PUT flips, >=15 for CALL flips, and hard-caps flips at ADX<=55 at the
  detection layer. Net effective test band: fresh flips with ADX in [40, 55]. That
  band ran ~56% WR historically, so the hypothesis stands, but the ADX>55 tail
  (strongest historical segment) is excluded by the levers, not by this gate.
