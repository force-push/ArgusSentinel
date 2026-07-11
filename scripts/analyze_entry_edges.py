"""Entry-edge deep dive over all settled live trades in decisions.db.

Buckets every settled win/loss trade by time, pair, and entry features,
tests each bucket's win rate against the 52.08% break-even (92% payout),
and runs a first-half/second-half stability split so regression-to-mean
candidates are flagged before anyone acts on them.

Read-only: no policy or config changes. Output: markdown to stdout.
"""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import binomtest

DB = Path(__file__).resolve().parent.parent / "data" / "decisions.db"
BE = 0.5208  # break-even WR at 92% payout
ADL = timezone(timedelta(hours=9, minutes=30))  # Australia/Adelaide (UTC+9:30)


def load() -> pd.DataFrame:
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT ts, pair_api, our_direction, outcome, pnl, data FROM decisions "
        "WHERE decision='TRADE' AND outcome IN ('win','loss') ORDER BY id"
    ).fetchall()
    recs = []
    for ts, pair, direction, outcome, pnl, data in rows:
        j = json.loads(data)
        fm = j.get("flip_metrics") or {}
        sa = j.get("signal_assessment") or {}
        t = datetime.fromisoformat(ts)
        recs.append(
            {
                "ts": t,
                "hour_utc": t.astimezone(timezone.utc).hour,
                "hour_adl": t.astimezone(ADL).hour,
                "dow_utc": t.astimezone(timezone.utc).strftime("%a"),
                "pair": pair,
                "direction": direction,
                "win": 1 if outcome == "win" else 0,
                "pnl": pnl or 0.0,
                "payout": j.get("payout_pct"),
                "agreement": j.get("agreement"),
                "top_pick": j.get("bot_is_top_pick"),
                "confluence": j.get("our_confluence_score"),
                "bot_wr": j.get("bot_win_rate"),
                "agreeing_signals": (sa.get("model_features") or {}).get("agreeing_signals"),
                "entry_kind": fm.get("entry_kind"),
                "flipped": fm.get("flipped"),
                "adx": fm.get("adx"),
                "adx_rising": fm.get("adx_rising"),
                "bars_in_trend": fm.get("bars_in_trend"),
                "dist_atr": fm.get("dist_atr"),
                "macd_gap_atr": fm.get("macd_gap_atr"),
                "gap_expansion": fm.get("gap_expansion"),
                "rsi": fm.get("rsi"),
                "atr_bps": fm.get("atr_bps"),
                "bb_width_bps": fm.get("bb_width_bps"),
                "macd_sign_consistency": fm.get("macd_sign_consistency"),
                "trade_strength": fm.get("trade_strength"),
                "roc": fm.get("roc"),
            }
        )
    return pd.DataFrame(recs)


def bucket_table(df: pd.DataFrame, key, min_n: int = 60, label: str | None = None) -> pd.DataFrame:
    """WR / PnL / p-value-vs-BE per bucket, plus half-split stability."""
    mid = df["ts"].sort_values().iloc[len(df) // 2]
    out = []
    for val, g in df.groupby(key, dropna=False, observed=True):
        n = len(g)
        if n < min_n:
            continue
        w = int(g["win"].sum())
        wr = w / n
        p = binomtest(w, n, BE, alternative="greater").pvalue
        h1 = g[g["ts"] <= mid]
        h2 = g[g["ts"] > mid]
        wr1 = h1["win"].mean() if len(h1) >= 20 else np.nan
        wr2 = h2["win"].mean() if len(h2) >= 20 else np.nan
        out.append(
            {
                (label or (key if isinstance(key, str) else "bucket")): val,
                "n": n,
                "wr": round(wr, 4),
                "pnl": round(g["pnl"].sum(), 2),
                "p_vs_be": round(p, 4),
                "wr_h1": round(wr1, 3) if wr1 == wr1 else None,
                "wr_h2": round(wr2, 3) if wr2 == wr2 else None,
            }
        )
    res = pd.DataFrame(out)
    return res.sort_values("wr", ascending=False) if len(res) else res


def show(title: str, tbl: pd.DataFrame, top: int | None = None) -> None:
    print(f"\n## {title}\n")
    if not len(tbl):
        print("(no bucket met the minimum-n threshold)")
        return
    t = tbl.head(top) if top else tbl
    print(t.to_string(index=False))


def main() -> None:
    df = load()
    n, w = len(df), int(df["win"].sum())
    print("# ArgusSentinel entry-edge deep dive (all settled live trades)")
    print(f"\ntrades={n}  wins={w}  wr={w/n:.4f}  break_even={BE}  pnl={df['pnl'].sum():.2f}")
    print(f"span: {df['ts'].min()} .. {df['ts'].max()}")

    show("Hour of day (UTC)", bucket_table(df, "hour_utc", min_n=80))
    show("Hour of day (Adelaide)", bucket_table(df, "hour_adl", min_n=80))
    show("Day of week (UTC)", bucket_table(df, "dow_utc", min_n=80))
    show("Pair", bucket_table(df, "pair", min_n=60))
    show("Direction", bucket_table(df, "direction", min_n=80))

    df["pair_dir"] = df["pair"] + " " + df["direction"].astype(str)
    show("Pair x direction", bucket_table(df, "pair_dir", min_n=60), top=15)

    show("Entry kind", bucket_table(df, "entry_kind", min_n=40))
    show("Flipped", bucket_table(df, "flipped", min_n=40))
    show("ADX rising", bucket_table(df, "adx_rising", min_n=80))
    show("Agreement (bot vs our signal)", bucket_table(df, "agreement", min_n=80))
    show("Bot top pick", bucket_table(df, "top_pick", min_n=80))
    show("Agreeing signals", bucket_table(df, "agreeing_signals", min_n=60))

    for feat, edges in {
        "adx": [0, 15, 20, 25, 30, 40, 100],
        "bars_in_trend": [0, 2, 4, 6, 10, 20, 1000],
        "dist_atr": [0, 0.5, 1, 2, 3, 100],
        "macd_gap_atr": [-100, 0, 0.25, 0.5, 1, 100],
        "gap_expansion": [-100, 0, 0.25, 0.5, 1, 100],
        "rsi": [0, 30, 40, 50, 60, 70, 100],
        "atr_bps": [0, 0.02, 0.05, 0.1, 0.2, 100],
        "bb_width_bps": [0, 0.05, 0.1, 0.2, 0.5, 100],
        "macd_sign_consistency": [0, 0.5, 0.8, 0.99, 1.01],
        "bot_wr": [0, 0.55, 0.6, 0.65, 0.7, 1.01],
        "confluence": [0, 0.5, 0.9, 1.01],
    }.items():
        s = pd.to_numeric(df[feat], errors="coerce")
        if s.notna().sum() < 200:
            continue
        d = df[s.notna()].copy()
        d["bucket"] = pd.cut(s.dropna(), bins=edges)
        show(f"Feature: {feat}", bucket_table(d, "bucket", min_n=80, label=feat))

    # weekly WR trend — is the whole book drifting?
    df["week"] = df["ts"].dt.tz_convert("UTC").dt.strftime("%G-W%V")
    show("Weekly win rate", bucket_table(df, "week", min_n=100).sort_values("week"))


if __name__ == "__main__":
    main()
