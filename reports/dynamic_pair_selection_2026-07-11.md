# Dynamic pair selection — analysis + activation (2026-07-11)

## What was activated

The dynamic pair-universe selector built earlier today to Kym's spec ("valid
statistics + ≥3 pairs trading") was wired end-to-end and switched on:

- `tools/pair_universe_update.py` → writes `data/pair_universe.json` hourly
  (new launchd job `com.kym.argussentinel-pairuniverse`, RunAtLoad + 3600s).
- `DYNAMIC_PAIRS_ENABLED=true` in `.env.config`; bot restarted 2026-07-11T14:16Z,
  scan log confirms `dynamic=10` in effect.
- Static `ALLOWED_PAIRS` (10 pairs) remains the fail-safe when the file is
  missing or >24h stale. Selector never touches stakes, gates, or risk config.
- Scan-log label now reports `dynamic=N` (was silently showing `allow=10` —
  the misleading-label class that caused the July 8 USDRUB-only incident).

Selector policy (unchanged from Kym's spec): Wilson 95% lower bound on 14d WR,
core seats need n≥30 and WR≥50%, backfill to ≥6 pairs from 28d stats, 2 rotating
probe slots for stale pairs, 2-run drop hysteresis, atomic writes, fail-open to
the static list on any error.

## Evidence review (this session's deep dive, decisions.db, all settled trades)

1. **Pair identity is NOT predictive within gated setups.** Among flip entries
   with ADX>40 (the forward-test population), per-pair win rates are
   statistically homogeneous: chi-square p=0.46 across 9 pairs with n≥15.
   The edge is the setup, not the pair.
2. **Trailing pair WR is non-predictive** (established in June live data;
   reconfirmed in the deep dive — top trailing-WR buckets decay to ~50% in the
   second half). The selector correctly uses Wilson LB as a *conservative floor*
   rather than raw WR ranking, and its probe slots stop the universe from
   freezing — both mitigate, but selection is still fundamentally WR-flavoured.
3. **Gated-setup supply is spread far wider than the universe.** Over 14 days,
   flip+ADX>40 signals at ≥92% payout appeared across ~49 pairs (row-level
   supply, multi-counted per cycle; tradeable-order-of-magnitude ≈ 5x the
   current universe's ~25 gated trades/day). The current 8-12 pair universe
   captures only a fraction of the gate's opportunity set.

## Tension to resolve after the ADX forward test reads out

If the ADX gate PASSES its pre-registered test, the evidence says pair
selection should flip from "pick pairs with good trailing stats" to "maximize
gated-setup supply across payout-eligible pairs, with a Wilson-LB veto only
for confirmed-bad pairs". That would multiply gated volume ~5x. **Not done
now** for two reasons: (a) it would change the forward-test population
mid-test (pre-registration forbids it); (b) pairs outside the historical
trade set are unvalidated — the homogeneity result only covers pairs we
actually traded. Proposal for after the test: expand via probe slots first
(raise PROBE_SLOTS), or run an expansion arm as shadow trades.

## Interaction with the ADX flip gate forward test

The dynamic universe (8-12 pairs, overlapping the static 10) keeps the traded
population comparable to the historical basis, which itself rotated pairs
across the 22-day window. Pair mix is noted as a covariate in
`reports/forward_test_adx_gate.md`; the homogeneity result (p=0.46) says pair
mix should not bias the gate's measured WR.

## Verification trail

- `launchctl list | grep pairuniverse` → job loaded, last exit 0.
- `data/pair_universe.json` → 10 pairs, roles core/backfill/probe/grace, stats attached.
- Bot log 14:16Z: `flip scan: 3/114 pairs ≥92% payout dynamic=10`.
- Full test suite: 337 passed (conftest pins live toggles to code defaults so
  production .env.config state can't leak into tests).
