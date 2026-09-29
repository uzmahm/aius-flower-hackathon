"""The leader: one centralized task that plans an event for whoever connects.

The leader runs at the SuperLink, where the runtime grants get_nodes /
push_messages / pull_messages and nothing else. Participants cannot talk to
each other, so every bit passes through this process. That makes this the
place to discover the roster, validate inbound payloads, and account for the
total released.

It never asks anyone when they are free or what they can spend. It proposes
fully specified offers -- this activity, at this hour, at this price -- and
collects one bit per offer per participant. Feasibility is discovered from
those bits alone, the way twenty questions discovers a word.

What this costs: the leader is searching blind, so it may need more than one
round. What it buys: nobody ever asserts an attribute. A rejected offer is
deniable -- a meeting, a commute, a budget, an allergy, a bad knee, a dislike
of crowds, all look identical from here.

The protocol is plain Python rather than model-driven. The model is called
once, for the one step that needs taste: ranking the public catalogue against
the brief.
"""

from __future__ import annotations

import json
from typing import Any

from flwr.agentapp import AgentSession
from flwr.app import Context

from event_planner import activities, brief as brief_mod, llm, policy, ui_events

PULL_TIMEOUT = 240.0
OFFERS_PER_ROUND = 5
# How much to favour parts of the space nobody has asked about yet. 0 is
# pure exploitation; see `_optimism`.
EXPLORATION = 0.35
MAX_ROUNDS = 4

RANK_INSTRUCTIONS = (
    "You rank activities for a group whose constraints you do not know and "
    "must not ask for. You are given the organiser's brief, the guest of "
    "honour's stated taste if there is one, and a catalogue of real "
    "activities. Return JSON only: {\"order\":[activity names, best first]}. "
    "Favour the requested activity tags and atmosphere, and somewhere new if "
    "that is preferred. Include a spread of price bands and times rather than "
    "only the cheapest or only the evening ones -- some people may be "
    "constrained in ways you cannot see."
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
            "side": "leader",
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
            # rather than letting it into the leader's context.
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


def _roster(agent: AgentSession, node_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Ask every connected node who it speaks for. Costs zero bits.

    This is what makes users spawnable: nothing about who is taking part is
    known before this round. Start another SuperNode and it is simply in the
    next run's roster.
    """
    replies = _exchange(
        agent, node_ids, {"phase": "identity"}, policy.identity_schema()
    )
    return {node_id: parsed for node_id, (parsed, _) in replies.items()}


def _rank(
    agent: AgentSession, ebrief: brief_mod.EventBrief, wishes: dict[str, Any]
) -> list[str]:
    """Rank the public catalogue against the brief and any stated wishes."""
    # The organiser asked for something specific; the honouree's standing
    # taste is a prior. Weight them accordingly rather than pooling them, or
    # a well-known guest of honour drowns out the brief entirely.
    weights: dict[str, float] = {tag: 2.0 for tag in ebrief.tags}
    for tag in wishes.get("activity_prefs", []):
        weights[tag] = weights.get(tag, 0.0) + 1.0
    wanted = sorted(weights, key=lambda t: -weights[t])
    pool = [
        {k: v for k, v in activity.items() if k != "needs"}
        for activity in activities.CATALOGUE
    ]

    # The deterministic ranking is the fallback, so a missing or flaky model
    # degrades the ordering instead of killing the run.
    def offline_key(activity: dict[str, Any]) -> tuple[float, int, str]:
        atmosphere_hit = activity["atmosphere"] == wishes.get("atmosphere")
        new_hit = bool(wishes.get("prefers_new_place")) and activity["new_opening"]
        return (
            -sum(weights.get(tag, 0.0) for tag in activity["tags"]),
            -(atmosphere_hit + new_hit),
            activity["name"],
        )

    offline = [a["name"] for a in sorted(activities.CATALOGUE, key=offline_key)]

    answer = llm.ask_json(
        agent,
        RANK_INSTRUCTIONS,
        json.dumps(
            {
                "brief": {"request": ebrief.prompt, "wanted_tags": wanted},
                "guest_of_honour_taste": wishes or None,
                "activities": pool,
            },
            indent=2,
        ),
        {"order": offline},
    )
    order = answer.get("order") if isinstance(answer, dict) else None
    known = {a["name"] for a in activities.CATALOGUE}
    ranked = [name for name in (order or []) if name in known]
    # Anything the model dropped keeps its offline position, at the back.
    return ranked + [name for name in offline if name not in ranked]


def _spread(
    pool: list[dict[str, Any]], rank: dict[str, int], taken: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Opening round: the best-ranked activities, each at a different time.

    Ranked order first, so the round actually answers the brief. One slot per
    offer, because five variations of one activity would waste a round if that
    activity is the problem, and five activities at one hour would waste it if
    the hour is.
    """
    by_rank = sorted(
        {offer["name"] for offer in pool}, key=lambda name: rank[name]
    )
    chosen: list[dict[str, Any]] = []
    slots_used: set[str] = set()
    for name in by_rank:
        options = [
            offer
            for offer in pool
            if offer["name"] == name
            and offer["slot"] not in slots_used
            and activities.key(offer) not in taken
        ]
        if not options:
            continue
        best = min(options, key=lambda o: policy.SLOTS.index(o["slot"]))
        chosen.append(best)
        slots_used.add(best["slot"])
        if len(chosen) == OFFERS_PER_ROUND:
            break
    return chosen


# The attributes the leader can reason about. Every one of them is a public
# fact about the offer; none of them is anything a participant said.
ATTRIBUTES = ("name", "slot", "price_band", "kind", "atmosphere", "area")


def _prior(history: list[dict[str, Any]]) -> float:
    """The overall accept rate so far: what to assume about the unasked."""
    return sum(p["rate"] for p in history) / len(history) if history else 0.5


def _rates(
    history: list[dict[str, Any]], prior: float
) -> dict[tuple[str, str], float]:
    """Accept rate per attribute value, smoothed toward the prior.

    One observation is one observation. Without smoothing a single 0/4 round
    writes off a whole price band or a whole neighbourhood for good, and the
    search stops exploring the part of the space where the answer actually
    is. Adding the prior as a pseudo-observation keeps early evidence
    suggestive rather than final.
    """
    seen: dict[tuple[str, str], list[float]] = {}
    for past in history:
        for attr in ATTRIBUTES:
            seen.setdefault((attr, past["offer"][attr]), []).append(past["rate"])
    return {
        key: (sum(vals) + prior) / (len(vals) + 1) for key, vals in seen.items()
    }


def _score(
    offer: dict[str, Any], rates: dict[tuple[str, str], float], prior: float
) -> float:
    """Estimate the chance everyone accepts this offer, from bits alone.

    Multiplicative, not additive, and that is the whole trick. An activity
    two people out of three can do, at an hour two out of three can make, is
    not a two-out-of-three offer -- the refusers are probably different
    people. Summing the evidence hides that; multiplying it does not, so the
    search stops chasing near misses that cannot compose.

    The only inputs are bits. The leader is inferring which hours, prices and
    kinds of activity the group can live with -- never why, and never which
    person.
    """
    estimate = 1.0
    for attr in ATTRIBUTES:
        estimate *= rates.get((attr, offer[attr]), prior)
    return estimate


def _optimism(
    offer: dict[str, Any], counts: dict[tuple[str, str], int]
) -> float:
    """A bonus for offers made of attributes nobody has asked about yet.

    Pure exploitation converges confidently on whichever region the first
    round happened to touch, and an offer that works for everyone can easily
    be one whose price band, part of town and kind of activity have each
    looked mediocre on their own. This keeps a little pressure on the corners
    of the space.

    Measured over 237 random feasible rosters of 3-6 people, this finds an
    offer everyone accepts 88.6% of the time within MAX_ROUNDS, against 87.3%
    for pure exploitation. A real improvement would need a better question,
    not a better coefficient -- see the limitations in the README.
    """
    unseen = sum(
        1 for attr in ATTRIBUTES if counts.get((attr, offer[attr]), 0) == 0
    )
    return 1.0 + EXPLORATION * unseen / len(ATTRIBUTES)


def _counts(history: list[dict[str, Any]]) -> dict[tuple[str, str], int]:
    """How many times each attribute value has been asked about."""
    counts: dict[tuple[str, str], int] = {}
    for past in history:
        for attr in ATTRIBUTES:
            key = (attr, past["offer"][attr])
            counts[key] = counts.get(key, 0) + 1
    return counts


def _next_round(
    pool: list[dict[str, Any]],
    rank: dict[str, int],
    taken: set[tuple[str, str]],
    history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Later rounds: the most promising unproposed offers, still spread a bit."""
    prior = _prior(history)
    rates = _rates(history, prior)
    counts = _counts(history)
    remaining = [offer for offer in pool if activities.key(offer) not in taken]
    remaining.sort(
        key=lambda o: (
            -_score(o, rates, prior) * _optimism(o, counts),
            rank[o["name"]],
            o["slot"],
        )
    )
    chosen: list[dict[str, Any]] = []
    slots_used: dict[str, int] = {}
    names_used: dict[str, int] = {}
    for offer in remaining:
        # At most two offers per slot and two per activity, so one promising
        # guess cannot eat a whole round. A round costs one bit per offer from
        # every participant; it should buy five genuinely different questions.
        if slots_used.get(offer["slot"], 0) >= 2:
            continue
        if names_used.get(offer["name"], 0) >= 2:
            continue
        chosen.append(offer)
        slots_used[offer["slot"]] = slots_used.get(offer["slot"], 0) + 1
        names_used[offer["name"]] = names_used.get(offer["name"], 0) + 1
        if len(chosen) == OFFERS_PER_ROUND:
            break
    return chosen


def plan(agent: AgentSession) -> dict[str, Any]:
    """Run the protocol. Returns the plan and everything it cost."""
    nodes = _grid(agent, "get_nodes", {"sample_size": None})["nodes"]
    node_ids = [node["id"] for node in nodes]
    if not node_ids:
        raise RuntimeError("No SuperNodes available; start some users first.")

    spend: dict[str, float] = {node_id: 0.0 for node_id in node_ids}
    # Announce the federation before the first round, so a console can show
    # the identity round happening rather than its result.
    ui_events.emit("start", prompt=agent.prompt, nodes=nodes)

    roster = _roster(agent, node_ids)
    ebrief = brief_mod.parse(agent.prompt, roster)

    honouree = next(
        (n for n, entry in roster.items() if entry["user"] == ebrief.honouree), None
    )
    # Only a surprise removes the honouree from the offer rounds. If the
    # organiser is not hiding anything, they vote like everybody else.
    excluded = [honouree] if (honouree and ebrief.surprise) else []
    voters = [node_id for node_id in node_ids if node_id not in excluded]
    if not voters:
        raise RuntimeError("Nobody left to plan for; nothing to do.")

    ui_events.emit(
        "roster",
        nodes=[
            {**node, **roster.get(node["id"], {})} for node in nodes
        ],
        brief={
            "tags": ebrief.tags,
            "honouree": ebrief.honouree,
            "surprise": ebrief.surprise,
        },
        honouree=honouree,
        guests=voters,
        excluded=excluded,
    )

    # The only attribute anyone states, and only if it is their event. Their
    # calendar and budget are not asked for either.
    wishes: dict[str, Any] = {}
    if honouree:
        replies = _exchange(
            agent, [honouree], {"phase": "wishes"}, policy.wishes_schema()
        )
        for node_id, (reply, bits) in replies.items():
            spend[node_id] += bits
            wishes = reply

    rank = {name: i for i, name in enumerate(_rank(agent, ebrief, wishes))}
    pool = activities.offers()

    taken: set[tuple[str, str]] = set()
    history: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    chosen: dict[str, Any] | None = None

    for round_no in range(1, MAX_ROUNDS + 1):
        offers = (
            _spread(pool, rank, taken)
            if round_no == 1
            else _next_round(pool, rank, taken, history)
        )
        if not offers:
            break
        taken.update(activities.key(offer) for offer in offers)
        ui_events.emit("round", round=round_no, offers=offers)

        replies = _exchange(
            agent,
            voters,
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
        ui_events.emit("tally", round=round_no, tallies=tallies, voters=len(replies))

        unanimous = [i for i, t in enumerate(tallies) if t == len(replies)]
        if unanimous:
            chosen = offers[unanimous[0]]
            break

    # Tell the people who are allowed to know.
    if chosen:
        ui_events.emit(
            "consensus",
            activity=chosen,
            round=len(rounds),
            offers_tried=len(taken),
            search_space=len(pool),
        )
        _exchange(agent, voters, {"phase": "plan", "activity": chosen}, policy.plan_schema())
        for node_id in voters:
            spend[node_id] += 1.0

    ui_events.emit(
        "done", activity=chosen, spend=spend, guests=voters, excluded=excluded
    )
    return {
        "activity": chosen,
        "brief": {
            "prompt": ebrief.prompt,
            "tags": ebrief.tags,
            "honouree": ebrief.honouree,
            "surprise": ebrief.surprise,
            "summary": ebrief.summary(),
        },
        "roster": roster,
        "wishes": wishes,
        "rounds": rounds,
        "spend": spend,
        "guests": voters,
        "excluded": excluded,
        "search_space": len(pool),
        "offers_tried": len(taken),
    }


def _report(result: dict[str, Any]) -> str:
    """A demo-legible summary: the plan, and exactly what it cost in privacy."""
    chosen = result["activity"]
    voters = result["guests"]
    names = {n: e["user"] for n, e in result["roster"].items()}
    lines = ["# Event plan", "", f"_Brief: {result['brief']['summary']}_", ""]
    if chosen:
        lines += [
            f"**{activities.describe(chosen)}**",
            "",
            f"Found in {len(result['rounds'])} round(s) of yes/no questions, "
            f"after trying {result['offers_tried']} of "
            f"{result['search_space']} possible offers.",
            "",
        ]
    else:
        lines += [
            f"No offer worked for everyone within {len(result['rounds'])} rounds.",
            "",
        ]

    for entry in result["rounds"]:
        lines += ["", f"## Round {entry['round']}", ""]
        for offer, tally in zip(entry["offers"], entry["tallies"]):
            won = chosen and activities.key(offer) == activities.key(chosen)
            lines.append(
                f"- {offer['name']} at {offer['slot']} "
                f"({offer['price_band']}, {'/'.join(offer['tags'])}): "
                f"{tally}/{len(voters)}{' <-- booked' if won else ''}"
            )

    total = sum(result["spend"][node_id] for node_id in voters)
    lines += [
        "",
        "## Disclosure ledger",
        "",
        "| user | node | bits disclosed |",
        "| --- | --- | --- |",
    ]
    for node_id in sorted(voters):
        lines.append(
            f"| {names.get(node_id, '?')} | {node_id} | {result['spend'][node_id]:.2f} |"
        )
    lines += [
        f"| **total** | | **{total:.2f}** |",
        "",
        "Nobody stated a budget, a price band, an availability window, a "
        "dietary need or a location. Every participant's entire contribution "
        "was yes/no answers to concrete offers, and a rejection does not say "
        "which constraint caused it.",
    ]
    if result["excluded"]:
        hidden = ", ".join(names.get(n, n) for n in result["excluded"])
        lines += [
            "",
            f"Surprise preserved: {hidden} saw no shortlist and was not told the "
            "outcome. Their stated taste ranked the catalogue; they never saw "
            "what was proposed.",
        ]
    return "\n".join(lines)


def run(agent: AgentSession, context: Context) -> None:
    """Run the protocol and report the plan plus its privacy cost."""
    result = plan(agent)
    report = _report(result)
    agent.events.emit({"type": "message", "role": "assistant", "content": report})
    print(report)
