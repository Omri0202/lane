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

from . import catalog, classify, config, keys, ledger, lanes, policy, providers

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
        value = args.value
        if not value:
            import getpass
            value = getpass.getpass(
                f"paste your {keys.PROVIDERS[args.provider]['name']} key "
                f"(hidden): ").strip()
        if not value:
            print("nothing entered")
            return 2
        try:
            where = keys.set(args.provider, value)
        except (KeyError, RuntimeError) as exc:
            print(c(str(exc), _RED))
            return 1
        print(f"{c('saved', _G)} {args.provider} key to {where}")
        return 0

    if args.action in ("rm", "delete", "remove"):
        if keys.delete(args.provider):
            print(f"removed {args.provider} key")
            return 0
        print(f"no stored {args.provider} key to remove")
        return 1
    return 2


# ── lane models ──────────────────────────────────────────────────────────────

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
        missing = sorted(mine - live)
        extra = sorted(live - known)
        unreachable += missing
        discovered += [(provider, m) for m in extra]
        print(f"  {c('✓', _G)} {provider}: {len(live)} models offered, "
              f"{len(mine & live)} of yours reachable")

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

    unverified = [p for p in ("anthropic", "openai", "google")
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

def cmd_stats(args) -> int:
    s = ledger.stats(args.days)
    t = s["total"]

    if not t["requests"]:
        print(f"\n  nothing recorded yet"
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
