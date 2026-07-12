"""ADX flip entry gate — 2026-07-11 forward test (reports/entry_edges_2026-07-11.md).

The gate is a hard entry filter layered ON TOP of existing policy: when enabled,
only flip entries with ADX >= threshold may trade. Everything else about the
assessment (penalties, probabilities) stays untouched so the forward-test
population matches the validated historical one (ADX>40 flips: 56.8% WR, n=544).
"""
import pandas as pd
import pytest

from config.settings import settings
from tests.test_manager_signals_loop import _strength_mgr

CLEAN_DF = pd.DataFrame([
    {"o": 1.00, "c": 1.01},
    {"o": 1.01, "c": 1.03},
])


def _assess(mgr, flip_metrics, tracked_rate=0.58, n_tracked=40):
    return mgr._assess_trade_signal(
        pair="USDRUB_otc",
        direction="CALL",
        expiry=5,
        payout_pct=92,
        tracked_rate=tracked_rate,
        n_tracked=n_tracked,
        flip_metrics=flip_metrics,
        df=CLEAN_DF,
        prospective_stake=1.5,
        our_confluence=1.0,
        agreeing_signals=3,
        bot_is_top_pick=False,
    )


def _base(monkeypatch):
    monkeypatch.setattr(settings, "stake_amount", 1.5)
    monkeypatch.setattr(settings, "min_expected_value", 0.0)


def test_gate_disabled_by_default():
    from config.settings import BotSettings
    assert BotSettings.model_fields["adx_flip_gate_enabled"].default is False
    assert BotSettings.model_fields["adx_flip_gate_min"].default == 40.0


def test_gate_off_leaves_trend_entries_tradeable(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(settings, "adx_flip_gate_enabled", False)
    mgr = _strength_mgr(pair_wr=0.55, pair_n=100)

    assessment = _assess(mgr, {
        "entry_kind": "trend", "dist_atr": 1.5, "macd_gap_atr": 0.5,
        "adx": 30.0, "rsi": 60.0,
    })

    assert assessment["skip"] is False
    assert not any(p.startswith("adx_flip_gate") for p in assessment["penalties"])


def test_gate_blocks_trend_entry_even_with_strong_stats(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(settings, "adx_flip_gate_enabled", True)
    mgr = _strength_mgr(pair_wr=0.60, pair_n=100)

    assessment = _assess(mgr, {
        "entry_kind": "trend", "dist_atr": 1.5, "macd_gap_atr": 0.5,
        "adx": 50.0, "rsi": 60.0,
    })

    assert assessment["skip"] is True
    assert "adx_flip_gate_entry_kind=trend" in assessment["penalties"]


def test_gate_blocks_flip_below_min_adx(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(settings, "adx_flip_gate_enabled", True)
    monkeypatch.setattr(settings, "adx_flip_gate_min", 40.0)
    mgr = _strength_mgr(pair_wr=0.60, pair_n=100)

    assessment = _assess(mgr, {
        "entry_kind": "flip", "bars_in_trend": 5, "gap_expansion": 0.3,
        "adx": 32.0, "rsi": 60.0,
    })

    assert assessment["skip"] is True
    assert "adx_flip_gate_adx=32.0<40.0" in assessment["penalties"]


def test_gate_blocks_flip_with_missing_adx(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(settings, "adx_flip_gate_enabled", True)
    mgr = _strength_mgr(pair_wr=0.60, pair_n=100)

    assessment = _assess(mgr, {
        "entry_kind": "flip", "bars_in_trend": 5, "gap_expansion": 0.3,
        "rsi": 60.0,
    })

    assert assessment["skip"] is True
    assert "adx_flip_gate_adx_missing" in assessment["penalties"]


def test_gate_passes_strong_adx_flip(monkeypatch):
    _base(monkeypatch)
    monkeypatch.setattr(settings, "adx_flip_gate_enabled", True)
    monkeypatch.setattr(settings, "adx_flip_gate_min", 40.0)
    mgr = _strength_mgr(pair_wr=0.55, pair_n=100)

    assessment = _assess(mgr, {
        "entry_kind": "flip", "bars_in_trend": 5, "gap_expansion": 0.3,
        "adx": 45.0, "rsi": 60.0,
    })

    assert assessment["skip"] is False
    assert not any(p.startswith("adx_flip_gate") for p in assessment["penalties"])


def test_gate_does_not_soften_existing_penalties(monkeypatch):
    """A high-ADX flip that fails other checks must still be skipped."""
    _base(monkeypatch)
    monkeypatch.setattr(settings, "adx_flip_gate_enabled", True)
    mgr = _strength_mgr(pair_wr=0.51, pair_n=100)

    assessment = _assess(mgr, {
        "entry_kind": "flip", "bars_in_trend": 14, "gap_expansion": 0.05,
        "adx": 45.0, "rsi": 61.0,
    }, tracked_rate=0.50, n_tracked=40)

    assert assessment["skip"] is True
    # stale_flip removed 2026-07-13 (inverted heuristic); the remaining
    # penalties (marginal_pair_wr, soft_direction_wr, weak gap) still skip.
    assert "marginal_pair_wr=51.0%/n=100" in assessment["penalties"]
    assert not any("stale_flip" in x for x in assessment["penalties"])
