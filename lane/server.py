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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from . import catalog, classify, config, keys, ledger, lanes, policy, providers
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


def _headers(decision: policy.Decision) -> dict:
    if not config.get("report_headers"):
        return {}
    h = {
        "x-lane-model": decision.model.id,
        "x-lane-provider": decision.model.provider,
        "x-lane-lane": decision.lane,
        "x-lane-mode": decision.mode,
        "x-lane-tier": str(decision.tier),
        "x-lane-reason": decision.reason[:180].replace("\n", " "),
    }
    if decision.degraded:
        h["x-lane-degraded"] = decision.degraded_note[:180]
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

    mode, forced_lane, pinned = _parse_model_field(body.get("model", "auto"))
    header_mode = request.headers.get("x-lane-mode")
    if header_mode in config.MODES:
        mode = header_mode

    try:
        if pinned:
            decision = _pinned_decision(pinned, messages, tools)
        else:
            decision = policy.route(
                messages, tools=tools, mode=mode, forced_lane=forced_lane,
                want_output=int(body.get("max_tokens") or 1024))
    except policy.NoModelAvailable as exc:
        return _error(503, str(exc), "service_unavailable")

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

    if stream:
        return await _stream_response(decision, body, started)
    return await _json_response(decision, body, started)


_MAX_ATTEMPTS = 3


async def _json_response(decision: policy.Decision, body: dict, started: float):
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
                          error=str(exc), tier=str(current.tier),
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
                      tier=str(current.tier), margin=current.margin,
                      latency_ms=int((time.perf_counter() - started) * 1000))
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


def _swap(decision: policy.Decision, model) -> policy.Decision:
    """The same decision, served by a fallback model."""
    return policy.Decision(
        model=model, lane=decision.lane, mode=decision.mode,
        reason=decision.reason + f"; fell back to {model.display}",
        tier=decision.tier, margin=decision.margin,
        degraded=True, degraded_note="first choice was unavailable",
        est_prompt_tokens=decision.est_prompt_tokens)


async def _stream_response(decision: policy.Decision, body: dict,
                           started: float):
    """Stream, and write the ledger entry when the last frame has gone.

    No fallback here on purpose. Once the first byte is on the wire the client
    has already begun rendering an answer; silently restarting on a different
    model would splice two different responses together. A stream that fails
    mid-flight fails visibly.
    """
    usage: dict = {}
    adapter = providers.get(decision.model.provider)
    key = keys.get(decision.model.provider)
    if not key:
        return _error(401, f"no API key for {decision.model.provider} — "
                           f"run: lane keys set {decision.model.provider}",
                      "authentication_error")

    kwargs = {"usage": usage}
    if decision.model.provider == "anthropic":
        kwargs["allow_sampling"] = decision.model.sampling

    async def body_iter():
        ok, err = True, ""
        try:
            async for frame in adapter.stream(body, decision.model.id, key,
                                              **kwargs):
                yield frame
        except ProviderError as exc:
            ok, err = False, str(exc)
            yield "data: " + json.dumps(
                {"error": {"message": str(exc), "type": "upstream_error"}}
            ) + "\n\ndata: [DONE]\n\n"
        finally:
            ledger.record(
                lane=decision.lane, mode=decision.mode,
                model=decision.model.id, provider=decision.model.provider,
                in_tokens=usage.get("in", 0), out_tokens=usage.get("out", 0),
                tier=str(decision.tier), margin=decision.margin,
                ok=ok, error=err, streamed=True,
                latency_ms=int((time.perf_counter() - started) * 1000))

    return StreamingResponse(
        body_iter(), media_type="text/event-stream",
        headers={**_headers(decision), "Cache-Control": "no-cache",
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


@app.get("/lane/stats")
async def stats(days: float | None = None):
    return ledger.stats(days)


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
