#!/usr/bin/env python3
"""Dynamic pair-universe selector — writes ``data/pair_universe.json``, which
the running bot hot-reloads via ``strategy/pair_filter.py`` (mtime-cached, same
pattern as flip_levers). Scheduled hourly by launchd
(``com.kym.argussentinel-pairuniverse``); safe to run by hand any time.

Selection policy (2026-07-11, per Kym: valid statistics + ≥3 pairs trading):
  * Statistic: Wilson 95% lower bound on the rolling {WINDOW_DAYS}d win rate —
    never raw trailing WR (that regressed to the mean in June live trading).
  * CORE pairs: n ≥ {MIN_N} and point WR ≥ {WR_FLOOR:.0%}, ranked by Wilson LB,
    up to {TARGET} pairs.
  * BACKFILL: if fewer than {MIN_UNIVERSE} core pairs qualify, top up from the
    best remaining ranked pairs so payout rotation can't starve the bot below
    3 concurrently-eligible pairs.
  * PROBE: {PROBE_SLOTS} slots rotate daily through pairs whose data is stale
    (no resolved trade in {STALE_DAYS}d) so the universe can rediscover pairs —
    otherwise the selection can never learn about anything it isn't trading.
  * Hysteresis: an incumbent pair is only dropped after failing selection in
    {DROP_AFTER} consecutive runs (July-8 lesson: one bad 18-trade day evicted
    the best pair in the dataset).
  * Fail-safe: on any error or empty result the existing file is left alone;
    if the file is missing/stale/invalid the bot falls back to the static
    ALLOWED_PAIRS list. This tool NEVER touches stakes, gates, or risk config.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pair_report import DB_PATH, REPO, pair_stats, wilson_lower  # noqa: E402

UNIVERSE_PATH = REPO / "data" / "pair_universe.json"

WINDOW_DAYS = 14      # rolling stats window
MIN_N = 30            # resolved trades required for a CORE seat
WR_FLOOR = 0.50       # point-estimate floor for CORE
TARGET = 10           # universe size to aim for
MIN_UNIVERSE = 6      # never select fewer (coverage for ≥3 concurrent eligible)
MAX_UNIVERSE = 12     # never select more
PROBE_SLOTS = 2       # rotating slots for stale/unseen pairs
STALE_DAYS = 7        # no resolved trade in this long → probe candidate
DROP_AFTER = 2        # consecutive failed runs before an incumbent is dropped

# Pairs never selected regardless of stats (mirror of confirmed-loser research).
HARD_EXCLUDE: set[str] = set()


def load_previous() -> dict:
    try:
        return json.loads(UNIVERSE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def probe_candidates(db: sqlite3.Connection, active: set[str]) -> list[str]:
    """All-time traded pairs with no resolved trade in STALE_DAYS, WR history
    not clearly broken (all-time WR ≥ 47%), rotated deterministically by day."""
    since = (datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)).isoformat()
    rows = db.execute(
        """
        SELECT pair_api, COUNT(*) n, SUM(outcome='win') wins, MAX(ts) last_ts
        FROM decisions
        WHERE shadow = 0 AND decision = 'TRADE' AND outcome IN ('win','loss')
        GROUP BY pair_api HAVING n >= 20
        """,
    ).fetchall()
    stale = [
        (pair, wins / n)
        for pair, n, wins, last_ts in rows
        if last_ts < since and pair not in active and pair not in HARD_EXCLUDE
        and (wins / n) >= 0.47
    ]
    stale.sort(key=lambda t: t[1], reverse=True)
    if not stale:
        return []
    # Deterministic daily rotation: shift the ranked list by day-of-year.
    shift = datetime.now(timezone.utc).timetuple().tm_yday % len(stale)
    rotated = stale[shift:] + stale[:shift]
    return [p for p, _ in rotated[:PROBE_SLOTS]]


def select() -> dict | None:
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        stats = pair_stats(db, WINDOW_DAYS)      # already sorted by Wilson LB
        prev = load_previous()
        prev_pairs = set(prev.get("pairs", []))
        fail_counts: dict[str, int] = prev.get("fail_counts", {})

        ranked = [r for r in stats if r["pair"] not in HARD_EXCLUDE]
        core = [r["pair"] for r in ranked
                if r["n"] >= MIN_N and r["wr"] >= WR_FLOOR][:TARGET]

        # Backfill toward MIN_UNIVERSE from a longer-window quality pool —
        # 28d stats with n ≥ MIN_N and WR ≥ 47%, ranked by Wilson LB. A pair
        # is vetoed if its recent {WINDOW_DAYS}d record shows a collapse
        # (n ≥ 5 and WR < 40%) — that's how OMRCNY (11% over its last 9)
        # nearly re-entered on day one of this selector.
        backfill = []
        if len(core) < MIN_UNIVERSE:
            recent = {r["pair"]: r for r in stats}
            pool = [r for r in pair_stats(db, 28)
                    if r["pair"] not in core and r["pair"] not in HARD_EXCLUDE
                    and r["n"] >= MIN_N and r["wr"] >= 0.47
                    and not (r["pair"] in recent
                             and recent[r["pair"]]["n"] >= 5
                             and recent[r["pair"]]["wr"] < 0.40)]
            for r in pool:                       # already LB-sorted
                backfill.append(r["pair"])
                if len(core) + len(backfill) >= MIN_UNIVERSE:
                    break

        selected = core + backfill

        # Hysteresis: incumbents that just missed selection get DROP_AFTER grace runs.
        new_fail_counts: dict[str, int] = {}
        for pair in prev_pairs:
            if pair in selected or pair in HARD_EXCLUDE:
                continue
            fails = fail_counts.get(pair, 0) + 1
            if fails < DROP_AFTER and len(selected) < MAX_UNIVERSE:
                selected.append(pair)            # keep on grace
                new_fail_counts[pair] = fails
        # Selected incumbents reset their fail count implicitly (not carried over).

        probes = probe_candidates(db, set(selected))
        selected = (selected + probes)[:MAX_UNIVERSE]

        if not selected:
            return None                          # fail-safe: never write empty

        by_pair = {r["pair"]: r for r in stats}
        return {
            "version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_days": WINDOW_DAYS,
            "policy": {"min_n": MIN_N, "wr_floor": WR_FLOOR, "target": TARGET,
                       "min": MIN_UNIVERSE, "max": MAX_UNIVERSE,
                       "probe_slots": PROBE_SLOTS, "drop_after": DROP_AFTER},
            "pairs": selected,
            "roles": {p: ("core" if p in core else
                          "backfill" if p in backfill else
                          "probe" if p in probes else "grace")
                      for p in selected},
            "fail_counts": new_fail_counts,
            "stats": {p: {k: by_pair[p][k] for k in
                          ("n", "wr", "wilson_lb", "ev_per_unit", "pnl")}
                      for p in selected if p in by_pair},
        }
    finally:
        db.close()


def main() -> int:
    dry = "--dry-run" in sys.argv
    universe = select()
    if universe is None:
        print("no pairs selectable — leaving existing universe untouched", file=sys.stderr)
        return 1
    prev = load_previous()
    added = sorted(set(universe["pairs"]) - set(prev.get("pairs", [])))
    dropped = sorted(set(prev.get("pairs", [])) - set(universe["pairs"]))
    if dry:
        print(json.dumps(universe, indent=2))
    else:
        tmp = UNIVERSE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(universe, indent=2))
        tmp.replace(UNIVERSE_PATH)               # atomic — bot never sees a partial file
    print(f"universe: {len(universe['pairs'])} pairs "
          f"(+{len(added)} {added or ''} / -{len(dropped)} {dropped or ''})"
          f"{' [dry-run]' if dry else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
