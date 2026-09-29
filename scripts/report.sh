#!/usr/bin/env bash
# Rebuild the static run report from a fresh offline run.
#
#   scripts/report.sh        # writes frontend/report/report.html and opens it
#
# The report reads the trace, so it can only ever show numbers the protocol
# actually produced. Regenerate it after changing the policy or the catalogue.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
uv run --project backend python frontend/report/make_trace.py > frontend/report/trace.json
uv run --project backend python frontend/report/build.py
[[ "${1:-}" == "--no-open" ]] || open frontend/report/report.html 2>/dev/null || true
