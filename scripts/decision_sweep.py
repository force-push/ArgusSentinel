"""Systematic decision-point sweep: find win-rate-maximising gate refinements.

Extends scripts/analyze_entry_edges.py from hand-picked buckets to a
systematic threshold sweep, ranked by the Wilson lower bound (95%) of win
rate rather than raw WR — raw WR trivially rewards trading less, Wilson-LB
rewards precision AND sample size. Method:

  * settled real trades only (win/loss; draws excluded per forward-test
    convention), loaded column-wise via json_extract — never the full blobs
  * time-based holdout: split at the median timestamp; a rule only counts
    as a candidate if it clears break-even in BOTH halves
  * single-feature threshold rules (decile cuts, both directions) plus
    categorical rules, swept over (a) all settled trades and (b) the
    go-forward baseline population (flip entries, ADX >= 40); then pairwise
    AND-combinations of the strongest validated singles
  * every rule evaluated is counted toward the reported hypothesis total so
    multiple-comparisons exposure stays visible

Read-only: no policy or config changes. Writes the report to
reports/decision_sweep_2026-07-12.md (and stdout summary).
"""

import json
import sqlite3
from datetime import datetime, timezone
from itertools import combinations
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "decisions.db"
REPORT = ROOT / "reports" / "decision_sweep_2026-07-12.md"

BE = 0.5208          # break-even WR at 92% payout
MIN_N = 300          # candidate volume floor (matches forward-test scale)
CAP_CHANGE_TS = "2026-07-12T08:24:00+00:00"  # flip_adx_max 55->999 (Amendment 1)

NUMERIC_FEATURES = [
    "adx", "rsi", "plus_di", "minus_di", "di_spread", "dist_atr",
    "gap_expansion", "gap_at_flip", "macd_gap_atr", "macd_sign_consistency",
    "bars_in_trend", "roc", "atr_bps", "bb_width_bps", "trade_strength",
]
JSON_FIELDS = {
    "payout_pct": "$.payout_pct",
    "martingale_level": "$.martingale_level",
    "adx": "$.flip_metrics.adx",
    "adx_rising": "$.flip_metrics.adx_rising",
    "rsi": "$.flip_metrics.rsi",
    "plus_di": "$.flip_metrics.plus_di",
    "minus_di": "$.flip_metrics.minus_di",
    "dist_atr": "$.flip_metrics.dist_atr",
    "gap_expansion": "$.flip_metrics.gap_expansion",
    "gap_at_flip": "$.flip_metrics.gap_at_flip",
    "macd_gap_atr": "$.flip_metrics.macd_gap_atr",
    "macd_sign_consistency": "$.flip_metrics.macd_sign_consistency",
    "bars_in_trend": "$.flip_metrics.bars_in_trend",
    "entry_kind": "$.flip_metrics.entry_kind",
    "roc": "$.flip_metrics.roc",
    "atr_bps": "$.flip_metrics.atr_bps",
    "bb_width_bps": "$.flip_metrics.bb_width_bps",
    "trade_strength": "$.flip_metrics.trade_strength",
    "reversal_against_entry": "$.flip_metrics.reversal_against_entry",
}


def wilson_lb(wins: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return (centre - margin) / denom


def load() -> pd.DataFrame:
    cols = ", ".join(
        f"json_extract(data, '{path}') AS {name}" for name, path in JSON_FIELDS.items()
    )
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        f"SELECT ts, pair_api, our_direction, expiry_seconds, outcome, pnl, {cols} "
        "FROM decisions WHERE decision='TRADE' AND shadow=0 "
        "AND outcome IN ('win','loss') ORDER BY id",
        con,
    )
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    df["hour_utc"] = df["ts"].dt.hour
    df["dow"] = df["ts"].dt.dayofweek
    df["win"] = (df["outcome"] == "win").astype(int)
    df["di_spread"] = df["plus_di"] - df["minus_di"]
    for c in NUMERIC_FEATURES + ["payout_pct", "martingale_level"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def evaluate(df: pd.DataFrame, mask: pd.Series, label: str, h_split: pd.Timestamp,
             total_days: float) -> dict | None:
    sub = df[mask]
    n = len(sub)
    if n == 0:
        return None
    w = int(sub["win"].sum())
    h1 = sub[sub["ts"] < h_split]
    h2 = sub[sub["ts"] >= h_split]
    return {
        "rule": label,
        "n": n,
        "wr": w / n,
        "lb": wilson_lb(w, n),
        "h1_wr": h1["win"].mean() if len(h1) else np.nan,
        "h1_n": len(h1),
        "h2_wr": h2["win"].mean() if len(h2) else np.nan,
        "h2_n": len(h2),
        "p": binomtest(w, n, BE, alternative="greater").pvalue,
        "per_day": n / total_days,
    }


def sweep(df: pd.DataFrame, h_split: pd.Timestamp, total_days: float,
          scope: str) -> tuple[list[dict], int, dict[str, pd.Series]]:
    """All single-feature rules on df. Returns (results, n_hypotheses, masks)."""
    results, masks = [], {}
    n_hyp = 0

    def add(mask: pd.Series, label: str):
        nonlocal n_hyp
        n_hyp += 1
        r = evaluate(df, mask, label, h_split, total_days)
        if r is not None:
            r["scope"] = scope
            results.append(r)
            masks[label] = mask

    for feat in NUMERIC_FEATURES:
        vals = df[feat].dropna()
        if len(vals) < MIN_N:
            continue
        cuts = np.unique(np.round(vals.quantile(np.arange(0.1, 1.0, 0.1)), 3))
        for cut in cuts:
            add(df[feat] >= cut, f"{feat} >= {cut}")
            add(df[feat] <= cut, f"{feat} <= {cut}")
    add(df["entry_kind"] == "flip", "entry_kind == flip")
    add(df["entry_kind"] == "trend", "entry_kind == trend")
    for v in (0, 1):
        add(df["adx_rising"] == v, f"adx_rising == {bool(v)}")
        add(df["reversal_against_entry"] == v, f"reversal_against_entry == {bool(v)}")
    for d in ("CALL", "PUT"):
        add(df["our_direction"] == d, f"direction == {d}")
    for h0, h1_ in ((0, 6), (6, 12), (12, 18), (18, 24)):
        add(df["hour_utc"].between(h0, h1_ - 1), f"hour_utc in [{h0},{h1_})")
    for h in range(24):
        add(df["hour_utc"] == h, f"hour_utc == {h}")
    add(df["payout_pct"] >= 92, "payout_pct >= 92")
    add(df["martingale_level"] == 0, "martingale_level == 0")
    return results, n_hyp, masks


def validated(results: list[dict]) -> list[dict]:
    """Candidates: volume floor, clears BE in both halves, significant overall."""
    return sorted(
        (r for r in results
         if r["n"] >= MIN_N and r["h1_n"] >= 50 and r["h2_n"] >= 50
         and r["h1_wr"] > BE and r["h2_wr"] > BE and r["p"] < 0.05),
        key=lambda r: r["lb"], reverse=True,
    )


def table(rows: list[dict], top: int | None = None) -> str:
    rows = rows[:top] if top else rows
    if not rows:
        return "_none_\n"
    out = ["| rule | n | WR | Wilson-LB | h1 WR (n) | h2 WR (n) | p | trades/day |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append(
            f"| `{r['rule']}` | {r['n']} | {r['wr']:.1%} | **{r['lb']:.1%}** "
            f"| {r['h1_wr']:.1%} ({r['h1_n']}) | {r['h2_wr']:.1%} ({r['h2_n']}) "
            f"| {r['p']:.4f} | {r['per_day']:.0f} |"
        )
    return "\n".join(out) + "\n"


def loosen_analysis() -> str:
    """Volume-only view of what current gates block (no WR claims possible:
    skips have no outcomes and shadow rows were purged 2026-06-23)."""
    con = sqlite3.connect(DB)
    q = (
        "SELECT skip_reason, COUNT(*) c FROM decisions "
        "WHERE decision='SKIP' AND ts >= datetime('now','-14 days') "
        "GROUP BY skip_reason ORDER BY c DESC LIMIT 12"
    )
    rows = con.execute(q).fetchall()
    blocked = con.execute(
        "SELECT COUNT(*) FROM decisions WHERE decision='SKIP' "
        "AND ts >= datetime('now','-14 days') "
        "AND skip_reason LIKE '%marginal_pair_wr%' "
        "AND json_extract(data,'$.flip_metrics.entry_kind')='flip' "
        "AND CAST(json_extract(data,'$.flip_metrics.adx') AS REAL) >= 40"
    ).fetchone()[0]
    con.close()
    out = ["| skip_reason (14d) | count |", "|---|---|"]
    for reason, c in rows:
        reason = (reason or "").split("(")[0].strip()[:70]
        out.append(f"| {reason} | {c} |")
    out.append("")
    out.append(
        f"**ADX>=40 flips blocked by `marginal_pair_wr` (14d): {blocked}** — the "
        "gate the 2026-07-11 deep dive flagged as inverted (trailing pair WR is "
        "non-predictive). These are the prime LOOSEN candidates, but with no "
        "shadow outcomes on record the only honest validation is a forward "
        "shadow arm."
    )
    return "\n".join(out) + "\n"


def post_cap_change(df: pd.DataFrame) -> str:
    seg = df[(df["ts"] >= pd.Timestamp(CAP_CHANGE_TS)) & (df["entry_kind"] == "flip")]
    bands = [("ADX [40,55]", (seg["adx"] >= 40) & (seg["adx"] <= 55)),
             ("ADX > 55", seg["adx"] > 55)]
    out = ["| segment since cap removal | n | wins |", "|---|---|---|"]
    for label, m in bands:
        s = seg[m]
        out.append(f"| {label} | {len(s)} | {int(s['win'].sum())} |")
    return "\n".join(out) + "\n"


def main() -> None:
    df = load()
    total_days = max((df["ts"].max() - df["ts"].min()).total_seconds() / 86400, 1.0)
    h_split = df["ts"].median()
    base_n, base_w = len(df), int(df["win"].sum())

    all_res, hyp_all, masks_all = sweep(df, h_split, total_days, "all")

    gated = df[(df["entry_kind"] == "flip") & (df["adx"] >= 40)]
    gated_days = total_days
    g_res, hyp_g, masks_g = sweep(gated, h_split, gated_days, "flip&adx>=40")

    cand_all = validated(all_res)
    cand_g = validated(g_res)

    # Pairwise AND-combinations among the strongest validated gated singles.
    pair_res, hyp_p = [], 0
    top_rules = [r["rule"] for r in cand_g[:6]]
    for a, b in combinations(top_rules, 2):
        hyp_p += 1
        r = evaluate(gated, masks_g[a] & masks_g[b], f"{a} AND {b}", h_split, gated_days)
        if r is not None:
            r["scope"] = "flip&adx>=40"
            pair_res.append(r)
    cand_pair = validated(pair_res)

    n_hyp = hyp_all + hyp_g + hyp_p
    lines = [
        "# Decision-point sweep — 2026-07-12",
        "",
        "Goal (Kym directive): maximise WIN RATE with increasing precision, "
        "measured as the Wilson lower bound (95%), volume reported alongside.",
        "",
        f"Population: {base_n} settled real trades ({base_w} wins, "
        f"{base_w/base_n:.2%} WR) from {df['ts'].min():%Y-%m-%d} to "
        f"{df['ts'].max():%Y-%m-%d}; draws excluded. Break-even {BE:.2%} "
        f"(92% payout). Holdout: median-timestamp split at {h_split:%Y-%m-%d %H:%M}.",
        "",
        f"**Hypotheses tested: {n_hyp}** ({hyp_all} on all trades, {hyp_g} on the "
        f"gated population, {hyp_p} pairwise). At p<0.05 expect ~{n_hyp//20} "
        "false positives by chance — treat every candidate below as a shadow-arm "
        "or forward-test hypothesis, never as a proven edge.",
        "",
        "Candidate bar: n >= 300, >= 50 trades in each half, WR > break-even in "
        "BOTH halves independently, and binomial p < 0.05 overall.",
        "",
        "## TIGHTEN candidates — all settled trades",
        "",
        table(cand_all, top=15),
        "",
        f"## TIGHTEN candidates — within go-forward population (flip & ADX>=40, "
        f"n={len(gated)}, WR {gated['win'].mean():.1%})",
        "",
        table(cand_g, top=15),
        "",
        "## Pairwise refinements (AND of top gated singles)",
        "",
        table(cand_pair, top=10),
        "",
        "## LOOSEN candidates (volume only — no outcome data exists for skips)",
        "",
        loosen_analysis(),
        "",
        "## Post-cap-removal segment check (since 2026-07-12T08:24Z)",
        "",
        post_cap_change(df),
        "",
        "## Shadow-arm recommendations",
        "",
        "_Filled in by the analyst from the ranked tables above._",
        "",
    ]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {REPORT}")
    print(f"hypotheses: {n_hyp}; candidates: all={len(cand_all)} "
          f"gated={len(cand_g)} pairwise={len(cand_pair)}")
    for r in (cand_g or cand_all)[:8]:
        print(f"  {r['scope']:14s} {r['rule']:42s} n={r['n']:5d} wr={r['wr']:.1%} "
              f"lb={r['lb']:.1%} h2={r['h2_wr']:.1%} p={r['p']:.4f}")


if __name__ == "__main__":
    main()
