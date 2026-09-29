# Bounded Disclosure Planner

Four people plan a surprise birthday dinner. Each has an agent holding their
real calendar, budget, address and medical details. A planner agent finds a
venue everyone can attend — and the amount of private information that leaves
any one machine is bounded, enforced in code, and printed at the end of the run
as a number.

```
| node | bits disclosed | attributes stated |
| ---  | ---            | ---               |
| 11   | 11.00          | none              |
| 12   | 11.00          | none              |
| 13   | 11.00          | none              |
```

Nobody states a budget, a price band, a set of free hours, a dietary need or a
location. Ieva can only spend $50 a head; Maya is coeliac; Emma has no car and
the last shuttle is 21:40. All three facts decide the booking. None of them
crosses a wire.

---

## What changed from the original sketch, and why

The first design was a table of two columns per agent: *private* and *shared
with other agents*. Ieva shares `7–10 PM`, `$$`, Italian; Maya shares "must
satisfy dietary constraint". The planner pools the sanitised constraints and
negotiates. Six gaps, in the order they matter.

### 1. Privacy was a prompt, not a control

The starter template's only guard is a sentence in `INSTRUCTIONS`. In
`collaborative-agent/agent/utils.py` that sentence is *garbled* — the strings
concatenate to `...do not invent results.EVER send raw data in a message`, with
the `N` of `NEVER` dropped and no separating space. The shipped template's sole
privacy control currently instructs the model to do the opposite of what was
intended, and nothing in the system would notice.

**Now:** `agent/guard.py` wraps the runtime grid with `PolicyGrid`, which
implements the same `AgentGrid` interface, so the app loop is unchanged. Every
`push_reply_message` is validated against this node's disclosure schema before a
Flower `Message` is constructed. A non-compliant payload is never sent; it comes
back to the model as a tool error. The model may retry, but it cannot widen what
it is permitted to say. Prompts describe the protocol; they no longer carry a
control they cannot provide.

### 2. Coarsened constraints still leaked, by intersection

"Must satisfy dietary constraint" plus the planner's final pick is a disclosure.
If the group lands on a gluten-free venue, everyone has learned Maya's medical
fact. Emma's `6–9 PM` plus "within selected area" narrows her location far more
than *exact location: private* suggests.

**Now:** a two-phase protocol replaces constraint publishing.

- **Phase A** asks only what is structurally needed to schedule *anything*:
  role, hour-slot availability, price band. **9 bits.**
- **Phase B** proposes a shortlist; each guest returns one accept/reject bit per
  candidate and **no reasons**. **5 bits** for a shortlist of five.
- **Phase C** tells the guests the outcome. **1 bit.**

Prefer a veto to a disclosure. The original design published cuisine
preferences (7 bits, and a genuine taste fingerprint); the veto phase decides
the same question without them. Total exposure per guest is 15 bits, and the
*reason* a venue was rejected — the diagnosis, the shuttle timetable, the
dislike of loud rooms — never leaves the node.

### 3. The topology in the sketch is not the topology the framework allows

The sketch implies agents negotiating with each other. They cannot. In
`flwr/supercore/task_process/agent/grid.py`, `RuntimeAgentGrid` grants tools by
role: a SuperNode gets `push_reply_message` **only**, while `get_nodes`,
`push_messages` and `pull_messages` are reserved for the SuperLink. A guest
agent physically cannot address another guest.

This is a gift, not an obstacle — it is a runtime-enforced star topology, so the
set of possible information flows is small enough to reason about. The design now
states it as the security boundary rather than working against it. It also means
`push_reply_message` is once-per-instruction (the runtime nulls the metadata
after use), which is why each phase is a fresh planner-initiated round.

### 4. The planner trusted its inputs

Guarding only the outbound side leaves the planner willing to ingest anything a
node sends, so one buggy or hostile node could dump raw data into the planner's
context.

**Now:** `planner_side._exchange` validates every inbound payload against the
expected phase schema and drops what fails. The guard is symmetric.

### 5. The surprise was undefined

"Birthday Girl's Agent" shares preferences, but nothing said what she must not
learn — which is the whole point of a surprise party.

**Now:** it is an explicit asymmetric information-flow rule. Her taste ranks the
venue pool; she is excluded from every offer round and from the booking, so she
never sees a shortlist or the outcome. `dryrun.py` asserts it.

Her *role* costs zero bits too. No agent discloses whether it is the honouree:
SuperNode names are infrastructure metadata configured when the federation
starts, and the organiser names the birthday person in the prompt.

This surfaces a real tension worth naming in the demo: **you cannot both
preserve the surprise and let her veto.** Letting her reject candidates would
reveal the shortlist. The resolution — her preferences shape what gets proposed,
her vetoes are forfeited — is a deliberate trade, not an oversight.

### 6. A model-driven protocol is a demo that fails at 17:30

**Now:** the protocol is plain Python. `planner_side` synthesises Grid tool calls
directly (`agent.grid.call({...})`), so phases run deterministically in two
round-trips. The model is called **once**, for the one step needing world
knowledge: proposing candidate restaurants from pooled, unattributed
constraints. `llm.ask_json` falls back to a static shortlist rather than raising,
so a flaky model degrades the shortlist instead of killing the demo.

---

## Architecture

```
                    SuperLink — planner_side.py
                    deterministic protocol, inbound validation, ledger
                    tools: get_nodes / push_messages / pull_messages
                                     |
              +----------+-----------+-----------+
              |          |           |           |
          SuperNode  SuperNode   SuperNode   SuperNode
            ieva       maya        emma       birthday
                    node_side.py + guard.PolicyGrid
                    tools: push_reply_message (runtime-enforced)
                    holds: raw calendar / budget / medical / address
```

| file | role |
| --- | --- |
| `agent/policy.py` | Declared disclosure fields, their finite domains, and their cost in bits |
| `agent/guard.py` | `PolicyGrid` — the enforcement point on every outbound reply |
| `agent/personas.py` | Raw private profiles; `load_private` returns only this node's own |
| `agent/venues.py` | The public venue pool; an offer is a venue crossed with an hour |
| `agent/node_side.py` | Guest agent: answer one question within policy, then stop |
| `agent/planner_side.py` | Deterministic three-phase protocol, ledger, report |
| `agent/agent_app.py` | One app, role read off the runtime toolset |
| `agent/selfcheck.py` | Offline adversarial cases against the guard |
| `dryrun.py` | Full protocol against simulated nodes, no federation or model |
| `make_trace.py` | Runs both and emits `trace.json` |
| `ui.template.html` / `build_ui.py` | The console; `build_ui` injects the trace |

## Run it

Verify the guard with no federation and no model — six adversarial payloads,
including a prompt-injection-shaped one:

```bash
cd dinner-planner
PYTHONPATH=. python -m agent.selfcheck
```

Rehearse the whole protocol against simulated guests:

```bash
PYTHONPATH=. python dryrun.py
```

Rebuild the console from a fresh run — the UI reads the trace, so it cannot
show numbers the protocol did not produce:

```bash
PYTHONPATH=. python make_trace.py > trace.json
python build_ui.py          # writes ui.html
```

Against a real federation, start one SuperNode per persona:

```bash
flower-supernode --superlink 127.0.0.1:9092 --insecure \
  --node-config 'persona="maya"'
```

Personas are `ieva`, `maya`, `emma`, `birthday`. Without `--node-config`,
`personas.persona_for` assigns one deterministically from the node id, so the
demo still runs on a federation started without per-node config.

## Demo beats, in order

1. **The claim.** Show the ledger table. Every guest, 15 bits, total 45.
2. **The blocked exfiltration.** Run `selfcheck`. A model that tries to send
   `"coeliac disease, strict gluten avoidance"` in a permitted-looking field is
   blocked by schema; one that smuggles it into an allowed field's *value* is
   blocked by the raw-value scan. Neither verdict depends on the model.
3. **The fix for the leak nobody asks about.** Maya's veto of every
   non-gluten-free venue is indistinguishable from a veto on price or
   atmosphere. The planner learns a bit, not a diagnosis.
4. **The typo.** Show `utils.py` in the starter. Prompt-level privacy is not a
   control, and here is a shipped example of it silently inverting.

## Honest limitations

State these before a judge finds them.

- **11 bits is a bound, not zero.** A guest who rejects every offer in a round
  has still said something about how constrained they are, even without saying
  what constrains them.
- **Blind search costs rounds.** Each additional round is 5 more bits per
  guest. The privacy win is paid for in round-trips, not for free.
- **The planner sees attribution.** `src_node_id` is on every reply, so the
  planner knows who sent which bit. A single-planner star cannot blind that
  without a shuffler or aggregation; the mitigation here is minimisation, not
  anonymity. Candidate generation is fed pooled, unattributed constraints, which
  narrows what the *model* sees but not what the planner process could log.
- **Repeated runs compose.** Bits add up across dinners. A production version
  would need a per-participant budget that depletes, which `policy.bits` already
  gives the machinery for.
- **The raw-value scan is defence in depth, not the primary control.** It is a
  token-level substring check on a 5-character floor; it catches quoting and
  copying, not clever paraphrase. The schema is what makes paraphrase
  unnecessary to catch — there is no free-text field to paraphrase into.
