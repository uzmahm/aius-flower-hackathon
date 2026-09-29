"""Run the offline protocol and the guard cases, and emit one trace JSON.

    uv run --project backend python frontend/report/make_trace.py > trace.json
    uv run --project backend python frontend/report/build.py

The report reads this file's output, so the page always shows a real run
rather than hand-written numbers. Everything narrative on the page is derived
here from the run, which means it cannot go stale when the catalogue, the
policy or the set of users changes.
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from event_planner import (  # noqa: E402
    activities,
    leader,
    policy,
    profiles,
    selfcheck,
    simulate,
)


def guard_cases() -> list[dict[str, object]]:
    """Replay every adversarial case and record the guard's verdict."""
    rows = []
    for name, payload, should_pass in selfcheck.CASES:
        sent, bits, blocked = selfcheck.verdict(payload)
        rows.append(
            {
                "name": name,
                "payload": payload,
                "sent": sent,
                "expected_sent": should_pass,
                "bits": bits,
                "kind": blocked.get("kind") if blocked else None,
                "reason": blocked.get("reason") if blocked else None,
            }
        )
    return rows


def deniability(result: dict) -> list[dict[str, object]]:
    """Find offers two people refused for genuinely different private reasons.

    This is the argument the page has to make, and it is made from the run
    rather than asserted: same bit, different cause, no way to tell them
    apart from the leader's side.
    """
    users = {node: entry["user"] for node, entry in result["roster"].items()}
    found: list[dict[str, object]] = []
    for entry in result["rounds"]:
        for index, offer in enumerate(entry["offers"]):
            refusers = [
                users[node]
                for node, verdicts in entry["verdicts"].items()
                if not verdicts[index]
            ]
            reasons = {
                user: simulate.why_rejected(user, offer) for user in refusers
            }
            distinct = {r for r in reasons.values() if r}
            if len(distinct) < 2:
                continue
            found.append(
                {
                    "offer": activities.describe(offer),
                    "round": entry["round"],
                    "tally": entry["tallies"][index],
                    "voters": len(entry["verdicts"]),
                    "reasons": reasons,
                    "saw": f"{entry['tallies'][index]} of "
                    f"{len(entry['verdicts'])} accepted",
                }
            )
    # The most instructive cases are the ones with the most distinct causes.
    found.sort(key=lambda c: -len({r for r in c["reasons"].values() if r}))
    return found[:3]


def main() -> None:
    """Emit the full trace as JSON on stdout."""
    agent = simulate.FakeAgent()
    with redirect_stdout(io.StringIO()) as captured:
        result = simulate.run_protocol(agent)
    trace = {
        "nodes": [
            {
                "id": node,
                "user": entry["user"],
                "display_name": profiles.display_name(entry["user"]),
                "role": entry["role"],
                # Field NAMES only. The values are exactly what must not
                # travel, so the trace behind the report does not carry them.
                "private_fields": sorted(
                    k
                    for k, v in profiles.load_private(entry["user"]).items()
                    if v not in ([], "", None)
                ),
            }
            for node, entry in sorted(result["roster"].items())
        ],
        "ledger": [
            e for e in agent.events.log if e.get("type") == "disclosure.ledger"
        ],
        "report": "\n".join(
            line
            for line in captured.getvalue().strip().splitlines()
            if not line.startswith("UI_EVENT ")
        ),
        "schemas": {
            "identity": {n: f.describe for n, f in policy.identity_schema().items()},
            "wishes": {n: f.describe for n, f in policy.wishes_schema().items()},
            "veto": {
                n: f.describe
                for n, f in policy.veto_schema(leader.OFFERS_PER_ROUND).items()
            },
            "plan": {n: f.describe for n, f in policy.plan_schema().items()},
        },
        "slots": list(policy.SLOTS),
        "activity_tags": list(policy.ACTIVITY_TAGS),
        "offers_per_round": leader.OFFERS_PER_ROUND,
        "max_rounds": leader.MAX_ROUNDS,
        "catalogue_size": len(activities.CATALOGUE),
        "guard_cases": guard_cases(),
        "deniability": deniability(result),
        **result,
    }
    json.dump(trace, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
