"""Test risk manager constraints."""

import pytest
from datetime import datetime, timedelta, timezone
from strategy.risk import RiskManager
from data.decisions_store import init_db, insert_decision


def test_max_balance_check():
    """Min balance check should block if insufficient."""
    rm = RiskManager(
        max_trades_per_hour=10,
        max_daily_loss_usd=20.0,
        cooldown_after_loss_seconds=120,
        trade_amount=1.0,
        min_balance_multiplier=5.0,
    )

    # Balance too low
    assert rm.is_allowed(current_balance=3.0) is False
    assert "Balance too low" in rm.block_reason

    # Balance sufficient
    assert rm.is_allowed(current_balance=5.0) is True


def test_max_trades_per_hour():
    """Should block after max trades/hour."""
    rm = RiskManager(
        max_trades_per_hour=2,
        max_daily_loss_usd=20.0,
        cooldown_after_loss_seconds=120,
        trade_amount=1.0,
        min_balance_multiplier=5.0,
    )

    # Place 2 trades
    rm.record_trade("CALL", 1.0, "WIN")
    rm.record_trade("PUT", 1.0, "WIN")

    # 3rd trade should be blocked
    assert rm.is_allowed(current_balance=100.0) is False
    assert "Max trades/hour" in rm.block_reason


def test_cooldown_after_loss():
    """Should block for cooldown period after loss."""
    rm = RiskManager(
        max_trades_per_hour=100,
        max_daily_loss_usd=20.0,
        cooldown_after_loss_seconds=60,
        trade_amount=1.0,
        min_balance_multiplier=5.0,
    )

    # Record a loss
    rm.record_trade("CALL", 1.0, "LOSS")

    # Immediate next trade should be blocked
    assert rm.is_allowed(current_balance=100.0) is False
    assert "Cooling down" in rm.block_reason


def _trade_row(ts: datetime, *, outcome: str, pnl: float, stake: float = 1.5) -> dict:
    return {
        "ts": ts.isoformat(),
        "cycle_id": "test",
        "trade_id": f"{outcome}-{ts.timestamp()}",
        "pair_api": "EURUSD_otc",
        "decision": "TRADE",
        "shadow": False,
        "our_direction": "CALL",
        "expiry_seconds": 5,
        "outcome": outcome,
        "pnl": pnl,
        "stake": stake,
        "bot_direction": "CALL",
    }


def test_seed_from_db_restores_daily_loss_limit(tmp_path):
    """Restarted risk manager should still block after today's DB loss cap."""
    db = tmp_path / "decisions.db"
    init_db(db)
    now = datetime(2026, 6, 25, 8, 30, tzinfo=timezone.utc)
    insert_decision(db, _trade_row(now - timedelta(hours=2), outcome="loss", pnl=-30.0))
    insert_decision(db, _trade_row(now - timedelta(hours=1), outcome="loss", pnl=-25.0))

    rm = RiskManager(
        max_trades_per_hour=100,
        max_daily_loss_usd=50.0,
        cooldown_after_loss_seconds=0,
        trade_amount=1.5,
        min_balance_multiplier=5.0,
    )

    assert rm.seed_from_db(db, now=now) == 2
    assert rm.daily_pnl == pytest.approx(-55.0)
    assert rm.is_allowed(current_balance=100.0) is False
    assert "Daily loss limit exceeded" in rm.block_reason


def test_seed_from_db_ignores_trades_outside_rolling_day(tmp_path):
    """Risk seed should match dashboard's rolling 1D window."""
    db = tmp_path / "decisions.db"
    init_db(db)
    now = datetime(2026, 6, 25, 8, 30, tzinfo=timezone.utc)
    insert_decision(db, _trade_row(now - timedelta(hours=25), outcome="loss", pnl=-55.0))

    rm = RiskManager(
        max_trades_per_hour=100,
        max_daily_loss_usd=50.0,
        cooldown_after_loss_seconds=0,
        trade_amount=1.5,
        min_balance_multiplier=5.0,
    )

    assert rm.seed_from_db(db, now=now) == 0
    assert rm.daily_pnl == pytest.approx(0.0)
    assert rm.is_allowed(current_balance=100.0) is True


def test_seed_from_db_restores_hourly_trade_count(tmp_path):
    """Restarted risk manager should preserve the trades/hour throttle."""
    db = tmp_path / "decisions.db"
    init_db(db)
    now = datetime(2026, 6, 25, 8, 30, tzinfo=timezone.utc)
    insert_decision(db, _trade_row(now - timedelta(minutes=45), outcome="win", pnl=1.38))
    insert_decision(db, _trade_row(now - timedelta(minutes=10), outcome="draw", pnl=0.0))

    rm = RiskManager(
        max_trades_per_hour=2,
        max_daily_loss_usd=50.0,
        cooldown_after_loss_seconds=0,
        trade_amount=1.5,
        min_balance_multiplier=5.0,
    )

    assert rm.seed_from_db(db, now=now) == 2
    assert rm.is_allowed(current_balance=100.0, now=now) is False
    assert "Max trades/hour" in rm.block_reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
