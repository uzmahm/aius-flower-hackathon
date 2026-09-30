#!/usr/bin/env bash
# Run THIS laptop as the leader, so friends on other laptops can join.
#
#   scripts/run_leader.sh              # leader + console + your own users
#   scripts/run_leader.sh --solo       # leader + console only; everyone joins remotely
#
# Starts the SuperLink (where the leader task runs), the live console, and one
# SuperNode for each profile in backend/event_planner/users/. Prints the exact
# command your friends need to run.
#
# Needs FLWR_MODEL_API_KEY in the environment or in backend/.env
# (Flower API key from flower.ai -> Profile -> Settings -> API Keys).
# Only this laptop needs the key -- the SuperLink holds it for everyone.
#
# Ctrl+C stops everything.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"

if [[ -f .env ]]; then set -a; source .env; set +a; fi
if [[ -z "${FLWR_MODEL_API_KEY:-}" ]]; then
  echo "Set FLWR_MODEL_API_KEY first: export FLWR_MODEL_API_KEY=..." >&2
  echo "No key? Rehearse offline instead: scripts/demo.sh" >&2
  exit 1
fi

# The address friends will point their SuperNode at.
LAN_IP="${LEADER_IP:-$(ipconfig getifaddr en0 2>/dev/null \
  || ipconfig getifaddr en1 2>/dev/null \
  || hostname -I 2>/dev/null | awk '{print $1}')}"
if [[ -z "$LAN_IP" ]]; then
  echo "Could not work out this laptop's network address." >&2
  echo "Find it in System Settings -> Network, then: LEADER_IP=1.2.3.4 $0" >&2
  exit 1
fi

# Register the local SuperLink with the CLI once, so `flwr chat` finds it.
CONFIG="$HOME/.flwr/config.toml"
mkdir -p "$(dirname "$CONFIG")"
if ! grep -q '^\[superlink.local-agent\]' "$CONFIG" 2>/dev/null; then
  printf '\n[superlink.local-agent]\naddress = "127.0.0.1:8000"\ninsecure = true\n' >> "$CONFIG"
fi

mkdir -p "$ROOT/logs"
trap 'kill 0' EXIT

echo "Starting the leader on $LAN_IP ..."
# The Fleet API (port 9092) already listens on every interface, which is what
# lets other laptops join. The control API stays on localhost: only you, the
# organiser, get to send the prompt.
uv run flower-superlink --insecure > "$ROOT/logs/superlink.log" 2>&1 &
sleep 8

SOLO=""
[[ "${1:-}" == "--solo" ]] && SOLO=1

if [[ -z "$SOLO" ]]; then
  port=9101
  for path in event_planner/users/*.json; do
    user="$(basename "$path" .json)"
    echo "  local user: $user"
    EVENT_PLANNER_USERS="$ROOT/backend/event_planner/users" \
    uv run flower-supernode --insecure --superlink 127.0.0.1:9092 \
      --port "$port" --node-config "user=\"$user\"" \
      > "$ROOT/logs/supernode-$user.log" 2>&1 &
    port=$((port + 1))
  done
fi

sleep 5
# A console left over from an earlier session would hold the default port and
# the new one would die on bind, so take the first port that is actually free.
UI_PORT=8765
while lsof -iTCP:"$UI_PORT" -sTCP:LISTEN -n >/dev/null 2>&1; do
  echo "  port $UI_PORT is already in use (an older console?), trying $((UI_PORT + 1))"
  UI_PORT=$((UI_PORT + 1))
done

# In solo mode this laptop has no agents, so the console hides its profiles.
uv run python "$ROOT/frontend/server.py" --superlink local-agent \
  --port "$UI_PORT" ${SOLO:+--no-local} \
  > "$ROOT/logs/console.log" 2>&1 &

# Never announce a console that is not there. Silent death in a log file is
# how you end up staring at a stale window from a previous run.
CONSOLE_URL="http://127.0.0.1:$UI_PORT/"
for _ in $(seq 20); do
  curl -sf -o /dev/null --max-time 1 "$CONSOLE_URL" && break
  sleep 0.5
done
if ! curl -sf -o /dev/null --max-time 2 "$CONSOLE_URL"; then
  echo
  echo "!! The console failed to start. Everything else is running." >&2
  echo "!! Why: $(tail -1 "$ROOT/logs/console.log")" >&2
  echo "!! Full log: logs/console.log" >&2
  CONSOLE_URL="(not running -- see logs/console.log)"
fi

cat <<EOF

────────────────────────────────────────────────────────────────────
Leader running. Console: $CONSOLE_URL

Send this to anyone who wants to join, on their own laptop:

    git clone <this repo> && cd $(basename "$ROOT")
    cd backend && uv sync && cd ..
    scripts/new_user.py <their-name>
    scripts/join.sh <their-name> --leader $LAN_IP

An API key is optional for them: with FLWR_MODEL_API_KEY set on their laptop
their agent uses the model, without it it decides by rules over their profile.
Their profile never leaves their laptop.

When everyone has joined, be the organiser in another terminal:

    cd backend && FLWR_CHAT_SUPERLINK=local-agent uv run flwr chat
    /load .
    Plan a relaxing foodie evening in the city for Sam's birthday.

Ctrl+C stops everything. Logs in logs/.
────────────────────────────────────────────────────────────────────
EOF
wait
