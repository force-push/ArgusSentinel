"""Risk manager: enforce trading limits and safeguards."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path

from utils.logger import log


@dataclass
class TradeRecord:
    timestamp: datetime
    direction: str
    amount: float
    result: str  # "WIN", "LOSS", "PENDING"


class RiskManager:
    """Enforce all risk constraints before allowing a trade."""

    def __init__(
        self,
        max_trades_per_hour: int,
        max_daily_loss_usd: float,
        cooldown_after_loss_seconds: int,
        trade_amount: float,
        min_balance_multiplier: float = 5.0,
    ):
        self.max_trades_per_hour = max_trades_per_hour
        self.max_daily_loss_usd = max_daily_loss_usd
        self.cooldown_after_loss_seconds = cooldown_after_loss_seconds
        self.trade_amount = trade_amount
        self.min_balance_multiplier = min_balance_multiplier

        self.trade_history: deque[TradeRecord] = deque()
        self.last_loss_time: datetime | None = None
        self.daily_pnl: float = 0.0

        self.block_reason: str = ""

    # ────────────────────────────────────────────────────────────────

    def is_allowed(
        self, current_balance: float | None = None, *, now: datetime | None = None
    ) -> bool:
        """Check all constraints. Set self.block_reason if blocked.

        ``now`` is injectable so the trades/hour and cooldown windows are
        evaluated against the same reference time used to seed risk state
        (see ``seed_from_db``); it defaults to the current UTC time.
        """
        self.block_reason = ""

        # Balance check
        if current_balance is not None:
            min_balance = self.trade_amount * self.min_balance_multiplier
            if current_balance < min_balance:
                self.block_reason = f"Balance too low: {current_balance:.2f} < {min_balance:.2f}"
                return False

        # Trades per hour
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        recent = [t for t in self.trade_history if t.timestamp > hour_ago]
        if len(recent) >= self.max_trades_per_hour:
            self.block_reason = f"Max trades/hour: {len(recent)} >= {self.max_trades_per_hour}"
            return False

        # Daily loss limit
        if self.daily_pnl < -self.max_daily_loss_usd:
            self.block_reason = f"Daily loss limit exceeded: {self.daily_pnl:.2f} <= -{self.max_daily_loss_usd:.2f}"
            return False

        # Cooldown after loss
        if self.last_loss_time is not None:
            elapsed = (now - self.last_loss_time).total_seconds()
            if elapsed < self.cooldown_after_loss_seconds:
                remaining = self.cooldown_after_loss_seconds - elapsed
                self.block_reason = f"Cooling down after loss: {remaining:.0f}s remaining"
                return False

        return True

    def record_trade(self, direction: str, amount: float, result: str) -> None:
        """Record a completed trade and update P&L."""
        now = datetime.now(timezone.utc)
        self.trade_history.append(TradeRecord(now, direction, amount, result))

        if result == "WIN":
            self.daily_pnl += amount
        elif result == "LOSS":
            self.daily_pnl -= amount
            self.last_loss_time = now

        log.info(
            f"Trade recorded: {result} {direction} ${amount:.2f} | Daily P&L: {self.daily_pnl:+.2f}"
        )

    def reset_daily(self) -> None:
        """Reset daily P&L (call at market open)."""
        self.daily_pnl = 0.0
        log.info("Daily P&L reset")

    def seed_from_db(self, db_path: str | Path, *, now: datetime | None = None) -> int:
        """Restore today's risk state from resolved real trades.

        Risk limits must survive process restarts. The dashboard and analytics
        read the SQLite store, so seed from the same source of truth at startup.
        """
        path = Path(db_path)
        if not path.exists():
            return 0

        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        # Match dashboard /api/state's 1D KPI window. This is stricter than
        # midnight-UTC and avoids a restart resetting loss exposure mid-session.
        day_start = now_utc - timedelta(days=1)
        hour_ago = now_utc - timedelta(hours=1)

        with sqlite3.connect(str(path), timeout=15.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT ts, outcome, pnl, data
                FROM decisions
                WHERE decision = 'TRADE'
                  AND shadow = 0
                  AND outcome IN ('win', 'loss', 'draw')
                  AND ts >= ?
                ORDER BY ts ASC
                """,
                (day_start.isoformat(),),
            ).fetchall()

        self.daily_pnl = 0.0
        self.trade_history.clear()
        self.last_loss_time = None

        for row in rows:
            trade_ts = self._parse_ts(row["ts"])
            if trade_ts is None:
                continue
            pnl = float(row["pnl"] or 0.0)
            self.daily_pnl += pnl

            outcome = str(row["outcome"] or "").upper()
            data = json.loads(row["data"] or "{}")
            amount = float(data.get("stake") or abs(pnl) or self.trade_amount)
            direction = str(data.get("bot_direction") or data.get("our_direction") or "")

            if trade_ts >= hour_ago:
                self.trade_history.append(TradeRecord(trade_ts, direction, amount, outcome))
            if outcome == "LOSS":
                self.last_loss_time = trade_ts

        log.info(
            "RiskManager seeded from DB: {} resolved trade(s), rolling 24h P&L {:+.2f}, {} trade(s) in last hour",
            len(rows),
            self.daily_pnl,
            len(self.trade_history),
        )
        return len(rows)

    @staticmethod
    def _parse_ts(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
