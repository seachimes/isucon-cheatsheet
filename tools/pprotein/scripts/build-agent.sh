#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v go >/dev/null || { echo 'Go >= 1.23.3 is required (macOS: brew install go)' >&2; exit 1; }
mkdir -p .artifacts
cd agent
for arch in amd64 arm64; do
  CGO_ENABLED=0 GOOS=linux GOARCH="$arch" go build -mod=readonly -trimpath -o "../.artifacts/agent-linux-$arch" .
done
