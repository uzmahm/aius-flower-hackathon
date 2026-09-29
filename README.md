# Event Planner

A group plans an event together. Every person's agent holds their real
calendar, budget, access needs and the kinds of thing they will not do. One
**leader** finds something everyone can actually make — and the amount of
private information that leaves any one machine is bounded, enforced in code,
and printed at the end of the run as a number.

```
| user | node | bits disclosed |
| ---  | ---  | ---            |
| emma | 11   | 6.00           |
| maya | 12   | 6.00           |
```

Nobody states a budget, a price band, a set of free hours, an access need or a
location. Maya is coeliac; Emma has no car and the last shuttle is 21:40. All of it decides the booking.
None of it crosses a wire.

## Try it in 30 seconds

No federation, no model, no API key:

```bash
scripts/demo.sh
```

That runs the guard checks, then the whole protocol against simulated users,
then replays it in the console at <http://127.0.0.1:8765/>.

## Where everything is

```
backend/      everything that runs inside the Flower federation
frontend/     everything a human looks at
scripts/      how you start, join and test the system
templates/    the stock Flower starters, kept for reference
```

| you want to | go to |
| --- | --- |
| Change the protocol, the policy or the activity catalogue | [backend/](backend/) |
| Change the console or the run report | [frontend/](frontend/) |
| Start the system, add a user, run the checks | [scripts/](scripts/) |
| Add or edit a person | `backend/event_planner/users/*.json` |

## How it fits together

```
                  SuperLink — the LEADER
                  backend/event_planner/leader.py
                  runs the protocol, validates everything inbound,
                  keeps the disclosure ledger
                             |
        +----------+---------+---------+----------+
        |          |         |         |          |
    SuperNode  SuperNode SuperNode SuperNode  ... one per user
    participant.py + guard.PolicyGrid
    holds: raw calendar / budget / access needs / address
```

The organiser is a person typing into `flwr chat`. Their prompt is the brief:
what kind of event, for whom, and whether it is a surprise.

Guests physically cannot talk to each other — the Flower runtime grants a
SuperNode `push_reply_message` and nothing else — so every bit passes through
the leader, which is what makes the total measurable.

## Running it for real, across laptops

One person leads. Everyone else joins from their own machine, and their
private profile stays there.

**You, the leader:**

```bash
echo 'FLWR_MODEL_API_KEY=...' > backend/.env    # from flower.ai → Settings → API Keys
scripts/run_leader.sh
```

That starts the SuperLink, the console, and a node for each of your local
profiles — then prints the join command with this laptop's network address.

**Your friend, on their laptop:**

```bash
git clone <your repo url> && cd aius-flower-hackathon
cd backend && uv sync && cd ..
scripts/new_user.py sam                       # their profile, on their disk
scripts/join.sh sam --leader 10.35.4.9        # the address you sent them
```

They need no API key. The app code is downloaded from your SuperLink; it reads
*their* profile from *their* disk.

**Then be the organiser,** in a second terminal on your laptop:

```bash
cd backend && FLWR_CHAT_SUPERLINK=local-agent uv run flwr chat
/load .
Plan a relaxing foodie evening in the city for Sam's birthday. Keep it a surprise.
```

In the console at <http://127.0.0.1:8765/>, your friend shows up with a 💻
avatar and an empty private panel — the leader has no copy of their calendar
or budget, so there is nothing to draw. All it ever receives from them is one
yes/no bit per offer.

Everything on one machine instead: `scripts/run_local.sh`. Full walkthrough,
including what to do when the firewall gets in the way:
[scripts/README.md](scripts/README.md).

## Spawning more users

The leader hardcodes nobody. It asks whoever connected who they are (the
identity round, which costs zero bits because a node's name is configuration,
not private data), and plans for them.

```bash
scripts/new_user.py alex --likes nature,morning,active --avoid foodie \
    --budget 70 --curfew 22 --needs step_free --busy "09:00-10:00 gym"
scripts/join.sh alex        # joins a running federation; nothing restarts
```

Run `scripts/new_user.py` with no arguments for an interactive prompt. The new
user takes part in `scripts/demo.sh` too, with no code change.

## Activity types

The vocabulary the whole system speaks, in `backend/event_planner/policy.py`:

`nature` · `city` · `morning` · `evening` · `active` · `relaxing` · `foodie` ·
`shopping`

Three places use it, and only these three:

- **The organiser's brief.** "A relaxing morning in nature" is parsed
  deterministically into tags — see `brief.py`. Synonyms count, so "brunch"
  reads as `morning` and "chill" as `relaxing`.
- **The guest of honour's wishes.** The only attribute anyone ever states, and
  only because it is their event. 8 bits.
- **Every activity in the catalogue.** `activities.py` tags each one, and
  `morning`/`evening` also constrain which time slots it can be offered in.

Everyone else's activity preferences stay private and show up only as yes/no
answers to concrete offers.

## The privacy argument, in one paragraph

Asking someone for their availability is asking for their calendar, coarsened.
Asking for their price band is asking for their budget. So the protocol asks
for neither. It proposes fully specified offers — this activity, this hour,
this price — and collects one bit each. A disclosed attribute is an assertion;
a veto is deniable. "I cannot do 20:00" could be a meeting, a commute, a
babysitter or a preference, and the leader cannot tell which.

The enforcement is not a sentence in a prompt. `guard.PolicyGrid` wraps the
runtime grid and validates every outbound reply against a schema before a
Flower message is ever constructed. Run `scripts/demo.sh --no-ui` to watch it
refuse seven payloads a helpful model might otherwise have sent.

For the full design argument, the measured numbers and the honest limitations,
see [backend/README.md](backend/README.md).
