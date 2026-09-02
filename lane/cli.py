"""
cli.py — the `lane` command.

Everything here works without the server running, on purpose. `lane why` in
particular is the command that makes the router arguable: it prints the lane,
the reason, and what each of the three modes would have picked, so a
disagreement with the routing is a conversation about a visible decision rather
than a complaint about a black box.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from . import (audit, catalog, classify, config, keys, ledger, lanes,
               policy, providers, teams, trail)

_DIM, _B, _R = "\033[2m", "\033[1m", "\033[0m"
_G, _Y, _RED = "\033[32m", "\033[33m", "\033[31m"


def _supports_colour() -> bool:
    return sys.stdout.isatty()


def c(text: str, code: str) -> str:
    return f"{code}{text}{_R}" if _supports_colour() else text


def _rule(title: str = "") -> str:
    return c(f"── {title} " + "─" * max(2, 58 - len(title)), _DIM)


# ── lane why ─────────────────────────────────────────────────────────────────

def cmd_why(args) -> int:
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        print("give me a prompt to classify: lane why \"fix my sql join\"")
        return 2

    messages = [{"role": "user", "content": prompt}]
    verdict = classify.explain(messages)
    tokens = policy.estimate_tokens(messages)

    print()
    print(_rule("classification"))
    print(f"  lane      {c(lanes.label(verdict['lane']), _B)}  "
          f"{c('(' + verdict['lane'] + ')', _DIM)}")
    print(f"  because   {verdict['reason']}")
    print(f"  decided   tier {verdict['tier']} in {verdict['took_us']}µs"
          + (f", margin {verdict['margin']}" if verdict["margin"] else ""))
    print(f"  size      ~{tokens:,} prompt tokens")

    if args.verbose and verdict.get("ranking"):
        print(f"\n  {c('centroid ranking', _DIM)}")
        for row in verdict["ranking"]:
            print(f"    {row['lane']:<10} {row['score']:.4f}")

    pool = catalog.usable()
    if not pool:
        print()
        print(_rule("routing"))
        print(c("  no API keys yet — run `lane keys set anthropic`", _Y))
        print()
        return 0

    print()
    print(_rule("what each mode would pick"))
    default = config.get("mode")
    for mode in config.MODES:
        try:
            d = policy.choose(verdict["lane"], mode=mode,
                              prompt_tokens=tokens, want_output=1024)
        except policy.NoModelAvailable as exc:
            print(f"  {mode:<12} {c(str(exc), _RED)}")
            continue
        star = c(" ←default", _G) if mode == default else ""
        est = d.model.cost(tokens, 500)
        print(f"  {mode:<12} {c(d.model.display, _B)} "
              f"{c('(' + d.model.provider + ')', _DIM)}  "
              f"~{ledger.money(est)}/request{star}")
        if d.degraded:
            print(f"               {c(d.degraded_note, _Y)}")
        if args.verbose and d.runners_up:
            alts = ", ".join(m.display for m in d.runners_up)
            print(f"               {c('then: ' + alts, _DIM)}")

    base = policy.baseline_model()
    if base:
        b = base.cost(tokens, 500)
        print(f"\n  {c('baseline', _DIM)}     {base.display}  "
              f"~{ledger.money(b)}/request")
    print()
    return 0


# ── lane keys ────────────────────────────────────────────────────────────────

def cmd_keys(args) -> int:
    if args.action in (None, "list"):
        print()
        print(_rule("api keys"))
        for name, meta in keys.PROVIDERS.items():
            key = keys.get(name)
            src = keys.source(name)
            if key:
                print(f"  {c('●', _G)} {meta['name']:<16} "
                      f"{keys.mask(key):<18} {c('via ' + src, _DIM)}")
            else:
                print(f"  {c('○', _DIM)} {meta['name']:<16} "
                      f"{c('not set', _DIM):<18} {c(meta['console'], _DIM)}")
        if not keys.keyring_available():
            note = ("no system keyring here — LANE will read environment "
                    "variables instead")
            print("\n  " + c(note, _Y))
        print()
        return 0

    if args.action == "set":
        if not args.provider:
            print("which provider? " + ", ".join(keys.PROVIDERS))
            return 2
        name = keys.PROVIDERS[args.provider]["name"]

        value = args.value
        if not value:
            if args.visible:
                value = input(f"paste your {name} key (VISIBLE): ").strip()
            else:
                import getpass
                value = getpass.getpass(
                    f"paste your {name} key (hidden): ").strip()

        ok, problem = keys.looks_valid(args.provider, value)
        if not ok:
            print(c(f"not saved: {problem}", _RED))
            if not args.visible:
                # The failure this catches is almost always a paste that the
                # hidden prompt swallowed, which several Windows terminals do.
                print("  " + c("some terminals will not paste into a hidden "
                               "prompt. Try:", _DIM))
                print(f"  {c(f'lane keys set {args.provider} --visible', _B)}"
                      + c("   (key will show on screen)", _DIM))
            return 2
        if problem:
            print(c("  " + problem, _Y))

        try:
            where = keys.set(args.provider, value)
        except (KeyError, RuntimeError) as exc:
            print(c(str(exc), _RED))
            return 1
        print(f"{c('saved', _G)} {args.provider} key to {where}")

        # Ask the provider whether the key actually works. Listing models is
        # free and instant, and "saved" without it is a claim LANE cannot
        # support — which is how a two-character key survived long enough to
        # look like a routing bug.
        print(f"  {c('checking it with ' + name + '...', _DIM)}")
        try:
            live = asyncio.run(
                providers.get(args.provider).list_models(value))
            print(f"  {c('✓ works', _G)} — {len(live)} models available")
        except Exception as exc:
            print("  " + c("✗ stored, but " + name + " rejected it", _RED))
            print("    " + c(str(exc)[:200], _DIM))
            return 1
        return 0

    if args.action in ("rm", "delete", "remove"):
        if keys.delete(args.provider):
            print(f"removed {args.provider} key")
            return 0
        print(f"no stored {args.provider} key to remove")
        return 1
    return 2


# ── lane models ──────────────────────────────────────────────────────────────

def _reachable(model_id: str, live: set) -> bool:
    """Is this catalog id usable, given what the provider listed?

    Not the same as being IN the list. Anthropic lists dated snapshots
    (claude-haiku-4-5-20251001) while its API happily accepts the undated
    alias (claude-haiku-4-5) — so a literal membership test hid a model the
    user could use perfectly well. Hiding a working model is the worse error
    here: an unreachable one merely fails loudly when tried, but a hidden one
    silently never gets chosen.
    """
    return model_id in live or any(o.startswith(model_id + "-") for o in live)


def _is_snapshot_of(offered: str, known: set) -> bool:
    """The mirror image: do not report a dated snapshot as a new discovery
    when the catalog already carries its alias."""
    return any(offered.startswith(k + "-") for k in known)


async def _sync() -> int:
    have = keys.present()
    if not have:
        print(c("no keys set — nothing to sync against", _Y))
        return 1

    known = {m.id for m in catalog.all_models()}
    unreachable, discovered = [], []

    for provider in have:
        try:
            adapter = providers.get(provider)
            live = set(await adapter.list_models(keys.get(provider)))
        except Exception as exc:
            print(f"  {c('!', _Y)} {provider}: could not list models ({exc})")
            continue

        mine = {m.id for m in catalog.all_models() if m.provider == provider}
        missing = sorted(m for m in mine if not _reachable(m, live))
        extra = sorted(i for i in live
                       if i not in known and not _is_snapshot_of(i, known))
        unreachable += missing
        discovered += [(provider, m) for m in extra]
        reachable = sum(1 for m in mine if _reachable(m, live))
        print(f"  {c('✓', _G)} {provider}: {len(live)} models offered, "
              f"{reachable}/{len(mine)} of yours reachable")

    if unreachable:
        catalog.mark_unavailable(unreachable)
        print(f"\n  {c('hidden from routing', _Y)} "
              f"(your key cannot reach them):")
        for mid in unreachable:
            print(f"    {mid}")
    else:
        catalog.mark_unavailable([])

    if discovered:
        print(f"\n  {c('offered but not in your catalog', _DIM)} — add them "
              f"to ~/.lane/models.local.json to route to them:")
        for provider, mid in discovered[:25]:
            print(f"    {provider:<10} {mid}")
        if len(discovered) > 25:
            print(f"    {c(f'... and {len(discovered) - 25} more', _DIM)}")
    return 0


def cmd_models(args) -> int:
    if args.sync:
        print()
        print(_rule("syncing against each provider"))
        rc = asyncio.run(_sync())
        print()
        return rc

    usable = {m.id for m in catalog.usable()}
    hidden = catalog.unavailable_ids()
    have = set(keys.present())

    print()
    print(_rule("model catalog"))
    print(f"  {'':2}{'model':<26}{'prov':<11}{'tier':>5}"
          f"{'in $/M':>9}{'out $/M':>9}{'context':>10}")
    for m in catalog.all_models():
        if m.id in usable:
            mark, style = c("●", _G), _B
        elif m.id in hidden:
            mark, style = c("✗", _RED), _DIM
        else:
            mark, style = c("○", _DIM), _DIM
        print(f"  {mark} {c(f'{m.id:<24}', style)}{m.provider:<11}"
              f"{m.tier:>5}{m.in_price:>9.2f}{m.out_price:>9.2f}"
              f"{m.context:>10,}")

    print(f"\n  {c('●', _G)} routable   "
          f"{c('○', _DIM)} no key   {c('✗', _RED)} key cannot reach it")

    unverified = [p for p in keys.PROVIDERS
                  if not catalog.pricing_verified(p)]
    if unverified:
        print("\n  " + c("prices unverified for: " + ", ".join(unverified), _Y))
        print("  " + c("these are starting guesses. Check the provider "
                       "pricing page and correct", _DIM))
        print("  " + c("~/.lane/models.local.json — savings figures depend "
                       "on them being right.", _DIM))
    print()
    return 0


# ── lane stats ───────────────────────────────────────────────────────────────

def _advisor_block(days) -> None:
    """What the browser panel has been telling you, and what it is worth.

    Kept visually and arithmetically apart from the proxy figures above. One is
    money that left the account; the other is money that would have stayed in
    it had every recommendation been taken. Adding them together would produce
    a bigger number and a dishonest one.
    """
    a = ledger.stats(days, source="advisor")["total"]
    if not a["requests"]:
        return
    print()
    print(_rule("advisor · potential"))
    print(f"  messages advised on   {a['requests']:,}")
    print(f"  top model throughout  {ledger.money(a['baseline_cost'])}")
    print(f"  following the advice  {ledger.money(a['cost'])}")
    if a["saved"] > 0:
        pct = f"({a['saved_pct']:.0f}% less)"
        print("  " + c("would have saved", _G) + "      "
              + c(ledger.money(a["saved"]), _G) + "  " + c(pct, _G))
    print("  " + c("potential, not measured - LANE cannot see which model "
                   "you picked", _DIM))


def cmd_stats(args) -> int:
    s = ledger.stats(args.days)
    t = s["total"]

    if not t["requests"]:
        _advisor_block(args.days)
        print(f"\n  no proxy traffic recorded yet"
              + (f" in the last {args.days:g} days" if args.days else "")
              + ". Run some traffic through `lane serve` first.\n")
        return 0

    window = f"last {args.days:g} days" if args.days else "all time"
    print()
    print(_rule(f"usage · {window}"))
    print(f"  requests        {t['requests']:,}")
    print(f"  tokens          {t['in_tokens']:,} in / {t['out_tokens']:,} out")
    print(f"  {c('you spent', _B)}       {c(ledger.money(t['cost']), _B)}")

    base = config.get("baseline_model")
    bm = catalog.by_id(base)
    print(f"  {base} only   {ledger.money(t['baseline_cost'])}   "
          f"{c('(' + (bm.display if bm else base) + ' for everything)', _DIM)}")

    saved, pct = t["saved"], t["saved_pct"]
    if saved > 0:
        print(f"  {c('saved', _G)}           {c(ledger.money(saved), _G)}  "
              f"{c(f'({pct:.0f}% less)', _G)}")
    elif saved < 0:
        print(f"  {c('cost more', _Y)}       {ledger.money(-saved)}  "
              f"{c('routing spent above your baseline', _Y)}")

    if t["estimated"]:
        print("\n  " + c("some prices are unverified — treat these as "
                         "estimates (lane models)", _Y))

    print(f"\n{_rule('by lane')}")
    for name in list(lanes.LANES) + ["?"]:
        row = s["by_lane"].get(name)
        if not row:
            continue
        share = row["cost"] / t["cost"] * 100 if t["cost"] else 0
        bar = "█" * int(share / 4)
        print(f"  {name:<11}{row['requests']:>6}  "
              f"{ledger.money(row['cost']):>10}  {c(bar, _DIM)} {share:.0f}%")

    print(f"\n{_rule('by model')}")
    for mid, row in sorted(s["by_model"].items(),
                           key=lambda kv: -kv[1]["cost"]):
        m = catalog.by_id(mid)
        print(f"  {(m.display if m else mid):<26}{row['requests']:>6}  "
              f"{ledger.money(row['cost']):>10}")

    if s["errors"]:
        print(f"\n  {c(str(s['errors']) + ' failed request(s)', _Y)} "
              f"{c('— see `lane tail`', _DIM)}")
    _advisor_block(args.days)
    print()
    return 0


def cmd_tail(args) -> int:
    rows = ledger.read(limit=args.n)
    if not rows:
        print("\n  ledger is empty\n")
        return 0
    print()
    for r in rows:
        when = r.get("iso", "")[11:19]
        ok = c("ok ", _G) if r.get("ok", True) else c("ERR", _RED)
        line = (f"  {c(when, _DIM)} {ok} {r.get('lane', '?'):<10}"
                f"{r.get('model', '?'):<24}"
                f"{r.get('in', 0):>7}→{r.get('out', 0):<7}"
                f"{ledger.money(r.get('cost', 0)):>9}")
        print(line)
        if r.get("error"):
            print(f"      {c(r['error'][:150], _RED)}")
    print()
    return 0



# ── lane audit ───────────────────────────────────────────────────────────────

async def _judge_all(rows, model_id: str) -> int:
    """Ask the judge about every unjudged pair.

    Which side the routed answer appears on alternates per row. Judges favour
    whichever answer they read first by a margin large enough to manufacture
    the result this command exists to report, so the position is varied and
    recorded, and the bias cancels across the sample instead of accumulating.
    """
    m = catalog.by_id(model_id)
    if m is None:
        print(c(f"judge model {model_id!r} is not in the catalog", _RED))
        return 0
    key = keys.get(m.provider)
    if not key:
        print(c(f"no key for {m.provider} — cannot judge", _RED))
        return 0

    adapter = providers.get(m.provider)
    done = 0
    for i, row in enumerate(rows):
        if row.get("verdict"):
            continue
        swapped = bool(i % 2)
        # Room to think. A one-word answer needs one token, but a reasoning
        # model spends its budget on reasoning FIRST — at max_tokens 8 the
        # whole allowance went to internal thought and the visible reply came
        # back empty, so every verdict was silently dropped and the audit
        # reported nothing judged. The models worth using as a judge are
        # exactly the ones that behave this way.
        body = {"messages": [{"role": "user",
                              "content": audit.judge_prompt(row, swapped)}],
                "max_tokens": 512, "model": m.id}
        kwargs = {}
        if m.provider == "anthropic":
            kwargs["allow_sampling"] = m.sampling
        try:
            reply = await adapter.complete(body, m.id, key, **kwargs)
            text = (reply["choices"][0]["message"].get("content") or "")
        except Exception as exc:
            print(f"  {c('!', _Y)} {str(exc)[:110]}")
            continue
        verdict = audit.read_verdict(text, swapped)
        if not verdict:
            # Silence here is what hid the empty-reply bug. Say so.
            print(f"  {c('?', _Y)} unreadable verdict: {text[:60]!r}")
        if verdict:
            row["verdict"] = verdict
            row["judge"] = {"model": m.id, "swapped": swapped}
            done += 1
            print(f"  {c('judged', _DIM)} {done}", end="\r")
    return done


def cmd_quality(args) -> int:
    rows = audit.read()
    if args.judge:
        pending = [r for r in rows if not r.get("verdict")]
        if not pending:
            print("\n  nothing left to judge\n")
        else:
            judge_id = (config.get("audit_judge_model")
                        or config.get("baseline_model"))
            print()
            print(_rule(f"judging {len(pending)} pairs with {judge_id}"))
            n = asyncio.run(_judge_all(rows, judge_id))
            audit.rewrite(rows)
            print(f"  judged {n}                    ")

    s = audit.summary(rows)
    if not s["sampled"]:
        print()
        print("  no audited requests yet.")
        print("  " + c("turn it on with: lane config audit_sample_rate 0.02",
                       _DIM))
        print("  " + c("then send traffic through `lane serve` as usual.", _DIM))
        print()
        return 0

    print()
    print(_rule("quality audit"))
    print(f"  sampled       {s['sampled']:,} requests"
          + (f"  ({s['rate']:.0%} of traffic)" if s["rate"] else ""))
    print(f"  judged        {s['judged']:,}")

    if s["judged"]:
        counts = s["counts"]
        good = c(f"{s['acceptable']:.0%}", _G)
        print()
        print(f"  {c('as good or better', _B)}   {good}   "
              + c(f"({counts['better']} better, {counts['same']} same)", _DIM))
        if counts["worse"]:
            print(f"  {c('worse', _Y)}               {s['worse_rate']:.0%}   "
                  + c(f"({counts['worse']} of {s['judged']})", _DIM))
        if s["factor"] > 1:
            print(f"  cost                {s['factor']:.1f}x less than the "
                  f"baseline on the same requests")

        if s["by_lane"]:
            print(f"\n{_rule('by request type')}")
            for name, b in sorted(s["by_lane"].items(),
                                  key=lambda kv: -kv[1]["n"]):
                ok = (b["better"] + b["same"]) / b["n"] if b["n"] else 0
                flag = c("  <-- check this", _Y) if ok < 0.8 and b["n"] >= 5 else ""
                print(f"  {name:<12}{b['n']:>5}   {ok:.0%} acceptable{flag}")

        print()
        print("  " + c(audit.headline(s), _DIM))
    else:
        print()
        print("  " + c("run `lane audit --judge` to grade them", _DIM))

    if args.show:
        for row in rows[-args.show:]:
            print()
            print(_rule(f"{row.get('lane','?')} \u00b7 {row.get('verdict') or 'unjudged'}"))
            print(f"  {c('asked', _DIM)}  {row.get('request','')[:200]}")
            print(f"  {c(row['routed']['model'], _B)}  "
                  f"{row['routed']['text'][:300]}")
            print(f"  {c(row['base']['model'], _DIM)}  "
                  f"{row['base']['text'][:300]}")
    print()
    return 0




# ── lane audit — the trail ───────────────────────────────────────────────────

def cmd_audit(args) -> int:
    """Who did what, and whether the record has been altered since."""
    if args.verify or args.seal:
        v = trail.verify()
        print()
        if v["ok"]:
            print(f"  {c('chain intact', _G)} - {v['entries']} entries")
            if args.seal:
                print()
                print("  " + c("head hash - record this somewhere LANE cannot "
                               "reach:", _DIM))
                print(f"  {c(v['head'], _B)}")
                print()
                print("  " + c("Anyone who can write the file can also append "
                               "to it, and truncating", _DIM))
                print("  " + c("the end leaves a chain that still verifies. A "
                               "hash held elsewhere", _DIM))
                print("  " + c("makes that truncation provable.", _DIM))
        else:
            print(f"  {c('CHAIN BROKEN', _RED)} - {v['message']}")
            print(f"  {c('reason: ' + v['reason'], _DIM)}")
        print()
        return 0 if v["ok"] else 1

    rows = trail.read()
    if args.actor:
        rows = [r for r in rows if r.get("actor") == args.actor]
    if args.action:
        rows = [r for r in rows if str(r.get("action", "")).startswith(args.action)]

    if not rows:
        print()
        print("  nothing recorded yet.")
        print("  " + c("the trail fills as teams are created, keys rotated, "
                       "budgets changed", _DIM))
        print("  " + c("and requests served.", _DIM))
        print()
        return 0

    shown = rows[-args.n:]
    print()
    print(_rule(f"audit trail \u00b7 last {len(shown)} of {len(rows)}"))
    for r in shown:
        if "_corrupt" in r:
            print(f"  {c('CORRUPT LINE', _RED)} {r['_corrupt'][:70]}")
            continue
        when = str(r.get("iso", ""))[:19].replace("T", " ")
        actor = str(r.get("actor", "?"))[:14]
        tone = _RED if str(r.get("action", "")).startswith(("auth.", "request.refused")) else _DIM
        print(f"  {c(str(r.get('seq', '')).rjust(4), _DIM)} "
              f"{c(when, _DIM)}  {c(actor.ljust(14), tone)} "
              f"{trail.describe(r)}")

    v = trail.verify()
    print()
    print("  " + (c(f"chain intact ({v['entries']} entries)", _G) if v["ok"]
                  else c("CHAIN BROKEN - " + v["message"], _RED)))
    print("  " + c("prompts are never recorded here - only who, when and "
                   "what.", _DIM))
    print()
    return 0 if v["ok"] else 1


# ── lane team / lane spend ───────────────────────────────────────────────────

def _bar(fraction: float, width: int = 22) -> str:
    filled = max(0, min(width, round(fraction * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)


def cmd_team(args) -> int:
    action = args.action or "list"

    if action == "list":
        rows = teams.all_teams()
        if not rows:
            print()
            print("  no teams yet — LANE is in single-user mode and accepts "
                  "any request.")
            print("  " + c("create one and it starts requiring a key:", _DIM))
            print("  " + c("lane team add Engineering --budget 500", _B))
            print()
            return 0

        print()
        print(_rule("teams"))
        for t in rows:
            st = teams.status(t["id"])
            mark = c("\u25cf", _G) if not st["disabled"] else c("\u25cb", _RED)
            role = st.get("role", teams.MEMBER)
            tone = _Y if role == teams.ADMIN else _DIM
            print(f"  {mark} {st['name']}  {c('(' + st['id'] + ')', _DIM)}"
                  f"  {c(role, tone)}")
            if st.get("allowed_models"):
                print(f"      {c('limited to: ' + ', '.join(st['allowed_models'][:3]), _DIM)}")
            if st["budget"]:
                pct = st["fraction"]
                tone = _RED if pct >= 1 else (_Y if pct >= 0.8 else _G)
                kind = "hard" if st["hard"] else "soft"
                print(f"      {c(_bar(pct), tone)} "
                      f"{ledger.money(st['spent'])} of "
                      f"{ledger.money(st['budget'])} {st['period']} "
                      f"{c('(' + kind + ')', _DIM)}")
                if st["over"]:
                    word = "blocked" if st["hard"] else "over, still allowed"
                    print(f"      {c(word, _RED if st['hard'] else _Y)}")
            else:
                print(f"      {ledger.money(st['spent'])} spent  "
                      + c("no budget set", _DIM))
        print()
        return 0

    if action == "add":
        if not args.name:
            print("give the team a name: lane team add Engineering")
            return 2
        try:
            team, key = teams.create(
                args.name, budget=args.budget or 0.0,
                period=args.period, hard=not args.soft,
                role=args.role or teams.MEMBER)
        except ValueError as exc:
            print(c(str(exc), _RED))
            return 1

        trail.record(trail.TEAM_CREATED, target=team["id"],
                     detail={"budget": team["budget"], "period": team["period"],
                             "hard": team["hard"], "role": team["role"]})
        print()
        print(f"  {c('created', _G)} {team['name']}  "
              + c("(" + team["id"] + ")", _DIM)
              + c("  role: " + team["role"], _DIM))
        if team["budget"]:
            kind = "hard - requests are refused at the limit" if team["hard"] \
                else "soft - requests are allowed, but flagged"
            print(f"  budget  {ledger.money(team['budget'])} "
                  f"{team['period']}  {c(kind, _DIM)}")
        print()
        print(_rule("their key - shown once, never again"))
        print()
        print(f"  {c(key, _B)}")
        print()
        print("  " + c("LANE stores only a hash of this. Lose it and the only "
                       "way back is", _DIM))
        print("  " + c(f"`lane team rotate {team['id']}`, which invalidates "
                       f"this one immediately.", _DIM))
        print()
        print(_rule("what they do with it"))
        print(f"  OPENAI_BASE_URL=http://{config.get('host')}:"
              f"{config.get('port')}/v1")
        print(f"  OPENAI_API_KEY={key}")
        print()
        print("  " + c("They never hold a provider key. Revoking this one "
                       "affects nobody else.", _DIM))
        print()
        return 0

    if not args.name:
        print(f"which team? lane team {action} <id>")
        return 2
    team_id = teams.slug(args.name)

    if action == "rotate":
        try:
            key = teams.rotate(team_id)
        except KeyError:
            print(c(f"no team {team_id!r}", _RED))
            return 1
        trail.record(trail.KEY_ROTATED, target=team_id)
        print()
        print(f"  {c('rotated', _G)} - the previous key stopped working now.")
        print(f"  {c(key, _B)}")
        print()
        return 0

    if action == "budget":
        if args.budget is None:
            print("how much? lane team budget engineering 500")
            return 2
        try:
            t = teams.set_budget(team_id, budget=args.budget,
                                 period=args.period,
                                 hard=(None if args.soft is None else not args.soft))
        except (KeyError, ValueError) as exc:
            print(c(str(exc), _RED))
            return 1
        trail.record(trail.BUDGET_CHANGED, target=team_id,
                     detail={"budget": t["budget"], "period": t["period"],
                             "hard": t["hard"]})
        print(f"{c('set', _G)} {t['name']}: {ledger.money(t['budget'])} "
              f"{t['period']} ({'hard' if t['hard'] else 'soft'})")
        return 0

    if action == "role":
        if not args.role:
            print(f"which role? one of {', '.join(teams.ROLES)}")
            return 2
        try:
            t = teams.set_role(team_id, args.role)
        except (KeyError, ValueError) as exc:
            print(c(str(exc), _RED))
            return 1
        trail.record(trail.ROLE_CHANGED, target=team_id,
                     detail={"role": t["role"]})
        print(f"{c('set', _G)} {t['name']} role to {t['role']}")
        return 0

    if action == "models":
        allowed = [m for m in (args.models or "").split(",") if m.strip()]
        known = {m.id for m in catalog.all_models()}
        unknown = [m for m in allowed if m not in known]
        if unknown:
            print(c(f"not in the catalog: {', '.join(unknown)}", _RED))
            return 1
        try:
            t = teams.set_allowed_models(team_id, allowed)
        except KeyError:
            print(c(f"no team {team_id!r}", _RED))
            return 1
        trail.record(trail.MODELS_RESTRICTED, target=team_id,
                     detail={"allowed": allowed})
        if allowed:
            print(f"{c('restricted', _G)} {t['name']} to "
                  f"{len(allowed)} model(s)")
        else:
            print(f"{c('cleared', _G)} the model restriction on {t['name']}")
        return 0

    if action in ("disable", "enable"):
        try:
            t = teams.set_disabled(team_id, action == "disable")
        except KeyError:
            print(c(f"no team {team_id!r}", _RED))
            return 1
        trail.record(trail.TEAM_DISABLED if action == "disable"
                     else trail.TEAM_ENABLED, target=team_id)
        print(f"{c(action + 'd', _G)} {t['name']}")
        return 0

    if action in ("rm", "remove", "delete"):
        if teams.remove(team_id):
            trail.record(trail.TEAM_REMOVED, target=team_id)
            print(f"removed {team_id} - its key no longer works")
            print(c("  past spend stays in the ledger for the record", _DIM))
            return 0
        print(c(f"no team {team_id!r}", _RED))
        return 1

    print(f"unknown action {action!r}")
    return 2


def cmd_spend(args) -> int:
    """Where the money went, by team. The report a finance owner asks for."""
    rows = teams.all_teams()
    s = ledger.stats(args.days, source="proxy")
    audit_total = ledger.stats(args.days, source="audit")["total"]

    print()
    window = f"last {args.days:g} days" if args.days else "all time"
    print(_rule(f"spend \u00b7 {window}"))

    if not rows:
        t = s["total"]
        print(f"  {ledger.money(t['cost'])} over {t['requests']:,} requests")
        print("  " + c("no teams configured - nothing to attribute it to.",
                       _DIM))
        print("  " + c("lane team add Engineering --budget 500", _B))
        print()
        return 0

    total = 0.0
    for t in rows:
        st = teams.status(t["id"])
        by = s["by_team"].get(t["id"], {"requests": 0, "cost": 0.0,
                                        "saved": 0.0})
        total += by["cost"]
        pct = st["fraction"]
        tone = _RED if pct >= 1 else (_Y if pct >= 0.8 else _G)

        print(f"  {c(st['name'], _B)}")
        line = (f"      {by['requests']:>6,} requests   "
                f"{ledger.money(by['cost']):>10}")
        if by["saved"] > 0:
            line += c(f"   saved {ledger.money(by['saved'])}", _G)
        print(line)
        if st["budget"]:
            print(f"      {c(_bar(pct), tone)} {pct:.0%} of "
                  f"{ledger.money(st['budget'])} {st['period']}")

    print()
    print(f"  {'total':<10}{ledger.money(total)}")
    if audit_total["cost"]:
        print(f"  {'audit':<10}{ledger.money(audit_total['cost'])}  "
              + c("shadow calls, billed separately", _DIM))
    if s["total"]["saved"] > 0:
        print(f"  {c('saved', _G):<19}"
              f"{c(ledger.money(s['total']['saved']), _G)}  "
              + c(f"vs {config.get('baseline_model')} throughout", _DIM))
    print()
    return 0


# ── lane config / doctor ─────────────────────────────────────────────────────

def cmd_config(args) -> int:
    if args.key and args.value is not None:
        try:
            config.set(args.key, config.coerce(args.key, args.value))
        except KeyError as exc:
            print(c(str(exc), _RED))
            return 2
        print(f"{c('set', _G)} {args.key} = {config.get(args.key)}")
        return 0
    if args.key:
        print(config.get(args.key))
        return 0

    print()
    print(_rule("settings"))
    current = config.all()
    for k in config.DEFAULTS:
        v = current.get(k)
        shown = json.dumps(v) if isinstance(v, (list, dict)) else v
        changed = "" if v == config.DEFAULTS[k] else c("  (changed)", _DIM)
        print(f"  {k:<24}{shown}{changed}")
    print(f"\n  {c('config file: ' + str(config.CONFIG_FILE), _DIM)}")
    print(f"  {c('change with: lane config <key> <value>', _DIM)}\n")
    return 0


def cmd_doctor(args) -> int:
    print()
    print(_rule("lane doctor"))
    ok = True

    have = keys.present()
    if have:
        print(f"  {c('✓', _G)} keys for: {', '.join(have)}")
    else:
        ok = False
        print(f"  {c('✗', _RED)} no API keys. Run: "
              f"{c('lane keys set anthropic', _B)}")

    if not keys.keyring_available():
        print(f"  {c('!', _Y)} no system keyring — keys must come from "
              f"environment variables")

    usable = catalog.usable()
    if usable:
        print(f"  {c('✓', _G)} {len(usable)} routable models "
              f"({len(catalog.all_models())} in catalog)")
    else:
        ok = False
        print(f"  {c('✗', _RED)} no routable models")

    hidden = catalog.unavailable_ids()
    if hidden:
        print(f"  {c('!', _Y)} {len(hidden)} model(s) hidden by a previous "
              f"sync: {', '.join(sorted(hidden)[:4])}")

    unverified = [p for p in have if not catalog.pricing_verified(p)]
    if unverified:
        print(f"  {c('!', _Y)} unverified pricing for "
              f"{', '.join(unverified)} — savings figures are estimates")

    for lane_name in lanes.LANES:
        try:
            d = policy.choose(lane_name, prompt_tokens=500)
            flag = c(" degraded", _Y) if d.degraded else ""
            print(f"    {lane_name:<11}→ {d.model.display}{flag}")
        except policy.NoModelAvailable as exc:
            ok = False
            print(f"    {lane_name:<11}→ {c(str(exc), _RED)}")

    base = policy.baseline_model()
    if base is None:
        print(f"  {c('!', _Y)} baseline model "
              f"{config.get('baseline_model')!r} is not in the catalog — "
              f"savings will read as zero")

    print(f"\n  {c('state: ' + str(config.HOME), _DIM)}")
    print(f"  {c('ok' if ok else 'problems above', _G if ok else _Y)}\n")
    return 0 if ok else 1


def cmd_serve(args) -> int:
    from . import server
    host = args.host or config.get("host")
    port = args.port or config.get("port")
    n = len(catalog.usable())

    print()
    print(f"  {c('L.A.N.E.', _B)}  listening on "
          f"{c(f'http://{host}:{port}/v1', _B)}")
    print(f"  {n} routable model(s), default mode "
          f"{c(config.get('mode'), _B)}")

    # Say this loudly. Creating a single team switches authentication on for
    # everything, and the symptom - every request suddenly 401s - looks like a
    # broken install rather than a setting somebody chose.
    if teams.enabled():
        names = ", ".join(t["id"] for t in teams.all_teams()[:4])
        print(f"  {c('team keys required', _Y)} - "
              f"{len(teams.all_teams())} team(s): {names}")
        print("  " + c("requests without an Authorization: Bearer "
                       "lane-sk-... header will get 401.", _DIM))
        print("  " + c("remove every team to go back to open mode.", _DIM))
    if not n:
        print(f"  {c('no keys yet — run `lane keys set anthropic`', _Y)}")
    print()
    print(f"  {c('point any OpenAI client at it:', _DIM)}")
    print(f"    export OPENAI_BASE_URL=http://{host}:{port}/v1")
    print(f"    {c('and use model', _DIM)} auto {c('or', _DIM)} lane-save")
    print()
    try:
        server.run(host=host, port=port, reload=args.reload)
    except KeyboardInterrupt:
        print("\n  stopped\n")
    return 0


# ── argument parsing ─────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lane",
        description="L.A.N.E. — Language Agent Network Exchange. "
                    "A local proxy that sends each prompt to the model that "
                    "should answer it.")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="run the local proxy")
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--reload", action="store_true",
                   help="restart on code changes (development)")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("why", help="explain where a prompt would be routed")
    s.add_argument("prompt", nargs="*")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_why)

    s = sub.add_parser("keys", help="manage provider API keys")
    s.add_argument("action", nargs="?",
                   choices=["list", "set", "rm", "delete", "remove"])
    s.add_argument("provider", nargs="?", choices=list(keys.PROVIDERS))
    s.add_argument("value", nargs="?",
                   help="the key itself; omit to be prompted without echo")
    s.add_argument("--visible", action="store_true",
                   help="show the key as you paste it — for terminals that "
                        "will not paste into a hidden prompt")
    s.set_defaults(func=cmd_keys)

    s = sub.add_parser("models", help="show the catalog")
    s.add_argument("--sync", action="store_true",
                   help="ask each provider which models your key can reach")
    s.set_defaults(func=cmd_models)

    s = sub.add_parser("stats", help="what you spent, and what you saved")
    s.add_argument("--days", type=float, default=None)
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("tail", help="the most recent requests")
    s.add_argument("-n", type=int, default=20)
    s.set_defaults(func=cmd_tail)

    s = sub.add_parser("config", help="show or change settings")
    s.add_argument("key", nargs="?")
    s.add_argument("value", nargs="?")
    s.set_defaults(func=cmd_config)

    s = sub.add_parser(
        "quality",
        help="prove the cheap route was good enough, on your own traffic")
    s.add_argument("--judge", action="store_true",
                   help="grade the sampled pairs with the judge model")
    s.add_argument("--show", type=int, default=0, metavar="N",
                   help="print the last N pairs in full")
    s.set_defaults(func=cmd_quality)

    s = sub.add_parser("audit", help="the tamper-evident record of who did what")
    s.add_argument("-n", type=int, default=30, help="how many entries to show")
    s.add_argument("--verify", action="store_true",
                   help="check the hash chain and report where it breaks")
    s.add_argument("--seal", action="store_true",
                   help="print the head hash, to be recorded off-machine")
    s.add_argument("--actor", help="only entries by this team or actor")
    s.add_argument("--action", help="only actions with this prefix, e.g. key.")
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("team", help="issue keys, set budgets, see who spent what")
    s.add_argument("action", nargs="?",
                   choices=["list", "add", "rotate", "budget", "role",
                            "models", "disable", "enable", "rm", "remove",
                            "delete"])
    s.add_argument("name", nargs="?", help="team name, or id for later actions")
    s.add_argument("budget", nargs="?", type=float,
                   help="budget in USD, for add and budget")
    s.add_argument("--budget", dest="budget", type=float,
                   help=argparse.SUPPRESS)
    s.add_argument("--period", default=teams.MONTHLY, choices=list(teams.PERIODS))
    s.add_argument("--soft", action="store_const", const=True, default=None,
                   help="warn at the limit instead of refusing")
    s.add_argument("--role", choices=list(teams.ROLES),
                   help="member sends requests, viewer only reads reports, "
                        "admin does both")
    s.add_argument("--models", help="comma-separated model ids this team may "
                                    "use; empty clears the restriction")
    s.set_defaults(func=cmd_team)

    s = sub.add_parser("spend", help="what each team spent, and against what budget")
    s.add_argument("--days", type=float, default=None)
    s.set_defaults(func=cmd_spend)

    s = sub.add_parser("doctor", help="check the installation")
    s.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
