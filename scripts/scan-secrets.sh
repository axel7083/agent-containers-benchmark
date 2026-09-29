#!/usr/bin/env bash
# Refuse to publish artifacts that contain anything shaped like an OpenRouter key.
set -euo pipefail
if grep -rIlE 'sk-or-(v1-)?[0-9a-f]{32,}' "$1" 2>/dev/null; then
  echo "::error::OpenRouter key material found in $1; artifacts will not be uploaded" >&2
  exit 1
fi
echo "no key material in $1"
