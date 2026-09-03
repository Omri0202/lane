"""
build_core.py — generate the extension's JavaScript brain from the Python one.

The extension needs to classify without a server, which means a second copy of
the classifier. Two copies of anything drift, and a router whose advice differs
depending on which half of the product you asked is worse than one that is
merely wrong — so nothing here is hand-written. The corpus, the model catalog,
the lane table and every regex are read out of the live Python modules and
emitted as JavaScript, and `tests/test_core_parity.py` fails if the two ever
disagree.

The only genuinely tricky part is the regexes. Several are written with re.X,
which lets them carry whitespace and comments; JavaScript has no equivalent
flag, so the pattern has to be flattened first. That flattening is done here
and then CHECKED against the original on every string in the corpus, because a
silently mis-stripped character class would change the routing in a way no
amount of reading would catch.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lane import catalog, classify, corpus, lanes  # noqa: E402

OUT = ROOT / "extension" / "core" / "lane-core.js"


def flatten_verbose(pattern: str) -> str:
    """Strip re.X whitespace and comments, leaving an equivalent pattern.

    Whitespace inside a character class is significant and must survive; so is
    an escaped space. Everything else goes, along with `#` comments — but only
    those outside a class, since `#` is an ordinary character within one.
    """
    out = []
    in_class = False
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            out.append(pattern[i:i + 2])
            i += 2
            continue
        if ch == "[":
            in_class = True
        elif ch == "]":
            in_class = False
        if not in_class:
            if ch in " \t\n\r":
                i += 1
                continue
            if ch == "#":
                while i < len(pattern) and pattern[i] != "\n":
                    i += 1
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def js_flags(flags: int) -> str:
    out = ""
    if flags & re.I:
        out += "i"
    if flags & re.M:
        out += "m"
    return out


def check(name: str, original: re.Pattern, flat: str, samples: list[str]) -> None:
    """The flattened pattern must behave identically on real inputs."""
    rebuilt = re.compile(flat, original.flags & ~re.X)
    for s in samples:
        if bool(original.search(s)) != bool(rebuilt.search(s)):
            raise SystemExit(
                f"{name}: flattening changed behaviour on {s!r}")


def emit_regex(name: str, pattern: re.Pattern, samples: list[str]) -> str:
    flat = flatten_verbose(pattern.pattern) if pattern.flags & re.X \
        else pattern.pattern
    check(name, pattern, flat, samples)
    # JS regex literals need / escaped; everything else is compatible.
    return f"const {name} = /{flat.replace('/', chr(92) + '/')}/{js_flags(pattern.flags)};"


def main() -> None:
    samples = [t for t, _ in corpus.TRAIN] + [t for t, _ in corpus.HELDOUT] + [
        "translate this bash script into powershell",
        "create a picture of Germany",
        "```python\nprint(1)\n```",
        "Traceback (most recent call last):",
        "why does my binary search overflow",
        "whats the polish word for bread",
        "todays exchange rate for the shekel",
        "fix my sql join",
    ]

    regexes = [
        emit_regex("FENCE", classify._FENCE, samples),
        emit_regex("TRACE", classify._TRACE, samples),
        emit_regex("THINK_HARD", classify._THINK_HARD, samples),
        emit_regex("CODE_REQ", classify._CODE_REQ, samples),
        emit_regex("MATH", classify._MATH, samples),
        emit_regex("IMAGE_REQ", classify._IMAGE_REQ, samples),
        emit_regex("TRANSLATE_VERB", classify._TRANSLATE_VERB, samples),
        emit_regex("LOOKUP", classify._LOOKUP, samples),
        emit_regex("CODE_VERB", classify._CODE_VERB, samples),
        emit_regex("TOKEN", re.compile(classify._TOKEN.pattern, re.I), samples),
    ]

    models = []
    for m in catalog.all_models():
        models.append({
            "id": m.id, "provider": m.provider, "display": m.display,
            "tier": m.tier, "in_price": m.in_price, "out_price": m.out_price,
            "context": m.context, "max_output": m.max_output,
            "vision": m.vision, "tools": m.tools, "web": m.web,
            "kind": m.kind, "image_out": m.image_out,
            "per_image": m.per_image, "speed": m.speed,
            "strengths": list(m.strengths),
        })

    lane_table = {}
    for name, spec in lanes.LANES.items():
        lane_table[name] = {
            "label": spec["label"],
            "floor": spec["floor"],
            "needs": list(spec["needs"]),
            "kind": spec.get("kind", "chat"),
            "prefers": spec["prefers"],
            "wants": lanes.wants(name),
            "fit": lanes.fit_reason(name),
            "expected_output": lanes.expected_output(name),
        }

    payload = {
        "LANES": lane_table,
        "ORDER": list(lanes.ORDER),
        "LADDER": list(classify._LADDER),
        "DEFAULT_LANE": lanes.DEFAULT_LANE,
        "TRAIN": [[t, l] for t, l in corpus.TRAIN],
        "MODELS": models,
        "CONFIDENT": classify.CONFIDENT,
        "UPBIAS": classify._UPBIAS,
        "DOC_WORDS": classify._DOC_WORDS,
        "TECH_WORDS": sorted(classify._TECH_WORDS),
        "CREATE_WORDS": sorted(classify._CREATE_WORDS),
        "FAULT_WORDS": sorted(classify._FAULT_WORDS),
        "HUMAN_LANGS": sorted(classify._HUMAN_LANGS),
        "PROG_LANGS": sorted(classify._PROG_LANGS),
        "PROG_STRICT": sorted(classify._PROG_STRICT),
    }

    template = (ROOT / "tools" / "core_template.js").read_text(encoding="utf-8")
    js = template.replace("/*__REGEXES__*/", "\n".join(regexes))
    js = js.replace("/*__DATA__*/", json.dumps(payload, indent=1,
                                               ensure_ascii=False))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(js, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} "
          f"({len(js):,} bytes, {len(payload['TRAIN'])} training examples, "
          f"{len(models)} models)")


if __name__ == "__main__":
    main()
