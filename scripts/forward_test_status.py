"""Status of the ADX flip gate forward test (pre-registered 2026-07-11).

Registration (reports/forward_test_adx_gate.md):
- Gate: only flip entries with ADX >= 40 trade (ADX_FLIP_GATE_ENABLED=true).
- Evaluate at >= 300 settled trades. Kill early if WR < 52.1% at any point
  after 150 settled trades. Success: WR >= 54% at 300+ (one-sided binomial
  vs 52.08% break-even, p < 0.05).

Read-only. Run: ./venv/bin/python scripts/forward_test_status.py
"""

import sqlite3
from pathlib import Path

from scipy.stats import binomtest

DB = Path(__file__).resolve().parent.parent / "data" / "decisions.db"
TEST_START = "2026-07-11T13:59:20+00:00"
BE = 0.5208
MIN_EVAL_N = 300
EARLY_KILL_N = 150


def main() -> None:
    con = sqlite3.connect(DB)
    settled = con.execute(
        "SELECT outcome, COUNT(*), COALESCE(SUM(pnl),0) FROM decisions "
        "WHERE decision='TRADE' AND ts > ? AND outcome IN ('win','loss','draw') "
        "GROUP BY outcome",
        (TEST_START,),
    ).fetchall()
    counts = {o: (n, p) for o, n, p in settled}
    wins, losses = counts.get("win", (0, 0))[0], counts.get("loss", (0, 0))[0]
    draws = counts.get("draw", (0, 0))[0]
    pnl = sum(p for _, p in counts.values())
    n = wins + losses

    gate_skips = con.execute(
        "SELECT COUNT(*) FROM decisions WHERE decision='SKIP' AND ts > ? "
        "AND skip_reason LIKE '%adx_flip_gate%'",
        (TEST_START,),
    ).fetchone()[0]

    print(f"ADX flip gate forward test — started {TEST_START}")
    print(f"settled: {n} (win {wins} / loss {losses} / draw {draws})  pnl: {pnl:+.2f}")
    print(f"gate skips: {gate_skips}")
    if n == 0:
        print("verdict: NO DATA yet")
        return

    wr = wins / n
    p = binomtest(wins, n, BE, alternative="greater").pvalue
    print(f"wr: {wr:.4f}  (break-even {BE})  p_vs_be: {p:.4f}")

    if n >= EARLY_KILL_N and wr < 0.521:
        print(f"verdict: KILL — WR below break-even at n={n} (pre-registered early stop)")
    elif n < MIN_EVAL_N:
        print(f"verdict: RUNNING — {n}/{MIN_EVAL_N} settled trades")
    elif wr >= 0.54 and p < 0.05:
        print("verdict: PASS — edge confirmed at pre-registered thresholds")
    elif wr < 0.521:
        print("verdict: KILL — below break-even at evaluation size")
    else:
        print("verdict: INCONCLUSIVE — extend or stop per Kym's call")


if __name__ == "__main__":
    main()
