"""The public venue pool the planner draws offers from.

Nothing here is private. Prices, cuisines, areas, atmospheres and dietary
accommodations are the restaurant's own published facts, which is what makes
them safe to put in a proposal. An *offer* is one of these crossed with one
hour slot -- fully specified, so a guest can answer it with a single bit.
"""

from __future__ import annotations

from typing import Any

# Approximate per-head spend for each band, used only by the demo's simulated
# guests to decide locally whether they can afford an offer. The planner never
# sees these and never learns anyone's ceiling.
BAND_SPEND = {"$": 20, "$$": 45, "$$$": 80, "$$$$": 140}

VENUES: list[dict[str, Any]] = [
    {
        "name": "Ozora Handroll Bar",
        "cuisine": "japanese",
        "price_band": "$$",
        "area": "downtown_palo_alto",
        "atmosphere": "cosy",
        "dietary": ["gluten_free", "no_shellfish_option"],
        "new_opening": True,
    },
    {
        "name": "Trattoria Bruna",
        "cuisine": "italian",
        "price_band": "$$",
        "area": "downtown_palo_alto",
        "atmosphere": "cosy",
        "dietary": [],
        "new_opening": False,
    },
    {
        "name": "Banchan House",
        "cuisine": "korean",
        "price_band": "$$",
        "area": "california_ave",
        "atmosphere": "lively",
        "dietary": ["gluten_free"],
        "new_opening": True,
    },
    {
        "name": "Kiyoshi on University",
        "cuisine": "japanese",
        "price_band": "$$$",
        "area": "downtown_palo_alto",
        "atmosphere": "formal",
        "dietary": ["gluten_free"],
        "new_opening": False,
    },
    {
        "name": "Sawatdee Express",
        "cuisine": "thai",
        "price_band": "$",
        "area": "el_camino",
        "atmosphere": "casual",
        "dietary": ["no_shellfish_option"],
        "new_opening": True,
    },
    {
        "name": "Ferro & Sale",
        "cuisine": "italian",
        "price_band": "$$",
        "area": "midtown",
        "atmosphere": "casual",
        "dietary": ["gluten_free"],
        "new_opening": True,
    },
]


def offers(slots: tuple[str, ...]) -> list[dict[str, Any]]:
    """Every venue crossed with every slot: the planner's whole search space."""
    return [{**venue, "slot": slot} for slot in slots for venue in VENUES]


def key(offer: dict[str, Any]) -> tuple[str, str]:
    """Identity of one offer."""
    return offer["name"], offer["slot"]
