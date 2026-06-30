#!/usr/bin/env bash
# Watchdog supervisor for main_v2.py.
#
# Failure modes handled:
#   1. CRASH  — process exits → restart after 10s (stderr lands in runtime.log).
#   2. HANG   — the main loop stops completing cycles (data/heartbeat stale for
#               STALE_SECS) → kill -9, restart with a fresh WS connection. The
#               heartbeat is rewritten at the END of every main-loop cycle, so a
#               busy hot-loop that only spams logs no longer masks a hang (the
#               old check used bot.log mtime, which background tasks kept fresh).
#   3. BLOAT  — preventive restart every MAX_RUN_SECONDS to cap memory growth of
#               the long-running process (and the Rust WS client's buffers).
# Also keeps runtime.log bounded so it can't grow without limit.
#
# Tunables (env-overridable):
#   STALE_SECS=300         hang threshold (s)
#   MAX_RUN_SECONDS=21600  preventive restart interval (s, 6h; 0 disables)
#   MAX_LOG_MB=100         runtime.log size cap (MB)
#
# Usage:  nohup tools/run_supervised.sh > /dev/null 2>&1 &
cd "$(dirname "$0")/.." || exit 1
STALE_SECS=${STALE_SECS:-300}
MAX_RUN_SECONDS=${MAX_RUN_SECONDS:-21600}
MAX_LOG_MB=${MAX_LOG_MB:-100}
# Grace period after SIGTERM before SIGKILL. Must exceed the bot's internal
# SDK drain timeout (10s) so close() can complete before we hard-kill it.
SIGTERM_GRACE_SECS=${SIGTERM_GRACE_SECS:-20}
# Restart backoff caps a crash loop: 10s → 20s → 40s → … up to MAX_BACKOFF.
# Resets to MIN_BACKOFF when a run survives longer than BACKOFF_RESET_SECS.
MIN_BACKOFF=${MIN_BACKOFF:-10}
MAX_BACKOFF=${MAX_BACKOFF:-300}
BACKOFF_RESET_SECS=${BACKOFF_RESET_SECS:-600}

# Cap the tokio (Rust async runtime) worker thread pool.  Default is
# num_cpus * 2 which on a 4-core Mac is 8, but observed crashes showed
# 37 tokio threads due to thread-pool exhaustion from concurrent WS
# connections.  4 is enough for all async I/O BinaryOptionsToolsV2 needs.
export TOKIO_WORKER_THREADS=${TOKIO_WORKER_THREADS:-4}
HEARTBEAT=data/heartbeat
LOG=logs/runtime.log

note() { echo "[supervisor] $(date -u +%FT%TZ) $*" >> "$LOG"; }

_mtime() { stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null; }
_size_mb() {
  local b
  b=$(stat -f %z "$1" 2>/dev/null || stat -c %s "$1" 2>/dev/null || echo 0)
  echo $((b / 1048576))
}

rotate_log() {
  # When runtime.log exceeds the cap, keep only the last ~2000 lines.
  if [ -f "$LOG" ] && [ "$(_size_mb "$LOG")" -gt "$MAX_LOG_MB" ]; then
    tail -n 2000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
    note "rotated runtime.log (exceeded ${MAX_LOG_MB}MB)"
  fi
}

# Drain the bot with SIGTERM, then SIGKILL if it doesn't exit in time.
# Used by both BLOAT and HANG paths so close() can run.
drain_bot() {
  local pid="$1"
  local reason="$2"
  note "draining bot pid=$pid (reason=$reason, grace=${SIGTERM_GRACE_SECS}s)"
  kill -TERM "$pid" 2>/dev/null
  local waited=0
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$SIGTERM_GRACE_SECS" ]; do
    sleep 1
    waited=$((waited + 1))
  done
  if kill -0 "$pid" 2>/dev/null; then
    note "bot pid=$pid did not exit after ${SIGTERM_GRACE_SECS}s — SIGKILL"
    kill -9 "$pid" 2>/dev/null
  else
    note "bot pid=$pid drained cleanly in ${waited}s"
  fi
}

mkdir -p logs data
note "starting (stale=${STALE_SECS}s max_run=${MAX_RUN_SECONDS}s log_cap=${MAX_LOG_MB}MB grace=${SIGTERM_GRACE_SECS}s backoff=${MIN_BACKOFF}-${MAX_BACKOFF}s)"
backoff=$MIN_BACKOFF
while true; do
  rotate_log
  # Fresh heartbeat so a stale file from a previous run can't trip the watchdog
  # before the new bot writes its first one.
  date +%s > "$HEARTBEAT" 2>/dev/null
  .venv/bin/python main_v2.py >> "$LOG" 2>&1 &
  BOT=$!
  START=$(date +%s)
  note "bot started pid=$BOT"
  LAST_BACKUP=0
  while kill -0 "$BOT" 2>/dev/null; do
    sleep 30
    now=$(date +%s)
    rotate_log
    # Hourly safety-net backup of the decisions log (kept: latest only).
    if [ $((now - LAST_BACKUP)) -gt 3600 ] && [ -f data/decisions.jsonl ]; then
      cp data/decisions.jsonl data/decisions.jsonl.bak 2>/dev/null && LAST_BACKUP=$now
    fi
    # BLOAT: preventive restart to cap memory growth (0 disables).
    if [ "$MAX_RUN_SECONDS" -gt 0 ] && [ $((now - START)) -gt "$MAX_RUN_SECONDS" ]; then
      drain_bot "$BOT" "preventive_restart_after_$((now - START))s"
      break
    fi
    # HANG: heartbeat stale (fall back to bot.log if the heartbeat file is absent,
    # e.g. an older bot build that doesn't write one).
    hb="$HEARTBEAT"; [ -f "$hb" ] || hb=logs/bot.log
    if [ -f "$hb" ]; then
      age=$((now - $(_mtime "$hb")))
      if [ "$age" -gt "$STALE_SECS" ]; then
        drain_bot "$BOT" "stale_${age}s"
        break
      fi
    fi
  done
  wait "$BOT" 2>/dev/null
  rc=$?
  END=$(date +%s)
  ran=$((END - START))
  # Backoff management: if the bot survived BACKOFF_RESET_SECS, reset; otherwise
  # double the backoff up to MAX_BACKOFF to soften crash loops.
  if [ "$ran" -ge "$BACKOFF_RESET_SECS" ]; then
    backoff=$MIN_BACKOFF
  fi
  note "bot exited rc=$rc after ${ran}s — restarting in ${backoff}s"
  sleep "$backoff"
  next=$((backoff * 2))
  if [ "$next" -gt "$MAX_BACKOFF" ]; then next=$MAX_BACKOFF; fi
  backoff=$next
done
