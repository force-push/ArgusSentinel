#!/usr/bin/env python3
"""Per-pair performance report from resolved real trades — the single source of
truth for pair-universe decisions (used by tools/pair_universe_update.py and the
6-hourly OpenClaw analysis cron).

Statistics policy ("valid data sets", 2026-07-11):
  * Only real resolved trades count: shadow=0, decision='TRADE', outcome win/loss.
  * Wilson 95% lower bound is the selection statistic, not the raw win rate —
    raw trailing WR selection regressed to the mean in live trading (June).
  * EV/trade is computed at each pair's own observed mean payout.
  * A pair with n below --min-n is reported but never eligible for selection.

Usage:
  python3 tools/pair_report.py                # human-readable report, 14d window
  python3 tools/pair_report.py --json         # machine output for the selector
  python3 tools/pair_report.py --days 28
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "decisions.db"

Z95 = 1.959963984540054


def wilson_lower(wins: int, n: int, z: float = Z95) -> float:
    """Wilson score interval lower bound for a binomial proportion."""
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def breakeven(payout_pct: float) -> float:
    """Win rate needed for zero EV at a given payout percentage."""
    return 1.0 / (1.0 + payout_pct / 100.0)


def pair_stats(db: sqlite3.Connection, days: int) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = db.execute(
        """
        SELECT pair_api,
               COUNT(*)                                    AS n,
               SUM(outcome = 'win')                        AS wins,
               AVG(json_extract(data, '$.payout_pct'))     AS payout,
               SUM(COALESCE(pnl, 0))                       AS pnl,
               MAX(ts)                                     AS last_trade
        FROM decisions
        WHERE shadow = 0 AND decision = 'TRADE'
          AND outcome IN ('win', 'loss') AND ts >= ?
        GROUP BY pair_api
        """,
        (since,),
    ).fetchall()
    out = []
    for pair, n, wins, payout, pnl, last_trade in rows:
        payout = payout or 92.0
        wr = wins / n
        be = breakeven(payout)
        lb = wilson_lower(wins, n)
        out.append({
            "pair": pair,
            "n": n,
            "wins": wins,
            "wr": round(wr, 4),
            "wilson_lb": round(lb, 4),
            "payout_pct": round(payout, 2),
            "breakeven": round(be, 4),
            # EV per $1 staked at observed payout: WR*(1+payout) - 1
            "ev_per_unit": round(wr * (1 + payout / 100.0) - 1, 4),
            "pnl": round(pnl, 2),
            "last_trade": last_trade,
        })
    out.sort(key=lambda r: r["wilson_lb"], reverse=True)
    return out


def coverage_stats(db: sqlite3.Connection, hours: int = 24) -> dict:
    """Eligibility coverage proxy: distinct pairs evaluated (TRADE or SKIP)
    per hour. A pair only reaches evaluation when it clears the allowlist,
    payout floor, and cooldowns — so this tracks the live tradable set."""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    rows = db.execute(
        """
        SELECT strftime('%Y-%m-%dT%H', ts) AS hr, COUNT(DISTINCT pair_api) AS k
        FROM decisions WHERE shadow = 0 AND ts >= ? GROUP BY hr
        """,
        (since,),
    ).fetchall()
    counts = [k for _, k in rows]
    hours_seen = len(counts)
    return {
        "window_hours": hours,
        "hours_with_activity": hours_seen,
        "hours_with_3plus_pairs": sum(1 for k in counts if k >= 3),
        "min_pairs_per_hour": min(counts) if counts else 0,
        "median_pairs_per_hour": sorted(counts)[hours_seen // 2] if counts else 0,
        "dead_hours": hours - hours_seen,
    }


def build_report(days: int, min_n: int) -> dict:
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        stats = pair_stats(db, days)
        cov = coverage_stats(db)
    finally:
        db.close()
    for row in stats:
        if row["n"] < min_n:
            row["verdict"] = "insufficient-n"
        elif row["wilson_lb"] >= row["breakeven"]:
            row["verdict"] = "proven-edge"       # LB clears break-even: rare, strong
        elif row["wr"] >= row["breakeven"]:
            row["verdict"] = "positive-point"    # point estimate above BE, LB below
        else:
            row["verdict"] = "below-breakeven"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": days,
        "min_n": min_n,
        "pairs": stats,
        "coverage_24h": cov,
    }


def render_text(rep: dict) -> str:
    lines = [
        f"ArgusSentinel pair report — {rep['window_days']}d window, "
        f"generated {rep['generated_at'][:16]}Z",
        f"{'pair':<14}{'n':>6}{'WR%':>7}{'LB%':>7}{'BE%':>7}{'EV/u':>8}{'PnL$':>9}  verdict",
    ]
    for r in rep["pairs"]:
        lines.append(
            f"{r['pair']:<14}{r['n']:>6}{r['wr']*100:>7.1f}{r['wilson_lb']*100:>7.1f}"
            f"{r['breakeven']*100:>7.1f}{r['ev_per_unit']:>8.3f}{r['pnl']:>9.2f}  {r['verdict']}"
        )
    c = rep["coverage_24h"]
    lines.append(
        f"coverage 24h: {c['hours_with_3plus_pairs']}/{c['window_hours']}h with ≥3 pairs, "
        f"{c['dead_hours']} dead hours, median {c['median_pairs_per_hour']} pairs/h"
    )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = build_report(args.days, args.min_n)
    print(json.dumps(rep, indent=2) if args.json else render_text(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
