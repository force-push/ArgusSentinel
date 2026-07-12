"""Persistent tick/bar capture for tick-replay backtesting.

Nothing the bot receives from PocketOption was persisted before this module:
1s candles were built in memory and discarded, so entry-timing and
expiry-duration questions ("what if we entered 2 bars later / used 60s
expiry?") were unanswerable from history. This module records the raw price
stream so those replays become possible.

What gets captured (all rows carry a ``k`` kind tag):
  k="t"  live tick        {p, t, px}        from TickAccumulator.process()
  k="s"  history-seed tick {p, t, px}       from the changeSymbol seed string
  k="b"  prefetched bar   {p, t, per, o, h, l, c, v}  from the poll loop's
         history() prefetch (deduped by a per-(pair, period) watermark so the
         overlapping 200-bar windows fetched every cycle are stored once)

Coverage: ticks cover the FlipStreamer's streamed pairs (subscription cap ~4)
plus any focus-session pair — the paths that place tightest-timing trades.
Bars cover every pair the poll loop evaluates each cycle at 1s (and 5s shadow)
resolution. Pairs never evaluated are not captured.

Storage: ``data/ticks/YYYY-MM-DD.jsonl.gz`` (UTC date), one JSON object per
line. Each flush appends an independent gzip member, which is valid gzip —
readers just see a concatenated stream — and means a crash can never corrupt
previously flushed data. Expected volume: ~2 ticks/s x ~5 streamed pairs plus
deduped bars for ~10 scanned pairs ≈ 1.5M rows/day ≈ 15-40 MB/day compressed.

Fail-silent contract (same as _record_feed_stats): capture must NEVER raise
into, block, or meaningfully slow the trading loop. Every public method
swallows exceptions, logs one warning per failure burst, and degrades to
dropping rows (counted) if the buffer fills.
"""
from __future__ import annotations

import gzip
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config.settings import settings
from utils.logger import log

CAPTURE_DIR = Path("data/ticks")

_FLUSH_INTERVAL_S = 5.0     # flush at most this many seconds after first buffered row
_FLUSH_ROWS = 2000          # ...or as soon as this many rows are buffered
_BUFFER_CAP = 50_000        # hard cap; beyond this rows are dropped (and counted)
_WARN_EVERY_S = 300.0       # rate-limit failure warnings


class TickCapture:
    """Buffered, fail-silent appender of price rows to daily .jsonl.gz files."""

    def __init__(
        self,
        directory: Path | str = CAPTURE_DIR,
        now_fn: Callable[[], float] = time.time,
    ) -> None:
        self._dir = Path(directory)
        self._now = now_fn
        self._buf: list[dict] = []
        self._first_buffered_at: float | None = None
        self._watermarks: dict[tuple[str, int], float] = {}  # (pair, period) → max bar ts
        self._dropped = 0
        self._last_warn_at = 0.0

    # ── public recorders (hot path: list.append + occasional flush) ─────────

    def record_tick(self, pair: str, ts_utc: float, price: float) -> None:
        if not settings.tick_capture_enabled:
            return
        try:
            self._add({"k": "t", "p": pair, "t": float(ts_utc), "px": float(price)})
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)

    def record_seed(self, pair: str, ts_utc: float, price: float) -> None:
        if not settings.tick_capture_enabled:
            return
        try:
            self._add({"k": "s", "p": pair, "t": float(ts_utc), "px": float(price)})
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)

    def record_bars(self, pair: str, df: Any, period: int) -> None:
        """Record prefetched OHLC bars newer than the (pair, period) watermark.

        The poll loop re-fetches an overlapping ~200-bar window every cycle;
        the watermark ensures each bar is stored exactly once.
        """
        if not settings.tick_capture_enabled:
            return
        try:
            if df is None or len(df) == 0:
                return
            key = (pair, int(period))
            wm = self._watermarks.get(key, float("-inf"))
            new_wm = wm
            for ts, row in df.iterrows():
                t = float(ts.timestamp())
                if t <= wm:
                    continue
                self._add({
                    "k": "b", "p": pair, "t": t, "per": int(period),
                    "o": float(row["o"]), "h": float(row["h"]),
                    "l": float(row["l"]), "c": float(row["c"]),
                    "v": float(row.get("v", 0.0)),
                })
                if t > new_wm:
                    new_wm = t
            self._watermarks[key] = new_wm
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)

    def flush(self) -> None:
        """Force-write the buffer. Safe to call any time (used by tests/shutdown)."""
        try:
            self._flush()
        except Exception as exc:  # noqa: BLE001
            self._warn(exc)

    # ── internals ────────────────────────────────────────────────────────────

    def _add(self, row: dict) -> None:
        if len(self._buf) >= _BUFFER_CAP:
            self._dropped += 1
            return
        if not self._buf:
            self._first_buffered_at = self._now()
        self._buf.append(row)
        if (len(self._buf) >= _FLUSH_ROWS
                or self._now() - (self._first_buffered_at or 0.0) >= _FLUSH_INTERVAL_S):
            self._flush()

    def _flush(self) -> None:
        if not self._buf:
            return
        rows, self._buf = self._buf, []
        self._first_buffered_at = None
        day = datetime.fromtimestamp(self._now(), tz=timezone.utc).strftime("%Y-%m-%d")
        path = self._dir / f"{day}.jsonl.gz"
        self._dir.mkdir(parents=True, exist_ok=True)
        payload = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows)
        # Each append is a self-contained gzip member — crash-safe by design.
        with open(path, "ab") as fh:
            fh.write(gzip.compress(payload.encode("utf-8")))
        if self._dropped:
            log.warning("TickCapture: dropped {} rows (buffer cap)", self._dropped)
            self._dropped = 0

    def _warn(self, exc: Exception) -> None:
        now = self._now()
        if now - self._last_warn_at >= _WARN_EVERY_S:
            self._last_warn_at = now
            log.warning("TickCapture degraded (capture skipped): {}", exc)


# Module-level singleton — import and call; never raises, never blocks.
capture = TickCapture()
