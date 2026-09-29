#!/usr/bin/env bash
# Stop the metering proxy; it resolves billed cost per generation before exiting.
set -uo pipefail
PID=$(cat "$RUNNER_TEMP/meter.pid" 2>/dev/null) || exit 0
kill -TERM "$PID" 2>/dev/null || exit 0
for _ in $(seq 1 240); do
  kill -0 "$PID" 2>/dev/null || exit 0
  sleep 1
done
echo "meter did not finish in time" >&2
kill -KILL "$PID" 2>/dev/null
