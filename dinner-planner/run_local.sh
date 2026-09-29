#!/usr/bin/env bash
# Start a local federation: one SuperLink (the planner), one SuperNode per
# persona, and the live console from ../ui. Then, in another terminal:
#   FLWR_CHAT_SUPERLINK=local-agent uv run flwr chat
# and type `/load .` followed by the organiser's request.
#
# Needs FLWR_MODEL_API_KEY in the environment or in dinner-planner/.env
# (Flower API key from flower.ai -> Profile -> Settings -> API Keys).
# .env is gitignored; never commit the key.
# Ctrl+C stops everything.
set -euo pipefail
cd "$(dirname "$0")"

# Load the key from a gitignored .env if present.
if [[ -f .env ]]; then set -a; source .env; set +a; fi

if [[ -z "${FLWR_MODEL_API_KEY:-}" ]]; then
  echo "Set FLWR_MODEL_API_KEY first: export FLWR_MODEL_API_KEY=..." >&2
  exit 1
fi

# Register the local SuperLink with the CLI once.
CONFIG="$HOME/.flwr/config.toml"
if ! grep -q '^\[superlink.local-agent\]' "$CONFIG" 2>/dev/null; then
  printf '\n[superlink.local-agent]\naddress = "127.0.0.1:8000"\ninsecure = true\n' >> "$CONFIG"
fi

mkdir -p logs
trap 'kill 0' EXIT

uv run flower-superlink --insecure > logs/superlink.log 2>&1 &
sleep 8

port=9101
for persona in ieva maya emma birthday; do
  uv run flower-supernode --insecure --superlink 127.0.0.1:9092 \
    --port "$port" --node-config "persona=\"$persona\"" \
    > "logs/supernode-$persona.log" 2>&1 &
  port=$((port + 1))
done

# Live console: opens a window when a prompt starts a planner run.
sleep 5
uv run python ../ui/server.py --superlink local-agent > logs/ui.log 2>&1 &

echo "SuperLink + 4 SuperNodes + console running. Logs in dinner-planner/logs/. Ctrl+C to stop."
wait
