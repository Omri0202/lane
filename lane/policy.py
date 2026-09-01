"""
policy.py — turn a lane into a model the user can actually be billed for.

The classifier says what the request needs. This says what to do about it,
given three things it cannot control: which providers have keys, what the
catalog currently believes, and how big this particular request is.

The order matters and is not negotiable:

  1. FEASIBLE   Hard constraints. A model without vision cannot serve a request
                with an image. A model with a 200K window cannot serve a 400K
                prompt. These are not preferences and no mode may override
                them.
  2. FLOOR      The lane's minimum capability. Save mode is allowed to be as
                cheap as it likes above this line and not one point below it.
                Without the floor, "cheapest wins" quietly degrades every
                request to the worst model the user owns, which is how cost
                routers get uninstalled.
  3. MODE       Only now does save / balanced / performance get a say, and only
                among models that already passed 1 and 2.

When step 2 empties the set, LANE does not fail — it takes the strongest model
that passed step 1 and marks the decision `degraded`, so the user is told they
are getting less than the request asked for rather than silently receiving it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import catalog, config, lanes
from .catalog import Model
from .lanes import Lane

#: Leave room for the answer and for the fact that a character-count estimate
#: is only ever approximate. A request that fits a context window exactly will
#: fail once the model starts generating.
_CONTEXT_HEADROOM = 1.35


@dataclass
class Decision:
    model: Model
    lane: str
    mode: str
    reason: str
    tier: str = ""
    margin: float = 0.0
    degraded: bool = False
    degraded_note: str = ""
    considered: int = 0
    runners_up: list = field(default_factory=list)
    est_prompt_tokens: int = 0

    @property
    def model_id(self) -> str:
        return self.model.id

    def as_dict(self) -> dict:
        return {
            "lane": self.lane,
            "lane_label": lanes.label(self.lane),
            "mode": self.mode,
            "model": self.model.id,
            "provider": self.model.provider,
            "display": self.model.display,
            "reason": self.reason,
            "tier": self.tier,
            "margin": self.margin,
            "degraded": self.degraded,
            "degraded_note": self.degraded_note,
            "considered": self.considered,
            "runners_up": [m.id for m in self.runners_up],
            "est_prompt_tokens": self.est_prompt_tokens,
        }


class NoModelAvailable(RuntimeError):
    """Raised when not one model in the catalog can serve the request."""


def estimate_tokens(messages: list[dict]) -> int:
    """A character-count estimate, deliberately not a tokeniser call.

    Every provider tokenises differently and an exact count would mean a
    network round trip per request — which is latency and, on some providers,
    money. This is used only to exclude models whose context window cannot
    possibly fit the prompt, where being roughly right is enough.
    """
    chars = 0
    for msg in messages or []:
        content = msg.get("content")
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    chars += len(part.get("text", ""))
                else:
                    # An image is worth roughly a page of text in every
                    # provider's accounting. Better to over-reserve.
                    chars += 4000
    return max(1, chars // 4)


def feasible(models: list[Model], *, need_vision: bool = False,
             need_tools: bool = False, prompt_tokens: int = 0,
             want_output: int = 1024, kind: str = "chat") -> list[Model]:
    out = []
    for m in models:
        # The hardest constraint of the lot, and the only one that cannot be
        # traded against anything: a text model does not draw, and an image
        # model does not hold a conversation.
        if m.kind != kind:
            continue
        if kind == "image":
            out.append(m)
            continue
        if need_vision and not m.vision:
            continue
        if need_tools and not m.tools:
            continue
        if prompt_tokens and m.context < prompt_tokens * _CONTEXT_HEADROOM:
            continue
        if want_output and m.max_output < min(want_output, 4096):
            continue
        out.append(m)
    return out


def _rank(models: list[Model], mode: str, prefers: str) -> list[Model]:
    """Order the feasible, qualified models best-first for this mode."""
    if mode == config.MODE_SAVE:
        # Cheapest first; among equally priced models take the stronger one,
        # which is free capability and happens more often than you would think
        # (Sonnet 5 vs Sonnet 4.6).
        return sorted(models, key=lambda m: (m.blended(), -m.tier))

    if mode == config.MODE_PERFORMANCE:
        # Strongest first. Speed breaks ties for lanes that want speed, price
        # breaks them otherwise — never leave a tie to dict ordering, or the
        # chosen model silently depends on catalog file order.
        if prefers == "speed":
            return sorted(models, key=lambda m: (-m.tier, -m.speed, m.blended()))
        return sorted(models, key=lambda m: (-m.tier, m.blended(), -m.speed))

    # Balanced: most capability per dollar. This is the mode that actually
    # rewards a good catalog, because it is the only one that reads both
    # columns at once.
    return sorted(models, key=lambda m: (-m.value, -m.tier))


def choose(lane: str, *, mode: str | None = None,
           models: list[Model] | None = None,
           prompt_tokens: int = 0, want_output: int = 1024,
           need_vision: bool | None = None,
           need_tools: bool | None = None) -> Decision:
    """Pick the model that serves `lane` under `mode`."""
    mode = mode or config.get("mode")
    if mode not in config.MODES:
        mode = config.MODE_BALANCED

    pool = models if models is not None else catalog.usable()
    if not pool:
        raise NoModelAvailable(
            "no models available — add a key with `lane keys set <provider>`")

    need = lanes.needs(lane)
    if need_vision is None:
        need_vision = "vision" in need
    if need_tools is None:
        need_tools = "tools" in need

    want_kind = lanes.kind(lane)
    cand = feasible(pool, need_vision=need_vision, need_tools=need_tools,
                    prompt_tokens=prompt_tokens, want_output=want_output,
                    kind=want_kind)
    degraded, note = False, ""

    if not cand:
        # Relax the output-size requirement first: it is the constraint most
        # likely to be over-specified by a client that always sends max_tokens.
        cand = feasible(pool, need_vision=need_vision, need_tools=need_tools,
                        prompt_tokens=prompt_tokens, want_output=0,
                        kind=want_kind)
        if cand:
            degraded, note = True, "no model could produce an answer that long"
    if not cand:
        raise NoModelAvailable(
            f"no available model can serve a {lanes.label(lane).lower()} "
            f"request of about {prompt_tokens:,} tokens"
            + (" with images" if need_vision else "")
            + (" with tools" if need_tools else ""))

    floor = lanes.floor(lane)
    qualified = [m for m in cand if m.tier >= floor]

    if qualified:
        ranked = _rank(qualified, mode, lanes.spec(lane)["prefers"])
        if mode == config.MODE_SAVE:
            why = ("cheapest model that still clears the "
                   f"{lanes.label(lane).lower()} bar")
        elif mode == config.MODE_PERFORMANCE:
            why = ("strongest model available for "
                   f"{lanes.label(lane).lower()} work")
        else:
            why = "best capability per dollar for this lane"
    else:
        # Nothing clears the bar, so MODE NO LONGER APPLIES. The user has asked
        # for more capability than exists in their catalog; the only sensible
        # answer is the most there is.
        #
        # Ranking by mode here was a real bug: with only a free-tier provider
        # installed, balanced mode answered the REASONING lane with the
        # weakest 8B model, because once the floor is dropped the cheapest
        # model also has the best capability-per-dollar. That is the exact
        # under-routing failure the floor exists to prevent, arriving through
        # the door left open when the floor cannot be met.
        qualified = cand
        degraded = True
        ranked = sorted(cand, key=lambda m: (-m.tier, m.blended()))
        note = (note + "; " if note else "") + (
            f"nothing you have keys for meets the {lanes.label(lane).lower()} "
            f"bar (needs {floor}, best available is {ranked[0].tier}) — "
            f"using the strongest you have")
        why = (f"no model meets the {lanes.label(lane).lower()} bar; "
               f"this is the strongest available")

    winner = ranked[0]

    return Decision(model=winner, lane=lane, mode=mode, reason=why,
                    degraded=degraded, degraded_note=note,
                    considered=len(qualified), runners_up=ranked[1:4],
                    est_prompt_tokens=prompt_tokens)


def route(messages: list[dict], *, tools: list | None = None,
          mode: str | None = None, forced_lane: str | None = None,
          want_output: int = 1024,
          models: list[Model] | None = None) -> Decision:
    """Classify then choose. The single entry point the server uses."""
    from . import classify as _classify

    verdict = _classify.classify(messages, tools=tools, forced=forced_lane)
    tokens = estimate_tokens(messages)

    decision = choose(
        verdict["lane"], mode=mode, models=models,
        prompt_tokens=tokens, want_output=want_output,
        need_vision=_classify._has_image(messages) or
        "vision" in lanes.needs(verdict["lane"]),
        need_tools=bool(tools) or "tools" in lanes.needs(verdict["lane"]),
    )
    decision.tier = verdict["tier"]
    decision.margin = verdict["margin"]
    decision.reason = f"{verdict['reason']}; {decision.reason}"
    return decision


def baseline_model() -> Model | None:
    """The model the ledger compares against when reporting savings."""
    return catalog.by_id(config.get("baseline_model"))
