# TradingAgents Learnings for ArgusSentinel

Date: 2026-06-25

Local fork: `/Users/kym/code/openclaw/projects/TradingAgents`

Fork remote: `https://github.com/force-push/TradingAgents`

Upstream paper: `arXiv:2412.20138v7`, revised 2025-06-03.

## Verdict

TradingAgents is useful for Argus as an architecture and auditability reference, not as a drop-in trading engine.

The stock-oriented workflow in TradingAgents does not directly transfer to PocketOption OTC binary options. It is daily/swing stock analysis with fundamentals, news, social sentiment, and portfolio ratings. Argus is short-horizon, broker-synthetic, payout-constrained, and already has evidence that most price-derived indicators are near-random at the 30s horizon.

What is worth importing:

- structured agent outputs
- report tree / evidence artifacts
- decision memory with resolved-outcome reflection
- checkpoint/resume discipline
- verified data-access contracts
- explicit risk review before execution
- provider/model configurability
- tests that guard against stale data, lookahead, and fabricated market context

What should not be imported:

- "LLM decides the trade" execution
- stock fundamentals/news flow as a live gate
- bull/bear debates that are not measured against outcomes
- any agent output that can affect real trades before it proves predictive in shadow mode

## TradingAgents Components Worth Mining

### Structured outputs

Source:

- `tradingagents/agents/schemas.py`

The key design is typed model output plus a markdown renderer. Argus should do the same for research notes:

```python
class ArgusTradeReview:
    trade_id: str | None
    cycle_id: str
    pair_api: str
    candidate_direction: str
    analyst_vote: str
    bull_case: str
    bear_case: str
    risk_flags: list[str]
    confidence: float
    recommended_action: str  # follow, fade, skip, observe
    required_evidence: list[str]
```

This should be stored as data, not only prose.

### Agent state / handoff protocol

Source:

- `tradingagents/agents/utils/agent_states.py`

TradingAgents keeps role-specific reports in named state fields. Argus should not pass a long chat transcript between agents. Use compact state:

- market snapshot
- signal breakdown
- pair/payout/risk context
- recent resolved analogs
- bull note
- bear note
- risk note
- final research memo

### Decision memory and reflection

Source:

- `tradingagents/graph/reflection.py`
- `TradingMemoryLog` references in `tradingagents/graph/trading_graph.py`

Argus already has a stronger raw substrate than TradingAgents: `data/decisions.db`.

Add a reflection layer that runs after outcomes resolve:

- Was the agent note directionally useful?
- Did the risk flags predict a loss?
- Did "fade" or "follow" advice correlate with outcomes?
- Which field should change before the next similar setup?

Reflections must be short and queryable. They should not become motivational prose.

### Report tree

Source:

- `tradingagents/reporting.py`

Argus should write each research experiment into a stable artifact tree:

```text
reports/research-council/<run-id>/
  input_snapshot.json
  signal_analyst.md
  bull.md
  bear.md
  risk.md
  final_memo.md
  structured_review.json
  outcome_review.md
```

This makes cockpit integration straightforward: every research decision has an artifact path.

### Verified data access

Source:

- TradingAgents changelog v0.3.0: verified data-access contract, stale-OHLCV rejection, lookahead-safe news windows.

Argus equivalent:

- never let LLM reports use future outcome fields
- distinguish live candidates from resolved historical analogs
- stamp every agent input with `as_of_ts`
- reject stale candle/sentiment data
- record whether the review saw real OHLC, flat fallback candles, sentiment, payout, and open-trade state

## Proposed Argus Research Council

This is a shadow-only LLM review layer around candidate trades.

### Roles

1. **Signal Analyst**
   Summarizes deterministic facts only: pair, payout, direction, signal breakdown, agreement count, confluence, expiry, pair history, recent analogs.

2. **Bull Researcher**
   Makes the strongest case for following the candidate direction.

3. **Bear Researcher**
   Makes the strongest case for fading or skipping the candidate direction.

4. **Risk Reviewer**
   Checks execution risk: open trades, cooldown, stake, pair blacklist, recent streak, data freshness, payout floor, unresolved outcomes.

5. **Research Manager**
   Emits structured `follow|fade|skip|observe` plus confidence and evidence refs.

No role places trades.

### Data Flow

```text
StrategyManagerV2 candidate
  -> deterministic snapshot builder
  -> Argus Research Council shadow review
  -> store review beside decision row
  -> outcome resolves
  -> reflection row generated
  -> dashboard/cockpit shows predictive value by role
```

### Storage

Add a new table rather than modifying the hot `decisions` table:

```sql
CREATE TABLE IF NOT EXISTS agent_reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  decision_row_id INTEGER,
  cycle_id TEXT,
  trade_id TEXT,
  pair_api TEXT,
  review_kind TEXT NOT NULL,
  model TEXT,
  prompt_version TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  recommendation TEXT,
  confidence REAL,
  risk_flags TEXT,
  evidence_refs TEXT,
  data TEXT NOT NULL,
  outcome TEXT,
  pnl REAL,
  reviewed_after_outcome INTEGER DEFAULT 0
);
```

This keeps the live trading path stable and lets us drop/rebuild the research layer if it proves useless.

### Promotion Gate

An LLM recommendation cannot influence live trades until it clears all gates:

- at least 500 resolved reviews
- recommendation bucket has a statistically meaningful edge over baseline
- effect replicates across at least 3 high-volume pairs or is explicitly pair-scoped
- no unacceptable latency impact
- no data leakage in audit
- deterministic risk gate still has final authority

Initial target:

- `fade` recommendations must reach at least 54% WR over 500 resolved reviews before being considered
- `skip` recommendations must show avoided-trade WR below break-even, not just sound plausible
- `follow` recommendations must beat the existing candidate baseline, not raw 50/50

## First Implementation Slice

### 1. Build a deterministic snapshot exporter

New module:

```text
strategy/research_snapshot.py
```

Inputs:

- decision row / candidate state
- signal breakdown
- pair stats
- payout/break-even
- current risk state
- last N similar resolved rows

Output:

```json
{
  "as_of_ts": "...",
  "cycle_id": "...",
  "pair_api": "...",
  "candidate_direction": "CALL",
  "expiry_seconds": 30,
  "payout": 0.92,
  "breakeven_wr": 0.5217,
  "signals": {},
  "risk": {},
  "recent_analogs": []
}
```

### 2. Add offline research runner

New tool:

```text
tools/run_research_council.py
```

Start with historical rows only. Do not touch `main_v2.py` yet.

Example:

```bash
python3 tools/run_research_council.py --limit 25 --dry-run
```

The dry run should build snapshots and validate schemas without calling an LLM.

### 3. Add storage and analysis

Extend `data/decisions_store.py` or add `data/agent_review_store.py`.

New analysis:

```text
tools/analyze_agent_reviews.py
```

Outputs:

- WR by recommendation
- WR by confidence bucket
- WR by pair
- risk flag correlation
- latency/cost summary
- leakage audit failures

### 4. Connect cockpit read-only

Expose:

- newest reviews
- sample sizes
- current recommendation bucket performance
- pending promotion gates

Cockpit should show this as evidence, not action.

## Why This Fits Current Argus Findings

Current research says the existing price-derived signal stack is mostly not predictive. The two repeated structures are second-order:

- unanimity may be a fade/exhaustion signal
- ADX/high-trend regime may be the only context where direction matters

The Research Council should therefore focus on second-order context:

- Is this a trend continuation or exhaustion setup?
- Is this signal agreement independent or redundant?
- Is pair/payout/regime favorable enough?
- Is the correct action follow, fade, or skip?

It should not invent new indicator confidence.

## Immediate Tasks

- [ ] Add read-only TradingAgents fork reference to cockpit project registry.
- [ ] Add Argus project card to cockpit if missing.
- [ ] Build `strategy/research_snapshot.py` with tests.
- [ ] Build `tools/run_research_council.py --dry-run` using historical rows.
- [ ] Add `agent_reviews` storage table.
- [ ] Add `tools/analyze_agent_reviews.py`.
- [ ] Only after dry-run validation, enable LLM calls against a small historical sample.
- [ ] Only after 500 resolved shadow reviews, consider whether recommendations should affect execution.

## Hard Rule

The LLM layer is a research instrument until proven otherwise. Execution remains controlled by deterministic gates, payout math, risk limits, and explicit approval.
