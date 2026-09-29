"""The organiser's brief: what kind of event, and for whom.

The leader is a person typing into `flwr chat`. Everything they say is public
by construction -- they are the one organising -- so parsing it costs nobody
any privacy, and it is done deterministically rather than by a model. A demo
that has to work at 17:30 should not depend on a model to notice the word
"morning".

    "Plan a relaxing morning in nature for Sofia, and keep it a surprise."
      -> tags {nature, morning, relaxing}, honouree sofia, surprise True
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from event_planner import policy

# Words the organiser is likely to type, mapped onto the tag vocabulary. The
# tag's own name always counts; these are the synonyms worth catching.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "nature": ("outdoors", "outdoor", "hike", "hiking", "park", "trail", "green"),
    "city": ("downtown", "urban", "in town"),
    "morning": ("breakfast", "brunch", "sunrise", "early"),
    "evening": ("dinner", "night", "sunset", "late", "after work", "supper"),
    "active": ("sporty", "exercise", "workout", "energetic", "adventurous"),
    "relaxing": ("chill", "relaxed", "low key", "low-key", "calm", "mellow"),
    "foodie": ("food", "eat", "eating", "restaurant", "tasting", "culinary"),
    "shopping": ("shops", "market", "browse", "boutique", "vintage"),
}

SURPRISE_WORDS = ("surprise", "secret", "don't tell", "do not tell", "keep it from")
# Checked first, so an organiser can always overrule the node's own config.
NO_SURPRISE_WORDS = (
    "no surprise",
    "not a surprise",
    "no secret",
    "not secret",
    "everyone votes",
    "everyone decides",
    "include everyone",
)


@dataclass
class EventBrief:
    """What the organiser asked for, in the planner's own vocabulary."""

    prompt: str
    tags: list[str] = field(default_factory=list)
    honouree: str | None = None
    surprise: bool = False

    def summary(self) -> str:
        """One line for the report header."""
        parts = [", ".join(self.tags) if self.tags else "no stated preference"]
        if self.honouree:
            parts.append(f"for {self.honouree}" + (" (surprise)" if self.surprise else ""))
        return " · ".join(parts)


def tags_in(text: str) -> list[str]:
    """Every activity tag the text asks for, in catalogue order."""
    lowered = text.lower()
    found = []
    for tag in policy.ACTIVITY_TAGS:
        needles = (tag, *SYNONYMS.get(tag, ()))
        if any(re.search(rf"\b{re.escape(n)}\b", lowered) for n in needles):
            found.append(tag)
    return found


def parse(prompt: str, roster: dict[str, dict[str, Any]]) -> EventBrief:
    """Read the organiser's request against the roster of connected users.

    `roster` maps node id -> {"user": slug, "role": role}, as returned by the
    identity phase. The honouree is whoever the organiser named, falling back
    to whichever node declared the honouree role in its own config.
    """
    lowered = prompt.lower()
    named = None
    for entry in roster.values():
        slug = entry["user"]
        if re.search(rf"\b{re.escape(slug)}\b", lowered):
            named = slug
            break

    declared = next(
        (e["user"] for e in roster.values() if e["role"] == policy.ROLES[1]), None
    )
    honouree = named or declared

    # A node started with `role: honouree` is being surprised -- that is why
    # the operator configured it that way -- but the organiser always has the
    # last word, so an explicit "no surprise" wins.
    if any(word in lowered for word in NO_SURPRISE_WORDS):
        surprise = False
    else:
        surprise = honouree is not None and (
            honouree == declared or any(w in lowered for w in SURPRISE_WORDS)
        )

    return EventBrief(
        prompt=prompt, tags=tags_in(prompt), honouree=honouree, surprise=surprise
    )
