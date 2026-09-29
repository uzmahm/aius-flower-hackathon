# Stock Flower starter templates

These are unmodified `flwr new` output, kept for reference and diffing. They
are not part of the Event Planner — nothing in `backend/` or `frontend/`
imports them.

| | |
| --- | --- |
| `agent/` | The minimal AgentApp: one model call, no SuperNodes |
| `collaborative-agent/` | The AgentApp that talks to SuperNodes over the Grid |

`collaborative-agent` is worth keeping around for one reason: its only privacy
control is a sentence in `agent/utils.py`, and that sentence is garbled. The
strings concatenate to `...do not invent results.EVER send raw data in a
message` — the `N` of `NEVER` was dropped. The shipped template's sole privacy
control instructs the model to do the opposite of what was intended, and
nothing in the system would notice. That is the argument for
`backend/event_planner/guard.py` being code instead of a prompt.
