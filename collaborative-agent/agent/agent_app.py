"""A minimal Flower AgentApp that involves SuperNodes."""

import os
from typing import Any

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context
from openai import OpenAI

from agent.utils import _conversation, _stream_response

MAX_TOOL_ROUNDS = 20
app = AgentApp()


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    """Let the model choose and call a Grid tool."""

    client = OpenAI(
        base_url=os.environ["FLWR_RUNTIME_BASE_URL"],
        api_key=os.environ["FLWR_RUNTIME_API_KEY"],
        max_retries=0,
    )
    input_items: list[Any] = _conversation(agent, context)
    try:
        connector_tools = agent.connectors.tools(["filesystem"])
    except ValueError:
        connector_tools = []
    connector_tool_names = {tool["name"] for tool in connector_tools}
    tools = [*agent.grid.tools(), *connector_tools]

    for _ in range(MAX_TOOL_ROUNDS):
        response, completed_event = _stream_response(client, agent, input_items, tools)
        response_output = [item.to_dict() for item in response.output]
        tool_calls = [
            item for item in response_output if item.get("type") == "function_call"
        ]
        input_items.extend(response_output)
        if not tool_calls:
            agent.events.emit(completed_event)
            return
        input_items.extend(
            (
                agent.connectors.call(item)
                if item.get("name") in connector_tool_names
                else agent.grid.call(item)
            )
            for item in tool_calls
        )
    raise RuntimeError(f"Agent exceeded {MAX_TOOL_ROUNDS} tool rounds")
