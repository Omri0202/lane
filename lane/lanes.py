"""
lanes.py — the seven kinds of request LANE distinguishes.

A lane is NOT a model. It is a statement about what the request needs, made
before anything is known about which providers the user has keys for. The lane
is stable; the model that serves it changes with the mode, the catalog, and
which keys are present.

Splitting the cheap end into TRIVIAL and SIMPLE is the single highest-value
distinction here. "thanks!" and "what year did the Berlin wall fall" are both
short, but the first needs no capability at all and the second needs a model
that knows things. Collapsing them — as most routers do — either wastes a
frontier model on pleasantries or answers real questions with a toy.
"""

from __future__ import annotations


class Lane:
    TRIVIAL = "trivial"
    SIMPLE = "simple"
    GENERAL = "general"
    LONGFORM = "longform"
    REASONING = "reasoning"
    VISION = "vision"
    TOOLS = "tools"


#: floor      — minimum capability score a model must have to serve this lane.
#:              This is the safety rail: save-mode may go as cheap as it likes,
#:              but never below the floor. Without it, "cheapest wins" degrades
#:              every request to the worst model you own.
#: needs      — hard capability requirements. A model lacking one is not merely
#:              worse for the lane, it cannot serve it at all.
#: prefers    — soft signal used only to break ties in performance mode.
LANES: dict[str, dict] = {
    Lane.TRIVIAL: {
        "label": "Trivial",
        "floor": 0,
        "needs": (),
        "prefers": "speed",
        "blurb": "Greetings, acknowledgements, one-word replies. No capability "
                 "is required and none should be paid for.",
    },
    Lane.SIMPLE: {
        "label": "Simple",
        "floor": 40,
        "needs": (),
        "prefers": "speed",
        "blurb": "Short factual questions, definitions, conversions, lookups "
                 "of things the model already knows.",
    },
    Lane.GENERAL: {
        "label": "General",
        "floor": 60,
        "needs": (),
        "prefers": "value",
        "blurb": "Ordinary conversation and explanation. The default when "
                 "nothing more specific is detected.",
    },
    Lane.LONGFORM: {
        "label": "Long-form",
        "floor": 70,
        "needs": (),
        "prefers": "prose",
        "blurb": "Writing, drafting, rewriting, summarising. Judged on voice "
                 "and structure rather than correctness.",
    },
    Lane.REASONING: {
        "label": "Reasoning",
        "floor": 85,
        "needs": (),
        "prefers": "depth",
        "blurb": "Code, mathematics, debugging, analysis, planning. The one "
                 "lane where using a cheaper model is a false economy.",
    },
    Lane.VISION: {
        "label": "Vision",
        "floor": 60,
        "needs": ("vision",),
        "prefers": "depth",
        "blurb": "An image is attached. Only models that can read images are "
                 "candidates at all.",
    },
    Lane.TOOLS: {
        "label": "Tools",
        "floor": 70,
        "needs": ("tools",),
        "prefers": "depth",
        "blurb": "The request declares tools or function schemas. Tool-calling "
                 "reliability matters more than raw intelligence here, and the "
                 "floor is high because a model that emits malformed tool JSON "
                 "costs more in retries than it saves per token.",
    },
}

DEFAULT_LANE = Lane.GENERAL

#: Order from least to most demanding. Used when a constraint (context length,
#: missing capability) makes the chosen lane unservable and LANE must find the
#: nearest lane it can actually serve.
ORDER = [Lane.TRIVIAL, Lane.SIMPLE, Lane.GENERAL, Lane.LONGFORM,
         Lane.REASONING]


def spec(lane: str) -> dict:
    return LANES.get(lane, LANES[DEFAULT_LANE])


def floor(lane: str) -> int:
    return spec(lane)["floor"]


def needs(lane: str) -> tuple:
    return spec(lane)["needs"]


def label(lane: str) -> str:
    return spec(lane)["label"]
