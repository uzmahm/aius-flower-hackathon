"""End-to-end run of the protocol against simulated participants.

    python -m event_planner.simulate

Stubs the Grid and the model so the orchestration can be verified without a
live federation, a model key, or any SuperNodes. Each simulated participant
applies its own private rules locally -- calendar, budget, accessibility,
transport, disliked activity types -- and answers only with the bits its phase
schema permits, exactly as the real participant agent is constrained to.

`accepts()` below is the interesting part: every `return False` is a private
fact being used and not disclosed. It is driven entirely by the JSON profiles
in `event_planner/users/`, so a user you spawn with `scripts/new_user.py`
takes part here too, with no code change.
"""

from __future__ import annotations

import itertools
import json
import re
import sys
from typing import Any

from event_planner import activities, leader, policy, profiles, rules
from event_planner.rules import accepts, busy_slots, why_rejected, wishes_of  # noqa: F401

ORGANISER_PROMPT = (
    "Plan a relaxing foodie evening in the city for Sofia's birthday. "
    "Keep it a surprise from her."
)

def nodes() -> dict[str, str]:
    """Simulated node id -> user slug, one node per profile on disk."""
    return {str(11 + i): user for i, user in enumerate(profiles.available())}


class FakeEvents:
    def __init__(self) -> None:
        self.log: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.log.append(event)

    def get_trace(self) -> list[dict[str, Any]]:
        return []


class FakeGrid:
    """Minimal stand-in for RuntimeAgentGrid at the SuperLink."""

    def __init__(self, roster: dict[str, str]) -> None:
        self.roster = roster
        self.ids = itertools.count(100)
        self.inbox: dict[str, tuple[str, dict[str, Any]]] = {}

    def _reply_payload(self, user: str, request: dict[str, Any]) -> dict[str, Any]:
        """What one simulated participant's guarded agent would send back."""
        return rules.answer(user, request)

    def call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        name = tool_call["name"]
        args = json.loads(tool_call["arguments"])
        if name == "get_nodes":
            out: dict[str, Any] = {
                "nodes": [
                    {"id": n, "name": u, "location": "palo_alto"}
                    for n, u in self.roster.items()
                ],
                "num_available": len(self.roster),
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
                payload = self._reply_payload(self.roster[node], request)
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
    def __init__(self, prompt: str = ORGANISER_PROMPT) -> None:
        self.grid = FakeGrid(nodes())
        self.events = FakeEvents()
        self.prompt = prompt


# Force the deterministic ranking instead of calling a model.
leader.llm.ask_json = lambda agent, instructions, prompt, fallback: fallback


def run_protocol(agent: FakeAgent) -> dict[str, Any]:
    """Run the leader's protocol against the simulated nodes and report."""
    result = leader.plan(agent)
    print(leader._report(result))  # noqa: SLF001 -- the report is the output
    return result


def main() -> int:
    """Run the protocol and assert the properties the design claims."""
    agent = FakeAgent(sys.argv[1] if len(sys.argv) > 1 else ORGANISER_PROMPT)
    result = run_protocol(agent)
    users = {n: e["user"] for n, e in result["roster"].items()}

    print("\n--- checks ---")
    ledger = [e for e in agent.events.log if e.get("type") == "disclosure.ledger"]
    phases = {e["phase"] for e in ledger}
    assert "availability" not in phases, "an availability round still exists"
    assert "budget" not in phases, "a budget round still exists"
    print("rounds that happened:", sorted(phases))

    print("roster discovered at runtime:", sorted(users.values()))

    if result["excluded"]:
        told = {e["node"] for e in ledger if e["phase"] == "plan"}
        for node in result["excluded"]:
            assert node not in told, f"{users[node]} was told the plan!"
        print(
            "surprise held: told",
            sorted(users[n] for n in told),
            "| excluded",
            sorted(users[n] for n in result["excluded"]),
        )

    for event in ledger:
        if event["phase"] == "veto" and event["verdict"] == "received":
            assert set(event["fields"]) == {"verdicts"}, event
            assert all(isinstance(v, bool) for v in event["fields"]["verdicts"])
    print("every participant reply in the offer rounds was booleans only")

    worst = max(result["spend"][g] for g in result["guests"])
    print(f"worst-case participant disclosure: {worst:.2f} bits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
