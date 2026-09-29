"""The enforcement point: an AgentGrid that refuses to carry a disclosure.

The template hands `agent.grid` straight to the model and trusts a sentence in
the system prompt to keep private data on the node. That trust is misplaced --
in the shipped template the sentence is even garbled ("...do not invent
results." + "EVER send raw data...", missing its N), so the only privacy
control in the starter currently instructs the model to do the opposite of what
was intended.

`PolicyGrid` wraps the runtime grid and implements the same interface, so the
app loop is unchanged. Every `push_reply_message` is validated against this
user's disclosure schema before a Flower message is ever constructed. A payload
that fails validation is not sent -- it is returned to the model as a tool
error. The model can retry, but it cannot widen what it is allowed to say.
"""

from __future__ import annotations

import json
from typing import Any

from flwr.agentapp import AgentEvents, AgentGrid

from event_planner import policy

REPLY_TOOL = "push_reply_message"
MAX_VIOLATIONS = 3


class PolicyGrid(AgentGrid):
    """Mediate one user's outbound replies through a disclosure schema."""

    def __init__(
        self,
        inner: AgentGrid,
        events: AgentEvents,
        *,
        user: str,
        phase: str,
        schema: dict[str, policy.Field],
        secrets: set[str],
        fallback: dict[str, Any],
    ) -> None:
        self._inner = inner
        self._events = events
        self._user = user
        self._phase = phase
        self._schema = schema
        self._secrets = secrets
        self._fallback = fallback
        self._violations = 0
        self.disclosed: dict[str, Any] | None = None
        self.bits = 0.0

    def tools(self) -> list[dict[str, Any]]:
        """Expose the runtime tools, with the reply schema spelled out."""
        tools = [dict(tool) for tool in self._inner.tools()]
        for tool in tools:
            if tool.get("name") == REPLY_TOOL:
                tool["description"] = (
                    "Send your one reply. The payload MUST be a single JSON "
                    "object with exactly these fields and nothing else: "
                    f"{self._schema_hint()}. Free text, explanations, raw "
                    "calendar entries, exact amounts, addresses and medical "
                    "details are rejected before they are sent."
                )
        return tools

    def call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        """Validate a reply before letting it reach the federation."""
        if tool_call.get("name") != REPLY_TOOL:
            return self._inner.call(tool_call)

        arguments = tool_call["arguments"]
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        payload = arguments.get("payload", "")
        if not isinstance(payload, str):
            payload = json.dumps(payload)

        raw = policy.scan_for_raw(payload, self._secrets)
        if raw is not None:
            return self._blocked(
                tool_call,
                f"Blocked: the reply contained the raw private token '{raw}'. "
                "Derive a permitted field value instead of quoting your data.",
                kind="raw_value",
            )

        try:
            parsed, cost = policy.validate(payload, self._schema)
        except policy.PolicyViolation as err:
            return self._blocked(tool_call, f"Rejected: {err}", kind="schema")

        self.disclosed = parsed
        self.bits = cost
        self._ledger("allowed", fields=parsed, bits=cost)
        # Re-serialise from the parsed value so only validated content is sent.
        return self._inner.call(
            {
                **tool_call,
                "arguments": json.dumps({"payload": json.dumps(parsed, sort_keys=True)}),
            }
        )

    # --- internals -------------------------------------------------------

    def _schema_hint(self) -> str:
        return json.dumps(
            {name: field.describe for name, field in self._schema.items()},
            sort_keys=True,
        )

    def _blocked(
        self, tool_call: dict[str, Any], message: str, *, kind: str
    ) -> dict[str, Any]:
        """Refuse a disclosure, and keep the protocol live if it keeps failing."""
        self._violations += 1
        self._ledger("blocked", reason=message, kind=kind)

        if self._violations >= MAX_VIOLATIONS:
            # The planner is blocked on pull_messages, so silence is not an
            # option. Send the policy default: the minimum-information answer.
            self.disclosed = self._fallback
            _, cost = policy.validate(json.dumps(self._fallback), self._schema)
            self.bits = cost
            self._ledger("fallback", fields=self._fallback, bits=cost)
            return self._inner.call(
                {
                    **tool_call,
                    "arguments": json.dumps(
                        {"payload": json.dumps(self._fallback, sort_keys=True)}
                    ),
                }
            )

        return {
            "type": "function_call_output",
            "call_id": tool_call["call_id"],
            "output": json.dumps({"message_id": None, "error": message}),
        }

    def _ledger(self, verdict: str, **extra: Any) -> None:
        """Record what crossed this boundary, or failed to."""
        self._events.emit(
            {
                "type": "disclosure.ledger",
                "user": self._user,
                "phase": self._phase,
                "verdict": verdict,
                **extra,
            }
        )
