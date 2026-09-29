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

from event_planner import llm, policy, profiles, rules
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
    "detail. A bare true or false is the whole answer. Do not answer in "
    "text: only the push_reply_message call counts, and its payload is JSON "
    "only."
)


def _request(prompt: str) -> dict[str, Any]:
    """Unwrap the leader's request from the runtime's prompt envelope."""
    envelope = json.loads(prompt)
    payload = envelope.get("payload", "{}")
    return json.loads(payload) if isinstance(payload, str) else payload


def _json_in(text: str) -> dict[str, Any] | None:
    """The JSON object in a model's text answer, if there is one."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


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
    # Decided by plain rules on this node, from this node's profile. Sent when
    # the model is unavailable or will not produce a compliant reply; it is
    # held to the same schema, so it discloses no more than the model could.
    fallback = rules.answer(user, request)

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
        try:
            text = llm.run_tool_loop(agent, grid, prompt, INSTRUCTIONS)
        except Exception as err:  # pylint: disable=broad-exception-caught
            # Typically no FLWR_MODEL_API_KEY on this laptop.
            print(f"[{user}] model unavailable, deciding by local rules: {err}")
            text = ""
        # The model can finish without calling the reply tool, often by
        # writing the JSON as text. The leader is blocked waiting for exactly
        # one message from this node, so send that text through the guard, or
        # failing that the rule-based answer.
        if grid.disclosed is None and (answer := _json_in(text)) is not None:
            _send(grid, answer)
        if grid.disclosed is None:
            _send(grid, fallback)

    if grid.disclosed is None:
        raise RuntimeError(f"{user}: no compliant reply was produced for {phase}")
    print(f"[{user}] {phase}: disclosed {grid.disclosed} ({grid.bits:.2f} bits)")
