#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for tool in go git npm python3; do command -v "$tool" >/dev/null || { echo "Required: $tool" >&2; exit 1; }; done
mkdir -p .artifacts/bin
ui_build=$(mktemp -d "$PWD/.artifacts/ui-build.XXXXXX")
git clone --depth 1 --branch v1.2.4 https://github.com/kaz/pprotein.git "$ui_build/source"
test "$(git -C "$ui_build/source" rev-parse HEAD)" = fd0b0b1da93994dc4abb986222b92606c4fe9b2b
# Upstream binds all interfaces. Keep the Mac UI strictly on loopback.
python3 - "$ui_build/source/cli/pprotein/main.go" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
s = p.read_text()
old = 'e.Start(":" + port)'
assert s.count(old) == 1, 'Upstream binding changed; inspect before building'
p.write_text(s.replace(old, 'e.Start("127.0.0.1:" + port)'))
PY
npm --prefix "$ui_build/source/view" ci
npm --prefix "$ui_build/source/view" run build
(
  cd "$ui_build/source"
  go build -mod=readonly -trimpath -o ../../bin/pprotein ./cli/pprotein
)
GOBIN="$PWD/.artifacts/bin" go install github.com/tkuchiki/alp/cmd/alp@v1.0.21
GOBIN="$PWD/.artifacts/bin" go install github.com/tkuchiki/slp/cmd/slp@v0.2.1
echo 'Ready. Install graphviz separately, then run: bash scripts/start-ui.sh'
