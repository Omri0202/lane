/*
 * lane-core.js — GENERATED. Do not edit; edit the Python and re-run
 * `python tools/build_core.py`.
 *
 * The classifier, the catalog and the policy, in the browser, with no server.
 *
 * This exists so the panel works the moment somebody installs the extension:
 * no Python, no terminal, no process to keep running. That was the single
 * biggest thing standing between this and anyone actually using it — a person
 * who has to clone a repository before they see a suggestion never sees one.
 *
 * It is generated rather than written because two copies of a classifier drift,
 * and advice that differs depending on which half of the product you asked is
 * worse than advice that is merely wrong. The corpus, the regexes, the lane
 * table and the model catalog are all read out of the Python at build time, and
 * tests/test_core_parity.py fails if the two ever disagree on the held-out set.
 *
 * Everything runs locally and costs nothing: no model is called to decide which
 * model to call, here or anywhere else in this product.
 */

const LaneCore = (() => {
  "use strict";

  /*__REGEXES__*/

  const D = /*__DATA__*/;

  const TECH = new Set(D.TECH_WORDS);
  const CREATE = new Set(D.CREATE_WORDS);
  const FAULT = new Set(D.FAULT_WORDS);
  const HUMAN_LANGS = new Set(D.HUMAN_LANGS);
  const PROG_LANGS = new Set(D.PROG_LANGS);
  const PROG_STRICT = new Set(D.PROG_STRICT);
  const DIGITS = /\d/;
  const WORDS = /[a-z+#]+/g;

  // ── features ───────────────────────────────────────────────────────────────
  // Words plus adjacent pairs, so phrasing carries weight but no single word
  // decides, plus three domain vocabularies that survive rephrasing better than
  // any individual word does.
  function features(text) {
    const raw = String(text || "").toLowerCase();
    const all = raw.match(new RegExp(TOKEN.source, "g")) || [];
    const words = all.slice(0, 60);
    const f = new Map();
    const add = (k, n) => f.set(k, (f.get(k) || 0) + n);

    for (const w of words) add(w, 1);
    for (let i = 0; i + 1 < words.length; i++) add(words[i] + "_" + words[i + 1], 1);

    const n = words.length;
    if (n <= 2) add("<<tiny>>", 3);
    else if (n <= 5) add("<<short>>", 2);
    else if (n >= 25) add("<<long>>", 2);
    if (raw.trim().endsWith("?")) add("<<question>>", 1);

    const seen = new Set(words);
    let tech = 0;
    for (const w of seen) if (TECH.has(w)) tech++;
    if (tech) add("<<tech>>", Math.min(tech, 3));
    for (const w of seen) if (CREATE.has(w)) { add("<<create>>", 2); break; }
    for (const w of seen) if (FAULT.has(w)) { add("<<fault>>", 2); break; }
    if (DIGITS.test(raw)) add("<<numeric>>", 1);
    return f;
  }

  // ── nearest centroid over TF-IDF ───────────────────────────────────────────
  // Trained at load from the same corpus the Python uses. Roughly a millisecond
  // for two hundred examples, once, when the page loads.
  const model = { idf: new Map(), centroids: new Map() };

  function normalise(v) {
    let mag = 0;
    for (const x of v.values()) mag += x * x;
    mag = Math.sqrt(mag) || 1;
    const out = new Map();
    for (const [k, x] of v) out.set(k, x / mag);
    return out;
  }

  function vectorise(f) {
    const v = new Map();
    for (const [w, c] of f) {
      v.set(w, (1 + Math.log(c)) * (model.idf.get(w) || 1.0));
    }
    return normalise(v);
  }

  function train(samples) {
    const docs = samples.map(([t, lane]) => [features(t), lane]);
    const n = docs.length || 1;
    const df = new Map();
    for (const [f] of docs) {
      for (const w of f.keys()) df.set(w, (df.get(w) || 0) + 1);
    }
    model.idf = new Map();
    for (const [w, c] of df) {
      model.idf.set(w, Math.log((n + 1) / (c + 1)) + 1.0);
    }

    const sums = new Map();
    const counts = new Map();
    for (const [f, lane] of docs) {
      const v = vectorise(f);
      if (!sums.has(lane)) sums.set(lane, new Map());
      const bucket = sums.get(lane);
      for (const [w, x] of v) bucket.set(w, (bucket.get(w) || 0) + x);
      counts.set(lane, (counts.get(lane) || 0) + 1);
    }
    model.centroids = new Map();
    for (const [lane, bucket] of sums) {
      const c = new Map();
      for (const [w, x] of bucket) c.set(w, x / counts.get(lane));
      model.centroids.set(lane, normalise(c));
    }
  }

  function rank(text) {
    const v = vectorise(features(text));
    const scored = [];
    for (const [lane, c] of model.centroids) {
      let dot = 0;
      for (const [w, x] of c) {
        const a = v.get(w);
        if (a) dot += a * x;
      }
      scored.push([dot, lane]);
    }
    // Descending by score, then by lane name — the Python sorts tuples, so ties
    // fall back to the lane string there too. Without this the two can disagree
    // on a tie, which is exactly the drift this file exists to avoid.
    scored.sort((a, b) => (b[0] - a[0]) || (b[1] < a[1] ? -1 : b[1] > a[1] ? 1 : 0));
    return scored;
  }

  // ── tier 0 ─────────────────────────────────────────────────────────────────
  function wordsOf(text) {
    return new Set(String(text || "").toLowerCase().match(WORDS) || []);
  }

  function isTranslation(text) {
    if (!TRANSLATE_VERB.test(text)) return false;
    const w = wordsOf(text);
    for (const p of w) if (PROG_LANGS.has(p)) return false;
    for (const h of w) if (HUMAN_LANGS.has(h)) return true;
    return false;
  }

  function isCodeContext(text) {
    if (!CODE_VERB.test(text)) return false;
    const w = wordsOf(text);
    for (const p of w) if (PROG_STRICT.has(p)) return true;
    return false;
  }

  function tier0(text) {
    const t = text || "";
    if (IMAGE_REQ.test(t)) return ["image_gen", "you are asking for a picture to be made"];
    if (isTranslation(t)) return ["translate", "this is a translation between languages"];
    if (LOOKUP.test(t)) return ["web_search", "this needs current information"];
    if (TRACE.test(t)) return ["reasoning", "the message contains a stack trace"];
    if (FENCE.test(t)) return ["reasoning", "the message contains code"];
    if (THINK_HARD.test(t)) return ["reasoning", "you asked for careful reasoning"];
    if (CODE_REQ.test(t)) return ["reasoning", "this asks for code"];
    if (isCodeContext(t)) return ["reasoning", "this names a programming language"];
    if (MATH.test(t)) return ["reasoning", "this is a maths problem"];
    if (t.split(/\s+/).filter(Boolean).length > D.DOC_WORDS)
      return ["longform", "the message is document-length"];
    return [null, ""];
  }

  // ── the decision ───────────────────────────────────────────────────────────
  function classify(text, opts) {
    opts = opts || {};
    const t0 = performance.now();
    const done = (lane, reason, tier, margin) => ({
      lane, reason, tier, margin: Math.round((margin || 0) * 1e4) / 1e4,
      took_us: Math.round((performance.now() - t0) * 1000),
    });

    if (opts.tools) return done("tools", "the request declares tools", "structural", 0);
    if (opts.hasImage) return done("vision", "an image is attached", "structural", 0);

    const [lane0, why0] = tier0(text);
    if (lane0) return done(lane0, why0, "0", 0);

    const scored = rank(text || "");
    if (!scored.length) return done(D.DEFAULT_LANE, "no strong signal either way", "default", 0);

    let [best, lane] = scored[0];
    const [runnerScore, runnerLane] = scored.length > 1 ? scored[1] : [0, lane];
    const margin = best - runnerScore;

    if (margin < D.CONFIDENT)
      return done(D.DEFAULT_LANE, "no strong signal either way", "default", margin);

    let reason = "how the message reads";
    // The cost asymmetry, confined to the difficulty ladder: rounding trivial
    // up to reasoning is caution, rounding a thank-you up into a web search is
    // a category error.
    const li = D.LADDER.indexOf(lane);
    const ri = D.LADDER.indexOf(runnerLane);
    if (margin < D.UPBIAS && li !== -1 && ri !== -1 && ri > li) {
      lane = runnerLane;
      reason = "how the message reads, rounded up - it was close and this is the safer half";
    }

    if (lane === "translate" && !isTranslation(text || "")) {
      const w = wordsOf(text || "");
      let isProg = false;
      for (const p of w) if (PROG_LANGS.has(p)) { isProg = true; break; }
      if (isProg) {
        lane = "reasoning";
        reason = "this moves code between languages";
      } else {
        const alt = scored.find((s) => s[1] !== "translate");
        lane = alt ? alt[1] : D.DEFAULT_LANE;
        reason = "how the message reads";
      }
    }
    return done(lane, reason, "1", margin);
  }

  // ── catalog and policy ─────────────────────────────────────────────────────
  const MODELS = D.MODELS;

  function blended(m, outRatio) {
    const r = outRatio === undefined ? 0.25 : outRatio;
    return m.in_price * (1 - r) + m.out_price * r;
  }

  function costFor(m, inTok, outTok, images) {
    if (m.kind === "image") return m.per_image * Math.max(images || 1, 1);
    return (inTok * m.in_price + outTok * m.out_price) / 1e6;
  }

  function estimateTokens(text) {
    return Math.max(1, Math.floor(String(text || "").length / 4));
  }

  function feasible(models, laneName, promptTokens) {
    const spec = D.LANES[laneName] || D.LANES[D.DEFAULT_LANE];
    const kind = spec.kind || "chat";
    return models.filter((m) => {
      if ((m.kind || "chat") !== kind) return false;
      if (kind === "image") return true;
      for (const cap of spec.needs) if (!m[cap]) return false;
      if (promptTokens && m.context < promptTokens * 1.35) return false;
      return true;
    });
  }

  function choose(laneName, mode, models, promptTokens) {
    const spec = D.LANES[laneName] || D.LANES[D.DEFAULT_LANE];
    let cand = feasible(models, laneName, promptTokens);
    if (!cand.length) return null;

    let qualified = cand.filter((m) => m.tier >= spec.floor);
    let degraded = false;
    let ranked;
    if (qualified.length) {
      if (mode === "save") {
        ranked = qualified.slice().sort((a, b) => blended(a) - blended(b) || b.tier - a.tier);
      } else if (mode === "performance") {
        const wants = spec.wants;
        ranked = qualified.slice().sort((a, b) => {
          const af = wants && a.strengths.includes(wants) ? 0 : 1;
          const bf = wants && b.strengths.includes(wants) ? 0 : 1;
          if (af !== bf) return af - bf;
          if (a.tier !== b.tier) return b.tier - a.tier;
          if (spec.prefers === "speed" && a.speed !== b.speed) return b.speed - a.speed;
          return blended(a) - blended(b);
        });
      } else {
        const value = (m) => m.tier / Math.max(blended(m), 1e-6);
        ranked = qualified.slice().sort((a, b) => value(b) - value(a) || b.tier - a.tier);
      }
    } else {
      // Nothing clears the bar, so mode stops applying: they asked for more
      // capability than exists, and the only sensible answer is the most there
      // is. Ranking by price here would answer the hardest request with the
      // weakest model.
      degraded = true;
      ranked = cand.slice().sort((a, b) => b.tier - a.tier || blended(a) - blended(b));
    }
    return { model: ranked[0], degraded, runners: ranked.slice(1, 4) };
  }

  // ── the whole advisory answer, as the panel wants it ───────────────────────
  const SITE_PROVIDER = { claude: "anthropic", chatgpt: "openai", gemini: "google" };
  const PROVIDER_SITE = { anthropic: "Claude", openai: "ChatGPT", google: "Gemini",
                          groq: "Groq", openrouter: "OpenRouter" };

  function priceWord(x) {
    if (x <= 0) return "free";
    if (x < 0.01) return "$" + x.toFixed(4);
    if (x < 1) return "$" + x.toFixed(3);
    return "$" + x.toFixed(2);
  }

  const LACKS = {
    image_gen: "No model here draws pictures - it can only read them.",
    vision: "No model here reads images.",
    tools: "No model here calls tools.",
    web_search: "No model here can search the web, so the answer would come from memory.",
  };

  const BY_LANE = {
    trivial: "There is nothing here to think about. The smallest model produces the same reply for {f}x less.",
    simple: "This is recall, not reasoning. Every model knows it; only one of them charges {f}x more to say so.",
    general: "An explanation, not a hard problem. The mid model reads the same and costs {f}x less.",
    longform: "Judged on voice rather than correctness, where the gap between models is smallest - and {f}x cheaper.",
    reasoning: "This one is worth capability, so the floor is high. Even so, you do not need the very top: {f}x less buys the same answer.",
    translate: "Translation into a major language is close to solved - this is one of the few places where the cheap model is not a compromise, and it is {f}x less.",
    web_search: "The answer is not in any model's training data, so make sure web search is switched on. Once it is, {f}x less summarises what it found just as well.",
    vision: "Reading an image needs a vision model, and the cheapest one that can see is {f}x lighter than the best.",
    tools: "Tool calls are judged on well-formed output, not brilliance. {f}x less gets you that.",
  };

  function advise(text, site, variation, allowedIds) {
    const spec = (name) => D.LANES[name] || D.LANES[D.DEFAULT_LANE];
    const verdict = classify(text);
    const laneName = verdict.lane;
    const s = spec(laneName);
    const inTok = estimateTokens(text);
    const outTok = s.expected_output;

    const provider = SITE_PROVIDER[site];
    let here = MODELS.filter((m) => !provider || m.provider === provider);
    if (allowedIds && allowedIds.length) {
      here = here.filter((m) => allowedIds.includes(m.id));
    }

    const out = {
      lane: laneName, lane_label: s.label, reason: verdict.reason,
      tier: verdict.tier, took_us: verdict.took_us,
      words: String(text || "").split(/\s+/).filter(Boolean).length,
      kind: s.kind, est_in: inTok, est_out: outTok,
      options: [], elsewhere: [], assuming_all: !(allowedIds && allowedIds.length),
      local: true,
    };

    const servable = here.filter((m) => {
      if ((m.kind || "chat") !== s.kind) return false;
      for (const cap of s.needs) if (!m[cap]) return false;
      return true;
    });

    if (!servable.length) {
      for (const m of MODELS) {
        if ((m.kind || "chat") !== s.kind) continue;
        let ok = true;
        for (const cap of s.needs) if (!m[cap]) { ok = false; break; }
        if (!ok) continue;
        out.elsewhere.push({
          site: PROVIDER_SITE[m.provider] || m.provider,
          provider: m.provider, id: m.id, display: m.display,
          cost: Math.round(costFor(m, inTok, outTok) * 1e6) / 1e6,
        });
      }
      out.elsewhere.sort((a, b) => a.cost - b.cost);
      out.unavailable_here = true;
      out.site_name = PROVIDER_SITE[provider] || site || "this site";
      const first = out.elsewhere[0];
      out.explain = first
        ? (LACKS[laneName] || ("No model here handles " + s.label.toLowerCase() + " work."))
          + " " + first.site + " does this with " + first.display
          + " for about " + priceWord(first.cost) + (s.kind === "image" ? " an image" : "") + "."
        : "Nothing available can do this.";
      return out;
    }

    out.unavailable_here = false;
    for (const mode of ["save", "balanced", "performance"]) {
      const d = choose(laneName, mode, here, inTok);
      if (!d) continue;
      out.options.push({
        mode, id: d.model.id, display: d.model.display, tier: d.model.tier,
        degraded: d.degraded,
        cost: Math.round(costFor(d.model, inTok, outTok) * 1e6) / 1e6,
        per_image: d.model.kind === "image",
        fit: mode === "performance" ? s.fit : "",
      });
    }

    const top = servable.reduce((a, b) => (b.tier > a.tier ? b : a));
    const wanted = (variation === "best" || variation === "performance")
      ? "performance" : "save";
    out.variation = wanted === "performance" ? "best" : "save";

    const row = out.options.find((o) => o.mode === wanted) || out.options[0];
    const rec = row ? MODELS.find((m) => m.id === row.id) : top;
    out.fit = row ? row.fit : "";

    const recCost = costFor(rec, inTok, outTok);
    const topCost = costFor(top, inTok, outTok);
    const factor = recCost > 0 ? Math.round((topCost / recCost) * 10) / 10 : 1.0;

    out.recommend = { id: rec.id, display: rec.display, tier: rec.tier,
                      cost: Math.round(recCost * 1e6) / 1e6,
                      per_image: rec.kind === "image" };
    out.top = { id: top.id, display: top.display, tier: top.tier,
                cost: Math.round(topCost * 1e6) / 1e6 };
    out.factor = factor;
    out.is_top = rec.id === top.id;
    out.saving = Math.round((topCost - recCost) * 1e6) / 1e6;

    if (out.variation === "best") {
      const save = out.options.find((o) => o.mode === "save");
      if (save && save.id !== rec.id && save.cost > 0) {
        const times = Math.round((recCost / save.cost) * 10) / 10;
        out.explain = times + "x the price of the cheapest model that would cope. "
          + "Worth it when the answer matters more than the bill; switch to SAVE when it does not.";
      } else {
        out.explain = "The cheapest model that can do this is also the one best suited to it - no trade-off here.";
      }
    } else if (out.is_top) {
      out.explain = "Nothing cheaper clears the bar for this one - the strongest model is the right call.";
    } else if (s.kind === "image") {
      out.explain = "This needs an image generator, not a chat model. "
        + rec.display + " is billed per picture, not per token.";
    } else {
      out.explain = (BY_LANE[laneName] || "").replace("{f}", factor);
    }
    return out;
  }

  train(D.TRAIN);

  return { classify, advise, choose, rank, tier0, features, estimateTokens,
           costFor, MODELS, LANES: D.LANES, DATA: D };
})();

if (typeof module !== "undefined" && module.exports) module.exports = LaneCore;
