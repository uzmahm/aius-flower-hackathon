"""Disclosure policy: what may leave a node, and what it costs in bits.

This module is the whole privacy argument of the project. Every value that
crosses a node boundary must be an instance of a declared field here, so the
set of things an agent *can* say is finite and enumerable before the model
runs. Because each field has a finite domain, the information released is not
just "small" in a hand-wavy sense -- it is measurable, and `bits()` measures it.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any, Callable

# One-hour slots are the coarsest unit that still lets us pick a dinner time.
# A subset of a 6-element set is exactly 6 bits, whoever answers.
SLOTS: tuple[str, ...] = (
    "17-18",
    "18-19",
    "19-20",
    "20-21",
    "21-22",
    "22-23",
)

PRICE_BANDS: tuple[str, ...] = ("$", "$$", "$$$", "$$$$")

ATMOSPHERES: tuple[str, ...] = ("cosy", "lively", "formal", "casual")

CUISINES: tuple[str, ...] = (
    "italian",
    "japanese",
    "korean",
    "thai",
    "mexican",
    "indian",
    "american",
)


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


# --- Phase schemas -------------------------------------------------------
# A phase is a question the planner may ask and the exact shape of the only
# answer a node is permitted to give. Nodes never emit free text.


# There is deliberately no availability or budget schema.
#
# An earlier version of this protocol opened by asking every guest for their
# hour-slot availability and the highest price band they accept. Both are
# disclosures of exactly the kind this project exists to avoid:
#
#   * A price band IS the budget, coarsened. "I am a $ person" is the socially
#     costly fact, not the figure behind it. Nobody wants their friends to
#     learn they are the reason the group ate cheaply.
#   * An availability subset IS the calendar, coarsened. A guest free in
#     exactly one slot has disclosed a busy week; one free in all six has
#     disclosed an empty one.
#
# Both are decidable by veto instead, so neither is asked. The principle that
# removed cuisine preferences from the opening round removes these too: if a
# yes/no answer to a concrete proposal can settle it, do not ask for the
# attribute. What remains is `veto_schema`, and the difference matters --
#
#   A disclosed attribute is an assertion. A veto is deniable.
#
# "I cannot do 20:00" could be a meeting, a commute, a babysitter or a
# preference, and the planner cannot tell which. "My availability is
# [19-20, 20-21]" is a statement about the shape of someone's week.


def wishes_schema() -> dict[str, Field]:
    """Phase A': the guest of honour contributes taste, not a calendar."""
    return {
        f.name: f
        for f in (
            enum_field("atmosphere", ATMOSPHERES, "Preferred atmosphere."),
            enum_field("cuisine_pref", CUISINES, "Preferred cuisine."),
            bool_field("prefers_new_place", "True if somewhere new is preferred."),
        )
    }


def veto_schema(num_candidates: int) -> dict[str, Field]:
    """The only channel a guest has. One bit per concrete offer, no reasons.

    Each candidate is a fully specified offer -- venue, cuisine, price band,
    area, atmosphere and a time -- so a single bit answers every private
    constraint at once: the calendar, the budget ceiling, the allergy, the
    transport cut-off, the dislike of loud rooms. The planner learns which
    offers are live. It never learns which constraint killed the others.
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


def canaries(private: dict[str, Any]) -> set[str]:
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
    # Never treat a legal disclosure value as a secret.
    allowed = {v.lower() for v in SLOTS + PRICE_BANDS + ATMOSPHERES + CUISINES}
    return {c for c in out if c not in allowed}


def scan_for_raw(payload: str, secrets: set[str]) -> str | None:
    """Return the first raw private token found in `payload`, if any."""
    haystack = payload.lower()
    for secret in sorted(secrets, key=len, reverse=True):
        if secret in haystack:
            return secret
    return None
