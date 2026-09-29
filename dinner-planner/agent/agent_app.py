"""One AgentApp, two roles.

A Flower FAB declares a single `agentapp` component, and the same app runs at
the SuperLink and on every SuperNode. The runtime decides which Grid tools each
side gets -- `push_reply_message` on a SuperNode, `get_nodes` / `push_messages`
/ `pull_messages` at the SuperLink -- so the app can read its own role off the
toolset rather than guessing from a node id.
"""

from __future__ import annotations

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context

from agent import node_side, planner_side

app = AgentApp()

REPLY_ONLY_TOOL = "push_reply_message"


def _is_guest_node(agent: AgentSession) -> bool:
    """True when the runtime only permits replying, i.e. we are a SuperNode."""
    return any(tool.get("name") == REPLY_ONLY_TOOL for tool in agent.grid.tools())


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    """Dispatch to the guest agent or the planner."""
    if _is_guest_node(agent):
        node_side.run(agent, context)
    else:
        planner_side.run(agent, context)
