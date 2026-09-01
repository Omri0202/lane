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
    IMAGE_GEN = "image_gen"
    WEB_SEARCH = "web_search"
    TRANSLATE = "translate"


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
    Lane.TRANSLATE: {
        "label": "Translate",
        "floor": 55,
        "needs": (),
        "prefers": "prose",
        "blurb": "Moving text between human languages. Its own lane because "
                 "the capability gap between models is unusually small here — "
                 "translation into a major language is close to solved, so "
                 "this is one of the few places a cheap model is not a "
                 "compromise. The floor is lower than long-form for exactly "
                 "that reason.",
    },
    Lane.WEB_SEARCH: {
        "label": "Look it up",
        "floor": 60,
        "needs": ("web",),
        "prefers": "value",
        "blurb": "Needs information the model was not trained on. No amount "
                 "of capability substitutes for being able to search: the "
                 "strongest model without web access answers confidently from "
                 "a stale memory, which is worse than the weakest model that "
                 "can look.",
    },
    Lane.IMAGE_GEN: {
        "label": "Make an image",
        "floor": 0,
        "needs": ("image_out",),
        "kind": "image",
        "prefers": "depth",
        "blurb": "Asking for a picture to be DRAWN, not described. The one "
                 "lane where the usual advice is useless: no amount of "
                 "capability makes a text model produce an image, so the only "
                 "honest answer when the current site has no image model is "
                 "to say which site does.",
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

#: Roughly how many tokens a reply in each lane runs to. Output is priced 4-5x
#: higher than input on every provider here, so an estimate that counted only
#: the prompt would be wrong by an order of magnitude and always in the
#: flattering direction. Measured loosely, and always presented as an estimate.
EXPECTED_OUTPUT = {
    Lane.TRIVIAL: 30,
    Lane.SIMPLE: 120,
    Lane.GENERAL: 550,
    Lane.LONGFORM: 900,
    Lane.REASONING: 1200,
    Lane.VISION: 400,
    Lane.TOOLS: 600,
    Lane.IMAGE_GEN: 0,
    Lane.TRANSLATE: 400,
    Lane.WEB_SEARCH: 700,
}

DEFAULT_LANE = Lane.GENERAL

#: Order from least to most demanding. Used when a constraint (context length,
#: missing capability) makes the chosen lane unservable and LANE must find the
#: nearest lane it can actually serve.
#: Ordered by capability floor, which is what "more demanding" has to mean if
#: the under-routing guard is to be worth anything. Leaving the newer lanes out
#: of this list silently ranked them as the MOST demanding of all, because the
#: lookup fell through to the end.
ORDER = [Lane.TRIVIAL, Lane.SIMPLE, Lane.TRANSLATE, Lane.GENERAL,
         Lane.WEB_SEARCH, Lane.LONGFORM, Lane.REASONING]


def spec(lane: str) -> dict:
    return LANES.get(lane, LANES[DEFAULT_LANE])


def floor(lane: str) -> int:
    return spec(lane)["floor"]


def needs(lane: str) -> tuple:
    return spec(lane)["needs"]


def label(lane: str) -> str:
    return spec(lane)["label"]


def kind(lane: str) -> str:
    """"chat" or "image" — which sort of model can serve this at all."""
    return spec(lane).get("kind", "chat")


def expected_output(lane: str) -> int:
    return EXPECTED_OUTPUT.get(lane, 550)
