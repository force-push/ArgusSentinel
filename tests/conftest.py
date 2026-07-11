"""Shared test fixtures.

The settings singleton loads the live .env.config, so operational policy
toggles flipped for production (e.g. the ADX flip gate forward test) would
otherwise leak into every test. Pin such toggles to their code defaults here;
tests that exercise a toggle opt in explicitly via monkeypatch.
"""
import pytest

from config.settings import BotSettings, settings


_LIVE_TOGGLES = ("adx_flip_gate_enabled", "adx_flip_gate_min", "dynamic_pairs_enabled")


@pytest.fixture(autouse=True)
def _neutral_live_toggles(monkeypatch):
    for field in _LIVE_TOGGLES:
        monkeypatch.setattr(settings, field, BotSettings.model_fields[field].default)
