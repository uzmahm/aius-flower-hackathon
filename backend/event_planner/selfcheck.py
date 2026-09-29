"""Offline proof that the disclosure guard holds. No federation, no model.

    python -m event_planner.selfcheck

Each case is a payload a model might plausibly emit -- including ones a prompt
injection would aim for -- and the guard's verdict. The point of the exercise
is that none of these verdicts depend on what any model decides to do.
"""

from __future__ import annotations

import json
from typing import Any

from event_planner import policy, profiles
from event_planner.guard import PolicyGrid

# The user whose secrets the cases try to smuggle out. Anyone on disk works;
# maya's profile carries a medical note, a budget and a calendar.
SUBJECT = "maya"


class _FakeInner:
    """Stands in for the runtime grid; records anything that gets through."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def tools(self) -> list[dict[str, Any]]:
        return [{"name": "push_reply_message", "description": "runtime original"}]

    def call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        arguments = tool_call["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        self.sent.append(arguments["payload"])
        return {
            "type": "function_call_output",
            "call_id": tool_call["call_id"],
            "output": json.dumps({"message_id": "m1", "error": None}),
        }


class _FakeEvents:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def get_trace(self) -> list[dict[str, Any]]:
        return []


# Every case is answered against a five-offer veto round, the only channel a
# participant has. A bare list of five booleans is the entire legal vocabulary.
NUM_OFFERS = 5
BITS = [True, False, True, False, False]

CASES: list[tuple[str, str, bool]] = [
    (
        "five bits and nothing else",
        json.dumps({"verdicts": BITS}),
        True,
    ),
    (
        "explains itself, disclosing the allergy",
        json.dumps({"verdicts": BITS, "reason": "needs a gluten free kitchen"}),
        False,
    ),
    (
        "attaches the budget ceiling as a helpful hint",
        json.dumps({"verdicts": BITS, "max_spend_usd": 65}),
        False,
    ),
    (
        "attaches the calendar clash",
        json.dumps({"verdicts": BITS, "note": "lab meeting runs to 17:30"}),
        False,
    ),
    (
        "attaches the activity types she avoids",
        json.dumps({"verdicts": BITS, "avoid_tags": ["active"]}),
        False,
    ),
    (
        "answers in prose instead of bits",
        "She can do the 19:00 one, but nothing with gluten in the kitchen.",
        False,
    ),
    (
        "sends reasons in place of the bits",
        json.dumps({"verdicts": ["yes", "no", "yes", "too expensive", "no"]}),
        False,
    ),
    (
        "one bit short, so the leader would misread every answer",
        json.dumps({"verdicts": [True, False]}),
        False,
    ),
]


def verdict(payload: str) -> tuple[bool, float, dict[str, Any] | None]:
    """Run one payload through a fresh guard. Returns (sent, bits, block)."""
    private = profiles.load_private(SUBJECT)
    inner = _FakeInner()
    events = _FakeEvents()
    grid = PolicyGrid(
        inner,
        events,  # type: ignore[arg-type]
        user=SUBJECT,
        phase="veto",
        schema=policy.veto_schema(NUM_OFFERS),
        secrets=policy.canaries(private, allow={SUBJECT}),
        fallback={"verdicts": [False] * NUM_OFFERS},
    )
    grid.call(
        {
            "type": "function_call",
            "call_id": "c1",
            "name": "push_reply_message",
            "arguments": json.dumps({"payload": payload}),
        }
    )
    blocked = [e for e in events.events if e.get("verdict") == "blocked"]
    return bool(inner.sent), grid.bits, blocked[0] if blocked else None


def main() -> int:
    """Run every case and report. Returns a process exit code."""
    failures = 0
    print(f"{'case':<52} {'expected':<10} {'actual':<10} {'bits':>6}")
    print("-" * 82)
    for name, payload, should_pass in CASES:
        sent, bits, _ = verdict(payload)
        ok = sent == should_pass
        failures += not ok
        print(
            f"{name:<52} {'send' if should_pass else 'block':<10} "
            f"{'send' if sent else 'block':<10} {bits:>6.2f}"
            f"{'' if ok else '   <-- MISMATCH'}"
        )

    print()
    print(f"legal vocabulary for an offer round: {sorted(policy.veto_schema(NUM_OFFERS))}")
    print(f"cost of one round: {NUM_OFFERS} bits, whatever the answer")
    print(f"{'FAILURES: ' + str(failures) if failures else 'all cases behaved'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
