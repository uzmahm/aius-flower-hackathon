#!/usr/bin/env bash
# Join an event as one participant, from this laptop.
#
#   scripts/join.sh alex                       # leader is on this machine
#   scripts/join.sh alex --leader 10.35.4.9    # leader is on someone else's
#   scripts/join.sh alex --leader 10.35.4.9 --port 9160
#
# Your profile is read from backend/event_planner/users/<user>.json ON THIS
# MACHINE and never leaves it. The leader sends this node the app code; it
# never sends your calendar, budget or needs anywhere. All the leader ever
# gets back is yes/no answers to concrete offers.
#
# You do not need an API key -- the leader's SuperLink holds one for everyone.
# Ctrl+C leaves the event.
set -euo pipefail
SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
ROOT="$(dirname "$(dirname "$SELF")")"
cd "$ROOT/backend"

USERS_DIR="$ROOT/backend/event_planner/users"
LEADER="127.0.0.1"
PORT=""
USER_SLUG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --leader) LEADER="$2"; shift 2 ;;
    --port)   PORT="$2";   shift 2 ;;
    -h|--help) sed -n '2,14p' "$SELF" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 1 ;;
    *)  USER_SLUG="$1"; shift ;;
  esac
done

known() { ls "$USERS_DIR"/*.json 2>/dev/null | xargs -n1 basename | sed 's/.json//' | tr '\n' ' '; }

if [[ -z "$USER_SLUG" ]]; then
  echo "usage: scripts/join.sh <user> [--leader <host>] [--port <port>]" >&2
  echo "known users on this laptop: $(known)" >&2
  echo "make a new one: scripts/new_user.py <name>" >&2
  exit 1
fi
if [[ ! -f "$USERS_DIR/$USER_SLUG.json" ]]; then
  echo "No profile for '$USER_SLUG' on this laptop." >&2
  echo "Create one: scripts/new_user.py $USER_SLUG" >&2
  echo "Known: $(known)" >&2
  exit 1
fi

# Take the next free port above the ones the leader hands out locally.
if [[ -z "$PORT" ]]; then
  PORT=9101
  while lsof -iTCP:"$PORT" -sTCP:LISTEN -n >/dev/null 2>&1; do PORT=$((PORT + 1)); done
fi

# Check we can actually reach the leader before starting, so a typo or a
# firewall gives a clear error instead of a silent retry loop. Done in Python
# because `nc -w` is an idle timeout on macOS, not a connect timeout, so it
# hangs for minutes on an unroutable address.
reachable() {
  python3 - "$1" <<'PY'
import socket, sys
host = sys.argv[1]
try:
    socket.create_connection((host, 9092), timeout=5).close()
except OSError:
    sys.exit(1)
PY
}
if ! reachable "$LEADER"; then
  echo "Cannot reach the leader at $LEADER:9092." >&2
  echo "  - Is scripts/run_leader.sh running on their laptop?" >&2
  echo "  - Are you both on the same network?" >&2
  echo "  - Their macOS firewall may need to allow incoming connections." >&2
  exit 1
fi

mkdir -p "$ROOT/logs"
echo "Joining as '$USER_SLUG' -> leader $LEADER:9092 (local port $PORT)."
echo "Your profile stays in $USERS_DIR. Ctrl+C to leave."

# EVENT_PLANNER_USERS is the important part: the app code arrives from the
# leader, but it reads YOUR profile from YOUR disk.
exec env EVENT_PLANNER_USERS="$USERS_DIR" \
  uv run flower-supernode --insecure --superlink "$LEADER:9092" \
  --port "$PORT" --node-config "user=\"$USER_SLUG\"" \
  2>&1 | tee "$ROOT/logs/supernode-$USER_SLUG.log"
