"""
Tick Capture Daemon — subscribes to all universe pairs and records ticks to daily JSONL.gz.

Run as a launchd daemon: com.kym.argussentinel-tickcapture
"""

import asyncio
import gzip
import json
import os
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Set

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

class TickCapture:
    """Daemon that captures ticks for all universe pairs and writes to daily gzipped JSONL."""

    def __init__(
        self,
        data_dir: str = "data/ticks",
        universe_path: str = "data/pair_universe.json",
        flush_interval_sec: float = 5.0,
        universe_reload_interval_sec: float = 60.0,
    ):
        self.data_dir = Path(data_dir)
        self.universe_path = Path(universe_path)
        self.flush_interval = flush_interval_sec
        self.universe_reload_interval = universe_reload_interval_sec

        self.data_dir.mkdir(parents=True, exist_ok=True)

        self._tick_stream: Optional[Any] = None
        self._current_subscriptions: Set[str] = set()
        self._universe_pairs: Set[str] = set()

        # Write buffer
        self._buffer: Deque[str] = deque(maxlen=100000)
        self._running = False
        self._write_task: Optional[asyncio.Task] = None
        self._universe_task: Optional[asyncio.Task] = None
        self._maintain_task: Optional[asyncio.Task] = None

    def _load_universe(self) -> List[str]:
        """Load pairs from pair_universe.json."""
        try:
            if self.universe_path.exists():
                with open(self.universe_path, "r") as f:
                    data = json.load(f)
                pairs = data.get("pairs", [])
                return [p for p in pairs if isinstance(p, str)]
            else:
                print(f"[TickCapture] No universe file found at {self.universe_path}")
                return []
        except Exception as e:
            print(f"[TickCapture] Failed to load universe from {self.universe_path}: {e}")
            return []

    async def _subscribe_to_universe(self) -> None:
        """Subscribe to all pairs in the current universe."""
        if not self._tick_stream:
            return

        pairs = self._load_universe()
        if not pairs:
            print("[TickCapture] No pairs in universe, skipping subscription")
            return

        new_pairs = set(pairs)
        to_add = new_pairs - self._current_subscriptions
        to_remove = self._current_subscriptions - new_pairs

        for pair in to_remove:
            try:
                await self._tick_stream.unsubscribe_from_pair(pair)
                print(f"[TickCapture] Unsubscribed from {pair}")
            except Exception as e:
                print(f"[TickCapture] Error unsubscribing from {pair}: {e}")

        for pair in to_add:
            try:
                await self._tick_stream.subscribe_to_pair(pair)
                print(f"[TickCapture] Subscribed to {pair}")
            except Exception as e:
                print(f"[TickCapture] Error subscribing to {pair}: {e}")

        self._current_subscriptions = new_pairs
        print(f"[TickCapture] Active subscriptions: {sorted(self._current_subscriptions)}")

    async def _universe_watcher(self) -> None:
        """Periodically reload universe and update subscriptions."""
        last_modified = 0

        while self._running:
            try:
                if self.universe_path.exists():
                    mtime = self.universe_path.stat().st_mtime
                    if mtime > last_modified:
                        last_modified = mtime
                        await self._load_universe()
                        await self._sync_subscriptions()
            except Exception as e:
                print(f"[TickCapture] Universe watcher error: {e}")

            await asyncio.sleep(self.universe_reload_interval)

    async def _sync_subscriptions(self) -> None:
        """Subscribe to universe pairs, unsubscribe from removed pairs."""
        if not self._tick_stream:
            return

        # Subscribe to new pairs
        for pair in self._universe_pairs - self._current_subscriptions:
            try:
                await self._tick_stream.subscribe_to_pair(pair)
                self._current_subscriptions.add(pair)
                print(f"[TickCapture] Subscribed to {pair}")
            except Exception as e:
                print(f"[TickCapture] Failed to subscribe to {pair}: {e}")

        # Unsubscribe from removed pairs (optional — keep for cleanup)
        for pair in self._current_subscriptions - self._universe_pairs:
            try:
                await self._tick_stream.unsubscribe_from_pair(pair)
                self._current_subscriptions.discard(pair)
                print(f"[TickCapture] Unsubscribed from {pair}")
            except Exception as e:
                print(f"[TickCapture] Error unsubscribing from {pair}: {e}")

    def _on_tick(self, pair: str, ts: float, price: float, bid: Optional[float] = None, ask: Optional[float] = None) -> None:
        """Callback from TickStream for each tick."""
        record = {
            "k": "t",  # tick kind
            "p": pair,
            "t": ts,
            "px": price,
        }
        if bid is not None:
            record["b"] = bid
        if ask is not None:
            record["a"] = ask
        self._buffer.append(json.dumps(record, separators=(",", ":")))

    def _on_seed(self, pair: str, ts: float, price: float) -> None:
        """Callback for history seed (changeSymbol)."""
        record = {"k": "s", "p": pair, "t": ts, "px": price}
        self._buffer.append(json.dumps(record, separators=(",", ":")))

    def _on_bar(self, pair: str, ts: float, period: int,
                o: float, h: float, l: float, c: float, v: float) -> None:
        """Callback for prefetched bars (watermark-deduped)."""
        record = {"k": "b", "p": pair, "t": ts, "per": period, "o": o, "h": h, "l": l, "c": c, "v": v}
        self._buffer.append(json.dumps(record, separators=(",", ":")))

    def _get_day_file(self, day: str) -> gzip.GzipFile:
        """Get or create gzip file for the given UTC day (YYYY-MM-DD)."""
        if self._current_day != day:
            self._close_current_file()
            self._current_day = day
            filepath = self.data_dir / f"{day}.jsonl.gz"
            # Append mode: open existing or create new (concatenated gzip members)
            self._current_file = gzip.open(filepath, "at", encoding="utf-8")
        return self._current_file

    def _close_current_file(self) -> None:
        """Close current day file."""
        if self._current_file:
            self._current_file.close()
            self._current_file = None
            self._current_day = None

    async def _flush_buffer(self) -> None:
        """Flush buffer to daily files."""
        if not self._buffer:
            return

        # Group by day
        by_day: Dict[str, List[str]] = {}
        while self._buffer:
            line = self._buffer.popleft()
            try:
                record = json.loads(line)
                ts = record.get("t", 0)
                day = time.strftime("%Y-%m-%d", time.gmtime(ts))
            except Exception:
                day = time.strftime("%Y-%m-%d", time.gmtime())
            by_day.setdefault(day, []).append(line)

        # Write each day's records
        for day, lines in by_day.items():
            try:
                f = self._get_day_file(day)
                for line in lines:
                    f.write(line + "\n")
                f.flush()
                print(f"[TickCapture] Flushed {len(lines)} records to {day}.jsonl.gz")
            except Exception as e:
                print(f"[TickCapture] Failed to write {day}: {e}")
                # Re-buffer on failure
                for line in reversed(lines):
                    self._buffer.appendleft(line)

    async def _write_loop(self) -> None:
        """Background task: write buffered records to daily files."""
        while self._running:
            try:
                await self._flush_buffer()
            except Exception as e:
                print(f"[TickCapture] Write loop error: {e}")
            await asyncio.sleep(1)  # Flush every second

    async def _flush_loop(self) -> None:
        """Periodic explicit flush (every 10s)."""
        while self._running:
            await asyncio.sleep(10)
            try:
                await self._flush_buffer()
            except Exception as e:
                print(f"[TickCapture] Flush loop error: {e}")

    async def _maintain_connection(self) -> None:
        """Keep connection alive, reconnect if needed."""
        while self._running:
            if self._tick_stream and not self._tick_stream.is_connected():
                print("[TickCapture] Connection lost, reconnecting...")
                try:
                    await self._tick_stream.stop()
                except Exception:
                    pass
                try:
                    await self._tick_stream.start()
                    await self._sync_subscriptions()
                except Exception as e:
                    print(f"[TickCapture] Reconnect failed: {e}")
            await asyncio.sleep(5)

    async def start(self) -> None:
        """Start the tick capture daemon."""
        if self._running:
            return

        self._running = True
        print("[TickCapture] Starting...")

        # Initialize TickStream with callbacks
        self._tick_stream = TickStream(
            on_tick=self._on_tick,
            on_seed=self._on_seed,
            on_bar=self._on_bar,
        )

        # Start TickStream connection
        await self._tick_stream.start()

        # Load universe and subscribe
        await self._load_universe()
        await self._sync_subscriptions()

        # Start background tasks
        self._write_task = asyncio.create_task(self._write_loop())
        self._universe_task = asyncio.create_task(self._universe_watcher())
        self._maintain_task = asyncio.create_task(self._maintain_connection())

        print("[TickCapture] Running. Press Ctrl+C to stop.")

    async def stop(self) -> None:
        """Stop the tick capture daemon."""
        if not self._running:
            return

        self._running = False
        print("[TickCapture] Stopping...")

        # Cancel background tasks
        for task in (self._write_task, self._universe_task, self._maintain_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Final flush
        await self._flush_buffer()
        self._close_current_file()

        # Stop TickStream
        if self._tick_stream:
            await self._tick_stream.stop()

        print("[TickCapture] Stopped.")

    async def run_forever(self) -> None:
        """Run until signal received (for launchd)."""
        await self.start()

        # Wait for shutdown signal
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except (AttributeError, NotImplementedError):
                pass  # Windows

        await stop_event.wait()
        await self.stop()


async def main() -> None:
    """Entry point for launchd daemon."""
    # Import settings
    from config.settings import BotSettings

    settings = BotSettings()

    # Check if tick capture is enabled
    if not getattr(settings, "TICK_CAPTURE_ENABLED", True):
        print("[TickCapture] Disabled by config (TICK_CAPTURE_ENABLED=false)")
        return

    capture = TickCapture(
        data_dir=getattr(settings, "TICK_DATA_DIR", "data/ticks"),
        universe_path=getattr(settings, "PAIR_UNIVERSE_PATH", "data/pair_universe.json"),
        flush_interval_sec=float(getattr(settings, "TICK_FLUSH_INTERVAL", 5.0)),
        universe_reload_interval_sec=float(getattr(settings, "TICK_UNIVERSE_RELOAD_INTERVAL", 60.0)),
    )
    await capture.run_forever()


class _TickRecorder:
    """Lightweight singleton for recording ticks/bars from the main bot process.

    Writes records to data/ticks/<YYYY-MM-DD>.jsonl.gz, same format as
    TickCapture.  Import as ``from broker.tick_capture import capture``.
    Records are buffered and flushed synchronously on each call; the overhead
    is negligible compared to network I/O in the signal loop.
    """

    def __init__(self, data_dir: str = "data/ticks") -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._current_day: Optional[str] = None
        self._current_file: Optional[gzip.GzipFile] = None

    def _open_day(self, ts: float) -> gzip.GzipFile:
        day = time.strftime("%Y-%m-%d", time.gmtime(ts))
        if day != self._current_day:
            if self._current_file:
                self._current_file.close()
            self._current_day = day
            self._current_file = gzip.open(
                self._data_dir / f"{day}.jsonl.gz", "at", encoding="utf-8"
            )
        return self._current_file  # type: ignore[return-value]

    def _write(self, record: dict) -> None:
        try:
            f = self._open_day(record.get("t", time.time()))
            f.write(json.dumps(record, separators=(",", ":")) + "\n")
            f.flush()
        except Exception:
            pass  # never let recording errors crash the trading loop

    def record_tick(self, pair: str, ts: float, price: float) -> None:
        self._write({"k": "t", "p": pair, "t": ts, "px": price})

    def record_seed(self, pair: str, ts: float, price: float) -> None:
        self._write({"k": "s", "p": pair, "t": ts, "px": price})

    def record_bars(self, pair: str, df: Any, period: int) -> None:
        if df is None or not hasattr(df, "iterrows"):
            return
        for ts_idx, row in df.iterrows():
            try:
                ts = float(ts_idx.timestamp())
                self._write({
                    "k": "b", "p": pair, "t": ts, "per": period,
                    "o": float(row.get("o", 0)), "h": float(row.get("h", 0)),
                    "l": float(row.get("l", 0)), "c": float(row.get("c", 0)),
                    "v": float(row.get("v", 0)),
                })
            except Exception:
                pass


capture = _TickRecorder()


if __name__ == "__main__":
    asyncio.run(main())