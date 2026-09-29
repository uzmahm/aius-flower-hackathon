"""Raw private profiles. These dicts never leave the node that holds them.

In a real deployment each node would read its own profile from local storage
and no single file would contain all four. They are colocated here so the demo
runs from one checkout; `load_private` only ever returns one of them, chosen by
this node's own config, so no agent process holds another agent's raw data.
"""

from __future__ import annotations

from typing import Any

from flwr.app import Context

# Everything in `private` is the "only this agent knows" column: full
# calendars, exact budgets, medical facts, street addresses. Nothing here is
# shaped for disclosure -- that is the point. The disclosure schema in
# policy.py is what the agent is allowed to derive from it.
PROFILES: dict[str, dict[str, Any]] = {
    "ieva": {
        "role": "guest",
        "private": {
            "calendar": [
                "09:00-10:30 standup and sprint review",
                "13:00-14:00 dentist on Hamilton Avenue",
                "18:00-19:00 pick up dry cleaning before it closes",
            ],
            "budget_usd": 50,
            "home_address": "412 Waverley Street, Palo Alto",
            "dislikes": ["very loud rooms", "sharing plates with strangers"],
            "commitments": "leaving early Saturday for a family wedding",
            "tastes": ["italian", "american"],
        },
    },
    "maya": {
        "role": "guest",
        "private": {
            "calendar": ["11:00-12:00 physiotherapy", "16:30-17:30 lab meeting"],
            "budget_usd": 65,
            "medical": "coeliac disease, strict gluten avoidance, carries epinephrine",
            "dietary": "no gluten, no shellfish",
            "dislikes": ["buffets"],
            "tastes": ["japanese", "thai", "italian"],
        },
    },
    "emma": {
        "role": "guest",
        "private": {
            "calendar": ["14:00-15:00 advisor one-on-one"],
            "exact_location": "Escondido Village, Building 4B, Stanford",
            "transport": "no car, relies on the Marguerite shuttle which stops at 21:40",
            "dislikes": ["long walks after dark"],
            "tastes": ["japanese", "korean"],
        },
    },
    "birthday": {
        "role": "guest_of_honour",
        "private": {
            "wishlist": ["a ceramics class", "noise cancelling headphones"],
            "favourite_foods": ["handroll sushi", "tteokbokki", "black sesame dessert"],
            "visited_recently": ["Kiyoshi on University", "Seoul Garden"],
            "dislikes": ["singing waiters", "surprise photography"],
            "tastes": ["japanese", "korean"],
        },
    },
}

# The guest of honour must not learn the outcome. This is an information-flow
# rule, not a courtesy: it is enforced in planner_side.py, which never includes
# her node in the final-plan broadcast.
SURPRISE_EXCLUDED_ROLE = "guest_of_honour"

_ORDER = ("ieva", "maya", "emma", "birthday")


def persona_for(context: Context) -> str:
    """Return the persona this node speaks for.

    Prefers explicit node config (`--node-config 'persona="maya"'`). Falls back
    to a deterministic assignment by node id so the demo still runs on a
    federation started without per-node config.
    """
    configured = context.node_config.get("persona")
    if isinstance(configured, str) and configured in PROFILES:
        return configured
    return _ORDER[context.node_id % len(_ORDER)]


def load_private(persona: str) -> dict[str, Any]:
    """Return one persona's raw private data."""
    return PROFILES[persona]["private"]


def role_of(persona: str) -> str:
    """Return whether this persona is a guest or the guest of honour."""
    return PROFILES[persona]["role"]
