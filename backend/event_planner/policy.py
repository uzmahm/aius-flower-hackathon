"""Disclosure policy: what may leave a participant's node, and what it costs.

This module is the whole privacy argument of the project. Every value that
crosses a node boundary must be an instance of a declared field here, so the
set of things a participant's agent *can* say is finite and enumerable before
the model runs. Because each field has a finite domain, the information
released is not just "small" in a hand-wavy sense -- it is measurable, and
`bits()` measures it.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

# Two-hour blocks spanning a whole day, because an event is not necessarily
# dinner: a hike starts at 09:00 and a night market ends at 23:00. A subset of
# a 7-element set is exactly 7 bits, whoever answers.
SLOTS: tuple[str, ...] = (
    "09-11",
    "11-13",
    "13-15",
    "15-17",
    "17-19",
    "19-21",
    "21-23",
)

# Which part of the day each slot belongs to. Used to keep a "morning" activity
# out of an evening slot; never asked of anyone.
DAYPARTS: dict[str, str] = {
    "09-11": "morning",
    "11-13": "morning",
    "13-15": "afternoon",
    "15-17": "afternoon",
    "17-19": "evening",
    "19-21": "evening",
    "21-23": "evening",
}

# The activity-type vocabulary. This is the "what kind of thing shall we do"
# axis of the planner: the organiser puts some of these in the brief, the guest
# of honour may state a few, and every activity in the catalogue is tagged with
# the ones it satisfies.
ACTIVITY_TAGS: tuple[str, ...] = (
    "nature",
    "city",
    "morning",
    "evening",
    "active",
    "relaxing",
    "foodie",
    "shopping",
)

PRICE_BANDS: tuple[str, ...] = ("$", "$$", "$$$", "$$$$")

ATMOSPHERES: tuple[str, ...] = ("cosy", "lively", "formal", "casual")

# Identity slugs are infrastructure configuration -- the name the operator gave
# the SuperNode when they started it -- so they are matched by shape, not drawn
# from a fixed domain, and they cost zero bits. See `label_field`.
USER_SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")

ROLES: tuple[str, ...] = ("participant", "honouree")


@dataclass(frozen=True)
class Field:
    """One declared disclosure: its domain, its validator, its price in bits."""

    name: str
    describe: str
    check: Callable[[Any], bool]
    bits: Callable[[Any], float]


def subset_field(name: str, domain: tuple[str, ...], describe: str) -> Field:
    """A subset of a fixed domain. Costs one bit per domain member."""

    def check(value: Any) -> bool:
        return (
            isinstance(value, list)
            and all(isinstance(v, str) for v in value)
            and set(value) <= set(domain)
            and len(set(value)) == len(value)
        )

    return Field(name, describe, check, lambda _v: float(len(domain)))


def enum_field(name: str, domain: tuple[str, ...], describe: str) -> Field:
    """Exactly one member of a fixed domain. Costs log2(|domain|) bits."""

    def check(value: Any) -> bool:
        return isinstance(value, str) and value in domain

    return Field(name, describe, check, lambda _v: math.log2(len(domain)))


def bool_field(name: str, describe: str) -> Field:
    """A single bit."""
    return Field(name, describe, lambda v: isinstance(v, bool), lambda _v: 1.0)


def bitmask_field(name: str, length: int, describe: str) -> Field:
    """One accept/reject bit per candidate. Costs exactly `length` bits."""

    def check(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) == length
            and all(isinstance(v, bool) for v in value)
        )

    return Field(name, describe, check, lambda v: float(len(v)))


def label_field(name: str, describe: str) -> Field:
    """A configuration identifier. Costs zero bits, and that is a claim.

    The slug a node answers with is the one the operator typed when they
    started the SuperNode (`--node-config 'user="alex"'`). It is not derived
    from the person's private profile, so answering it discloses nothing the
    operator did not already publish by naming the node. The shape check is
    what keeps it from becoming a free-text side channel: 24 lowercase
    characters with no spaces and no punctuation cannot carry a calendar entry.
    """

    def check(value: Any) -> bool:
        return isinstance(value, str) and bool(USER_SLUG.match(value))

    return Field(name, describe, check, lambda _v: 0.0)


# --- Phase schemas -------------------------------------------------------
# A phase is a question the leader may ask and the exact shape of the only
# answer a participant is permitted to give. Nodes never emit free text.


# There is deliberately no availability or budget schema.
#
# An earlier version of this protocol opened by asking every participant for
# their hour-slot availability and the highest price band they accept. Both are
# disclosures of exactly the kind this project exists to avoid:
#
#   * A price band IS the budget, coarsened. "I am a $ person" is the socially
#     costly fact, not the figure behind it. Nobody wants the group to learn
#     they are the reason it did the cheap thing.
#   * An availability subset IS the calendar, coarsened. Someone free in
#     exactly one slot has disclosed a busy week; someone free in all seven has
#     disclosed an empty one.
#
# Both are decidable by veto instead, so neither is asked. The principle that
# keeps activity-type preferences out of the opening round keeps these out too:
# if a yes/no answer to a concrete proposal can settle it, do not ask for the
# attribute. What remains is `veto_schema`, and the difference matters --
#
#   A disclosed attribute is an assertion. A veto is deniable.
#
# "I cannot do 20:00" could be a meeting, a commute, a babysitter or a
# preference, and the leader cannot tell which. "My availability is
# [19-21, 21-23]" is a statement about the shape of someone's week.


def identity_schema() -> dict[str, Field]:
    """Phase 0: who is on this node, so the leader can build a roster.

    This is what makes users spawnable. The leader hardcodes nobody; it asks
    whoever connected. Both fields are configuration, so the round is free.
    """
    return {
        f.name: f
        for f in (
            label_field("user", "The slug this SuperNode was started with."),
            enum_field("role", ROLES, "participant, or honouree for a surprise."),
        )
    }


def wishes_schema() -> dict[str, Field]:
    """Phase A: the guest of honour contributes taste, not a calendar.

    Only the honouree is asked this, and only because it is their event. Every
    other participant answers in vetoes alone.
    """
    return {
        f.name: f
        for f in (
            subset_field(
                "activity_prefs",
                ACTIVITY_TAGS,
                "The kinds of thing they would enjoy, as a subset of the tags.",
            ),
            enum_field("atmosphere", ATMOSPHERES, "Preferred atmosphere."),
            bool_field("prefers_new_place", "True if somewhere new is preferred."),
        )
    }


def veto_schema(num_candidates: int) -> dict[str, Field]:
    """The only channel a participant has. One bit per offer, no reasons.

    Each candidate is a fully specified offer -- activity, tags, price band,
    area, atmosphere and a time -- so a single bit answers every private
    constraint at once: the calendar, the budget ceiling, the allergy, the
    transport cut-off, the bad knee, the dislike of crowds. The leader learns
    which offers are live. It never learns which constraint killed the others.
    """
    return {
        "verdicts": bitmask_field(
            "verdicts", num_candidates, "One accept/reject bit per candidate, in order."
        )
    }


def plan_schema() -> dict[str, Field]:
    """Phase C: acknowledge the agreed plan. One bit."""
    return {"acknowledged": bool_field("acknowledged", "True once noted.")}


SCHEMAS: dict[str, Callable[..., dict[str, Field]]] = {
    "identity": identity_schema,
    "wishes": wishes_schema,
    "veto": veto_schema,
    "plan": plan_schema,
}


class PolicyViolation(Exception):
    """Raised when a proposed disclosure is not permitted by the schema."""


def validate(payload: str, schema: dict[str, Field]) -> tuple[dict[str, Any], float]:
    """Check one proposed outbound payload. Return the parsed value and its cost.

    Raises PolicyViolation with a message the model can act on. Every rejection
    path here is a disclosure that did not happen.
    """
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError) as err:
        raise PolicyViolation(
            "Reply must be a single JSON object and nothing else."
        ) from err

    if not isinstance(parsed, dict):
        raise PolicyViolation("Reply must be a JSON object, not a list or scalar.")

    extra = sorted(set(parsed) - set(schema))
    if extra:
        raise PolicyViolation(
            f"Fields {extra} are not disclosable. Allowed fields: {sorted(schema)}."
        )

    missing = sorted(set(schema) - set(parsed))
    if missing:
        raise PolicyViolation(f"Fields {missing} are required.")

    cost = 0.0
    for name, field in schema.items():
        value = parsed[name]
        if not field.check(value):
            raise PolicyViolation(
                f"Field '{name}' is malformed. Expected: {field.describe}"
            )
        cost += field.bits(value)

    return parsed, cost


# --- Defence in depth: raw-value scan ------------------------------------
# Schema validation already makes free text impossible, so this scan should
# never fire in a well-behaved run. It exists because "should never fire" is
# exactly the claim an adversarial prompt is trying to falsify, and because a
# blocked exfiltration attempt is the most legible thing a demo can show.

_WORD = re.compile(r"[a-z0-9]+")


def canaries(private: dict[str, Any], *, allow: set[str] | None = None) -> set[str]:
    """Derive a set of raw private tokens that must never appear in a payload."""
    out: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)
        elif isinstance(value, str):
            for word in _WORD.findall(value.lower()):
                # Short words collide with legitimate enum values; the schema
                # already covers those, so only track distinctive tokens.
                if len(word) >= 5:
                    out.add(word)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            out.add(str(value))

    walk(private)
    # Never treat a legal disclosure value as a secret. `allow` carries the
    # node's own slug, which is configuration rather than private data.
    allowed = {v.lower() for v in SLOTS + PRICE_BANDS + ATMOSPHERES + ACTIVITY_TAGS}
    allowed |= {v.lower() for v in ROLES} | {v.lower() for v in (allow or set())}
    return {c for c in out if c not in allowed}


def scan_for_raw(payload: str, secrets: set[str]) -> str | None:
    """Return the first raw private token found in `payload`, if any."""
    haystack = payload.lower()
    for secret in sorted(secrets, key=len, reverse=True):
        if secret in haystack:
            return secret
    return None
