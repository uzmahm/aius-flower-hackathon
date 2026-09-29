"""The public catalogue the leader draws offers from.

Nothing here is private. Prices, areas, atmospheres, opening hours and
accessibility notes are each venue's own published facts, which is what makes
them safe to put in a proposal. An *offer* is one activity crossed with one
time slot -- fully specified, so a participant can answer it with a single bit.

Every activity carries a subset of `policy.ACTIVITY_TAGS`. Those tags are the
only vocabulary the organiser's brief and the guest of honour's wishes use, so
"a relaxing morning in nature" and "an evening foodie thing in the city" are
both expressible without anyone naming a place.
"""

from __future__ import annotations

from typing import Any

from event_planner import policy

# Approximate per-head spend for each band, used only by the simulated
# participants in simulate.py to decide locally whether they can afford an
# offer. The leader never sees these and never learns anyone's ceiling.
BAND_SPEND = {"$": 20, "$$": 45, "$$$": 80, "$$$$": 140}

# `needs` lists the accommodations an activity can actually provide, and
# `serves_food` says whether food is part of it at all -- a dietary
# requirement only binds on something you eat at, an access requirement binds
# everywhere. A participant checks their own requirements against these
# locally; the requirement itself never travels.
DIETARY_NEEDS = frozenset({"gluten_free", "no_shellfish_option", "vegan_option"})

CATALOGUE: list[dict[str, Any]] = [
    {
        "name": "Windy Hill Ridge Walk",
        "kind": "hike",
        "tags": ["nature", "active", "morning"],
        "price_band": "$",
        "area": "skyline",
        "atmosphere": "casual",
        "needs": [],
        "serves_food": False,
        "outdoor": True,
        "new_opening": False,
    },
    {
        "name": "Baylands Sunrise Loop",
        "kind": "walk",
        "tags": ["nature", "relaxing", "morning"],
        "price_band": "$",
        "area": "baylands",
        "atmosphere": "casual",
        "needs": ["step_free"],
        "serves_food": False,
        "outdoor": True,
        "new_opening": False,
    },
    {
        "name": "California Ave Farmers Market",
        "kind": "market",
        "tags": ["foodie", "shopping", "morning", "city"],
        "price_band": "$",
        "area": "california_ave",
        "atmosphere": "lively",
        "needs": ["step_free", "gluten_free", "no_shellfish_option"],
        "serves_food": True,
        "outdoor": True,
        "new_opening": False,
    },
    {
        "name": "Cantor Arts Museum",
        "kind": "museum",
        "tags": ["city", "relaxing"],
        "price_band": "$",
        "area": "stanford",
        "atmosphere": "formal",
        "needs": ["step_free"],
        "serves_food": False,
        "outdoor": False,
        "new_opening": False,
    },
    {
        "name": "Clay & Kiln Ceramics Studio",
        "kind": "class",
        "tags": ["relaxing", "city"],
        "price_band": "$$",
        "area": "midtown",
        "atmosphere": "cosy",
        "needs": ["step_free"],
        "serves_food": False,
        "outdoor": False,
        "new_opening": True,
    },
    {
        "name": "University Ave Vintage Crawl",
        "kind": "shopping",
        "tags": ["shopping", "city", "relaxing"],
        "price_band": "$$",
        "area": "downtown_palo_alto",
        "atmosphere": "casual",
        "needs": ["step_free"],
        "serves_food": False,
        "outdoor": False,
        "new_opening": False,
    },
    {
        "name": "Stevens Creek Kayak Hour",
        "kind": "sport",
        "tags": ["nature", "active"],
        "price_band": "$$",
        "area": "baylands",
        "atmosphere": "lively",
        "needs": [],
        "serves_food": False,
        "outdoor": True,
        "new_opening": True,
    },
    {
        "name": "Ozora Handroll Bar",
        "kind": "dinner",
        "tags": ["foodie", "evening", "city"],
        "price_band": "$$",
        "area": "downtown_palo_alto",
        "atmosphere": "cosy",
        "needs": ["step_free", "gluten_free", "no_shellfish_option"],
        "serves_food": True,
        "outdoor": False,
        "new_opening": True,
    },
    {
        "name": "Trattoria Bruna",
        "kind": "dinner",
        "tags": ["foodie", "evening"],
        "price_band": "$$",
        "area": "downtown_palo_alto",
        "atmosphere": "cosy",
        "needs": ["step_free"],
        "serves_food": True,
        "outdoor": False,
        "new_opening": False,
    },
    {
        "name": "Banchan House",
        "kind": "dinner",
        "tags": ["foodie", "evening", "city"],
        "price_band": "$$",
        "area": "california_ave",
        "atmosphere": "lively",
        "needs": ["gluten_free"],
        "serves_food": True,
        "outdoor": False,
        "new_opening": True,
    },
    {
        "name": "Ferro & Sale",
        "kind": "dinner",
        "tags": ["foodie", "evening", "relaxing"],
        "price_band": "$$",
        "area": "midtown",
        "atmosphere": "casual",
        "needs": ["step_free", "gluten_free"],
        "serves_food": True,
        "outdoor": False,
        "new_opening": True,
    },
    {
        "name": "Rooftop Jazz at The Epiphany",
        "kind": "music",
        "tags": ["evening", "city", "relaxing"],
        "price_band": "$$$",
        "area": "downtown_palo_alto",
        "atmosphere": "formal",
        "needs": ["step_free", "no_shellfish_option"],
        "serves_food": True,
        "outdoor": True,
        "new_opening": False,
    },
    {
        "name": "Midnight Night Market",
        "kind": "market",
        "tags": ["foodie", "shopping", "evening", "city"],
        "price_band": "$",
        "area": "el_camino",
        "atmosphere": "lively",
        "needs": ["no_shellfish_option"],
        "serves_food": True,
        "outdoor": True,
        "new_opening": True,
    },
    {
        "name": "Sunset Bouldering Gym",
        "kind": "sport",
        "tags": ["active", "evening", "city"],
        "price_band": "$$",
        "area": "el_camino",
        "atmosphere": "lively",
        "needs": [],
        "serves_food": False,
        "outdoor": False,
        "new_opening": False,
    },
]


def slots_for(activity: dict[str, Any]) -> tuple[str, ...]:
    """The slots this activity can actually happen in.

    `morning` and `evening` are activity tags the organiser can ask for, so
    they have to mean something: a sunrise loop is not offered at 21:00 and a
    night market is not offered at 09:00. Everything untagged for time of day
    is offered in every slot.
    """
    wanted = {tag for tag in activity["tags"] if tag in ("morning", "evening")}
    if not wanted:
        return policy.SLOTS
    return tuple(slot for slot in policy.SLOTS if policy.DAYPARTS[slot] in wanted)


def offers() -> list[dict[str, Any]]:
    """Every activity crossed with its plausible slots: the whole search space."""
    return [
        {**activity, "slot": slot}
        for slot in policy.SLOTS
        for activity in CATALOGUE
        if slot in slots_for(activity)
    ]


def key(offer: dict[str, Any]) -> tuple[str, str]:
    """Identity of one offer."""
    return offer["name"], offer["slot"]


def tag_score(activity: dict[str, Any], wanted: list[str] | set[str]) -> int:
    """How many of the wanted activity tags this activity satisfies."""
    return len(set(activity["tags"]) & set(wanted))


def describe(offer: dict[str, Any]) -> str:
    """One human-readable line for an offer, for reports and logs."""
    start, end = offer["slot"].split("-")
    return (
        f"{offer['name']} ({offer['kind']}) {start}:00-{end}:00 "
        f"· {offer['price_band']} · {offer['area']} · {'/'.join(offer['tags'])}"
    )
