"""Model client and trace helpers.

Derived from the starter template's utils.py. Two changes worth noting:

* `INSTRUCTIONS` no longer carries the template's broken "EVER send raw data"
  sentence. Privacy is enforced in guard.py, so the prompt does not have to
  carry a control it cannot provide -- it only has to describe the protocol.
* Instruction strings are joined with a space. The template concatenated them
  directly, producing "...reply directly to the user.Use the available Grid".
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from flwr.agentapp import AgentSession
from openai import OpenAI

MODEL = "openai/gpt-5.6-terra"
STREAM_EVENT_TYPES = {
    "response.output_text.delta",
    "response.reasoning_summary_text.delta",
}
MAX_TOOL_ROUNDS = 12


def client() -> OpenAI:
    """Return a client bound to the Flower runtime's model proxy."""
    import os

    return OpenAI(
        base_url=os.environ["FLWR_RUNTIME_BASE_URL"],
        api_key=os.environ["FLWR_RUNTIME_API_KEY"],
        max_retries=0,
    )


def stream_turn(
    openai_client: OpenAI,
    agent: AgentSession,
    input_items: list[Any],
    tools: list[dict[str, Any]],
    instructions: str,
) -> tuple[Any, dict[str, Any]]:
    """Stream one model turn and return its completed response and event."""
    completed_response = None
    completed_event = None
    stream = openai_client.responses.create(
        model=MODEL,
        reasoning={"effort": "medium"},
        input=input_items,
        instructions=instructions,
        tools=tools,
        stream=True,
    )
    for event in stream:
        if event.type in STREAM_EVENT_TYPES:
            agent.events.emit(event.to_dict())
        elif event.type == "response.completed":
            completed_response = event.response
            completed_event = event.to_dict()

    if completed_response is None or completed_event is None:
        raise RuntimeError("Model response stream ended before completion")
    return completed_response, completed_event


def run_tool_loop(
    agent: AgentSession,
    grid: Any,
    prompt: str,
    instructions: str,
) -> None:
    """Drive the model until it stops calling tools."""
    openai_client = client()
    input_items: list[Any] = [{"type": "message", "role": "user", "content": prompt}]
    tools = grid.tools()

    for _ in range(MAX_TOOL_ROUNDS):
        response, completed_event = stream_turn(
            openai_client, agent, input_items, tools, instructions
        )
        output = [item.to_dict() for item in response.output]
        calls = [item for item in output if item.get("type") == "function_call"]
        input_items.extend(output)
        if not calls:
            agent.events.emit(completed_event)
            return
        input_items.extend(grid.call(item) for item in calls)
    raise RuntimeError(f"Agent exceeded {MAX_TOOL_ROUNDS} tool rounds")


def ask_json(
    agent: AgentSession, instructions: str, prompt: str, fallback: Any
) -> Any:
    """One model call that must return JSON. Falls back rather than dying.

    Used for the single genuinely fuzzy step in the protocol (ranking the
    activity catalogue). A hackathon demo should degrade, not crash, so a
    malformed answer returns `fallback`.
    """
    openai_client = client()
    try:
        response, _ = stream_turn(
            openai_client,
            agent,
            [{"type": "message", "role": "user", "content": prompt}],
            [],
            instructions,
        )
        text = "".join(
            part.get("text", "")
            for item in (i.to_dict() for i in response.output)
            if item.get("type") == "message"
            for part in item.get("content", [])
        )
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return fallback
        return json.loads(text[start : end + 1])
    except Exception:  # pylint: disable=broad-exception-caught
        return fallback


def call_id() -> str:
    """Return a fresh synthetic tool call id."""
    return f"call_{uuid.uuid4().hex[:24]}"
