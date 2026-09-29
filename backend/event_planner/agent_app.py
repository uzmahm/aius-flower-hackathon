"""One AgentApp, two roles: the leader and every participant.

A Flower FAB declares a single `agentapp` component, and the same app runs at
the SuperLink and on every SuperNode. The runtime decides which Grid tools
each side gets -- `push_reply_message` on a SuperNode, `get_nodes` /
`push_messages` / `pull_messages` at the SuperLink -- so the app reads its own
role off the toolset rather than guessing from a node id.

    SuperLink  -> leader.run       (the centralized planning task)
    SuperNode  -> participant.run  (one user, one private profile)
"""

from __future__ import annotations

from flwr.agentapp import AgentApp, AgentSession
from flwr.app import Context

from event_planner import leader, participant

app = AgentApp()

REPLY_ONLY_TOOL = "push_reply_message"


def _is_participant(agent: AgentSession) -> bool:
    """True when the runtime only permits replying, i.e. we are a SuperNode."""
    return any(tool.get("name") == REPLY_ONLY_TOOL for tool in agent.grid.tools())


@app.main()
def main(agent: AgentSession, context: Context) -> None:
    """Dispatch to this side's implementation."""
    if _is_participant(agent):
        participant.run(agent, context)
    else:
        leader.run(agent, context)
