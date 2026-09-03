"""
classify.py — read a request, name the lane it belongs to. Costs nothing.

The whole point of LANE is to spend less money. A router that calls a model to
decide which model to call has already lost the argument on short prompts,
where the classification can cost more than the answer. So every tier here runs
locally, in microseconds, on the machine the proxy is running on.

Four tiers, each allowed to abstain:

  structural  Facts, not guesses. An image is attached, or a tool schema is
              present. Looking is always better than inferring, so these are
              checked before a single character of prompt text is read.
  tier 0      Deterministic regex over signals that are unambiguous in
              practice: a traceback, a fenced code block, a request phrased as
              "think carefully". Written to be silent rather than wrong — a
              pattern that fires on the wrong thing is worse than no pattern.
  tier 1      Nearest-centroid over TF-IDF of words and adjacent word pairs.
              Reports a MARGIN and declines when the margin is thin, which is
              the only reason it beats the regex classifier it replaced.
  default     GENERAL. Not a guess dressed up as a decision — a deliberate
              middle that is wrong cheaply in both directions.

One asymmetry is built in on purpose. Sending a reasoning problem to a small
model produces a wrong answer the user must notice, re-ask, and pay for twice.
Sending a greeting to a large model wastes a fraction of a cent. These are not
symmetric errors, so when tier 1's top two lanes are close and the runner-up is
the more demanding of the pair, the more demanding one wins. See _UPBIAS.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from .corpus import TRAIN
from .lanes import Lane, ORDER

# ── structural tier: look, do not infer ──────────────────────────────────────


def _has_image(messages: list[dict]) -> bool:
    for msg in messages or []:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in (
                        "image_url", "image", "input_image"):
                    return True
    return False


def text_of(messages: list[dict]) -> str:
    """The last user turn, flattened. Routing reads the request, not the whole
    history — earlier turns describe what was already answered, and letting a
    long history outvote the actual question is how a router ends up sending
    'thanks' to a frontier model because the conversation was about compilers.
    """
    for msg in reversed(messages or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [p.get("text", "") for p in content
                     if isinstance(p, dict) and p.get("type") == "text"]
            return "\n".join(parts)
    return ""


# ── tier 0: deterministic signals ────────────────────────────────────────────

_FENCE = re.compile(r"```|^\s*(def |class |function |const |let |var |import |"
                    r"from \w+ import|#include|public static|SELECT .+ FROM)",
                    re.M)
_TRACE = re.compile(r"Traceback \(most recent|^\s+at [\w.$]+\(|"
                    r"^\w+Error:|^\w+Exception:|panic:|Segmentation fault",
                    re.M)
_THINK_HARD = re.compile(r"\b(think (hard|carefully|step by step)|"
                         r"take your time|be thorough|reason through|"
                         r"work through this carefully)\b", re.I)

#: Asking for code to be WRITTEN rather than debugged. Without this, "write me
#: a python function" reads as a writing task to any bag-of-words model,
#: because "write" is the single strongest long-form signal in the language.
_CODE_REQ = re.compile(r"""
    \b(write|make|build|create|generate|give\s+me|need|want|implement|
       help\s+me\s+with|show\s+me|code)\b [^.?!]{0,40}?
      \b(code|script|function|program|app|class|method|query|regex|
         algorithm|component|endpoint|module|test|tests|snippet|parser|
         api|cli|hook|migration)\b
  | \b(code|script|program)\s+(this|that|it|something|me)\b
  | \b(in|using|with|into)\s+(python|javascript|typescript|java|c\+\+|rust|go|
      sql|bash|powershell|html|css|react|node)\b
  | \b(fix|debug|refactor|optimi[sz]e|rewrite|profile)\b [^.?!]{0,30}?
      \b(code|script|function|bug|error|class|query|loop|test)\b
""", re.I | re.X)

#: Mathematical notation that no amount of word-frequency modelling will catch.
_MATH = re.compile(r"""
    \b(integrate|derivative|differentiate|solve\s+for|prove\s+that|
       factorise|factorize|eigenvalue|matrix|logarithm)\b
  | \b\d+\s*[\^]\s*\d+
  | \b(sin|cos|tan|log|ln|sqrt)\s*\(
""", re.I | re.X)

#: Asking for a picture to be MADE. This is tier 0 rather than a learned
#: feature because getting it wrong is not a matter of degree: recommending a
#: chat model to somebody who wants a picture is not a slightly worse answer,
#: it is an impossible one, and the phrasing is narrow enough to be caught
#: exactly.
#:
#: The verb is required. "describe this photo", "what is in the picture" and
#: "the image is blurry" all contain the nouns and none of them is a request
#: to draw anything.
_IMAGE_REQ = re.compile(r"""
    \b(draw|paint|sketch|render|generate|create|make|design|produce|
       give\s+me|i\s+want|i\s+need|can\s+you\s+(?:make|create|draw|generate))\b
    [^.?!]{0,60}?
    \b(image|images|picture|pictures|photo|photos|photograph|logo|logos|
       illustration|drawing|artwork|poster|icon|icons|banner|wallpaper|
       thumbnail|mockup|avatar|sticker|painting|portrait|comic|meme)\b
  | \b(an?\s+(?:image|picture|photo|illustration|drawing|painting|logo)\s+of)\b
  | \b(text[\s-]?to[\s-]?image|image\s+generation)\b
""", re.I | re.X)

#: Human languages, and programming languages. Both lists exist for one
#: sentence: "translate this bash script into powershell" is a porting job, not
#: a translation, and it must land in REASONING. Naming a programming language
#: vetoes the translate lane outright.
_HUMAN_LANGS = frozenset("""
english spanish french german hebrew arabic japanese chinese mandarin
cantonese korean russian italian portuguese dutch polish turkish hindi greek
swedish norwegian danish finnish czech hungarian romanian bulgarian serbian
croatian slovak ukrainian thai vietnamese indonesian malay tagalog filipino
persian farsi urdu bengali tamil telugu punjabi swahili yiddish latin
catalan basque welsh irish icelandic estonian latvian lithuanian
""".split())

_PROG_LANGS = frozenset("""
python javascript typescript java rust golang go sql bash powershell shell
html css react node ruby php swift kotlin scala perl haskell elixir clojure
lua dart matlab fortran cobol assembly regex json yaml xml
""".split())

#: Longest first, so "portuguese" is tried before any prefix of it could win,
#: then alphabetically. The second key is not cosmetic: sorting a set by length
#: alone leaves equal-length words in set-iteration order, which differs
#: between processes, so the compiled pattern - and anything generated from it
#: - was different on every run.
_LANG_ALT = "|".join(sorted(_HUMAN_LANGS, key=lambda w: (-len(w), w)))

#: A translation cue. Deliberately loose, because it is only ever consulted
#: AFTER a human language has been found and a programming language ruled out —
#: two conditions that already exclude almost everything. Keeping the language
#: list in one place is the point: spelling a subset of it into this pattern by
#: hand is what made "the polish word for bread" fall through.
_TRANSLATE_VERB = re.compile(r"""
    \b(translate|translation|translating|translated)\b
  | \bhow\s+(?:do|would)\s+you\s+say\b
  | \b(?:word|phrase|term|expression|equivalent)\s+for\b
  | \b(?:say|write|put|render|convert)\s+
      (?:this|that|it|the\s+following|my\s+\w+)\s+(?:in|into|to)\b
  | \b(?:in|into|to|from)\s+(?:""" + _LANG_ALT + r""")\b
""", re.I | re.X)

#: Must express INTENT to look something up, never merely contain a word that
#: also means something else. A bare "search" sent "why does my binary search
#: overflow" to the web lane — in a tier whose entire job is to be never wrong.
#: The same trap waits in "current" (current value), "latest" (latest commit)
#: and "as of" (as of this version), so each is required to sit next to a word
#: that only makes sense for live information.
_LOOKUP = re.compile(r"""
    \b(search|look)\s+(?:the\s+web|online|the\s+internet|it\s+up|this\s+up|
                       that\s+up|for\s+me)\b
  | \bgoogle\s+(?:it|that|this|for)\b
  | \b(?:latest|current|today'?s|tonight'?s|this\s+week'?s|recent)\s+
      (?:\w+\s+){0,2}
      (?:news|headlines?|price|prices|score|scores|weather|forecast|results?|
         release|version|rate|rates|update|updates|stock|standings|
         exchange\s+rate)\b
  | \bnews\s+(?:about|on|from)\b
  | \bwhat'?s\s+(?:happening|going\s+on|new)\b
  | \b(?:right\s+now|as\s+of\s+(?:today|now|this\s+morning))\b
  | \bwho\s+won\s+the\b
  | \b(?:is|are|was|were)\s+.{0,25}\b(?:still|currently)\s+(?:open|available|
      running|down|up)\b
  | \bhow\s+much\s+(?:is|does).{0,25}\b(?:cost|trading|worth)\s+(?:now|today)\b
""", re.I | re.X)


def _is_translation(text: str) -> bool:
    """A translation request names a human language and no programming one."""
    if not _TRANSLATE_VERB.search(text):
        return False
    words = set(re.findall(r"[a-z+#]+", text.lower()))
    if words & _PROG_LANGS:
        return False
    return bool(words & _HUMAN_LANGS)


#: Words that name a programming language AND are not also ordinary English.
#: "go", "rust", "swift" and "shell" are dropped: "go through this report" must
#: not read as a Go question.
_PROG_STRICT = _PROG_LANGS - {"go", "rust", "swift", "dart", "assembly",
                              "shell", "lua", "perl", "scala", "elixir"}

_CODE_VERB = re.compile(r"""
    \b(fix|debug|refactor|optimi[sz]e|rewrite|profile|port|migrate|
       implement|write|convert|translate|review|explain)\b
""", re.I | re.X)


def _is_code_context(text: str) -> bool:
    """A code verb sitting next to a named programming language.

    Deterministic, and it closes a gap the noun list could not: "fix my sql
    join" names no noun from the code list — "join" is a database word, not a
    programming one — so it fell through to the statistical tier, where
    reasoning beat simple by 0.005 and the router abstained into the default
    lane. Naming a language while asking for something to be fixed is not
    ambiguous.
    """
    if not _CODE_VERB.search(text):
        return False
    import re as _re
    words = set(_re.findall(r"[a-z+#]+", text.lower()))
    return bool(words & _PROG_STRICT)

#: Past this many words the message is a document being worked on, not a
#: question being asked, whatever its verbs look like.
_DOC_WORDS = 600


def tier0(text: str) -> tuple[str | None, str]:
    """Deterministic only. Returns (lane, reason) or (None, "")."""
    t = text or ""
    # Checked first: an image request that also mentions code ("draw a diagram
    # of my class hierarchy") is still an image request, and sending it to a
    # reasoning model produces an essay nobody asked for.
    if _IMAGE_REQ.search(t):
        return Lane.IMAGE_GEN, "you are asking for a picture to be made"
    if _is_translation(t):
        return Lane.TRANSLATE, "this is a translation between languages"
    if _LOOKUP.search(t):
        return Lane.WEB_SEARCH, "this needs current information"
    if _TRACE.search(t):
        return Lane.REASONING, "the message contains a stack trace"
    if _FENCE.search(t):
        return Lane.REASONING, "the message contains code"
    if _THINK_HARD.search(t):
        return Lane.REASONING, "you asked for careful reasoning"
    if _CODE_REQ.search(t):
        return Lane.REASONING, "this asks for code"
    if _is_code_context(t):
        return Lane.REASONING, "this names a programming language"
    if _MATH.search(t):
        return Lane.REASONING, "this is a maths problem"
    if len(t.split()) > _DOC_WORDS:
        return Lane.LONGFORM, "the message is document-length"
    return None, ""


# ── tier 1: nearest-centroid over TF-IDF ─────────────────────────────────────

_TOKEN = re.compile(r"[a-z']+")

#: Vocabulary that belongs to software and infrastructure. This is NOT a rule —
#: a bare hit means nothing, because "what does api stand for" is a simple
#: factual question that happens to contain "api". It is injected as a FEATURE
#: (<<tech>>), so the training corpus decides how much weight it carries and
#: the abstain margin still applies. A hand-written rule here was tried first
#: and mislabelled every definitional question about a technical term.
_TECH_WORDS = frozenset("""
api endpoint database schema query sql sqlite postgres mysql redis mongo
docker container kubernetes deploy deployment server serverless lambda
latency throughput cache caching thread threading async await mutex lock
deadlock null nullptr undefined nan exception stacktrace traceback compiler
linker runtime regex json yaml xml http https tcp udp ssl tls oauth jwt
middleware webhook repo repository git branch merge rebase commit diff
npm pip yarn pnpm gradle maven webpack vite bundler
react vue angular svelte django flask fastapi rails spring express nextjs
dependency dependencies package module import export function func method
class variable array list dict hashmap pointer heap stack recursion
segfault leak linter typescript javascript python java rust golang kotlin
swift php ruby scala haskell bash powershell shell cli daemon cron
frontend backend api's microservice monolith orm migration index
""".split())

#: Verbs that ask for prose to be produced or reshaped.
_CREATE_WORDS = frozenset("""
write draft compose pen script author rewrite reword rephrase edit proofread
summarise summarize condense shorten lengthen expand polish tighten outline
caption blurb tagline translate paraphrase
""".split())

#: Words that describe something being wrong. Strong reasoning signal, and
#: importantly one that fires on operational faults with no code in sight —
#: "my container exits immediately" contains no code and no code verb.
_FAULT_WORDS = frozenset("""
bug bugs broken breaks broke crash crashes crashing fail fails failing failed
error errors wrong incorrect slow hangs hanging stuck freezes exits timeout
timeouts leak leaking corrupt mismatch unexpected regression flaky
""".split())

_DIGITS = re.compile(r"\d")


def _features(text: str) -> Counter:
    """Words plus adjacent pairs, so phrasing carries weight but no single word
    decides. Case and punctuation are discarded as noise; length, the question
    mark, and three domain vocabularies are kept because they are genuinely
    predictive of lane and survive rephrasing better than any individual word.
    """
    raw = (text or "").lower()
    words = _TOKEN.findall(raw)[:60]
    f = Counter(words)
    f.update(f"{a}_{b}" for a, b in zip(words, words[1:]))

    n = len(words)
    if n <= 2:
        f["<<tiny>>"] += 3
    elif n <= 5:
        f["<<short>>"] += 2
    elif n >= 25:
        f["<<long>>"] += 2
    if raw.strip().endswith("?"):
        f["<<question>>"] += 1

    seen = set(words)
    # Capped: a document about Docker should not out-vote its own verb.
    if tech := len(_TECH_WORDS & seen):
        f["<<tech>>"] += min(tech, 3)
    if len(_CREATE_WORDS & seen):
        f["<<create>>"] += 2
    if len(_FAULT_WORDS & seen):
        f["<<fault>>"] += 2
    if _DIGITS.search(raw):
        f["<<numeric>>"] += 1
    return f


class Centroid:
    """Nearest-centroid over TF-IDF, in pure Python.

    Chosen because it generalises from few examples, trains in milliseconds at
    import time, needs no dependency at all, and — the part that matters —
    reports a margin, so it can decline to answer. A classifier forced to
    always pick is exactly how the regex version it replaced reached 35% on
    real phrasing while scoring perfectly on its author's own examples.
    """

    def __init__(self) -> None:
        self.idf: dict[str, float] = {}
        self.centroids: dict[str, dict[str, float]] = {}
        self.trained = False

    def fit(self, samples: list[tuple[str, str]]) -> None:
        docs = [(_features(t), lane) for t, lane in samples]
        n = len(docs) or 1
        df: Counter = Counter()
        for f, _ in docs:
            df.update(f.keys())
        self.idf = {w: math.log((n + 1) / (c + 1)) + 1.0 for w, c in df.items()}

        sums: dict[str, Counter] = {}
        counts: Counter = Counter()
        for f, lane in docs:
            vec = self._vec(f)
            bucket = sums.setdefault(lane, Counter())
            for w, x in vec.items():
                bucket[w] += x
            counts[lane] += 1
        self.centroids = {
            lane: self._norm({w: x / counts[lane] for w, x in bucket.items()})
            for lane, bucket in sums.items()
        }
        self.trained = True

    def _vec(self, f: Counter) -> dict[str, float]:
        v = {w: (1 + math.log(c)) * self.idf.get(w, 1.0) for w, c in f.items()}
        return self._norm(v)

    @staticmethod
    def _norm(v: dict[str, float]) -> dict[str, float]:
        mag = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {w: x / mag for w, x in v.items()}

    def rank(self, text: str) -> list[tuple[float, str]]:
        if not self.trained:
            return []
        v = self._vec(_features(text))
        return sorted(
            ((sum(v.get(w, 0.0) * x for w, x in c.items()), lane)
             for lane, c in self.centroids.items()),
            reverse=True)


#: How much better the winner must be before tier 1 is trusted, and how close
#: the top two must be before the cost asymmetry breaks the tie upward.
#:
#: Both were swept against HELDOUT rather than chosen by eye. Re-swept when the
#: translate and web_search lanes were added: two more classes changed the
#: centroid geometry and shrank every margin, which pushed "fix my sql join"
#: below the abstain line and into the default lane. Measured on the 60
#: held-out prompts at these values:
#:
#:     exact lane        90.0%
#:     UNDER-routed       0.0%   <- the number that matters
#:     over-routed       10.0%
#:
#: Under-routing is the only failure mode with a real cost: a reasoning problem
#: sent to a small model produces a wrong answer the user has to notice,
#: re-ask, and pay for twice. Over-routing wastes a fraction of a cent and
#: nobody notices. So the sweep maximised (accuracy - 2 x under-routing), not
#: accuracy.
#:
#: Raising CONFIDENT is not free — abstaining falls back to GENERAL, which is
#: BELOW reasoning. An abstain is not a safe non-answer here; it is a cheap
#: answer, and at 0.030 under-routing climbs to 5%.
CONFIDENT = 0.010
_UPBIAS = 0.045

_MODEL = Centroid()
_MODEL.fit(TRAIN)


#: The pure DIFFICULTY axis, and the only place the upward tie-break applies.
#:
#: ORDER contains every text lane so the under-routing metric can rank them by
#: cost risk. But translate and web_search are not harder versions of simple —
#: they are different KINDS of request, and "round up when it is close" across
#: that boundary is a category error rather than a safety margin. It sent
#: "thanks that worked perfectly" to the web-search lane, because simple beat
#: web_search by less than the bias and web_search sits higher in ORDER.
#:
#: Rounding trivial up to reasoning is caution. Rounding a thank-you up into a
#: web search is just wrong.
_LADDER = [Lane.TRIVIAL, Lane.SIMPLE, Lane.GENERAL, Lane.LONGFORM,
           Lane.REASONING]


def _demand(lane: str) -> int:
    try:
        return ORDER.index(lane)
    except ValueError:
        return len(ORDER)


def tier1(text: str) -> tuple[str | None, float, str]:
    """Returns (lane, margin, reason). lane is None when it declines."""
    scored = _MODEL.rank(text or "")
    if not scored:
        return None, 0.0, ""
    best, lane = scored[0]
    runner_score, runner_lane = scored[1] if len(scored) > 1 else (0.0, lane)
    margin = best - runner_score

    if margin < CONFIDENT:
        return None, margin, ""

    if (margin < _UPBIAS
            and lane in _LADDER and runner_lane in _LADDER
            and _LADDER.index(runner_lane) > _LADDER.index(lane)):
        return runner_lane, margin, ("how the message reads, rounded up - it "
                                     "was close and this is the safer half")
    return lane, margin, "how the message reads"


# ── the decision ─────────────────────────────────────────────────────────────

def classify(messages: list[dict], tools: list | None = None,
             forced: str | None = None) -> dict:
    """Name the lane for one request.

    Never raises and never returns nothing. Returns a dict with lane, reason,
    tier, margin and took_us — everything needed to explain the decision to a
    user who asks why their prompt went where it went.
    """
    import time
    t0 = time.perf_counter()

    def done(lane, reason, tier, margin=0.0):
        return {"lane": lane, "reason": reason, "tier": tier,
                "margin": round(margin, 4),
                "took_us": int((time.perf_counter() - t0) * 1e6)}

    if forced:
        return done(forced, "you pinned this lane", "forced")

    if tools:
        return done(Lane.TOOLS, "the request declares tools", "structural")
    if _has_image(messages):
        return done(Lane.VISION, "an image is attached", "structural")

    text = text_of(messages)
    lane, reason = tier0(text)
    if lane:
        return done(lane, reason, "0")

    lane, margin, reason = tier1(text)
    if lane == Lane.TRANSLATE and not _is_translation(text):
        # tier 0 already declined this, so the hunch is wrong. WHY it is wrong
        # decides where the request goes: a named programming language means
        # this is a porting job and belongs in reasoning, while anything else
        # means the translate centroid simply scored oddly and the sensible
        # move is the runner-up, not a lane picked out of the air.
        words = set(_TOKEN.findall((text or "").lower()))
        if words & _PROG_LANGS:
            lane, reason = Lane.REASONING, "this moves code between languages"
        else:
            scored = _MODEL.rank(text or "")
            alt = next((l for _, l in scored if l != Lane.TRANSLATE), None)
            lane = alt or Lane.GENERAL
            reason = "how the message reads"
    if lane:
        return done(lane, reason, "1", margin)

    return done(Lane.GENERAL, "no strong signal either way", "default", margin)


def explain(messages: list[dict], tools: list | None = None) -> dict:
    """Same decision, plus the full ranking. For `lane why`."""
    decision = classify(messages, tools)
    decision["ranking"] = [
        {"lane": lane, "score": round(score, 4)}
        for score, lane in _MODEL.rank(text_of(messages))
    ]
    return decision
