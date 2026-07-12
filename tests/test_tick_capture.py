"""Tests for broker/tick_capture.py — buffered .jsonl.gz price capture."""
import gzip
import json

import pandas as pd
import pytest

from broker.tick_capture import TickCapture, _BUFFER_CAP, _FLUSH_ROWS
from broker.tick_stream import TickAccumulator, _EPOCH_OFFSET
from config.settings import settings


def _read_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setattr(settings, "tick_capture_enabled", True)


def test_disabled_records_nothing(tmp_path):
    cap = TickCapture(tmp_path)  # conftest pins tick_capture_enabled=False
    cap.record_tick("EURUSD_otc", 1_700_000_000.5, 1.2345)
    cap.flush()
    assert list(tmp_path.iterdir()) == []


def test_tick_and_seed_roundtrip(tmp_path, enabled):
    cap = TickCapture(tmp_path, now_fn=lambda: 1_700_000_000.0)
    cap.record_tick("EURUSD_otc", 1_700_000_000.5, 1.2345)
    cap.record_seed("EURUSD_otc", 1_699_999_999.0, 1.2344)
    cap.flush()
    files = list(tmp_path.iterdir())
    assert len(files) == 1 and files[0].name.endswith(".jsonl.gz")
    rows = _read_rows(files[0])
    assert rows == [
        {"k": "t", "p": "EURUSD_otc", "t": 1_700_000_000.5, "px": 1.2345},
        {"k": "s", "p": "EURUSD_otc", "t": 1_699_999_999.0, "px": 1.2344},
    ]


def test_row_threshold_autoflushes(tmp_path, enabled):
    cap = TickCapture(tmp_path, now_fn=lambda: 1_700_000_000.0)
    for i in range(_FLUSH_ROWS):
        cap.record_tick("X_otc", 1_700_000_000.0 + i, 1.0)
    assert len(_read_rows(next(tmp_path.iterdir()))) == _FLUSH_ROWS


def test_time_threshold_autoflushes(tmp_path, enabled):
    clock = {"now": 1_700_000_000.0}
    cap = TickCapture(tmp_path, now_fn=lambda: clock["now"])
    cap.record_tick("X_otc", clock["now"], 1.0)
    clock["now"] += 6.0  # > _FLUSH_INTERVAL_S
    cap.record_tick("X_otc", clock["now"], 1.1)
    assert len(_read_rows(next(tmp_path.iterdir()))) == 2


def test_daily_rotation(tmp_path, enabled):
    clock = {"now": 1_700_006_400.0}  # 2023-11-15 00:00 UTC
    cap = TickCapture(tmp_path, now_fn=lambda: clock["now"])
    cap.record_tick("X_otc", clock["now"], 1.0)
    cap.flush()
    clock["now"] += 86_400.0
    cap.record_tick("X_otc", clock["now"], 2.0)
    cap.flush()
    assert len(list(tmp_path.iterdir())) == 2


def test_multi_member_gzip_appends_are_readable(tmp_path, enabled):
    cap = TickCapture(tmp_path, now_fn=lambda: 1_700_000_000.0)
    cap.record_tick("X_otc", 1.0, 1.0)
    cap.flush()
    cap.record_tick("X_otc", 2.0, 2.0)
    cap.flush()
    assert len(_read_rows(next(tmp_path.iterdir()))) == 2


def test_bar_watermark_dedup(tmp_path, enabled):
    cap = TickCapture(tmp_path, now_fn=lambda: 1_700_000_000.0)
    idx = pd.to_datetime([1_700_000_000, 1_700_000_001], unit="s", utc=True)
    df = pd.DataFrame({"o": [1.0, 1.1], "h": [1.2, 1.3], "l": [0.9, 1.0],
                       "c": [1.1, 1.2], "v": [3.0, 4.0]}, index=idx)
    cap.record_bars("X_otc", df, 1)
    cap.record_bars("X_otc", df, 1)  # overlapping refetch → no duplicates
    idx2 = pd.to_datetime([1_700_000_001, 1_700_000_002], unit="s", utc=True)
    df2 = pd.DataFrame({"o": [1.1, 1.2], "h": [1.3, 1.4], "l": [1.0, 1.1],
                        "c": [1.2, 1.3], "v": [4.0, 5.0]}, index=idx2)
    cap.record_bars("X_otc", df2, 1)  # only the new second is recorded
    cap.record_bars("X_otc", df, 5)   # different period → separate watermark
    cap.flush()
    rows = _read_rows(next(tmp_path.iterdir()))
    assert [r["t"] for r in rows if r["per"] == 1] == [
        1_700_000_000.0, 1_700_000_001.0, 1_700_000_002.0]
    assert len([r for r in rows if r["per"] == 5]) == 2
    assert rows[0] == {"k": "b", "p": "X_otc", "t": 1_700_000_000.0, "per": 1,
                       "o": 1.0, "h": 1.2, "l": 0.9, "c": 1.1, "v": 3.0}


def test_buffer_cap_drops_instead_of_growing(tmp_path, enabled, monkeypatch):
    cap = TickCapture(tmp_path, now_fn=lambda: 1_700_000_000.0)
    # Make flushing a no-op to simulate a stalled writer.
    monkeypatch.setattr(cap, "_flush", lambda: None)
    for i in range(_BUFFER_CAP + 10):
        cap.record_tick("X_otc", float(i), 1.0)
    assert len(cap._buf) == _BUFFER_CAP
    assert cap._dropped == 10


def test_malformed_input_never_raises(tmp_path, enabled):
    cap = TickCapture(tmp_path, now_fn=lambda: 1_700_000_000.0)
    cap.record_tick("X_otc", "not-a-number", 1.0)   # coercion fails inside
    cap.record_bars("X_otc", object(), 1)            # not a DataFrame
    cap.record_bars("X_otc", None, 1)
    cap.flush()


def test_accumulator_feeds_capture(tmp_path, enabled, monkeypatch):
    import broker.tick_stream as ts_mod
    cap = TickCapture(tmp_path, now_fn=lambda: 1_700_000_000.0)
    monkeypatch.setattr(ts_mod, "capture", cap)
    acc = TickAccumulator("EURUSD_otc")
    acc.process([["EURUSD_otc", 1_700_000_000.0 + _EPOCH_OFFSET, 1.5]])
    acc.process([["OTHER_otc", 1_700_000_000.0 + _EPOCH_OFFSET, 9.9]])  # wrong pair: ignored
    cap.flush()
    rows = _read_rows(next(tmp_path.iterdir()))
    assert rows == [{"k": "t", "p": "EURUSD_otc", "t": 1_700_000_000.0, "px": 1.5}]
