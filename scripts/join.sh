#!/usr/bin/env bash
# Add one more user to a federation that is already running.
#
#   scripts/join.sh alex          # uses backend/event_planner/users/alex.json
#   scripts/join.sh alex 9150     # pick the port yourself
#
# The leader discovers the new node on the next prompt -- nothing needs
# restarting and no code knows the roster in advance. Ctrl+C removes the user
# again.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

USER_SLUG="${1:-}"
if [[ -z "$USER_SLUG" ]]; then
  echo "usage: scripts/join.sh <user> [port]" >&2
  echo "known users: $(ls event_planner/users/*.json | xargs -n1 basename | sed 's/.json//' | tr '\n' ' ')" >&2
  exit 1
fi
if [[ ! -f "event_planner/users/$USER_SLUG.json" ]]; then
  echo "No profile for '$USER_SLUG'. Create one: scripts/new_user.py $USER_SLUG" >&2
  exit 1
fi

# Take the next free port above the ones run_local.sh hands out.
PORT="${2:-}"
if [[ -z "$PORT" ]]; then
  PORT=9101
  while lsof -iTCP:"$PORT" -sTCP:LISTEN -n >/dev/null 2>&1; do PORT=$((PORT + 1)); done
fi

mkdir -p "$ROOT/logs"
echo "Joining as '$USER_SLUG' on port $PORT. Ctrl+C to leave."
exec uv run flower-supernode --insecure --superlink 127.0.0.1:9092 \
  --port "$PORT" --node-config "user=\"$USER_SLUG\"" \
  2>&1 | tee "$ROOT/logs/supernode-$USER_SLUG.log"
