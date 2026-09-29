"""Participant agent: answers one question, within policy, then stops.

A SuperNode agent only ever holds its own user's raw profile, and the runtime
only grants it `push_reply_message` -- it cannot address another participant
even if it wanted to (see RuntimeAgentGrid: SuperNodes get
_SUPERNODE_GRID_TOOL_NAMES). So the threat model here is narrow and real: the
only way private data escapes is through this node's own reply, and
guard.PolicyGrid is the one door.
"""

from __future__ import annotations

import json
from typing import Any

from flwr.agentapp import AgentSession
from flwr.app import Context

from event_planner import llm, policy, profiles
from event_planner.guard import PolicyGrid

INSTRUCTIONS = (
    "You are one person's private event-planning agent. The raw profile below "
    "is confidential and stays on this machine. Read all of it -- the "
    "calendar, the budget, the dietary, medical and mobility notes, the "
    "transport situation, the kinds of activity they like and avoid -- and "
    "use every part of it to decide. "
    "For each offer, answer true only if your person could actually go and "
    "would want to: the time must not clash with their calendar, the price "
    "band must sit inside their budget, the activity must be safe and "
    "accessible for them, they must be able to get there and home, and it "
    "must not be a kind of thing they avoid. "
    "Then send your answer with push_reply_message exactly once. "
    "Never state the reason for any answer, and never quote, paraphrase or "
    "hint at anything from the profile: not a calendar entry, not an amount "
    "or a price band, not an address, not a medical, dietary or mobility "
    "detail. A bare true or false is the whole answer. Reply with JSON only."
)


def _request(prompt: str) -> dict[str, Any]:
    """Unwrap the leader's request from the runtime's prompt envelope."""
    envelope = json.loads(prompt)
    payload = envelope.get("payload", "{}")
    return json.loads(payload) if isinstance(payload, str) else payload


def _fallback(phase: str, request: dict[str, Any], user: str) -> dict[str, Any]:
    """The minimum-information answer, sent if no compliant reply appears.

    Never "helpfully" widened. Refusing everything is the conservative default
    for a veto round: it can cost the group an option, but it cannot leak a
    preference.
    """
    if phase == "veto":
        return {"verdicts": [False] * len(request["candidates"])}
    if phase == "identity":
        return {"user": user, "role": profiles.role_of(user)}
    if phase == "wishes":
        return {"activity_prefs": [], "atmosphere": "casual", "prefers_new_place": False}
    return {"acknowledged": True}


def _send(grid: PolicyGrid, payload: dict[str, Any]) -> None:
    grid.call(
        {
            "type": "function_call",
            "call_id": llm.call_id(),
            "name": "push_reply_message",
            "arguments": json.dumps({"payload": json.dumps(payload)}),
        }
    )


def _schema_for(request: dict[str, Any]) -> dict[str, policy.Field]:
    phase = request["phase"]
    if phase == "veto":
        return policy.veto_schema(len(request["candidates"]))
    return policy.SCHEMAS[phase]()


def run(agent: AgentSession, context: Context) -> None:
    """Answer the leader's question under this node's disclosure policy."""
    user = profiles.user_for(context)
    private = profiles.load_private(user)
    request = _request(agent.prompt)
    phase = request["phase"]
    schema = _schema_for(request)
    fallback = _fallback(phase, request, user)

    grid = PolicyGrid(
        agent.grid,
        agent.events,
        user=user,
        phase=phase,
        schema=schema,
        # The node's own slug is configuration the operator chose, not private
        # data, so it must not be treated as a canary in the identity round.
        secrets=policy.canaries(private, allow={user}),
        fallback=fallback,
    )

    # The identity round is pure configuration, so there is nothing for a
    # model to decide and no reason to spend a call on it.
    if phase == "identity":
        _send(grid, fallback)
    else:
        prompt = json.dumps(
            {
                "question": request,
                "your_role": profiles.role_of(user),
                "raw_profile_LOCAL_ONLY": private,
                "disclosure_schema": {
                    name: field.describe for name, field in schema.items()
                },
            },
            indent=2,
        )
        llm.run_tool_loop(agent, grid, prompt, INSTRUCTIONS)
        # The model can finish without ever calling the reply tool, and the
        # leader is blocked waiting for exactly one message from this node.
        if grid.disclosed is None:
            _send(grid, fallback)

    if grid.disclosed is None:
        raise RuntimeError(f"{user}: no compliant reply was produced for {phase}")
    print(f"[{user}] {phase}: disclosed {grid.disclosed} ({grid.bits:.2f} bits)")
