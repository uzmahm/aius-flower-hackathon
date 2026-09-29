"""Run the offline protocol and the guard cases, and emit one trace JSON.

The UI in ui.html reads this file's output, so the dashboard always shows a
real run rather than hand-written numbers. Regenerate after changing policy:

    PYTHONPATH=. python make_trace.py > trace.json
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout

import dryrun
from agent import personas, planner_side, policy, selfcheck, venues
from agent.guard import PolicyGrid


def guard_cases() -> list[dict[str, object]]:
    """Replay every adversarial case and record the guard's verdict."""
    private = personas.load_private("maya")
    rows = []
    for name, payload, should_pass in selfcheck.CASES:
        inner = selfcheck._FakeInner()
        events = selfcheck._FakeEvents()
        grid = PolicyGrid(
            inner,
            events,  # type: ignore[arg-type]
            persona="maya",
            phase="veto",
            schema=policy.veto_schema(selfcheck.NUM_OFFERS),
            secrets=policy.canaries(private),
            fallback={"verdicts": [False] * selfcheck.NUM_OFFERS},
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
        rows.append(
            {
                "name": name,
                "payload": payload,
                "sent": bool(inner.sent),
                "expected_sent": should_pass,
                "bits": grid.bits,
                "kind": blocked[0].get("kind") if blocked else None,
                "reason": blocked[0].get("reason") if blocked else None,
            }
        )
    return rows


def main() -> None:
    """Emit the full trace as JSON on stdout."""
    agent = dryrun.FakeAgent()
    with redirect_stdout(io.StringIO()) as captured:
        result = dryrun.run_protocol(agent)
    trace = {
        "nodes": [
            {
                "id": nid,
                "persona": persona,
                "role": personas.role_of(persona),
                # Field NAMES only. The values are exactly what must not travel,
                # so the trace that feeds the UI does not carry them either.
                "private_fields": sorted(personas.load_private(persona)),
            }
            for nid, persona in dryrun.NODES.items()
        ],
        "ledger": [e for e in agent.events.log if e.get("type") == "disclosure.ledger"],
        "report": captured.getvalue().strip(),
        "schemas": {
            "wishes": {n: f.describe for n, f in policy.wishes_schema().items()},
            "veto": {
                n: f.describe
                for n, f in policy.veto_schema(planner_side.OFFERS_PER_ROUND).items()
            },
            "plan": {n: f.describe for n, f in policy.plan_schema().items()},
        },
        "slots": list(policy.SLOTS),
        "offers_per_round": planner_side.OFFERS_PER_ROUND,
        "max_rounds": planner_side.MAX_ROUNDS,
        "venue_pool": len(venues.VENUES),
        "guard_cases": guard_cases(),
        **result,
    }
    json.dump(trace, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
