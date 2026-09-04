"""
server.py — the local OpenAI-compatible front door.

Anything that speaks OpenAI speaks to LANE: point `base_url` at
http://127.0.0.1:8080/v1 and change nothing else. The client keeps thinking it
is talking to one model; LANE decides which one that actually is, per request.

The `model` field is how the client asks for a routing behaviour:

    auto            route using the configured default mode
    lane-save       route, minimising cost
    lane-balanced   route, maximising capability per dollar
    lane-perf       route, maximising capability
    lane-reasoning  skip the classifier, force this lane, route within it
    claude-opus-5   no routing at all — send it there, but still meter it

That last row matters. A router that cannot be switched off is a router people
work around. An explicit model id is an explicit instruction and is obeyed.

Every response carries x-lane-* headers saying what was chosen and why, so a
user never has to wonder which model answered them.
"""

from __future__ import annotations

import json
import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import (audit, catalog, classify, config, keys, ledger, lanes,
               policy, providers, teams, trail)
from .lanes import Lane
from .providers import ProviderError

app = FastAPI(title="L.A.N.E.", version="0.1.0",
              description="Language Agent Network Exchange")

#: Aliases a client can put in the `model` field. Anything not listed here and
#: not a known catalog id is treated as "route it" rather than rejected —
#: refusing an unknown model name would break clients that hard-code one.
_MODE_ALIASES = {
    "lane-save": config.MODE_SAVE, "lane:save": config.MODE_SAVE,
    "save": config.MODE_SAVE, "lane-cheap": config.MODE_SAVE,
    "lane-balanced": config.MODE_BALANCED, "lane:balanced": config.MODE_BALANCED,
    "balanced": config.MODE_BALANCED,
    "lane-performance": config.MODE_PERFORMANCE,
    "lane-perf": config.MODE_PERFORMANCE, "lane:performance": config.MODE_PERFORMANCE,
    "performance": config.MODE_PERFORMANCE, "lane-best": config.MODE_PERFORMANCE,
}

_AUTO = {"auto", "lane", "lane-auto", "router", "default"}

_RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def _parse_model_field(raw: str) -> tuple[str | None, str | None, str | None]:
    """(mode, forced_lane, pinned_model_id) — at most one is not None."""
    name = (raw or "auto").strip()
    low = name.lower()

    if low in _AUTO:
        return None, None, None
    if low in _MODE_ALIASES:
        return _MODE_ALIASES[low], None, None
    if low.startswith(("lane-", "lane:")):
        candidate = low[5:]
        if candidate in lanes.LANES:
            return None, candidate, None
    if catalog.by_id(name):
        return None, None, name
    # An id LANE has never heard of. It may still be real — the catalog is
    # allowed to be incomplete — so pin it and let the provider decide.
    if "/" in name or "-" in name:
        return None, None, name
    return None, None, None


def _error(status: int, message: str, kind: str = "invalid_request_error"):
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": kind, "code": None}})


def _header_safe(text: str, limit: int = 180) -> str:
    """HTTP headers are latin-1. Any character outside it raises on send.

    Reasons are written for people, and people get em-dashes, curly quotes and
    accents. One of those reaching x-lane-reason did not produce a formatting
    blemish - it produced a 500 on the proxy's happy path, for every response
    that carried it. Sanitising here rather than policing the wording makes the
    failure impossible instead of merely unlikely.
    """
    text = (text or "").replace("\n", " ").replace("\r", " ")
    for src, dst in (
            ("\u2014", "-"), ("\u2013", "-"),
            ("\u2018", "'"), ("\u2019", "'"),
            ("\u201c", '"'), ("\u201d", '"'),
            ("\u2026", "..."), ("\u00d7", "x"), ("\u2192", "->")):
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")[:limit]


def _headers(decision: policy.Decision) -> dict:
    if not config.get("report_headers"):
        return {}
    h = {
        "x-lane-model": decision.model.id,
        "x-lane-provider": decision.model.provider,
        "x-lane-lane": decision.lane,
        "x-lane-mode": decision.mode,
        "x-lane-tier": str(decision.tier),
        "x-lane-reason": _header_safe(decision.reason),
    }
    if decision.degraded:
        h["x-lane-degraded"] = _header_safe(decision.degraded_note)
    return h


def _pinned_decision(model_id: str, messages, tools) -> policy.Decision:
    """A client that named a model gets that model. It is still classified, so
    the ledger can report what routing WOULD have done — which is the only way
    a user can judge whether to stop pinning."""
    m = catalog.by_id(model_id)
    if m is None:
        # Unknown to the catalog: route it anyway, but with zero prices so no
        # invented cost enters the ledger.
        m = catalog.Model(id=model_id, provider=_guess_provider(model_id),
                          display=model_id, tier=0, in_price=0.0,
                          out_price=0.0, context=200_000, max_output=8192)
    verdict = classify.classify(messages, tools=tools)
    return policy.Decision(
        model=m, lane=verdict["lane"], mode="pinned",
        reason="you named this model explicitly",
        tier="pinned", margin=verdict["margin"],
        est_prompt_tokens=policy.estimate_tokens(messages))


def _guess_provider(model_id: str) -> str:
    low = model_id.lower()
    if low.startswith("claude"):
        return "anthropic"
    if low.startswith("gemini"):
        return "google"
    return "openai"


#: What a lane needs, said the way somebody typing into a chat box would say
#: it. Used only when nothing they own can serve the request.
_NEED_PHRASE = {
    Lane.IMAGE_GEN: "a model that makes images",
    Lane.VISION: "a model that reads images",
    Lane.TOOLS: "a model that can call tools",
    Lane.WEB_SEARCH: "a model that can search the web",
}


def _capability_offer(lane: str, prompt_tokens: int = 0) -> dict | None:
    """Who could serve this, that the user has not given LANE a key for?

    Returned instead of a bare failure. Somebody who asks for a picture and
    gets "no available model can serve an image request" has learned nothing
    they can act on; the useful answer names the model that can do it, what it
    costs, and where to get the key — and then the same request works next
    time. That loop is the product, and a 503 is the point it breaks.

    None when the gap is not about capability at all, in which case the plain
    error is the honest answer.
    """
    need = lanes.needs(lane)
    kind = lanes.kind(lane)

    def serves(m) -> bool:
        if m.kind != kind:
            return False
        return all(getattr(m, cap, False) for cap in need)

    # Only models they cannot reach today are worth offering.
    have = set(keys.present())
    candidates = [m for m in catalog.all_models()
                  if serves(m) and m.provider not in have]
    if not candidates:
        return None

    out_tokens = lanes.expected_output(lane)
    best_per_provider: dict[str, dict] = {}
    for m in sorted(candidates, key=lambda x: -x.tier):
        meta = keys.PROVIDERS.get(m.provider) or {}
        row = best_per_provider.setdefault(m.provider, {
            "provider": m.provider,
            "provider_name": meta.get("name", m.provider),
            "console": meta.get("console", ""),
            "models": [],
        })
        if len(row["models"]) < 2:
            row["models"].append({
                "id": m.id, "display": m.display,
                "cost": round(m.cost_for(prompt_tokens, out_tokens), 6),
                "per_image": m.kind == "image",
            })

    return {
        "lane": lane,
        "lane_label": lanes.label(lane),
        "need": _NEED_PHRASE.get(lane, f"a model for {lanes.label(lane).lower()}"),
        "providers": list(best_per_provider.values()),
        "setup_url": f"http://{config.get('host')}:{config.get('port')}/setup",
    }


async def _call(decision: policy.Decision, body: dict, usage: dict):
    """Non-streaming call through the right adapter."""
    adapter = providers.get(decision.model.provider)
    key = keys.get(decision.model.provider)
    if not key:
        raise ProviderError(decision.model.provider, 401,
                            f"no API key for {decision.model.provider} — "
                            f"run: lane keys set {decision.model.provider}")
    kwargs = {}
    if decision.model.provider == "anthropic":
        kwargs["allow_sampling"] = decision.model.sampling
    result = await adapter.complete(body, decision.model.id, key, **kwargs)
    u = result.get("usage") or {}
    usage["in"] = int(u.get("prompt_tokens") or 0)
    usage["out"] = int(u.get("completion_tokens") or 0)
    return result


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    started = time.perf_counter()
    try:
        body = await request.json()
    except Exception:
        return _error(400, "request body is not valid JSON")
    if not isinstance(body, dict):
        return _error(400, "request body must be a JSON object")

    messages = body.get("messages") or []
    tools = body.get("tools")
    stream = bool(body.get("stream"))
    budget_note = ""

    mode, forced_lane, pinned = _parse_model_field(body.get("model", "auto"))
    header_mode = request.headers.get("x-lane-mode")
    if header_mode in config.MODES:
        mode = header_mode

    # Identify the caller BEFORE routing, because a team's model restriction
    # changes which models the router is allowed to consider. Applying it
    # afterwards would mean refusing a request the router could have served
    # from the permitted set — a policy that produces errors instead of
    # alternatives is a policy that gets switched off.
    team = None
    if teams.enabled():
        team = teams.authenticate(request.headers.get("authorization"))
        if team is None:
            trail.record(trail.AUTH_FAILED, actor="unknown")
            return _error(
                401,
                "this LANE requires a team key. Ask whoever runs it for one, "
                "and send it as `Authorization: Bearer lane-sk-...`.",
                "authentication_error")
        if not teams.can(team, "infer"):
            trail.record(trail.REQUEST_REFUSED, actor=team["id"],
                         detail={"why": f"role {team.get('role')} cannot infer"})
            return _error(
                403,
                f"the {team.get('name', team['id'])} key has the "
                f"{team.get('role', 'member')} role, which can read reports "
                f"but not send requests.",
                "permission_denied")

    pool = teams.permitted(team, catalog.usable()) if team else None
    if pool is not None and not pool:
        return _error(
            503,
            f"{team.get('name', team['id'])} is restricted to models LANE "
            f"cannot currently reach. Check `lane team list` and `lane doctor`.",
            "service_unavailable")

    try:
        if pinned:
            decision = _pinned_decision(pinned, messages, tools)
            if pool is not None and decision.model.id not in {m.id for m in pool}:
                return _error(
                    403,
                    f"{team.get('name', team['id'])} is not permitted to use "
                    f"{decision.model.id}.", "permission_denied")
        else:
            decision = policy.route(
                messages, tools=tools, mode=mode, forced_lane=forced_lane,
                want_output=int(body.get("max_tokens") or 1024), models=pool)
    except policy.NoModelAvailable as exc:
        # Before reporting a dead end, check whether it is really a capability
        # gap — something they could fix by adding one key.
        verdict = classify.classify(messages, tools=tools)
        offer = _capability_offer(verdict["lane"],
                                  policy.estimate_tokens(messages))
        if offer:
            names = ", ".join(p["provider_name"] for p in offer["providers"])
            payload = {
                "error": {
                    "message": f"None of your models can do this — it needs "
                               f"{offer['need']}. {names} can.",
                    "type": "capability_unavailable", "code": None},
                "lane": offer,
            }
            return JSONResponse(status_code=503, content=payload)
        return _error(503, str(exc), "service_unavailable")

    if teams.enabled():

        # Charge the estimate against the budget BEFORE calling, so a ceiling
        # cannot be stepped over by one large request. A budget crossed once
        # per period is not a ceiling.
        estimate = decision.model.cost(decision.est_prompt_tokens,
                                       int(body.get("max_tokens") or 1024))
        ok, note = teams.check(team, estimate)
        if not ok:
            trail.record(trail.REQUEST_REFUSED, actor=team["id"],
                         target=decision.model.id,
                         detail={"why": "over budget", "lane": decision.lane})
            return _error(402, note, "budget_exceeded")
        if note:
            budget_note = note

    guard = config.get("max_cost_per_request") or 0.0
    if guard:
        worst = decision.model.cost(decision.est_prompt_tokens,
                                    int(body.get("max_tokens") or 1024))
        if worst > guard:
            return _error(
                402,
                f"this request could cost up to {ledger.money(worst)} on "
                f"{decision.model.display}, over your "
                f"{ledger.money(guard)} per-request limit. Raise it with "
                f"`lane config set max_cost_per_request <amount>` or 0 to "
                f"disable.", "cost_limit_exceeded")

    team_id = team["id"] if team else None
    if stream:
        return await _stream_response(decision, body, started, team=team_id)
    return await _json_response(decision, body, started, team=team_id)


_MAX_ATTEMPTS = 3


async def _json_response(decision: policy.Decision, body: dict,
                         started: float, team: str | None = None):
    """Call the chosen model, routing around providers that turn out to be dead.

    Three distinct failure kinds, three different responses:

      provider-fatal   A bad key, an empty credit balance, a suspended account.
                       Not a property of the request, so retrying a different
                       model owned by the same account is pure waste. The whole
                       PROVIDER is excluded and the lane is re-chosen without
                       it.
      transient        Overloaded, rate-limited, a gateway blip. Worth another
                       model's money.
      bad request      A 400 that means what it says. It will be a 400
                       everywhere; returned immediately.
    """
    usage: dict = {}
    dead_providers: set[str] = set()
    tried: list[str] = []
    last: ProviderError | None = None
    current = decision
    want_output = int(body.get("max_tokens") or 1024)

    for attempt in range(_MAX_ATTEMPTS):
        if attempt:
            pool = [m for m in catalog.usable()
                    if m.provider not in dead_providers and m.id not in tried]
            if not pool:
                break
            try:
                current = policy.choose(
                    decision.lane, mode=decision.mode, models=pool,
                    prompt_tokens=decision.est_prompt_tokens,
                    want_output=want_output)
            except policy.NoModelAvailable:
                break
            current.tier = decision.tier
            current.margin = decision.margin
            current.degraded = True
            current.degraded_note = (
                f"{', '.join(sorted(dead_providers))} unavailable"
                if dead_providers else "first choice was unavailable")

        model = current.model
        tried.append(model.id)
        try:
            result = await _call(current, body, usage)
        except ProviderError as exc:
            last = exc
            ledger.record(lane=current.lane, mode=current.mode,
                          model=model.id, provider=model.provider,
                          in_tokens=0, out_tokens=0, ok=False,
                          error=str(exc), tier=str(current.tier), team=team,
                          latency_ms=int((time.perf_counter() - started) * 1000))
            if exc.provider_fatal:
                dead_providers.add(model.provider)
                continue
            if exc.status not in _RETRYABLE:
                return _error(exc.status, str(exc), "upstream_error")
            continue

        ledger.record(lane=current.lane, mode=current.mode, model=model.id,
                      provider=model.provider,
                      in_tokens=usage.get("in", 0), out_tokens=usage.get("out", 0),
                      tier=str(current.tier), margin=current.margin, team=team,
                      latency_ms=int((time.perf_counter() - started) * 1000))
        if team:
            # Facts only. An audit log that accumulates the text of every
            # question anyone asked is a data-protection liability that grows
            # without bound.
            trail.record(trail.REQUEST_SERVED, actor=team,
                         target=model.id,
                         detail={"lane": current.lane, "model": model.id,
                                 "cost": round(model.cost(usage.get("in", 0),
                                                          usage.get("out", 0)), 8)})
        await _maybe_audit(current, body, result, usage, team=team)
        return JSONResponse(content=result, headers=_headers(current))

    if last and last.provider_fatal:
        # Say what to DO about it. "anthropic returned 400" sends people to
        # debug the proxy; naming the account problem and the escape hatch does
        # not.
        return _error(
            last.status,
            f"{str(last)} — every provider LANE could reach for this request "
            f"is unavailable. Turn one off permanently with: "
            f"lane config disabled_providers {','.join(sorted(dead_providers))}",
            "upstream_error")
    return _error(last.status if last else 502,
                  str(last) if last else "no provider answered",
                  "upstream_error")


async def _maybe_audit(decision: policy.Decision, body: dict,
                       result: dict, usage: dict,
                       team: str | None = None) -> None:
    """Answer the same request on the baseline model, for the record.

    Runs AFTER the user's answer is settled and never touches it. The point of
    the audit is to find out whether the cheap route was good enough; serving a
    slower or different answer in order to measure that would corrupt the thing
    being measured and annoy the person paying for it.

    Silent on every failure. An audit is bookkeeping — it must never be the
    reason a request the user already paid for looks broken.
    """
    try:
        base = policy.baseline_model()
        if base is None or base.id == decision.model.id:
            return
        text = classify.text_of(body.get("messages") or [])
        if not audit.should_sample(f"{decision.model.id}|{text}"):
            return

        key = keys.get(base.provider)
        if not key:
            return
        kwargs = {}
        if base.provider == "anthropic":
            kwargs["allow_sampling"] = base.sampling
        shadow = await providers.get(base.provider).complete(
            body, base.id, key, **kwargs)

        def answer(payload):
            try:
                return payload["choices"][0]["message"].get("content") or ""
            except Exception:
                return ""

        su = shadow.get("usage") or {}
        s_in = int(su.get("prompt_tokens") or 0)
        s_out = int(su.get("completion_tokens") or 0)
        r_in, r_out = usage.get("in", 0), usage.get("out", 0)

        audit.record(
            request=text, lane=decision.lane,
            routed_model=decision.model.id, routed_text=answer(result),
            routed_cost=decision.model.cost(r_in, r_out),
            routed_tokens=(r_in, r_out),
            base_model=base.id, base_text=answer(shadow),
            base_cost=base.cost(s_in, s_out), base_tokens=(s_in, s_out))
        # The shadow call is real money and belongs in the books like any
        # other, marked so it is never mistaken for traffic the user asked for.
        ledger.record(lane=decision.lane, mode="audit", model=base.id,
                      provider=base.provider, in_tokens=s_in, out_tokens=s_out,
                      source="audit", team=team)
    except Exception:
        pass


def _swap(decision: policy.Decision, model) -> policy.Decision:
    """The same decision, served by a fallback model."""
    return policy.Decision(
        model=model, lane=decision.lane, mode=decision.mode,
        reason=decision.reason + f"; fell back to {model.display}",
        tier=decision.tier, margin=decision.margin,
        degraded=True, degraded_note="first choice was unavailable",
        est_prompt_tokens=decision.est_prompt_tokens)


async def _open_stream(decision: policy.Decision, body: dict, usage: dict,
                       started: float, team: str | None = None):
    """Get a provider actually streaming, routing around ones that refuse.

    The subtlety is WHEN a stream can be abandoned. Once real content has
    reached the client, restarting on another model would splice two different
    answers together — so that is never done. But a provider that refuses at
    connection time has sent nothing at all, and treating that as unrecoverable
    was a plain mistake: it made a dead account fatal to every streamed
    request, which is every request a chat UI makes.

    So the upstream is opened and its first frame pulled BEFORE any response
    goes back. Failures up to that point are free to fall back. Failures after
    it are not, and are surfaced.

    Returns (decision, first_frame, generator). Raises if nothing will answer.
    """
    dead: set[str] = set()
    tried: list[str] = []
    current = decision
    last: ProviderError | None = None
    want_output = int(body.get("max_tokens") or 1024)

    for attempt in range(_MAX_ATTEMPTS):
        if attempt:
            pool = [m for m in catalog.usable()
                    if m.provider not in dead and m.id not in tried]
            if not pool:
                break
            try:
                current = policy.choose(
                    decision.lane, mode=decision.mode, models=pool,
                    prompt_tokens=decision.est_prompt_tokens,
                    want_output=want_output)
            except policy.NoModelAvailable:
                break
            current.tier, current.margin = decision.tier, decision.margin
            current.degraded = True
            current.degraded_note = (
                f"{', '.join(sorted(dead))} unavailable" if dead
                else "first choice was unavailable")

        model = current.model
        tried.append(model.id)
        key = keys.get(model.provider)
        if not key:
            last = ProviderError(model.provider, 401,
                                 f"no API key for {model.provider}")
            dead.add(model.provider)
            continue

        kwargs = {"usage": usage}
        if model.provider == "anthropic":
            kwargs["allow_sampling"] = model.sampling
        agen = providers.get(model.provider).stream(
            body, model.id, key, **kwargs)

        try:
            first = await agen.__anext__()
        except StopAsyncIteration:
            return current, None, agen          # empty but successful
        except ProviderError as exc:
            last = exc
            ledger.record(lane=current.lane, mode=current.mode, model=model.id,
                          provider=model.provider, in_tokens=0, out_tokens=0,
                          ok=False, error=str(exc), tier=str(current.tier),
                          streamed=True,
                          latency_ms=int((time.perf_counter() - started) * 1000))
            if exc.provider_fatal:
                dead.add(model.provider)
                continue
            if exc.status in _RETRYABLE:
                continue
            raise
        return current, first, agen

    raise last or ProviderError("lane", 502, "no provider answered")


async def _stream_response(decision: policy.Decision, body: dict,
                           started: float, team: str | None = None):
    usage: dict = {}
    try:
        current, first, agen = await _open_stream(decision, body, usage,
                                                  started, team=team)
    except ProviderError as exc:
        detail = str(exc)
        if exc.provider_fatal:
            detail += (" — every provider LANE could reach for this request "
                       "is unavailable")
        return _error(exc.status, detail, "upstream_error")

    async def body_iter():
        ok, err = True, ""
        try:
            if first is not None:
                yield first
            async for frame in agen:
                yield frame
        except ProviderError as exc:
            # Content is already on the wire; the only honest move is to say so
            # in-band rather than silently truncate.
            ok, err = False, str(exc)
            yield "data: " + json.dumps(
                {"error": {"message": str(exc), "type": "upstream_error"}}
            ) + "\n\ndata: [DONE]\n\n"
        finally:
            ledger.record(
                lane=current.lane, mode=current.mode,
                model=current.model.id, provider=current.model.provider,
                in_tokens=usage.get("in", 0), out_tokens=usage.get("out", 0),
                tier=str(current.tier), margin=current.margin, team=team,
                ok=ok, error=err, streamed=True,
                latency_ms=int((time.perf_counter() - started) * 1000))

    return StreamingResponse(
        body_iter(), media_type="text/event-stream",
        headers={**_headers(current), "Cache-Control": "no-cache",
                 "X-Accel-Buffering": "no"})


@app.get("/v1/models")
async def list_models():
    """Every routing alias plus every model LANE can actually reach.

    The aliases come first because they are what a user should normally pick;
    a model picker that lists forty models and no way to say "you choose" has
    missed the point of installing this.
    """
    now = int(time.time())
    rows = [{"id": alias, "object": "model", "created": now,
             "owned_by": "lane", "description": desc}
            for alias, desc in (
                ("auto", "LANE picks, using your default mode"),
                ("lane-save", "LANE picks the cheapest model that fits"),
                ("lane-balanced", "LANE picks the best value for the request"),
                ("lane-perf", "LANE picks the strongest model available"),
            )]
    rows += [{"id": f"lane-{name}", "object": "model", "created": now,
              "owned_by": "lane",
              "description": f"force the {spec['label'].lower()} lane"}
             for name, spec in lanes.LANES.items()]
    rows += [{"id": m.id, "object": "model", "created": now,
              "owned_by": m.provider, "description": m.display}
             for m in catalog.usable()]
    return {"object": "list", "data": rows}


@app.post("/lane/route")
async def dry_run(request: Request):
    """Classify and choose without spending anything. What `lane why` calls."""
    try:
        body = await request.json()
    except Exception:
        return _error(400, "request body is not valid JSON")

    messages = body.get("messages") or [
        {"role": "user", "content": body.get("prompt", "")}]
    mode, forced_lane, pinned = _parse_model_field(body.get("model", "auto"))
    if request.headers.get("x-lane-mode") in config.MODES:
        mode = request.headers["x-lane-mode"]

    verdict = classify.explain(messages, tools=body.get("tools"))
    out = {"classification": verdict, "choices": {}}
    for m in config.MODES:
        try:
            d = policy.choose(
                verdict["lane"], mode=m,
                prompt_tokens=policy.estimate_tokens(messages),
                want_output=int(body.get("max_tokens") or 1024))
            out["choices"][m] = d.as_dict()
        except policy.NoModelAvailable as exc:
            out["choices"][m] = {"error": str(exc)}
    out["default_mode"] = mode or config.get("mode")
    return out


#: Sites the advisor overlay runs on. CORS is granted to these and ONLY for
#: /lane/advise, which spends nothing — deliberately not for
#: /v1/chat/completions. A page that could reach the completions endpoint
#: cross-origin could spend the user's money without them asking.
_ADVISOR_ORIGINS = {
    "https://claude.ai", "https://www.claude.ai",
    "https://chatgpt.com", "https://chat.openai.com",
    "https://gemini.google.com", "https://aistudio.google.com",
}

#: Which provider's models a given site can actually offer you. Advising
#: "use GPT-OSS 20B" to somebody sitting in claude.ai is worse than useless —
#: it is advice they cannot take.
_SITE_PROVIDER = {
    "claude": "anthropic", "chatgpt": "openai", "gemini": "google",
}


def _cors(origin: str | None) -> dict:
    if origin in _ADVISOR_ORIGINS:
        return {"Access-Control-Allow-Origin": origin,
                "Access-Control-Allow-Headers": "content-type",
                "Access-Control-Allow-Methods": "POST, OPTIONS",
                "Vary": "Origin"}
    return {}


#: Which site a provider corresponds to, for the times the honest advice is
#: "not here".
_PROVIDER_SITE = {"anthropic": "Claude", "openai": "ChatGPT",
                  "google": "Gemini", "groq": "Groq", "openrouter": "OpenRouter"}


def _price(x: float) -> str:
    if x <= 0:
        return "free"
    if x < 0.01:
        return f"${x:.4f}"
    if x < 1:
        return f"${x:.3f}"
    return f"${x:,.2f}"


#: What is missing, phrased for somebody mid-sentence in a chat box.
_LACKS = {
    Lane.IMAGE_GEN: "No model here draws pictures - it can only read them.",
    Lane.VISION: "No model here reads images.",
    Lane.TOOLS: "No model here calls tools.",
    Lane.WEB_SEARCH: "No model here can search the web, so the answer would "
                     "come from memory.",
}


def _explain(lane: str, rec, top, factor: float, images: bool,
             elsewhere: list) -> str:
    """One sentence saying why this recommendation is the right one.

    The numbers are already on screen; this says what they MEAN. "Haiku, $0.0004"
    is a fact. "There is nothing here to reason about, so the difference buys
    you nothing" is a reason to click the dropdown.
    """
    if rec is None and elsewhere:
        first = elsewhere[0]
        lacks = _LACKS.get(lane, f"No model here handles "
                                 f"{lanes.label(lane).lower()} work.")
        unit = " an image" if images else ""
        return (f"{lacks} {first['site']} does this with "
                f"{first['display']} for about {_price(first['cost'])}{unit}.")
    if images and rec is not None:
        return (f"This needs an image generator, not a chat model. "
                f"{rec.display} is billed per picture, not per token.")

    if rec is not None and top is not None and rec.id == top.id:
        return ("Nothing cheaper clears the bar for this one — the strongest "
                "model is the right call.")

    by_lane = {
        "trivial": "There is nothing here to think about. The smallest model "
                   "produces the same reply for {factor}x less.",
        "simple": "This is recall, not reasoning. Every model knows it; only "
                  "one of them charges {factor}x more to say so.",
        "general": "An explanation, not a hard problem. The mid model reads "
                   "the same and costs {factor}x less.",
        "longform": "Judged on voice rather than correctness, where the gap "
                    "between models is smallest — and {factor}x cheaper.",
        "reasoning": "This one is worth capability, so the floor is high. Even "
                     "so, you do not need the very top: {factor}x less buys "
                     "the same answer.",
        "translate": "Translation into a major language is close to solved — "
                     "this is one of the few places where the cheap model is "
                     "not a compromise, and it is {factor}x less.",
        "web_search": "The answer is not in any model's training data, so make "
                      "sure web search is switched on. Once it is, the model "
                      "is summarising what it found rather than knowing it, "
                      "and {factor}x less does that just as well.",
        "vision": "Reading an image needs a vision model, and the cheapest "
                  "one that can see is {factor}x lighter than the best.",
        "tools": "Tool calls are judged on well-formed output, not "
                 "brilliance. {factor}x less gets you that.",
    }
    return by_lane.get(lane, "").format(factor=factor)


@app.options("/lane/advise")
async def advise_preflight(request: Request):
    return Response(status_code=204,
                    headers=_cors(request.headers.get("origin")))


@app.post("/lane/advise")
async def advise(request: Request):
    """What should the person typing this pick, and what will it cost them?

    Three things this answers that /lane/route does not.

    WHICH KIND of request it is, not merely how hard — "create a picture of
    Germany" is not a difficult text request, it is not a text request at all,
    and recommending a chat model for it is not a worse answer but an
    impossible one. When the current site cannot do the job, the right advice
    is to name the site that can.

    WHAT IT COSTS, per option, for this specific message — prompt tokens
    measured, reply length estimated from the lane, because output is priced
    four to five times higher than input and an estimate that ignored it would
    be wrong in the flattering direction every time.

    WHY, in a sentence. The numbers are already on screen; a person deciding
    whether to touch the dropdown needs to know what they mean.
    """
    cors = _cors(request.headers.get("origin"))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad json"}, status_code=400,
                            headers=cors)

    text = (body.get("text") or "").strip()
    site = body.get("site") or ""
    provider = _SITE_PROVIDER.get(site)
    messages = [{"role": "user", "content": text}]
    verdict = classify.classify(messages)
    lane = verdict["lane"]

    in_tokens = policy.estimate_tokens(messages)
    out_tokens = lanes.expected_output(lane)
    is_image = lanes.kind(lane) == "image"

    out = {
        "lane": lane,
        "lane_label": lanes.label(lane),
        "reason": verdict["reason"],
        "tier": verdict["tier"],
        "took_us": verdict["took_us"],
        "words": len(text.split()),
        "kind": lanes.kind(lane),
        "est_in": in_tokens,
        "est_out": out_tokens,
        "options": [],
        "elsewhere": [],
        #: True while nobody has said which models they can reach, so the
        #: advice covers the whole catalog and may name something their plan
        #: does not offer. Better to admit that than to let them discover it
        #: in a dropdown with no such entry.
        "assuming_all": not (config.get("enabled_models") or []),
    }

    # What THIS person can pick, not what exists in the world. Before anyone
    # has said otherwise this is still the whole catalog, so the advisor is
    # useful out of the box and gets sharper the moment they tell it.
    here = catalog.declared(provider)
    # A consumer site can only offer what its own menu lists. GPT-5 nano is a
    # real model at a real price that nobody will ever find on chatgpt.com,
    # and advising it there is advice that cannot be taken. The proxy is not
    # filtered this way - it calls the API, where these models do exist.
    if provider:
        here = [m for m in here if getattr(m, "picker", True)]

    def cost_of(m):
        return m.cost_for(in_tokens, out_tokens)

    # Can this site do the job at all?
    #
    # Two ways it cannot. The KIND can be wrong — no chat model draws, whatever
    # its capabilities. Or the kind is right and the capability is missing: the
    # site has chat models but none that reads an image, or none that can
    # search. Both end in the same advice, which is the name of a site that
    # can, so both are answered here rather than only the first.
    need = lanes.needs(lane)
    servable = [m for m in here
                if m.kind == lanes.kind(lane)
                and all(getattr(m, cap, False) for cap in need)]
    if not servable:
        # Name who can. This is the one case where recommending a different
        # site is help rather than a chore.
        for m in catalog.all_models():
            if m.kind != lanes.kind(lane):
                continue
            if not all(getattr(m, cap, False) for cap in need):
                continue
            out["elsewhere"].append({
                "site": _PROVIDER_SITE.get(m.provider, m.provider),
                "provider": m.provider, "id": m.id, "display": m.display,
                "cost": round(cost_of(m), 6)})
        out["elsewhere"].sort(key=lambda e: e["cost"])
        out["unavailable_here"] = True
        out["site_name"] = _PROVIDER_SITE.get(provider, site or "this site")
        out["explain"] = _explain(lane, None, None, 1.0, is_image,
                                  out["elsewhere"])
        return JSONResponse(out, headers=cors)

    out["unavailable_here"] = False
    seen = set()
    for mode in config.MODES:
        try:
            d = policy.choose(lane, mode=mode, models=here,
                              prompt_tokens=in_tokens,
                              want_output=max(out_tokens, 512))
        except policy.NoModelAvailable:
            continue
        row = {"mode": mode, "id": d.model.id, "display": d.model.display,
               "tier": d.model.tier, "degraded": d.degraded,
               "cost": round(cost_of(d.model), 6),
               "per_image": d.model.kind == "image",
               "fit": d.reason}
        out["options"].append(row)
        seen.add(d.model.id)

    top = max(servable, key=lambda m: m.tier)

    # THE TWO VARIATIONS. "save" is the reason most people install this; "best"
    # is the reason they keep it when the answer matters. They are named on the
    # wire rather than derived from a server setting, because the choice
    # belongs to whoever is typing, message by message.
    variation = (body.get("variation") or "save").lower()
    wanted_mode = (config.MODE_PERFORMANCE if variation in ("best", "performance")
                   else config.MODE_SAVE)
    out["variation"] = "best" if wanted_mode == config.MODE_PERFORMANCE else "save"

    rec_row = next((o for o in out["options"] if o["mode"] == wanted_mode),
                   out["options"][0] if out["options"] else None)
    rec = catalog.by_id(rec_row["id"]) if rec_row else top
    out["fit"] = rec_row.get("fit", "") if rec_row else ""

    rec_cost, top_cost = cost_of(rec), cost_of(top)
    factor = round(top_cost / rec_cost, 1) if rec_cost > 0 else 1.0

    out["recommend"] = {"id": rec.id, "display": rec.display, "tier": rec.tier,
                        "cost": round(rec_cost, 6),
                        "per_image": rec.kind == "image"}
    out["top"] = {"id": top.id, "display": top.display, "tier": top.tier,
                  "cost": round(top_cost, 6)}
    out["factor"] = factor
    out["is_top"] = rec.id == top.id
    out["saving"] = round(top_cost - rec_cost, 6)

    if out["variation"] == "best":
        # BEST must say what the extra money BUYS, and must not contradict what
        # SAVE says about the same message. Reusing the save wording here
        # produced "nothing cheaper clears the bar" on a request where the save
        # view had just named something cheaper that did — the two variations
        # disagreeing about the same sentence, in the same panel, one click
        # apart.
        save_row = next((o for o in out["options"]
                         if o["mode"] == config.MODE_SAVE), None)
        cheap = catalog.by_id(save_row["id"]) if save_row else None
        if cheap and cheap.id != rec.id and save_row["cost"] > 0:
            times = round(rec_cost / save_row["cost"], 1)
            out["explain"] = (
                f"{times}x the price of the cheapest model that would cope. "
                f"Worth it when the answer matters more than the bill; "
                f"switch to SAVE when it does not.")
        else:
            out["explain"] = ("The cheapest model that can do this is also the "
                              "one best suited to it — no trade-off here.")
    else:
        out["explain"] = _explain(lane, rec, top, factor, is_image, [])
    return JSONResponse(out, headers=cors)


@app.options("/lane/advice-log")
async def advice_log_preflight(request: Request):
    return Response(status_code=204,
                    headers=_cors(request.headers.get("origin")))


@app.post("/lane/advice-log")
async def advice_log(request: Request):
    """Record that one recommendation was actually made and read.

    Called when the message is SENT, never on every keystroke — the panel
    re-advises as you type, and counting those would turn one message into
    forty and make the headline number meaningless.

    What it stores is a POTENTIAL saving. LANE cannot see which model you went
    on to pick, and a tool that counts its own advice as if it were always
    taken is flattering itself with the number it is selling on. The wording
    everywhere downstream says so.
    """
    cors = _cors(request.headers.get("origin"))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad json"}, status_code=400,
                            headers=cors)

    rec = catalog.by_id(body.get("model") or "")
    top = catalog.by_id(body.get("top") or "")
    if not rec or not top:
        return JSONResponse({"ok": False, "reason": "unknown model"},
                            headers=cors)

    in_tokens = int(body.get("est_in") or 0)
    out_tokens = int(body.get("est_out") or 0)
    row = ledger.advice(
        lane=body.get("lane") or "?", site=body.get("site") or "?",
        recommended=rec.id, top=top.id,
        rec_cost=rec.cost_for(in_tokens, out_tokens),
        top_cost=top.cost_for(in_tokens, out_tokens),
        in_tokens=in_tokens, out_tokens=out_tokens)
    return JSONResponse({"ok": True, "saved": row["saved"]}, headers=cors)


@app.options("/lane/advice-stats")
async def advice_stats_preflight(request: Request):
    return Response(status_code=204,
                    headers=_cors(request.headers.get("origin")))


@app.get("/lane/advice-stats")
async def advice_stats(request: Request, days: float | None = None):
    """The running total the panel shows. Potential, and labelled as such."""
    s = ledger.stats(days, source="advisor")
    t = s["total"]
    return JSONResponse({
        "messages": t["requests"],
        "would_cost": round(t["baseline_cost"], 6),
        "would_spend": round(t["cost"], 6),
        "potential_saving": round(t["saved"], 6),
        "pct": round(t["saved_pct"], 1),
        "by_lane": {k: v["requests"] for k, v in s["by_lane"].items()},
    }, headers=_cors(request.headers.get("origin")))


# ── setup: keys and model selection, from a browser ─────────────────────────
#
# These endpoints are the only ones that WRITE credentials, and none of them
# carries a CORS header. That is the security boundary, not an oversight:
# claude.ai may ask LANE what model to use, and must never be able to read or
# replace an API key. Requiring a JSON body helps enforce it — a JSON
# content-type is not a "simple request", so a browser preflights it, and with
# no CORS headers to find, the preflight fails and the request never lands.

def _local_only(request: Request):
    """Reject anything that arrives with a cross-origin stamp on it.

    Belt and braces beside the missing CORS headers. A same-origin fetch from
    the setup page sends no Origin, or sends our own.
    """
    origin = request.headers.get("origin")
    if not origin:
        return None
    host = request.headers.get("host", "")
    if origin.split("//")[-1] == host:
        return None
    return _error(403, "setup is local-only and cannot be driven by a website",
                  "forbidden")


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    """Where somebody actually sets this up.

    Key entry lived only in `lane keys set` until now, which meant the first
    thing a browser-extension user had to do was open a terminal. That is not
    an onboarding step, it is an exit.
    """
    path = config.PKG / "web" / "setup.html"
    if not path.is_file():
        return HTMLResponse("<p>setup page missing from this install</p>",
                            status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@app.get("/lane/setup-state")
async def setup_state():
    """Everything the setup page draws itself from."""
    on = set(config.get("enabled_models") or [])
    providers = []
    for name, meta in keys.PROVIDERS.items():
        key = keys.get(name)
        providers.append({
            "id": name, "name": meta["name"], "console": meta["console"],
            "note": meta.get("note", ""),
            "connected": bool(key),
            "masked": keys.mask(key) if key else "",
            "source": keys.source(name) or "",
        })
    models = [{
        "id": m.id, "display": m.display, "provider": m.provider,
        "tier": m.tier, "kind": m.kind,
        "in_price": m.in_price, "out_price": m.out_price,
        "per_image": m.per_image,
        "strengths": list(m.strengths),
        "enabled": (not on) or m.id in on,
    } for m in catalog.all_models()]
    return {
        "providers": providers,
        "models": models,
        "explicit_selection": bool(on),
        "keyring": keys.keyring_available(),
        "mode": config.get("mode"),
        "baseline": config.get("baseline_model"),
    }


@app.post("/lane/setup-key")
async def setup_key(request: Request):
    """Store a key, after checking the provider agrees it is one.

    The same two-step as the CLI, and for the same reason: a key that is
    accepted and reported as saved without ever being tried is how a
    two-character paste survived long enough to look like a routing bug.
    """
    blocked = _local_only(request)
    if blocked:
        return blocked
    try:
        body = await request.json()
    except Exception:
        return _error(400, "request body is not valid JSON")

    provider = (body.get("provider") or "").lower()
    if provider not in keys.PROVIDERS:
        return _error(400, f"unknown provider {provider!r}")

    if body.get("remove"):
        keys.delete(provider)
        trail.record(trail.PROVIDER_KEY_REMOVED, actor="setup", target=provider)
        return {"ok": True, "connected": False}

    value = (body.get("key") or "").strip()
    ok, problem = keys.looks_valid(provider, value)
    if not ok:
        return _error(400, problem, "invalid_key")

    try:
        live = await providers.get(provider).list_models(value)
    except Exception as exc:
        return _error(
            400, f"{keys.PROVIDERS[provider]['name']} rejected that key: "
                 f"{str(exc)[:200]}", "invalid_key")

    try:
        where = keys.set(provider, value)
    except (KeyError, RuntimeError) as exc:
        return _error(500, str(exc), "storage_error")

    catalog.reload()
    trail.record(trail.PROVIDER_KEY_SET, actor="setup", target=provider,
                 detail={"models_available": len(live)})
    return {"ok": True, "connected": True, "stored_in": where,
            "models_available": len(live), "warning": problem}


@app.post("/lane/setup-models")
async def setup_models(request: Request):
    """Record which models this person can actually pick."""
    blocked = _local_only(request)
    if blocked:
        return blocked
    try:
        body = await request.json()
    except Exception:
        return _error(400, "request body is not valid JSON")

    ids = body.get("models")
    if not isinstance(ids, list):
        return _error(400, "models must be a list of model ids")

    known = {m.id for m in catalog.all_models()}
    chosen = [i for i in ids if i in known]
    # An empty selection means "everything", never "nothing". Storing nothing
    # would leave the advisor with no models to suggest and no way back except
    # a config file, which is a trap rather than a setting.
    config.set("enabled_models", chosen if len(chosen) < len(known) else [])
    catalog.reload()
    trail.record(trail.CONFIG_CHANGED, actor="setup", target="enabled_models",
                 detail={"value": f"{len(chosen)} of {len(known)} models"})
    return {"ok": True, "selected": len(chosen), "of": len(known)}


@app.get("/lane/stats")
async def stats(days: float | None = None):
    return ledger.stats(days)


@app.get("/", response_class=HTMLResponse)
async def chat_page():
    """The reason LANE has a UI at all.

    A proxy nobody points anything at is a well-tested no-op, and asking
    someone to wire up a separate chat client before they can send a single
    message is a long way to walk on faith. This page ships with the server:
    start it, open the address it prints, type. The routing is visible while
    you use it rather than in a log you have to go looking for.
    """
    path = config.PKG / "web" / "chat.html"
    if not path.is_file():
        return HTMLResponse(
            "<p>The chat page is missing from this install. The API still "
            "works at <code>/v1/chat/completions</code>.</p>", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/dev/search", response_class=HTMLResponse)
async def dev_search(q: str = ""):
    """A pretend results page, for developing the search offer.

    The offer reads the query out of ?q= exactly as it does on the real
    engines, so this needs no scraping and behaves identically. What it is
    really for is the other half of the design: checking that the card stays
    away from the many searches a model should not be offered for.
    """
    path = config.PKG / "web" / "search-harness.html"
    if not path.is_file():
        return HTMLResponse("harness missing", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@app.get("/ui.js")
async def ui_js():
    """The design system, for this server's own pages.

    The extension carries its own copy - a content script cannot depend on a
    server being up - but the pages served from here can just ask for it, so
    the setup and chat pages look like the panel without repeating a line of
    it. tools/build_core.py keeps the two in step.
    """
    path = config.PKG / "web" / "ui.js"
    if not path.is_file():
        return Response("/* design system missing */",
                        media_type="application/javascript")
    return Response(path.read_text(encoding="utf-8"),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/dev/ext/{path:path}")
async def dev_extension(path: str):
    """Serve the extension's own files, so its pages can be opened and driven
    in a browser without side-loading it into Chrome for every change."""
    base = (config.PKG.parent / "extension").resolve()
    target = (base / path).resolve()
    if base not in target.parents and target != base:
        return Response("no", status_code=403)      # no climbing out
    if not target.is_file():
        return Response("not found", status_code=404)
    kind = ("text/html" if target.suffix == ".html"
            else "application/javascript" if target.suffix == ".js"
            else "application/json" if target.suffix == ".json"
            else "text/plain")
    return Response(target.read_text(encoding="utf-8"), media_type=kind,
                    headers={"Cache-Control": "no-store"})


@app.get("/dev/core.js")
async def dev_core():
    """The generated browser brain, served for the parity page."""
    path = config.PKG.parent / "extension" / "core" / "lane-core.js"
    if not path.is_file():
        return Response("// not built - run python tools/build_core.py",
                        status_code=404, media_type="application/javascript")
    return Response(path.read_text(encoding="utf-8"),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/dev/parity-data")
async def dev_parity_data():
    """Every held-out prompt with the answer the PYTHON gives for it.

    The point of generating the JavaScript rather than writing it is that the
    two cannot drift. This is how that is checked: the same inputs, the Python's
    verdicts, and a page that runs the JavaScript over them and reports every
    disagreement.
    """
    from .corpus import HELDOUT, TRAIN
    cases = []
    for text, _gold in list(HELDOUT) + list(TRAIN):
        v = classify.classify([{"role": "user", "content": text}])
        cases.append({"text": text, "lane": v["lane"], "tier": v["tier"]})
    return {"cases": cases}


@app.get("/dev/parity", response_class=HTMLResponse)
async def dev_parity():
    """Served from a file rather than built as a string.

    The previous version embedded the page in Python, and the escapes went
    through two rounds of parsing on the way out: a 
 intended for a
    JavaScript string arrived as a real newline inside a double-quoted one,
    which is a syntax error. HTML with script in it belongs in a .html file.
    """
    path = config.PKG / "web" / "parity.html"
    if not path.is_file():
        return HTMLResponse("parity page missing", status_code=404)
    return HTMLResponse(path.read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-store"})


@app.get("/dev/advisor.js")
async def advisor_script():
    """The extension's content script, served for the local harness below."""
    path = config.PKG.parent / "extension" / "advisor.js"
    if not path.is_file():
        return Response("// extension not present in this install", status_code=404,
                        media_type="application/javascript")
    # Never cached: this route exists so a change to the panel can be seen by
    # reloading, and a browser holding yesterday's copy turns every edit into a
    # false negative.
    return Response(path.read_text(encoding="utf-8"),
                    media_type="application/javascript",
                    headers={"Cache-Control": "no-store"})


@app.get("/dev/advisor", response_class=HTMLResponse)
async def advisor_harness(site: str = "claude"):
    """A fake composer AND a fake model picker, for developing the panel.

    The picker matters as much as the composer now. One-click apply has to find
    a dropdown it did not write, inside a page it does not control, and the
    only way to know the discovery heuristics work is to point them at
    something shaped like the real thing. Markup here deliberately mirrors what
    those apps actually render: a button with aria-haspopup, a listbox of
    role=option, and not one useful class name anywhere.
    """
    models = {
        # A paid model is in each list on purpose: switching TO one is the
        # path most likely to be wrong, because it is the one somebody only
        # takes after deciding to spend money.
        "claude": ["Claude Opus 4.1", "Claude Fable 5", "Claude Sonnet 5",
                   "Claude Haiku 4.5"],
        "chatgpt": ["GPT-5", "GPT-5 mini", "GPT-4.1 mini"],
        "gemini": ["Gemini 2.5 Pro", "Gemini 2.5 Flash"],
    }.get(site, ["Claude Sonnet 5"])
    options = "".join(
        f'<div role="option" class="x9f2" data-i="{i}">{m}</div>'
        for i, m in enumerate(models))
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8>
<title>LANE advisor harness \u2014 {site}</title>
<style>
 body {{ font: 15px/1.6 ui-sans-serif, system-ui, sans-serif; margin:0;
        min-height:100vh; background:#f2f3f5; color:#14171a;
        display:flex; flex-direction:column; }}
 @media (prefers-color-scheme: dark) {{
   body {{ background:#0e1013; color:#e8eaed; }}
   textarea, .p8k {{ background:#171a1f; color:#e8eaed; border-color:#2b313a; }}
   .m3q {{ background:#171a1f; border-color:#2b313a; }} }}
 header {{ padding:14px 20px; font-size:13px; opacity:.6; }}
 main {{ flex:1; display:flex; flex-direction:column; align-items:center;
         justify-content:flex-end; padding:0 20px 60px; gap:10px; }}
 .bar {{ width:min(680px,100%); display:flex; }}
 .p8k {{ font:inherit; font-size:13px; padding:7px 12px; border-radius:9px;
         border:1px solid #d8dbe0; background:#fff; cursor:pointer; }}
 .m3q {{ position:absolute; margin-top:6px; background:#fff;
         border:1px solid #d8dbe0; border-radius:10px; padding:5px;
         box-shadow:0 8px 24px rgba(0,0,0,.14); z-index:50; }}
 .m3q [role=option] {{ padding:7px 14px; border-radius:7px; cursor:pointer;
                       font-size:13.5px; white-space:nowrap; }}
 .m3q [role=option]:hover {{ background:#eceef1; }}
 textarea {{ width:min(680px,100%); height:110px; font:inherit; padding:14px;
             border-radius:12px; border:1px solid #d8dbe0; background:#fff; }}
</style>
<header>Pretending to be <b>{site}</b> \u2014 type below, then use the panel.</header>
<main>
  <div class="bar">
    <button class="p8k" aria-haspopup="listbox" aria-expanded="false"
            id="picker">{models[0]}</button>
  </div>
  <textarea placeholder="Ask something\u2026" autofocus></textarea>
</main>
<script>
// A dropdown that behaves like the real ones: nothing in the DOM until it is
// opened, options identified only by role, and the trigger's label changes to
// whatever was chosen.
const btn = document.getElementById("picker");
let menu = null;
// POINTERDOWN, not click - which is what Claude, ChatGPT and Gemini all do,
// because they are built on headless component libraries that open menus on
// the pointer going down rather than on a completed click. A harness whose
// menu opens on click is a harness that passes while the real thing fails.
btn.addEventListener("pointerdown", () => {{
  if (menu) {{ menu.remove(); menu = null; btn.setAttribute("aria-expanded","false"); return; }}
  menu = document.createElement("div");
  menu.className = "m3q";
  menu.setAttribute("role", "listbox");
  menu.innerHTML = `{options}`;
  btn.parentElement.appendChild(menu);
  btn.setAttribute("aria-expanded", "true");
  document.addEventListener("keydown", function esc(e) {{
    if (e.key === "Escape" && menu) {{
      menu.remove(); menu = null;
      btn.setAttribute("aria-expanded", "false");
    }}
  }});
  // And options commit on mousedown, for the same reason.
  menu.addEventListener("mousedown", (e) => {{
    const opt = e.target.closest('[role=option]');
    if (!opt) return;
    btn.textContent = opt.textContent;
    menu.remove(); menu = null;
    btn.setAttribute("aria-expanded", "false");
  }});
}});
</script>
<script src="/dev/ext/ui.js"></script><script src="/dev/core.js"></script><script src="/dev/ext/profile.js"></script><script src="/dev/advisor.js"></script>""")


@app.get("/lane/catalog")
async def lane_catalog():
    """Prices and labels, so the page can show what a message cost without a
    round trip per message."""
    return {
        "models": [{"id": m.id, "display": m.display, "provider": m.provider,
                    "in_price": m.in_price, "out_price": m.out_price,
                    "tier": m.tier} for m in catalog.usable()],
        "lanes": {name: spec["label"] for name, spec in lanes.LANES.items()},
        "baseline": config.get("baseline_model"),
        "mode": config.get("mode"),
        "providers": keys.present(),
    }


@app.get("/health")
async def health():
    have = keys.present()
    usable = catalog.usable()
    return {
        "status": "ok" if usable else "no models",
        "version": "0.1.0",
        "providers": have,
        "models": len(usable),
        "mode": config.get("mode"),
        "baseline": config.get("baseline_model"),
    }


def run(host: str | None = None, port: int | None = None,
        reload: bool = False) -> None:
    import uvicorn
    uvicorn.run("lane.server:app" if reload else app,
                host=host or config.get("host"),
                port=int(port or config.get("port")),
                reload=reload, log_level="warning")
