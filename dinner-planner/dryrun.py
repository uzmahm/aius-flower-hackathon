"""End-to-end dry run of the protocol against simulated guest agents.

Stubs the Grid and the model so the orchestration can be verified without a
live federation. Each simulated guest applies its own private rules locally --
calendar, budget, allergy, transport, dislikes -- and answers only with the
bits its phase schema permits, exactly as the real node agent is constrained
to. The `_rules` functions below are the interesting part: every `return False`
is a private fact being used and not disclosed.
"""

from __future__ import annotations

import itertools
import json

from agent import personas, planner_side, policy
from agent.venues import BAND_SPEND

NODES = {"11": "ieva", "12": "maya", "13": "emma", "14": "birthday"}

ORGANISER_PROMPT = (
    "Book a surprise birthday dinner. The guest of honour is birthday; "
    "do not let her agent see the shortlist or the booking."
)

WISHES = {"atmosphere": "cosy", "cuisine_pref": "japanese", "prefers_new_place": True}

# Hours each person cannot make, derived locally from the calendar in
# personas.PROFILES. The planner never sees this and never asks for it.
BUSY = {
    "ieva": {"18-19"},      # collecting dry cleaning before it closes
    "maya": {"17-18"},      # lab meeting runs to 17:30
    "emma": set(),
}
# The last hour each person can still get home. Emma has no car and the
# Marguerite shuttle stops at 21:40.
LAST_HOUR = {"ieva": 23, "maya": 23, "emma": 21}


def _rules(persona: str, offer: dict) -> bool:
    """One guest's private decision about one offer. Reasons never leave here."""
    private = personas.load_private(persona)
    start, end = (int(part) for part in offer["slot"].split("-"))

    if offer["slot"] in BUSY[persona]:
        return False                                    # calendar clash
    if end > LAST_HOUR[persona]:
        return False                                    # cannot get home
    budget = private.get("budget_usd")
    if budget is not None and BAND_SPEND[offer["price_band"]] > budget:
        return False                                    # over their ceiling
    if "gluten" in str(private.get("dietary", "")) and (
        "gluten_free" not in offer["dietary"]
    ):
        return False                                    # coeliac -- never disclosed
    if "very loud rooms" in private["dislikes"] and offer["atmosphere"] == "lively":
        return False
    if "exact_location" in private and offer["area"] == "el_camino":
        return False                                    # no car, too far
    return True


class FakeEvents:
    def __init__(self):
        self.log = []

    def emit(self, event):
        self.log.append(event)

    def get_trace(self):
        return []


class FakeGrid:
    """Minimal stand-in for RuntimeAgentGrid at the SuperLink."""

    def __init__(self):
        self.ids = itertools.count(100)
        self.inbox = {}

    def call(self, tool_call):
        name = tool_call["name"]
        args = json.loads(tool_call["arguments"])
        if name == "get_nodes":
            out = {
                "nodes": [
                    {"id": n, "name": p, "location": "palo_alto"}
                    for n, p in NODES.items()
                ],
                "num_available": len(NODES),
            }
        elif name == "push_messages":
            results = []
            for message in args["messages"]:
                mid = f"m{next(self.ids)}"
                self.inbox[mid] = (
                    message["dst_node_id"],
                    json.loads(message["payload"]),
                )
                results.append({"message_id": mid, "error": None})
            out = {"results": results}
        elif name == "pull_messages":
            messages = []
            for mid in args["message_ids"]:
                node, request = self.inbox.pop(mid)
                persona = NODES[node]
                phase = request["phase"]
                if phase == "wishes":
                    payload = WISHES
                elif phase == "veto":
                    payload = {
                        "verdicts": [
                            _rules(persona, offer) for offer in request["candidates"]
                        ]
                    }
                else:
                    payload = {"acknowledged": True}
                messages.append(
                    {
                        "message_id": f"r{mid}",
                        "reply_to_message_id": mid,
                        "src_node_id": node,
                        "payload": json.dumps(payload),
                        "error": None,
                    }
                )
            out = {"messages": messages, "pending_message_ids": []}
        else:
            raise AssertionError(f"unexpected Grid tool {name}")
        return {
            "type": "function_call_output",
            "call_id": tool_call["call_id"],
            "output": json.dumps(out),
        }


class FakeAgent:
    def __init__(self):
        self.grid = FakeGrid()
        self.events = FakeEvents()
        self.prompt = ORGANISER_PROMPT


# Force the deterministic venue ranking instead of calling a model.
planner_side.llm.ask_json = lambda agent, instructions, prompt, fallback: fallback


def run_protocol(agent):
    """Run the planner protocol against the simulated nodes and report."""
    result = planner_side.plan(agent)
    print(planner_side._report(result))
    return result


def main():
    agent = FakeAgent()
    result = run_protocol(agent)

    print("\n--- checks ---")
    ledger = [e for e in agent.events.log if e.get("type") == "disclosure.ledger"]
    phases = {e["phase"] for e in ledger}
    assert "availability" not in phases, "an availability round still exists"
    print("no availability round:", sorted(phases))

    told = {e["node"] for e in ledger if e["phase"] == "plan"}
    assert "14" not in told, "guest of honour was told the plan!"
    print("nodes told the plan:", sorted(told), "(14 excluded)")

    # Nothing a guest sent may be anything but a list of booleans.
    for event in ledger:
        if event["phase"] == "veto" and event["verdict"] == "received":
            assert set(event["fields"]) == {"verdicts"}, event
            assert all(isinstance(v, bool) for v in event["fields"]["verdicts"])
    print("every guest reply was booleans only")

    guest_bits = max(result["spend"][g] for g in result["guests"])
    print(f"worst-case guest disclosure: {guest_bits:.2f} bits")
    return result


if __name__ == "__main__":
    main()
