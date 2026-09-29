# Event Planner console

A live window that shows the four agents planning. It opens by itself when a
prompt in `flwr chat` starts a `dinner-planner` run. The plan panel on the right
only appears once every guest has accepted the same offer.

## How it works

- `dinner-planner/agent/ui_events.py`: the planner prints one `UI_EVENT {json}`
  line per protocol step (start, ask, reply, round, tally, consensus, done).
- `ui/server.py` polls the SuperLink for new runs, follows each one with
  `flwr log <run> --stream`, and pushes the events to the window over
  Server-Sent Events. This works on a local SuperLink and on SuperGrid.
- `ui/index.html` is the window.

The private panels are a narrator's view read from `personas.py` on this
machine. They are never sent anywhere. The speech bubbles show only what really
crossed the network: yes/no answers, never reasons.

## Run it

From the repo root:

```bash
# Local federation (dinner-planner/run_local.sh starts this for you)
uv run --project dinner-planner python ui/server.py

# Watch SuperGrid instead
uv run --project dinner-planner python ui/server.py --superlink supergrid

# Rehearse without any federation: replays dryrun.py
uv run --project dinner-planner python ui/server.py --demo
```

The "Replay demo" button in the window does the same replay. The console
lives at http://127.0.0.1:8765/.
