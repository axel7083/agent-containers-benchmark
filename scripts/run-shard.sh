#!/usr/bin/env bash
# Run one shard (harness x model x arm over the selected tasks) with Harbor.
# Inputs (env): SHARD_JSON, ACB_METER_URL, ACB_CLIENT_TOKEN, OUT_DIR.
set -euo pipefail
: "${SHARD_JSON:?}" "${ACB_METER_URL:?}" "${ACB_CLIENT_TOKEN:?}" "${OUT_DIR:?}"

field() { jq -r ".$1" <<<"$SHARD_JSON"; }
SHARD_ID=$(field id)
ARM=$(field arm)
printf '%s\n' "$SHARD_JSON" >"$OUT_DIR/shard.json"

args=(run -e podman -p build/tasks -k "$(field trials)" -n 1 --max-retries 0
      -o "$OUT_DIR/jobs" --job-name "$SHARD_ID" -y -q)
while read -r task; do args+=(-i "$task"); done < <(jq -r '.tasks[]' <<<"$SHARD_JSON")

.venv/bin/acb arm "$ARM" --out "$OUT_DIR/arm.md"
if [ "$ARM" != "implicit" ]; then
  args+=(--extra-instruction-path "$OUT_DIR/arm.md")
fi

mapfile -t agent_args < <(.venv/bin/python -c '
import json, os, sys
from acb.bench.harness import harbor_agent_args
s = json.loads(os.environ["SHARD_JSON"])
print("\n".join(harbor_agent_args(s["harness"], s["version"], s["model"], os.environ["ACB_METER_URL"], os.environ["ACB_CLIENT_TOKEN"])))
')

set +e
.venv/bin/harbor "${args[@]}" "${agent_args[@]}"
status=$?
if [ "$status" -ne 0 ] && ! compgen -G "$OUT_DIR/jobs/$SHARD_ID/*/result.json" >/dev/null; then
  # Harbor failed before any trial started (e.g. preflight timeout): retry once.
  echo "harbor produced no trial (exit $status); retrying once"
  timeout 60 podman info >/dev/null
  rm -rf "$OUT_DIR/jobs/$SHARD_ID"
  .venv/bin/harbor "${args[@]}" "${agent_args[@]}"
  status=$?
fi
set -e
echo "harbor exited with $status"
# A failing trial is a result, not a CI failure; the aggregate job decides.
exit 0
