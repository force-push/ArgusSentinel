"""Run-streak stake upscaler: adds a flat increment per consecutive win on a pair.

Rules:
- Win: streak increments (up to max_level cap).
- Loss: streak resets to zero.
- Draw: streak unchanged — draw returns stake, is neither win nor loss.
- Stake = base + (increment × min(streak, max_level)).
"""

from __future__ import annotations

from utils.logger import log


class RunStreakTracker:
    """Track consecutive win streaks per pair for stake upscaling."""

    def __init__(self) -> None:
        self._streak: dict[str, int] = {}

    def get_stake(
        self,
        pair: str,
        base_stake: float,
        *,
        increment: float,
        max_level: int,
    ) -> tuple[float, int]:
        """Return (scaled_stake, current_level). Level 0 means no streak."""
        level = min(self._streak.get(pair, 0), max_level)
        stake = round(base_stake + increment * level, 2)
        return stake, level

    def record_outcome(self, pair: str, outcome: str) -> None:
        """Update streak after a resolved trade. Draws leave streak unchanged."""
        outcome = outcome.lower()
        if outcome == "win":
            self._streak[pair] = self._streak.get(pair, 0) + 1
        elif outcome == "loss":
            self._streak.pop(pair, None)

    def current_level(self, pair: str, *, max_level: int) -> int:
        return min(self._streak.get(pair, 0), max_level)

    def seed_from_db(
        self,
        db_path: str,
        *,
        lookback_hours: float = 24.0,
        max_level: int = 3,
    ) -> None:
        """Reconstruct win streaks from DB on startup so a restart doesn't reset runs."""
        from datetime import datetime, timezone, timedelta
        from data.decisions_store import tail_outcomes_by_pair

        since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        try:
            # max_level + 1 outcomes is enough to reconstruct any streak up to the cap
            tails = tail_outcomes_by_pair(db_path, since_iso=since, max_per_pair=max_level + 1)
        except Exception as exc:
            log.warning("RunStreakTracker.seed_from_db failed — starting fresh: {}", exc)
            return

        restored = 0
        for pair, outcomes in tails.items():  # outcomes = newest-first
            streak = 0
            for outcome in outcomes:
                if outcome == "win":
                    streak += 1
                elif outcome == "loss":
                    break  # streak resets at any loss
                # draws: keep counting back

            if streak:
                self._streak[pair] = min(streak, max_level)
                restored += 1

        log.info(
            "RunStreakTracker seeded ({:.0f}h lookback): {} pairs with active win streaks — {}",
            lookback_hours,
            restored,
            {p: v for p, v in self._streak.items()},
        )

    def state(self) -> dict[str, int]:
        return dict(self._streak)
