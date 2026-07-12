# Feature: Pre-registered forward-test pipeline (win-rate program phase 4)

**Date:** 2026-07-13 · **Status:** requirements — process live (manual), tooling TODO
**Origin:** Kym directive 2026-07-12: maximise win rate (Wilson-LB) with
increasing precision; candidates graduate to live policy ONLY through
pre-registered forward tests.

## Problem

This project's history is a graveyard of backtests that died on contact with
forward data (Kronos, hot-bucket persistence, run-continuation, trailing-WR
pair selection). The decision sweep alone tested 555 hypotheses — ~27 clear
p<0.05 by chance. Without a standing graduation pipeline, plausible-but-wrong
candidates leak into live policy; with silent mid-test edits, even honest
tests become unscoreable. The ADX gate test (`reports/forward_test_adx_gate.md`)
is the working template — this feature makes it the standard path.

## Pipeline (candidate → live policy)

```
sweep/analysis  →  TIGHTEN candidate  →  live segment tracking (free)  ─┐
                →  LOOSEN candidate   →  shadow arm (FEATURE_SHADOW_ARMS)┤
                                                                         ▼
                                   pre-registration doc (before any data counts)
                                                                         ▼
                                   n≥300 settled → verdict per registered rules
                                                                         ▼
                        PASS → Kym approves live policy change (one at a time)
```

## Requirements

1. **Pre-registration before data.** Every test gets a
   `reports/forward_test_<name>.md` written BEFORE its first counted trade:
   hypothesis with historical basis (n, WR, p), exact machine-readable rule,
   decision table (kill / pass / inconclusive thresholds), expected volume,
   known risks. Template: `reports/forward_test_adx_gate.md`.
2. **Fixed decision rules.** Default: n≥300 settled; early kill at n≥150 if
   WR<52.1%; PASS needs WR≥54% AND binomial p<0.05 vs 52.08% BE; draws
   excluded from WR. Deviations must be justified in the registration.
3. **Amendment protocol, never silent edits.** Environment changes mid-test
   are recorded as numbered amendments with UTC timestamps and an explicit
   statement of how the verdict population is preserved (possible because
   every DecisionRow stamps its ADX/levers/metrics — segment in analysis,
   don't reset the test). Precedent: Amendments 1–2 in the ADX gate doc.
4. **Segment tracking for TIGHTEN candidates.** No new trading code: a
   read-only script (`scripts/segment_status.py`, TODO) reports n / WR /
   Wilson-LB / p for each registered candidate rule over live trades since
   its registration date, and prints the verdict when thresholds are met.
   First candidates (registered here, tracking from 2026-07-12):
   - `gap_at_flip <= 0.225 AND adx >= 41` (sweep LB 54.4%)
   - `dist_atr >= 3.0` (sweep LB 52.7%)
   - `bars_in_trend >= 13` (sweep LB 52.4%; also informs the stale_flip
     penalty question)
   - `adx >= 55` exploratory segment (cap-removal Amendment 1)
5. **One live change at a time.** A PASS graduates alone so its effect is
   attributable; overlapping policy changes destroyed attribution repeatedly
   in June.
6. **Monitoring.** Active tests surface in heartbeat/briefing checks (today:
   `scripts/forward_test_status.py` for the ADX gate); every new registration
   adds its status command to `HEARTBEAT.md` rotation.
7. **Win-rate metric.** All verdicts and rankings use Wilson lower bound
   (95%) with volume reported alongside — raw WR is never the headline number.

## Non-goals

- No automated policy flipping: a PASS produces a proposal for Kym, never a
  self-applied change (hard rule: no gate/stake/limit changes without Kym).
- No mid-test optimisation of a registered rule — a better variant is a NEW
  registration.

## TODO

- [ ] `scripts/segment_status.py` — candidate segment tracker (req. 4)
- [ ] Register the three TIGHTEN candidates formally in `reports/` when the
      first one approaches n≈150 forward trades
- [ ] Fold ADX-gate verdict handling (due ~2026-07-23 at current volume) into
      this pipeline's template
