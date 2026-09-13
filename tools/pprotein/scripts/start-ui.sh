#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$PWD/.artifacts/bin:$PATH"
for tool in pprotein alp slp dot; do
  command -v "$tool" >/dev/null || { echo "Missing $tool; see README.md" >&2; exit 1; }
done
umask 077
mkdir -p data
exec pprotein
