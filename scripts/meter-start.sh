#!/usr/bin/env bash
# Unseal this shard's OpenRouter child key and start the metering proxy.
# Inputs (env): ACB_UNSEAL_KEY (RSA private key, secret), SEALED_KEY, MODEL, OUT_DIR.
# The key goes: sealed blob -> openssl (pipe) -> meter stdin. It never touches
# disk, never lands in an env var, and the unseal key is scrubbed from the
# meter's environment.
set -euo pipefail

: "${ACB_UNSEAL_KEY:?}" "${SEALED_KEY:?}" "${MODEL:?}" "${OUT_DIR:?}"
mkdir -p "$OUT_DIR"

# Rootless containers reach the host through pasta's host-gateway mapping, which
# lands on the host's primary address (not loopback), so bind there.
HOST_IP=$(ip -4 route get 1.1.1.1 | awk '{for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1)}')
CLIENT_TOKEN=$(openssl rand -hex 24)

printf '%s' "$SEALED_KEY" | base64 -d \
  | openssl pkeyutl -decrypt -inkey <(printf '%s\n' "$ACB_UNSEAL_KEY") \
      -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 \
  | env -u ACB_UNSEAL_KEY -u SEALED_KEY ACB_METER_CLIENT_TOKEN="$CLIENT_TOKEN" \
      nohup .venv/bin/acb meter --host "$HOST_IP" --port 8787 --model "$MODEL" --log "$OUT_DIR/meter.jsonl" \
      >"$OUT_DIR/meter.stdout" 2>&1 &
echo $! >"$RUNNER_TEMP/meter.pid"

for _ in $(seq 1 30); do
  if curl -s -o /dev/null "http://$HOST_IP:8787/"; then break; fi
  sleep 1
done
curl -s -o /dev/null "http://$HOST_IP:8787/" || { cat "$OUT_DIR/meter.stdout"; exit 1; }

{
  echo "ACB_METER_URL=http://acb-meter:8787"
  echo "ACB_CLIENT_TOKEN=$CLIENT_TOKEN"
} >>"$GITHUB_ENV"
echo "meter listening on $HOST_IP:8787 for $MODEL"
