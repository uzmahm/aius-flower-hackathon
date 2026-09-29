"""A participant's private decisions, made by plain rules instead of a model.

Used by the offline rehearsal (simulate.py) and by a real participant whose
model is unavailable or did not produce a usable answer. Everything here runs
on the participant's own node against their own profile; only the bools and
the activity-type wishes it returns ever leave, and those still go through
guard.PolicyGrid.
"""

from __future__ import annotations

import re
from typing import Any

from event_planner import activities, policy, profiles

_TIME_RANGE = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


def busy_slots(calendar: list[str]) -> set[str]:
    """Slots a calendar entry overlaps. Computed on the node, never sent.

    The real participant agent reads the same free-text calendar with a model;
    here a regex stands in for it.
    """
    busy: set[str] = set()
    for entry in calendar:
        match = _TIME_RANGE.match(entry.strip())
        if not match:
            continue
        start = int(match.group(1)) + int(match.group(2)) / 60
        end = int(match.group(3)) + int(match.group(4)) / 60
        for slot in policy.SLOTS:
            slot_start, slot_end = (int(p) for p in slot.split("-"))
            if start < slot_end and end > slot_start:
                busy.add(slot)
    return busy


def why_rejected(user: str, offer: dict[str, Any]) -> str | None:
    """Why this participant says no, or None if they say yes.

    This string is the thing the whole design exists to keep off the wire.
    It never leaves the node: `accepts` returns only the bool, and the reason
    is available here purely so the narrator views -- the console's private
    panels and the report -- can show what the leader did not learn.
    """
    private = profiles.load_private(user)
    _, end = (int(part) for part in offer["slot"].split("-"))

    if offer["slot"] in busy_slots(private.get("calendar", [])):
        return "a calendar clash"
    if end > private.get("curfew_hour", 24):
        return f"no way home after {private['curfew_hour']}:00"
    budget = private.get("budget_usd")
    if budget is not None and activities.BAND_SPEND[offer["price_band"]] > budget:
        return f"over their ${budget} ceiling"
    required = set(private.get("needs", []))
    if not offer["serves_food"]:
        # A dietary requirement does not bind on something you do not eat at.
        required -= activities.DIETARY_NEEDS
    unmet = sorted(required - set(offer["needs"]))
    if unmet:
        return f"it cannot offer {', '.join(t.replace('_', ' ') for t in unmet)}"
    clash = sorted(set(private.get("avoid_tags", [])) & set(offer["tags"]))
    if clash:
        return f"they do not do {', '.join(clash)}"
    if offer["area"] in private.get("avoid_areas", []):
        return f"they cannot get to {offer['area'].replace('_', ' ')}"
    if offer["atmosphere"] in private.get("avoid_atmospheres", []):
        return f"they dislike {offer['atmosphere']} rooms"
    return None


def accepts(user: str, offer: dict[str, Any]) -> bool:
    """One participant's private decision about one offer.

    The reason stays inside `why_rejected`, which is the point: the only
    thing that leaves this machine is the bool returned here.
    """
    return why_rejected(user, offer) is None


def wishes_of(user: str) -> dict[str, Any]:
    """The honouree's wishes round, answered from their own profile."""
    private = profiles.load_private(user)
    liked = [t for t in policy.ACTIVITY_TAGS if t in private.get("like_tags", [])]
    avoid = set(private.get("avoid_atmospheres", []))
    atmosphere = next((a for a in policy.ATMOSPHERES if a not in avoid), "casual")
    return {
        "activity_prefs": liked,
        "atmosphere": atmosphere,
        "prefers_new_place": True,
    }


def answer(user: str, request: dict[str, Any]) -> dict[str, Any]:
    """This participant's full reply to one leader request."""
    phase = request["phase"]
    if phase == "identity":
        return {"user": user, "role": profiles.role_of(user)}
    if phase == "wishes":
        return wishes_of(user)
    if phase == "veto":
        return {"verdicts": [accepts(user, o) for o in request["candidates"]]}
    return {"acknowledged": True}
