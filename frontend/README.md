# Frontend — what a human looks at

Nothing in here is part of the federation. Both surfaces read the leader's
output; neither can show a number the protocol did not produce.

| | what it is | when to use it |
| --- | --- | --- |
| `index.html` + `server.py` | The live console | While a run is happening |
| `report/` | A static run report | After a run, to read the argument |

## The live console

A window that shows the agents planning in real time. It opens by itself when
a prompt in `flwr chat` starts a run.

```bash
# from the repo root
uv run --project backend python frontend/server.py                     # local SuperLink
uv run --project backend python frontend/server.py --superlink supergrid
uv run --project backend python frontend/server.py --demo              # no federation
```

`scripts/run_local.sh` starts it for you; `scripts/demo.sh` runs the replay.
It lives at <http://127.0.0.1:8765/>.

### How it gets its data

1. `backend/event_planner/ui_events.py` prints one `UI_EVENT {json}` line per
   protocol step: `start`, `roster`, `ask`, `reply`, `round`, `tally`,
   `consensus`, `done`.
2. `server.py` polls the SuperLink for new runs, follows each with
   `flwr log <run> --stream`, and pushes the events to the window over
   Server-Sent Events. This works identically against a local SuperLink and
   SuperGrid.
3. `index.html` renders them.

It knows nothing about who is taking part until the server tells it. The
roster comes from the leader's identity round and the avatars, names and
colours come from `backend/event_planner/users/*.json`, so a user you spawn
with `scripts/new_user.py` appears with no change here.

Anyone in the roster whose profile is **not** on this machine — a friend who
joined from their own laptop — still gets a station, drawn with a 💻 avatar
and an empty private panel. That is not a gap to fill in later: the console
has no copy of their calendar or budget because the leader does not either.

### The private panels are a narrator's view

The panel under each agent is read from that user's profile **on this
machine** and is never sent anywhere. It is there so you can see what the
agent is holding back. The speech bubbles show only what really crossed the
network: yes/no answers, never reasons.

## The static report

```bash
scripts/report.sh        # regenerate and open
```

Two steps behind that:

- `make_trace.py` runs the offline protocol and the guard cases and writes
  `trace.json` — field *names* from the private profiles, never their values.
- `build.py` injects the trace into `template.html` and writes `report.html`.

Everything narrative on the page is derived from the run, including the
"why a rejection is not a disclosure" cards: `make_trace.deniability` finds
offers that two people refused for genuinely different private reasons and
shows the two identical `false` bits. Change the catalogue or the policy and
the page follows, rather than going quietly stale.

`trace.json` and `report.html` are build products and are gitignored.
