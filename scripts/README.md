# Scripts — how to run the system

| script | what it does |
| --- | --- |
| `demo.sh` | Everything, offline. No federation, no model, no API key |
| `run_leader.sh` | Run **this** laptop as the leader so other people can join |
| `run_local.sh` | Everything on one laptop, no networking |
| `join.sh <user>` | Join as one participant, from this laptop |
| `new_user.py <slug>` | Create a user profile |
| `who.py` | List who has joined: every SuperNode with its agent's name |
| `report.sh` | Rebuild the static run report from a fresh offline run |

## Start here

```bash
scripts/demo.sh
```

Guard checks, then the full protocol against simulated users, then a replay in
the console. Nothing to configure. Add `--no-ui` for terminal output only.

## Two laptops: you lead, a friend joins

This is the real thing. The leader needs an API key; your friend's is
optional, and their private profile never leaves their machine.

### On your laptop (the leader)

```bash
echo 'FLWR_MODEL_API_KEY=...' > backend/.env     # flower.ai → Settings → API Keys
scripts/run_leader.sh
```

It starts the SuperLink, the console, and one SuperNode for each profile in
`backend/event_planner/users/`, then prints the exact command to send your
friend — including this laptop's network address.

Use `scripts/run_leader.sh --solo` if you want *everyone* to join from their
own machine, including you.

### On your friend's laptop

```bash
git clone <your repo url> && cd aius-flower-hackathon
cd backend && uv sync && cd ..
scripts/new_user.py sam                          # their profile, on their disk
scripts/join.sh sam --leader 10.35.4.9           # the address you sent them
```

The address can also go second without the flag: `scripts/join.sh sam 10.35.4.9`.
User names are lowercase (`sam`, not `Sam`), matching the profile file.

An API key is optional. Each agent calls the model with the key on its own
laptop; without one (`FLWR_MODEL_API_KEY` unset) it decides by simple rules
over the profile instead, and still sends only yes/no. `join.sh` checks it can
reach you first and tells you what to fix if it cannot.

### Then plan something

Back on your laptop, in a second terminal:

```bash
cd backend && FLWR_CHAT_SUPERLINK=local-agent uv run flwr chat
/load .
Plan a relaxing foodie evening in the city for Sam's birthday. Keep it a surprise.
```

Watch it happen at <http://127.0.0.1:8765/>. Your friend appears as a station
with a 💻 avatar and an empty private panel — the console cannot show their
calendar or budget, because it does not have them, and neither does the
leader.

### What actually crosses the network

| | |
| --- | --- |
| leader → friend | the app code (the FAB), and concrete offers |
| friend → leader | their name, then one yes/no bit per offer |
| never | their calendar, budget, access needs, address or reasons |

The app code your friend runs is downloaded from your SuperLink. It reads
*their* profile from *their* disk — `join.sh` sets `EVENT_PLANNER_USERS` to
their local `backend/event_planner/users/` to make sure of it.

### If they cannot connect

- Both laptops must be on the same network. Coffee-shop and university Wi-Fi
  often block machine-to-machine traffic; a phone hotspot is the usual fix.
- macOS may prompt to allow incoming connections the first time — say yes.
  System Settings → Network → Firewall → Options.
- `run_leader.sh` guesses your address from `en0`/`en1`. If it guesses wrong:
  `LEADER_IP=10.0.0.5 scripts/run_leader.sh`.
- Everything is `--insecure` plain gRPC. Fine on a hotspot between friends,
  not something to expose to the open internet.

## One laptop

```bash
scripts/run_local.sh
```

Same thing, all processes local, no network address involved.

## Adding people

```bash
scripts/new_user.py                       # interactive
scripts/new_user.py alex --likes nature,morning --avoid foodie --budget 70
scripts/join.sh alex                      # local leader
scripts/join.sh alex --leader 10.35.4.9   # someone else's leader
```

`join.sh` picks a free port and runs one SuperNode in the foreground; Ctrl+C
removes that user again. Nothing restarts, and no code knows the roster in
advance — the leader asks on the next prompt.

Profiles live in `backend/event_planner/users/`. Delete a file to remove
someone.
