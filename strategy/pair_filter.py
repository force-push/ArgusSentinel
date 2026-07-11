"""Shared pair-eligibility filter — one source of truth for which symbols are
tradable, used by both the poll loop (``manager_v2``) and ``FocusSession`` so
they can never disagree.

Precedence (highest first):
  1. ``ALLOWED_PAIR_REGEX`` — when set, a symbol is allowed only if the pattern
     matches (blocklist still applies). Looser than an exact list and adapts to
     whichever matching crosses are live (e.g. ``(USD|CNY|CNH)``).
  2. ``DYNAMIC_PAIRS_ENABLED`` — hot-reloaded allowlist from
     ``data/pair_universe.json`` (written hourly by tools/pair_universe_update.py).
     Falls back to (3) when the file is missing, invalid, empty, or stale.
  3. ``ALLOWED_PAIRS`` — exact-match allowlist (blocklist ignored for these).
  4. ``BLOCKED_PAIRS`` — default deny-list when no allowlist is configured.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from config.settings import settings

UNIVERSE_PATH = Path("data/pair_universe.json")

# Compile cache keyed by the pattern string (patterns rarely change at runtime).
_compiled: dict[str, re.Pattern | None] = {}

# mtime-cached dynamic universe: (mtime, pairs) — same pattern as flip_levers.
_universe_cache: dict = {"mtime": None, "pairs": None}


def load_dynamic_universe(cfg: Any = settings, path: Path | None = None) -> set[str] | None:
    """Return the dynamic pair set, or None when unavailable/stale (→ caller
    falls back to the static allowlist). Never raises."""
    if not getattr(cfg, "dynamic_pairs_enabled", False):
        return None
    path = path if path is not None else UNIVERSE_PATH
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    if time.time() - mtime > getattr(cfg, "dynamic_pairs_max_age_hours", 24.0) * 3600:
        return None  # updater is dead — don't trade a frozen universe silently
    if _universe_cache["mtime"] != mtime:
        try:
            data = json.loads(path.read_text())
            pairs = {p for p in data.get("pairs", []) if isinstance(p, str) and p}
        except (OSError, ValueError):
            return None
        _universe_cache.update(mtime=mtime, pairs=pairs or None)
    return _universe_cache["pairs"]


def _regex(pattern: str) -> re.Pattern | None:
    if pattern not in _compiled:
        try:
            _compiled[pattern] = re.compile(pattern) if pattern else None
        except re.error:
            _compiled[pattern] = None  # bad pattern → treat as "no regex"
    return _compiled[pattern]


def is_pair_allowed(symbol: str, cfg: Any = settings) -> bool:
    """Return True if ``symbol`` may be traded under the current config."""
    if not symbol:
        return False
    blocked = set(cfg.blocked_pairs)
    rx = _regex(cfg.allowed_pair_regex)
    if rx is not None:
        return bool(rx.search(symbol)) and symbol not in blocked
    dynamic = load_dynamic_universe(cfg)
    if dynamic is not None:
        return symbol in dynamic
    allow = set(cfg.allowed_pairs)
    if allow:
        return symbol in allow
    return symbol not in blocked
