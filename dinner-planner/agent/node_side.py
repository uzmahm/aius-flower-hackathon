"""Guest-side agent: answers one question, within policy, then stops.

A SuperNode agent only ever holds its own persona's raw data, and the runtime
only grants it `push_reply_message` -- it cannot address another guest even if
it wanted to (see RuntimeAgentGrid: SuperNodes get _SUPERNODE_GRID_TOOL_NAMES).
So the threat model here is narrow and real: the only way private data escapes
is through this node's own reply, and guard.PolicyGrid is the one door.
"""

from __future__ import annotations

import json
from typing import Any

from flwr.agentapp import AgentSession
from flwr.app import Context

from agent import llm, personas, policy
from agent.guard import PolicyGrid

# The minimum-information answer for each phase, sent if the model cannot
# produce a compliant reply. Never "helpfully" widened.
FALLBACKS: dict[str, dict[str, Any]] = {
    "wishes": {
        "atmosphere": "casual",
        "cuisine_pref": "italian",
        "prefers_new_place": False,
    },
    "plan": {"acknowledged": True},
}

INSTRUCTIONS = (
    "You are one person's private dinner-planning agent. The raw profile below "
    "is confidential and stays on this machine. Read all of it -- the calendar, "
    "the budget, the dietary and medical notes, the transport situation -- and "
    "use every part of it to decide. "
    "For each offer, answer true only if your person could actually go: the "
    "hour must not clash with their calendar, the price band must sit inside "
    "their budget, the food must be safe for them to eat, they must be able to "
    "get there and home, and it must not be something they dislike. "
    "Then send your answer with push_reply_message exactly once. "
    "Never state the reason for any answer, and never quote, paraphrase or "
    "hint at anything from the profile: not a calendar entry, not an amount or "
    "a price band, not an address, not a medical or dietary detail. A bare "
    "true or false is the whole answer. Reply with JSON only."
)


def _request(prompt: str) -> dict[str, Any]:
    """Unwrap the planner's request from the runtime's prompt envelope."""
    envelope = json.loads(prompt)
    payload = envelope.get("payload", "{}")
    return json.loads(payload) if isinstance(payload, str) else payload


def _schema_and_fallback(
    request: dict[str, Any], persona: str
) -> tuple[str, dict[str, policy.Field], dict[str, Any]]:
    phase = request["phase"]
    if phase == "veto":
        candidates = request["candidates"]
        schema = policy.veto_schema(len(candidates))
        # Refusing everything is the conservative default: it can cost the
        # group a venue, but it cannot leak a preference.
        fallback = {"verdicts": [False] * len(candidates)}
    else:
        schema = policy.SCHEMAS[phase]()
        fallback = dict(FALLBACKS[phase])
    return phase, schema, fallback


def run(agent: AgentSession, context: Context) -> None:
    """Answer the planner's question under this node's disclosure policy."""
    persona = personas.persona_for(context)
    private = personas.load_private(persona)
    request = _request(agent.prompt)
    phase, schema, fallback = _schema_and_fallback(request, persona)

    grid = PolicyGrid(
        agent.grid,
        agent.events,
        persona=persona,
        phase=phase,
        schema=schema,
        secrets=policy.canaries(private),
        fallback=fallback,
    )

    prompt = json.dumps(
        {
            "question": request,
            "your_role": personas.role_of(persona),
            "raw_profile_LOCAL_ONLY": private,
            "disclosure_schema": {
                name: field.describe for name, field in schema.items()
            },
        },
        indent=2,
    )
    llm.run_tool_loop(agent, grid, prompt, INSTRUCTIONS)

    if grid.disclosed is None:
        raise RuntimeError(f"{persona}: no compliant reply was produced for {phase}")
    print(f"[{persona}] {phase}: disclosed {grid.disclosed} ({grid.bits:.2f} bits)")
