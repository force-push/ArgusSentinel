"""Tests for RunStreakTracker."""
from __future__ import annotations

import pytest
from strategy.run_streak import RunStreakTracker


def make_tracker() -> RunStreakTracker:
    return RunStreakTracker()


# ── get_stake ──────────────────────────────────────────────────────────────────

def test_no_streak_returns_base():
    t = make_tracker()
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert stake == 1.50
    assert level == 0


def test_one_win_adds_one_increment():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "win")
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 1
    assert stake == pytest.approx(2.25)


def test_two_wins_adds_two_increments():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "win")
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 2
    assert stake == pytest.approx(3.00)


def test_capped_at_max_level():
    t = make_tracker()
    for _ in range(10):
        t.record_outcome("EURUSD_otc", "win")
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 3
    assert stake == pytest.approx(3.75)


def test_loss_resets_streak():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "loss")
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 0
    assert stake == pytest.approx(1.50)


def test_draw_does_not_reset_streak():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "draw")
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 2
    assert stake == pytest.approx(3.00)


def test_draw_does_not_increment_streak():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "draw")
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 0
    assert stake == pytest.approx(1.50)


def test_streaks_are_per_pair():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("MATIC_otc", "win")

    _, eur_level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    _, mat_level = t.get_stake("MATIC_otc", 1.50, increment=0.75, max_level=3)
    assert eur_level == 2
    assert mat_level == 1


def test_loss_on_one_pair_does_not_affect_other():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("MATIC_otc", "win")
    t.record_outcome("EURUSD_otc", "loss")

    _, eur_level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    _, mat_level = t.get_stake("MATIC_otc", 1.50, increment=0.75, max_level=3)
    assert eur_level == 0
    assert mat_level == 1


def test_win_after_reset_restarts_streak():
    t = make_tracker()
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "win")
    t.record_outcome("EURUSD_otc", "loss")
    t.record_outcome("EURUSD_otc", "win")
    stake, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 1
    assert stake == pytest.approx(2.25)


# ── seed_from_db ───────────────────────────────────────────────────────────────

def _recent_ts(minutes_ago):
    """Timestamps must stay inside the seed lookback window relative to *now* —
    hardcoded dates silently age out and the seed returns 0 pairs."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _db_row(trade_id, outcome, ts, pair="EURUSD_otc"):
    return {
        "cycle_id": "C1", "pair_raw": pair, "pair_api": pair,
        "bot_win_rate": 0.5, "bot_is_top_pick": False, "bot_direction": "CALL",
        "bot_setup": "signals", "bot_indicators_raw": "",
        "our_direction": "CALL", "our_confluence_score": 0.42,
        "our_signal_breakdown": {}, "agreement": True,
        "combined_probability": 0.55, "expiry_seconds": 5,
        "decision": "TRADE", "skip_reason": None, "stake": 1.50,
        "shadow": False, "shadow_kind": None, "trade_id": trade_id,
        "status": "PENDING", "outcome": outcome,
        "pnl": 1.38 if outcome == "win" else -1.50,
        "ts": ts,
    }


def test_seed_from_db_reconstructs_win_streak(tmp_path):
    db = str(tmp_path / "test.db")
    from data import decisions_store as store
    store.init_db(db)

    store.insert_decision(db, _db_row("t1", "win", _recent_ts(3)), clock=1.0)
    store.insert_decision(db, _db_row("t2", "win", _recent_ts(2)), clock=2.0)
    store.insert_decision(db, _db_row("t3", "win", _recent_ts(1)), clock=3.0)

    t = make_tracker()
    t.seed_from_db(db, lookback_hours=24.0, max_level=3)

    _, level = t.get_stake("EURUSD_otc", 1.50, increment=0.75, max_level=3)
    assert level == 3  # capped at max_level


def test_seed_from_db_stops_at_loss(tmp_path):
    db = str(tmp_path / "test.db")
    from data import decisions_store as store
    store.init_db(db)

    # loss then 2 wins (loss is oldest)
    store.insert_decision(db, _db_row("t1", "loss", _recent_ts(3), pair="MATIC_otc"), clock=1.0)
    store.insert_decision(db, _db_row("t2", "win",  _recent_ts(2), pair="MATIC_otc"), clock=2.0)
    store.insert_decision(db, _db_row("t3", "win",  _recent_ts(1), pair="MATIC_otc"), clock=3.0)

    t = make_tracker()
    t.seed_from_db(db, lookback_hours=24.0, max_level=3)

    _, level = t.get_stake("MATIC_otc", 1.50, increment=0.75, max_level=3)
    assert level == 2  # only the 2 wins after the loss count
