# Backend — the Flower AgentApp

Everything in here runs inside the federation. Nothing in here draws anything;
the front end is in [../frontend](../frontend).

One FAB, two roles. The Flower runtime decides which Grid tools each side
gets, so the app reads its own role off the toolset rather than guessing:

| where | role | module | runtime tools |
| --- | --- | --- | --- |
| SuperLink | the leader | `leader.py` | `get_nodes`, `push_messages`, `pull_messages` |
| SuperNode | one participant | `participant.py` | `push_reply_message` only |

## Module map

| file | role |
| --- | --- |
| `agent_app.py` | The single entry point; dispatches on the runtime toolset |
| `leader.py` | The centralized task: roster, brief, blind search, ledger, report |
| `participant.py` | One user's agent: answer one question within policy, then stop |
| `policy.py` | What may leave a node, its finite domain, and its cost in bits |
| `guard.py` | `PolicyGrid` — the enforcement point on every outbound reply |
| `brief.py` | Parses the organiser's prompt into activity tags and a honouree |
| `activities.py` | The public catalogue; an offer is one activity crossed with one slot |
| `profiles.py` | Loads one user's raw profile from `users/` |
| `users/*.json` | One file per person. This is the whole registry |
| `llm.py` | Model client and the tool loop |
| `ui_events.py` | The `UI_EVENT` lines the console reads |
| `selfcheck.py` | Offline adversarial cases against the guard |
| `simulate.py` | The whole protocol against simulated users, no federation, no model |

## Run the checks

```bash
uv run python -m event_planner.selfcheck    # can a participant's agent leak?
uv run python -m event_planner.simulate     # the whole protocol, offline
uv run python -m event_planner.simulate "Plan an active morning in nature. No surprise."
```

Both are also wrapped by `scripts/demo.sh` from the repo root.

## The protocol

Four rounds, all driven by plain Python. The model is called exactly once, for
the single step that needs taste.

| phase | who | what they send | bits |
| --- | --- | --- | --- |
| `identity` | everyone | their configured slug and role | **0** |
| `wishes` | guest of honour only | activity tags, atmosphere, new-or-not | **11** |
| `veto` | every participant, per round | one accept/reject bit per offer | **5** |
| `plan` | everyone who may know | acknowledged | **1** |

A participant who is not the guest of honour therefore spends
`5 × rounds + 1` bits and states no attribute at all.

### Why identity is free

A node's slug is the one the operator typed when they started the SuperNode
(`--node-config 'user="maya"'`). It is not derived from anyone's private
profile, so answering it discloses nothing the operator did not already
publish. `policy.label_field` enforces the shape — 24 lowercase characters, no
spaces, no punctuation — which is what stops it becoming a free-text side
channel. Everything else in the system follows from this round: it is how the
leader learns who is present without anybody hardcoding a roster.

### Why there is no availability round and no budget round

Both were in an earlier design and both are the sensitive thing itself, only
coarsened. A price band **is** the budget: "I am a $ person" is the socially
costly fact, not the figure behind it. An availability subset **is** the
calendar: someone free in exactly one slot has disclosed a busy week.

Both are decidable by veto instead, so neither is asked.

> A disclosed attribute is an assertion. A veto is deniable.

A rejection could be a meeting, a commute, a budget ceiling, a coeliac
diagnosis, a bad knee or a dislike of crowds. From the leader's side they are
identical. `frontend/report/` derives this from an actual run rather than
asserting it: it finds the offers two people refused for genuinely different
reasons and shows the two identical `false` bits.

### Why the guard is code, not a prompt

The stock `collaborative-agent` template's only privacy control is a sentence
in `INSTRUCTIONS`, and in `templates/collaborative-agent/agent/utils.py` that
sentence is garbled — the strings concatenate to
`...do not invent results.EVER send raw data in a message`, with the `N` of
`NEVER` dropped. The shipped template's sole privacy control currently
instructs the model to do the opposite of what was intended, and nothing in
the system would notice.

`guard.PolicyGrid` implements the same `AgentGrid` interface as the runtime
grid, so the app loop is unchanged, and validates every `push_reply_message`
against this node's schema before a Flower message is constructed. A
non-compliant payload is never sent; it comes back to the model as a tool
error. The model may retry, but it cannot widen what it is permitted to say.

The guard is symmetric: `leader._exchange` validates every inbound payload
too, and drops what fails, so one buggy or hostile node cannot dump raw data
into the leader's context.

### The surprise is an information-flow rule

If the brief names a guest of honour and does not say otherwise, that person's
node is excluded from every offer round and from the plan broadcast. Their
stated activity preferences rank the catalogue; they never see a shortlist or
the outcome. `simulate.py` asserts it.

This surfaces a real tension worth naming: **you cannot both preserve the
surprise and let them veto.** Letting them reject candidates would reveal the
shortlist. The resolution — their preferences shape what gets proposed, their
vetoes are forfeited — is a deliberate trade. Say "no surprise" in the brief
and they vote like everybody else.

## How the blind search works

The leader proposes offers and sees only tallies, so it has to infer which
hours, prices and kinds of activity the group can live with — never why, and
never which person.

It estimates the chance everyone accepts an offer as the **product** of the
accept rates it has seen for each of the offer's public attributes. The
multiplication is the whole trick: an activity two people out of three can do,
at an hour two out of three can make, is not a two-out-of-three offer, because
the refusers are probably different people. Summing the evidence hides that.

Rates are smoothed toward the overall prior so one round cannot write off a
whole price band, and offers built from attributes nobody has asked about get
a small optimism bonus.

Measured over 237 random feasible rosters of 3–6 people, this finds an offer
everyone accepts **88.6%** of the time within `MAX_ROUNDS`, against 87.3% for
pure exploitation. The honest reading: the gain is within noise, and a real
improvement would need a better question, not a better coefficient.

## Adding a person

A user is a JSON file in `users/`. That is the entire registry.

```json
{
  "display_name": "Alex",
  "emoji": "🧗",
  "role": "participant",
  "private": {
    "calendar": ["09:00-10:00 gym class"],
    "budget_usd": 70,
    "curfew_hour": 22,
    "needs": ["step_free"],
    "like_tags": ["nature", "active"],
    "avoid_tags": ["shopping"],
    "avoid_areas": [],
    "avoid_atmospheres": [],
    "home_area": "midtown",
    "notes": "training for a half marathon"
  }
}
```

Set `"role": "honouree"` to make someone the person being surprised. Use
`scripts/new_user.py` rather than writing these by hand — it validates the
vocabularies. Everything under `private` is what the guard exists to keep
local; nothing in it is shaped for disclosure.

In a real deployment each node would read only its own file from local
storage. They are colocated here so the demo runs from one checkout, and
`load_private` only ever returns one of them.

## Honest limitations

State these before a judge finds them.

- **11 bits is a bound, not zero.** Someone who rejects every offer in a round
  has still said something about how constrained they are, even without
  saying what constrains them.
- **Blind search costs rounds,** and it does not always succeed — see the
  88.6% above. Each extra round is 5 more bits per person. The privacy win is
  paid for in round-trips.
- **The leader sees attribution.** `src_node_id` is on every reply, so it
  knows who sent which bit. A single-leader star cannot blind that without a
  shuffler or aggregation; the mitigation here is minimisation, not anonymity.
- **Repeated runs compose.** Bits add up across events. A production version
  would need a per-participant budget that depletes, which `policy.bits`
  already gives the machinery for.
- **The raw-value scan is defence in depth, not the primary control.** It is a
  token-level substring check on a 5-character floor; it catches quoting and
  copying, not clever paraphrase. The schema is what makes paraphrase
  unnecessary to catch — there is no free-text field to paraphrase into.
- **The identity round's zero-bit claim rests on an assumption:** that the
  operator chose the slug, not the person's private data. Name a node
  `coeliac-maya` and that assumption is false.
