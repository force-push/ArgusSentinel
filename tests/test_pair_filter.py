"""Tests for the shared pair-eligibility filter."""
from __future__ import annotations

from types import SimpleNamespace

from strategy import pair_filter
from strategy.pair_filter import is_pair_allowed


def _cfg(regex="", allowed=None, blocked=None):
    return SimpleNamespace(
        allowed_pair_regex=regex,
        allowed_pairs=allowed or [],
        blocked_pairs=blocked or [],
    )


def test_regex_allows_matching_symbols():
    cfg = _cfg(regex="(USD|CNY|CNH|EUR)")
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert is_pair_allowed("JODCNY_otc", cfg)
    assert is_pair_allowed("EURNZD_otc", cfg)
    assert is_pair_allowed("USDCNH_otc", cfg)
    assert not is_pair_allowed("CADJPY_otc", cfg)   # no USD/CNY/CNH/EUR token


def test_regex_gbp_lookahead_excludes_all_gbp_crosses():
    cfg = _cfg(regex="^(?!.*GBP).*(USD|CNY|CNH|EUR)")
    assert is_pair_allowed("EURUSD_otc", cfg)
    assert is_pair_allowed("AUDUSD_otc", cfg)
    # GBP crosses are excluded even though they contain USD/EUR
    assert not is_pair_allowed("GBPUSD_otc", cfg)
    assert not is_pair_allowed("EURGBP_otc", cfg)
    assert not is_pair_allowed("GBPAUD_otc", cfg)


def test_regex_still_honours_blocklist():
    cfg = _cfg(regex="(USD)", blocked=["USDARS_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("USDARS_otc", cfg)


def test_exact_allowlist_when_no_regex():
    cfg = _cfg(allowed=["AUDUSD_otc", "EURNZD_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("EURUSD_otc", cfg)


def test_blocklist_only_when_no_allowlist():
    cfg = _cfg(blocked=["USDARS_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("USDARS_otc", cfg)


def test_bad_regex_falls_through_to_allowlist(monkeypatch):
    # An invalid pattern must not raise — it degrades to "no regex".
    pair_filter._compiled.clear()
    cfg = _cfg(regex="(unclosed", allowed=["AUDUSD_otc"])
    assert is_pair_allowed("AUDUSD_otc", cfg)
    assert not is_pair_allowed("EURUSD_otc", cfg)


def test_empty_symbol_rejected():
    assert not is_pair_allowed("", _cfg(regex="(USD)"))


# ── Dynamic pair universe (data/pair_universe.json hot-reload) ──────────────

def _dyn_cfg(tmp_path, pairs=None, enabled=True, max_age=24.0, static=None):
    import json as _json
    path = tmp_path / "pair_universe.json"
    if pairs is not None:
        path.write_text(_json.dumps({"pairs": pairs}))
    cfg = SimpleNamespace(
        allowed_pair_regex="",
        allowed_pairs=static or ["STATIC_otc"],
        blocked_pairs=[],
        dynamic_pairs_enabled=enabled,
        dynamic_pairs_max_age_hours=max_age,
    )
    return cfg, path


def _reset_universe_cache():
    pair_filter._universe_cache.update(mtime=None, pairs=None)


def test_dynamic_universe_overrides_static_allowlist(tmp_path, monkeypatch):
    _reset_universe_cache()
    cfg, path = _dyn_cfg(tmp_path, pairs=["MATIC_otc", "USDRUB_otc"])
    monkeypatch.setattr(pair_filter, "UNIVERSE_PATH", path)
    assert is_pair_allowed("MATIC_otc", cfg)
    assert not is_pair_allowed("STATIC_otc", cfg)   # dynamic replaces static


def test_dynamic_disabled_uses_static_allowlist(tmp_path, monkeypatch):
    _reset_universe_cache()
    cfg, path = _dyn_cfg(tmp_path, pairs=["MATIC_otc"], enabled=False)
    monkeypatch.setattr(pair_filter, "UNIVERSE_PATH", path)
    assert is_pair_allowed("STATIC_otc", cfg)
    assert not is_pair_allowed("MATIC_otc", cfg)


def test_missing_universe_file_falls_back_to_static(tmp_path, monkeypatch):
    _reset_universe_cache()
    cfg, path = _dyn_cfg(tmp_path, pairs=None)      # file never written
    monkeypatch.setattr(pair_filter, "UNIVERSE_PATH", path)
    assert is_pair_allowed("STATIC_otc", cfg)


def test_stale_universe_file_falls_back_to_static(tmp_path, monkeypatch):
    import os
    _reset_universe_cache()
    cfg, path = _dyn_cfg(tmp_path, pairs=["MATIC_otc"], max_age=1.0)
    old = 7200  # 2h ago > 1h max age
    stamp = __import__("time").time() - old
    os.utime(path, (stamp, stamp))
    monkeypatch.setattr(pair_filter, "UNIVERSE_PATH", path)
    assert is_pair_allowed("STATIC_otc", cfg)
    assert not is_pair_allowed("MATIC_otc", cfg)


def test_corrupt_universe_file_falls_back_to_static(tmp_path, monkeypatch):
    _reset_universe_cache()
    cfg, path = _dyn_cfg(tmp_path, pairs=None)
    path.write_text("{not json")
    monkeypatch.setattr(pair_filter, "UNIVERSE_PATH", path)
    assert is_pair_allowed("STATIC_otc", cfg)


def test_dynamic_universe_hot_reloads_on_mtime_change(tmp_path, monkeypatch):
    import json as _json, os
    _reset_universe_cache()
    cfg, path = _dyn_cfg(tmp_path, pairs=["MATIC_otc"])
    monkeypatch.setattr(pair_filter, "UNIVERSE_PATH", path)
    assert is_pair_allowed("MATIC_otc", cfg)
    path.write_text(_json.dumps({"pairs": ["DOGE_otc"]}))
    stamp = __import__("time").time() + 1           # force a distinct mtime
    os.utime(path, (stamp, stamp))
    assert is_pair_allowed("DOGE_otc", cfg)
    assert not is_pair_allowed("MATIC_otc", cfg)
