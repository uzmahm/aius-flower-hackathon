#!/usr/bin/env bash
# Start the whole system locally:
#   - one SuperLink, which is where the LEADER runs (the centralized task)
#   - one SuperNode per user profile in backend/event_planner/users/
#   - the live console from frontend/
#
# Then, in another terminal, be the organiser:
#   cd backend && FLWR_CHAT_SUPERLINK=local-agent uv run flwr chat
#   /load .
#   Plan a relaxing foodie evening in the city for Sofia's birthday. Keep it a surprise.
#
# Needs FLWR_MODEL_API_KEY in the environment or in backend/.env
# (Flower API key from flower.ai -> Profile -> Settings -> API Keys).
# .env is gitignored; never commit the key.
#
# To add another user while this is running, open a new terminal:
#   scripts/new_user.py alex --likes nature,morning --avoid foodie
#   scripts/join.sh alex
#
# Ctrl+C stops everything.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

# Load the key from a gitignored .env if present.
if [[ -f .env ]]; then set -a; source .env; set +a; fi

if [[ -z "${FLWR_MODEL_API_KEY:-}" ]]; then
  echo "Set FLWR_MODEL_API_KEY first: export FLWR_MODEL_API_KEY=..." >&2
  echo "No key? Rehearse the whole thing offline instead: scripts/demo.sh" >&2
  exit 1
fi

# Register the local SuperLink with the CLI once.
CONFIG="$HOME/.flwr/config.toml"
mkdir -p "$(dirname "$CONFIG")"
if ! grep -q '^\[superlink.local-agent\]' "$CONFIG" 2>/dev/null; then
  printf '\n[superlink.local-agent]\naddress = "127.0.0.1:8000"\ninsecure = true\n' >> "$CONFIG"
fi

mkdir -p "$ROOT/logs"
trap 'kill 0' EXIT

echo "Starting the leader (SuperLink)..."
uv run flower-superlink --insecure > "$ROOT/logs/superlink.log" 2>&1 &
sleep 8

port=9101
for path in event_planner/users/*.json; do
  user="$(basename "$path" .json)"
  echo "  joining user: $user (port $port)"
  uv run flower-supernode --insecure --superlink 127.0.0.1:9092 \
    --port "$port" --node-config "user=\"$user\"" \
    > "$ROOT/logs/supernode-$user.log" 2>&1 &
  port=$((port + 1))
done

# Live console: opens a window when a prompt starts a run.
sleep 5
# A console left over from an earlier session would hold the default port and
# the new one would die on bind, so take the first port that is actually free.
UI_PORT=8765
while lsof -iTCP:"$UI_PORT" -sTCP:LISTEN -n >/dev/null 2>&1; do
  echo "  port $UI_PORT is already in use (an older console?), trying $((UI_PORT + 1))"
  UI_PORT=$((UI_PORT + 1))
done
uv run python "$ROOT/frontend/server.py" --superlink local-agent --port "$UI_PORT" \
  > "$ROOT/logs/console.log" 2>&1 &

# Never announce a console that is not there.
CONSOLE_URL="http://127.0.0.1:$UI_PORT/"
for _ in $(seq 20); do
  curl -sf -o /dev/null --max-time 1 "$CONSOLE_URL" && break
  sleep 0.5
done
if ! curl -sf -o /dev/null --max-time 2 "$CONSOLE_URL"; then
  echo "!! The console failed to start: $(tail -1 "$ROOT/logs/console.log")" >&2
  CONSOLE_URL="(not running -- see logs/console.log)"
fi

echo
echo "Running. Logs in logs/. Console at $CONSOLE_URL"
echo "Now open another terminal:  cd backend && FLWR_CHAT_SUPERLINK=local-agent uv run flwr chat"
echo "Ctrl+C to stop everything."
wait
