#!/usr/bin/env python3
"""Create a new user profile, so you can spawn another participant.

    scripts/new_user.py alex --name Alex --likes foodie,city --avoid active \
        --budget 60 --curfew 22 --needs step_free --busy 13:00-14:00

Writes backend/event_planner/users/<slug>.json. Everything under "private"
stays on that user's machine; the planner only ever sees yes/no answers.
Run with no flags for an interactive prompt.

Once the file exists:

    scripts/join.sh alex        # against a running federation
    scripts/run_local.sh        # or restart, and everyone joins

Nothing else needs changing. The leader discovers the roster at runtime.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USERS = ROOT / "backend" / "event_planner" / "users"
sys.path.insert(0, str(ROOT / "backend"))

TAGS = (
    "nature", "city", "morning", "evening",
    "active", "relaxing", "foodie", "shopping",
)
NEEDS = ("step_free", "gluten_free", "no_shellfish_option", "vegan_option")
AREAS = (
    "downtown_palo_alto", "california_ave", "midtown",
    "el_camino", "stanford", "baylands", "skyline",
)
ATMOSPHERES = ("cosy", "lively", "formal", "casual")
SLUG = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")


def csv(value: str | None) -> list[str]:
    """Split a comma-separated flag into a clean list."""
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def check(name: str, values: list[str], allowed: tuple[str, ...]) -> list[str]:
    """Reject anything outside the vocabulary, with a useful message."""
    bad = [v for v in values if v not in allowed]
    if bad:
        raise SystemExit(f"Unknown {name}: {bad}. Choose from: {', '.join(allowed)}")
    return values


def ask(question: str, default: str = "") -> str:
    """One interactive prompt with a default."""
    suffix = f" [{default}]" if default else ""
    return input(f"{question}{suffix}: ").strip() or default


def interactive(slug: str | None) -> argparse.Namespace:
    """Fill the same fields the flags do, by asking."""
    print("Creating a participant. Press enter to accept a default.\n")
    slug = slug or ask("slug (lowercase, no spaces)", "alex")
    return argparse.Namespace(
        slug=slug,
        name=ask("display name", slug.title()),
        emoji=ask("emoji", "🙂"),
        honouree=ask(f"is this the guest of honour? (y/N)", "n").lower().startswith("y"),
        likes=ask(f"activity types they like ({', '.join(TAGS)})", "foodie,city"),
        avoid=ask("activity types they will not do", ""),
        budget=int(ask("budget per head in USD", "60")),
        curfew=int(ask("latest hour they must be home by (24h)", "23")),
        needs=ask(f"access or dietary needs ({', '.join(NEEDS)})", ""),
        busy=ask("busy times, e.g. 09:00-10:30 standup", ""),
        home=ask(f"home area ({', '.join(AREAS)})", "downtown_palo_alto"),
        avoid_areas=ask("areas they cannot get to", ""),
        avoid_atmospheres=ask(f"atmospheres they dislike ({', '.join(ATMOSPHERES)})", ""),
        notes=ask("private note (never leaves their machine)", ""),
        force=False,
    )


def build(args: argparse.Namespace) -> dict:
    """Turn the answers into a profile document."""
    return {
        "display_name": args.name or args.slug.title(),
        "emoji": args.emoji,
        "role": "honouree" if args.honouree else "participant",
        "private": {
            "calendar": [b.strip() for b in args.busy.split(";") if b.strip()],
            "budget_usd": args.budget,
            "home_area": args.home,
            "curfew_hour": args.curfew,
            "needs": check("need", csv(args.needs), NEEDS),
            "like_tags": check("tag", csv(args.likes), TAGS),
            "avoid_tags": check("tag", csv(args.avoid), TAGS),
            "avoid_areas": check("area", csv(args.avoid_areas), AREAS),
            "avoid_atmospheres": check(
                "atmosphere", csv(args.avoid_atmospheres), ATMOSPHERES
            ),
            "dislikes": [],
            "notes": args.notes,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.splitlines()[1:]),
    )
    parser.add_argument("slug", nargs="?", help="lowercase id, e.g. alex")
    parser.add_argument("--name", default="", help="display name")
    parser.add_argument("--emoji", default="🙂")
    parser.add_argument("--honouree", action="store_true",
                        help="this user is the one being surprised")
    parser.add_argument("--likes", default="", help=f"comma-separated: {','.join(TAGS)}")
    parser.add_argument("--avoid", default="", help="activity types they will not do")
    parser.add_argument("--budget", type=int, default=60, help="USD per head")
    parser.add_argument("--curfew", type=int, default=23, help="latest hour, 24h")
    parser.add_argument("--needs", default="", help=f"comma-separated: {','.join(NEEDS)}")
    parser.add_argument("--busy", default="",
                        help="semicolon-separated, e.g. '09:00-10:30 standup;13:00-14:00 dentist'")
    parser.add_argument("--home", default="downtown_palo_alto", help=f"one of: {','.join(AREAS)}")
    parser.add_argument("--avoid-areas", dest="avoid_areas", default="")
    parser.add_argument("--avoid-atmospheres", dest="avoid_atmospheres", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--force", action="store_true", help="overwrite an existing profile")
    args = parser.parse_args()

    if len(sys.argv) == 1 or (args.slug and len(sys.argv) == 2):
        args = interactive(args.slug)

    if not SLUG.match(args.slug or ""):
        raise SystemExit(
            f"'{args.slug}' is not a valid slug: lowercase letters, digits, - and _, "
            "starting with a letter, up to 24 characters."
        )
    check("area", [args.home], AREAS)

    path = USERS / f"{args.slug}.json"
    if path.exists() and not args.force:
        raise SystemExit(f"{path} already exists. Pass --force to overwrite.")

    path.write_text(json.dumps(build(args), indent=2, ensure_ascii=False) + "\n")
    print(f"\nWrote {path.relative_to(ROOT)}")
    print(f"Join a running federation with:  scripts/join.sh {args.slug}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
