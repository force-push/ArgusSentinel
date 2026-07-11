"""Shared test fixtures.

The settings singleton loads the live .env.config, so operational policy
toggles flipped for production (e.g. the ADX flip gate forward test) would
otherwise leak into every test. Pin such toggles to their code defaults here;
tests that exercise a toggle opt in explicitly via monkeypatch.
"""
import pytest

from config.settings import BotSettings, settings


@pytest.fixture(autouse=True)
def _neutral_adx_flip_gate(monkeypatch):
    monkeypatch.setattr(
        settings, "adx_flip_gate_enabled",
        BotSettings.model_fields["adx_flip_gate_enabled"].default,
    )
    monkeypatch.setattr(
        settings, "adx_flip_gate_min",
        BotSettings.model_fields["adx_flip_gate_min"].default,
    )
