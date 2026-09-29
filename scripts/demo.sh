#!/usr/bin/env bash
# Everything, offline. No federation, no model, no API key.
#
#   scripts/demo.sh            # guard checks + full protocol + live console replay
#   scripts/demo.sh --no-ui    # just the terminal output
#
# Use this to see the system work before wiring up a real federation, and to
# check that a user you just spawned behaves the way you meant.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

echo "=== 1. Can a participant's agent leak? (no model involved) ==="
uv run python -m event_planner.selfcheck
echo
echo "=== 2. The whole protocol, against simulated users ==="
uv run python -m event_planner.simulate | grep -v '^UI_EVENT '
echo

if [[ "${1:-}" != "--no-ui" ]]; then
  echo "=== 3. The same run, replayed in the console ==="
  exec uv run python "$ROOT/frontend/server.py" --demo
fi
