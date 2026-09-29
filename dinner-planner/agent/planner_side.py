"""Planner: blind search over concrete offers, using only yes/no answers.

The planner never asks anyone when they are free or what they can spend. It
proposes fully specified offers -- this venue, at this hour, at this price --
and collects one bit per offer per guest. Feasibility is discovered from those
bits alone, the way twenty questions discovers a word.

What this costs: the planner is searching blind, so it may need more than one
round. What it buys: no guest ever asserts an attribute. A rejected offer is
deniable -- a meeting, a commute, a budget, an allergy, a dislike of loud
rooms, all look identical from here.

The framework puts the planner at the SuperLink, where the runtime grants
get_nodes / push_messages / pull_messages and nothing else. Guests cannot talk
to each other, so every bit passes through this process. That makes this the
place to validate inbound payloads and to account for the total released.

The protocol is plain Python rather than model-driven. A demo that has to work
at 17:30 should not depend on a model choosing the right tool six times in a
row; the model is called once, for the one step that needs world knowledge.
"""

from __future__ import annotations

import json
from typing import Any

from flwr.agentapp import AgentSession
from flwr.app import Context

from agent import llm, policy, ui_events, venues

PULL_TIMEOUT = 240.0
OFFERS_PER_ROUND = 5
MAX_ROUNDS = 3

PROPOSE_INSTRUCTIONS = (
    "You rank restaurant offers for a group whose constraints you do not know "
    "and must not ask for. You are given the guest of honour's stated taste "
    "and a pool of real venues. Return JSON only: "
    '{"order":[venue names, best first]}. '
    "Favour her stated cuisine and atmosphere, and somewhere new if she "
    "prefers that. Include a spread of price bands rather than only the "
    "cheapest or only the priciest -- some guests may be constrained in ways "
    "you cannot see."
)


def _grid(agent: AgentSession, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call one Grid tool programmatically and return its parsed output."""
    output = agent.grid.call(
        {
            "type": "function_call",
            "call_id": llm.call_id(),
            "name": name,
            "arguments": json.dumps(arguments),
        }
    )
    return json.loads(output["output"])


def _ledger(
    agent: AgentSession, node_id: str, phase: str, verdict: str, **extra: Any
) -> None:
    agent.events.emit(
        {
            "type": "disclosure.ledger",
            "side": "planner",
            "node": node_id,
            "phase": phase,
            "verdict": verdict,
            **extra,
        }
    )


def _exchange(
    agent: AgentSession,
    node_ids: list[str],
    request: dict[str, Any],
    schema: dict[str, policy.Field],
) -> dict[str, tuple[dict[str, Any], float]]:
    """One protocol round: ask every node, then validate what comes back."""
    payload = json.dumps(request)
    ui_events.emit(
        "ask", phase=request["phase"], round=request.get("round"), nodes=node_ids
    )
    pushed = _grid(
        agent,
        "push_messages",
        {
            "messages": [
                {
                    "dst_node_id": node_id,
                    "payload": payload,
                    "reply_to_message_id": None,
                }
                for node_id in node_ids
            ]
        },
    )

    awaiting: dict[str, str] = {}
    for node_id, result in zip(node_ids, pushed["results"]):
        message_id = result.get("message_id")
        if message_id:
            awaiting[message_id] = node_id
    if not awaiting:
        raise RuntimeError(f"No node accepted the '{request['phase']}' request.")

    pulled = _grid(
        agent,
        "pull_messages",
        {"message_ids": list(awaiting), "timeout": PULL_TIMEOUT},
    )

    accepted: dict[str, tuple[dict[str, Any], float]] = {}
    phase = request["phase"]
    for message in pulled["messages"]:
        node_id = awaiting.get(message["reply_to_message_id"], message["src_node_id"])
        if message["error"] or not message["payload"]:
            _ledger(agent, node_id, phase, "error", reason=message["error"])
            ui_events.emit("reply", node=node_id, phase=phase, status="error")
            continue
        try:
            parsed, bits = policy.validate(message["payload"], schema)
        except policy.PolicyViolation as err:
            # Inbound enforcement: refuse to ingest an out-of-schema payload
            # rather than letting it into the planner's context.
            _ledger(agent, node_id, phase, "dropped", reason=str(err))
            ui_events.emit("reply", node=node_id, phase=phase, status="dropped")
            continue
        accepted[node_id] = (parsed, bits)
        ui_events.emit(
            "reply",
            node=node_id,
            phase=phase,
            status="ok",
            round=request.get("round"),
            fields=parsed,
            bits=bits,
        )
        _ledger(
            agent,
            node_id,
            phase,
            "received",
            fields=parsed,
            bits=bits,
            round=request.get("round"),
        )

    for pending in pulled["pending_message_ids"]:
        _ledger(agent, awaiting[pending], phase, "timeout")
        ui_events.emit("reply", node=awaiting[pending], phase=phase, status="timeout")
    return accepted


def _honoree(nodes: list[dict[str, Any]], prompt: str) -> str | None:
    """Identify the guest of honour without asking any agent to disclose it.

    SuperNode names are infrastructure metadata configured when the federation
    is started -- they are not a disclosure by the agent -- and the organiser
    names the birthday person in the prompt. So the role costs zero bits.
    """
    lowered = prompt.lower()
    for node in nodes:
        name = (node.get("name") or "").lower()
        if name and name in lowered:
            return node["id"]
    for node in nodes:
        if (node.get("name") or "").lower() == "birthday":
            return node["id"]
    return None


def _rank_venues(agent: AgentSession, wishes: dict[str, Any]) -> list[str]:
    """Ask the model to rank the public venue pool against her stated taste."""
    pool = [
        {k: v for k, v in venue.items() if k != "dietary"} for venue in venues.VENUES
    ]
    answer = llm.ask_json(
        agent,
        PROPOSE_INSTRUCTIONS,
        json.dumps({"her_taste": wishes, "venues": pool}, indent=2),
        {"order": [venue["name"] for venue in venues.VENUES]},
    )
    order = answer.get("order") if isinstance(answer, dict) else None
    known = {venue["name"] for venue in venues.VENUES}
    ranked = [name for name in (order or []) if name in known]
    # Anything the model dropped keeps its pool position at the back.
    return ranked + [name for name in known if name not in ranked]


def _spread(
    pool: list[dict[str, Any]], rank: dict[str, int], taken: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Opening round: one offer per hour slot, best-ranked venue each time.

    A spread rather than the top five, because five variations of one venue
    would waste a round if that venue is the problem.
    """
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for slot in policy.SLOTS:
        options = [
            offer
            for offer in pool
            if offer["slot"] == slot
            and venues.key(offer) not in taken
            and offer["name"] not in used
        ]
        if not options:
            continue
        best = min(options, key=lambda o: rank[o["name"]])
        chosen.append(best)
        used.add(best["name"])
        if len(chosen) == OFFERS_PER_ROUND:
            break
    return chosen


def _score(offer: dict[str, Any], history: list[dict[str, Any]]) -> float:
    """Score an unproposed offer from accept rates on what looked like it.

    The only inputs are bits. The planner is inferring which hours, prices and
    venues the group can live with -- never why, and never which guest.
    """
    score = 0.0
    for past in history:
        rate = past["rate"] - 0.5
        if past["offer"]["name"] == offer["name"]:
            score += 2.0 * rate
        if past["offer"]["slot"] == offer["slot"]:
            score += 1.5 * rate
        if past["offer"]["price_band"] == offer["price_band"]:
            score += 1.0 * rate
        if past["offer"]["atmosphere"] == offer["atmosphere"]:
            score += 0.5 * rate
        if past["offer"]["area"] == offer["area"]:
            score += 0.5 * rate
    return score


def _next_round(
    pool: list[dict[str, Any]],
    rank: dict[str, int],
    taken: set[tuple[str, str]],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Later rounds: the most promising unproposed offers, still spread a bit."""
    remaining = [offer for offer in pool if venues.key(offer) not in taken]
    remaining.sort(key=lambda o: (-_score(o, history), rank[o["name"]], o["slot"]))
    chosen: list[dict[str, Any]] = []
    slots_used: dict[str, int] = {}
    venues_used: dict[str, int] = {}
    for offer in remaining:
        # At most two offers per hour and two per venue, so one promising guess
        # cannot eat a whole round. A round is five bits from every guest; it
        # should buy five genuinely different questions.
        if slots_used.get(offer["slot"], 0) >= 2:
            continue
        if venues_used.get(offer["name"], 0) >= 2:
            continue
        chosen.append(offer)
        slots_used[offer["slot"]] = slots_used.get(offer["slot"], 0) + 1
        venues_used[offer["name"]] = venues_used.get(offer["name"], 0) + 1
        if len(chosen) == OFFERS_PER_ROUND:
            break
    return chosen


def plan(agent: AgentSession) -> dict[str, Any]:
    """Run the protocol. Returns the plan and everything it cost."""
    nodes = _grid(agent, "get_nodes", {"sample_size": None})["nodes"]
    node_ids = [node["id"] for node in nodes]
    if not node_ids:
        raise RuntimeError("No SuperNodes available; start the federation first.")

    spend: dict[str, float] = {node_id: 0.0 for node_id in node_ids}
    honoree = _honoree(nodes, agent.prompt)
    guests = [node_id for node_id in node_ids if node_id != honoree]
    if not guests:
        raise RuntimeError("No guests in the federation; nothing to plan.")
    ui_events.emit(
        "start", prompt=agent.prompt, nodes=nodes, honoree=honoree, guests=guests
    )

    # The only attribute anyone states, and it is her party. Her calendar and
    # budget are not asked for either.
    wishes: dict[str, Any] = {}
    if honoree:
        replies = _exchange(
            agent, [honoree], {"phase": "wishes"}, policy.wishes_schema()
        )
        for node_id, (reply, bits) in replies.items():
            spend[node_id] += bits
            wishes = reply

    rank = {name: i for i, name in enumerate(_rank_venues(agent, wishes))}
    pool = venues.offers(policy.SLOTS)

    taken: set[tuple[str, str]] = set()
    history: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    venue: dict[str, Any] | None = None

    for round_no in range(1, MAX_ROUNDS + 1):
        offers = (
            _spread(pool, rank, taken)
            if round_no == 1
            else _next_round(pool, rank, taken, history)
        )
        if not offers:
            break
        taken.update(venues.key(offer) for offer in offers)
        ui_events.emit("round", round=round_no, offers=offers)

        replies = _exchange(
            agent,
            guests,
            {"phase": "veto", "round": round_no, "candidates": offers},
            policy.veto_schema(len(offers)),
        )
        for node_id, (_, bits) in replies.items():
            spend[node_id] += bits

        tallies = [
            sum(1 for reply, _ in replies.values() if reply["verdicts"][i])
            for i in range(len(offers))
        ]
        for offer, tally in zip(offers, tallies):
            history.append(
                {"offer": offer, "rate": tally / max(len(replies), 1), "tally": tally}
            )
        rounds.append(
            {
                "round": round_no,
                "offers": offers,
                "tallies": tallies,
                "verdicts": {n: r[0]["verdicts"] for n, r in replies.items()},
                "bits": sum(bits for _, bits in replies.values()),
            }
        )

        ui_events.emit(
            "tally", round=round_no, tallies=tallies, voters=len(replies)
        )

        unanimous = [i for i, t in enumerate(tallies) if t == len(replies)]
        if unanimous:
            venue = offers[unanimous[0]]
            break

    # Tell the guests, and only the guests.
    if venue:
        ui_events.emit(
            "consensus",
            venue=venue,
            round=len(rounds),
            offers_tried=len(taken),
            search_space=len(pool),
        )
        _exchange(
            agent,
            guests,
            {"phase": "plan", "venue": venue},
            policy.plan_schema(),
        )
        for node_id in guests:
            spend[node_id] += 1.0

    ui_events.emit(
        "done",
        venue=venue,
        spend=spend,
        guests=guests,
        excluded=[honoree] if honoree else [],
    )
    return {
        "venue": venue,
        "wishes": wishes,
        "rounds": rounds,
        "spend": spend,
        "guests": guests,
        "excluded": [honoree] if honoree else [],
        "search_space": len(pool),
        "offers_tried": len(taken),
    }


def _report(result: dict[str, Any]) -> str:
    """A demo-legible summary: the plan, and exactly what it cost in privacy."""
    venue = result["venue"]
    guests = result["guests"]
    lines = ["# Dinner plan", ""]
    if venue:
        lines += [
            f"**{venue['name']}** at {venue['slot'].replace('-', ':00-')}:00 "
            f"({venue['cuisine']}, {venue['price_band']}, {venue['area']})",
            "",
            f"Found in {len(result['rounds'])} round(s) of yes/no questions, "
            f"after trying {result['offers_tried']} of "
            f"{result['search_space']} possible offers.",
            "",
        ]
    else:
        lines += [
            f"No offer was acceptable to every guest within "
            f"{len(result['rounds'])} rounds.",
            "",
        ]

    for entry in result["rounds"]:
        lines += ["", f"## Round {entry['round']}", ""]
        for offer, tally in zip(entry["offers"], entry["tallies"]):
            mark = " <-- booked" if venue and venues.key(offer) == venues.key(venue) else ""
            lines.append(
                f"- {offer['name']} at {offer['slot']} "
                f"({offer['price_band']}): {tally}/{len(guests)}{mark}"
            )

    total = sum(result["spend"][node_id] for node_id in guests)
    lines += [
        "",
        "## Disclosure ledger",
        "",
        "| node | bits disclosed |",
        "| --- | --- |",
    ]
    for node_id in sorted(guests):
        lines.append(f"| {node_id} | {result['spend'][node_id]:.2f} |")
    lines += [
        f"| **total** | **{total:.2f}** |",
        "",
        "Nobody stated a budget, a price band, an availability window, a "
        "dietary need or a location. Every guest's entire contribution was "
        "yes/no answers to concrete offers, and a rejection does not say "
        "which constraint caused it.",
    ]
    if result["excluded"]:
        lines += [
            "",
            f"Surprise preserved: node(s) {', '.join(result['excluded'])} saw no "
            "offer and were not told the booking. Her stated taste ranked the "
            "venue pool; she never saw what was proposed.",
        ]
    return "\n".join(lines)


def run(agent: AgentSession, context: Context) -> None:
    """Run the protocol and report the plan plus its privacy cost."""
    result = plan(agent)
    report = _report(result)
    agent.events.emit({"type": "message", "role": "assistant", "content": report})
    print(report)
