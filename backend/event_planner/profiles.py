"""Loading one user's profile. Raw profiles never leave the node holding them.

A user is a JSON file in `event_planner/users/`. That is the whole registry:
to add a participant to the federation, drop a file in that directory and
start a SuperNode with `--node-config 'user="<stem>"'`. Nothing in the planner
hardcodes who is taking part -- the leader discovers the roster at runtime
(see `policy.identity_schema`).

In a real deployment each node would read only its own file from local
storage and no machine would hold anybody else's. They are colocated here so
the demo runs from one checkout; `load_private` only ever returns one of them,
chosen by this node's own config.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flwr.app import Context

USERS_DIR = Path(__file__).parent / "users"

# The guest of honour must not learn the outcome. This is an information-flow
# rule, not a courtesy: it is enforced in leader.py, which never includes the
# honouree's node in the offer rounds or in the final-plan broadcast.
HONOUREE_ROLE = "honouree"
PARTICIPANT_ROLE = "participant"

# Keys that may appear under "private". Anything else is still loaded and still
# protected -- this list exists so the console can label the common ones and so
# `scripts/new_user.py` knows what to prompt for.
PRIVATE_KEYS = (
    "calendar",
    "budget_usd",
    "home_area",
    "home_address",
    "curfew_hour",
    "needs",
    "like_tags",
    "avoid_tags",
    "avoid_areas",
    "avoid_atmospheres",
    "dislikes",
    "notes",
)


def users_dir() -> Path:
    """Where user profiles live. `EVENT_PLANNER_USERS` overrides the default."""
    override = os.environ.get("EVENT_PLANNER_USERS")
    return Path(override) if override else USERS_DIR


def available() -> list[str]:
    """Every user slug this checkout knows about, in a stable order."""
    return sorted(path.stem for path in users_dir().glob("*.json"))


def load(user: str) -> dict[str, Any]:
    """Read one user's whole profile file."""
    path = users_dir() / f"{user}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No profile for user '{user}'. Known users: {available()}. "
            f"Create one with scripts/new_user.py."
        )
    return json.loads(path.read_text())


def load_all() -> dict[str, dict[str, Any]]:
    """Every profile, keyed by slug. Only the console (a narrator) uses this."""
    return {user: load(user) for user in available()}


def user_for(context: Context) -> str:
    """Return the user this node speaks for.

    Prefers explicit node config (`--node-config 'user="maya"'`). Falls back to
    a deterministic assignment by node id so a federation started without
    per-node config still runs.
    """
    configured = context.node_config.get("user")
    known = available()
    if isinstance(configured, str) and configured in known:
        return configured
    if not known:
        raise RuntimeError(f"No user profiles found in {users_dir()}.")
    return known[context.node_id % len(known)]


def load_private(user: str) -> dict[str, Any]:
    """Return one user's raw private data."""
    return load(user).get("private", {})


def role_of(user: str) -> str:
    """Whether this user is an ordinary participant or the guest of honour."""
    return load(user).get("role", PARTICIPANT_ROLE)


def display_name(user: str) -> str:
    """The name to show in reports and in the console."""
    return load(user).get("display_name", user.title())
