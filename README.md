# L.A.N.E.

**Language Agent Network Exchange** — a local proxy that reads each prompt and
sends it to the model that should answer it.

You have keys for Anthropic, OpenAI, and Google. You have one chat window. Every
message you send goes to whichever model you happened to pick that morning —
including "thanks", which costs the same as a debugging session.

LANE sits between your client and the providers. It classifies each request
locally, picks a model, calls it, and hands the answer back in the shape your
client already understands. Nothing in your setup changes except one base URL.

```
your app  ──▶  LANE  ──▶  Anthropic / OpenAI / Google
               │
               └─ classifies locally, in ~200µs, for free
```

---

## The two modes

| Mode | What it does |
|---|---|
| **`lane-save`** | The cheapest model that still clears the bar for what you asked. |
| **`lane-perf`** | The strongest model available for what you asked. |
| **`lane-balanced`** *(default)* | The most capability per dollar. |

The bar in "clears the bar" is the important part. Save mode is allowed to be as
cheap as it likes **above** a capability floor set per request type, and not one
point below it. Without that rail, "cheapest wins" quietly degrades everything
to your worst model — which is how cost routers get uninstalled in week two.

---

## Install

```bash
git clone https://github.com/Omri0202/lane.git
cd lane
python -m pip install -e .
```

Python 3.10 or newer. Windows, macOS, and Linux — there is nothing
platform-specific in it.

### Add your keys

```bash
lane keys set anthropic
```

It prompts without echoing and stores the key in your OS keyring (Windows
Credential Manager, macOS Keychain, Secret Service on Linux). Keys never touch
a config file. Repeat for `openai` and `google`.

You need **at least one**. LANE routes among whatever it finds — with one key it
still saves money by picking the right model *within* that provider; with three
it can cross between them.

If there is no keyring on the machine (headless Linux, usually), export
`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GOOGLE_API_KEY` instead. `lane doctor`
tells you which is in use.

### Check it

```bash
lane doctor
```

---

## Use it

```bash
lane serve
```

Then point any OpenAI-compatible client at it and use `auto` as the model:

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1
export OPENAI_API_KEY=unused        # LANE holds the real keys
```

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="unused")

client.chat.completions.create(
    model="lane-save",                       # or "auto", or "lane-perf"
    messages=[{"role": "user", "content": "why does my sql join drop rows"}],
)
```

Streaming, tool calls, images, and system prompts all work. Every response
carries headers saying what happened:

```
x-lane-model: claude-sonnet-5
x-lane-lane: reasoning
x-lane-mode: save
x-lane-reason: how the message reads; cheapest model that still clears the reasoning bar
```

### Turning it off for one request

Put a real model id in the `model` field and LANE sends it straight there:

```python
model="claude-opus-5"       # no routing — but still metered
```

A router you cannot switch off is a router people work around.

---

## What it decided, and why

```
$ lane why "thanks!"

── classification ────────────────────────────────────────────
  lane      Trivial  (trivial)
  because   how the message reads
  decided   tier 1 in 206µs, margin 0.7283

── what each mode would pick ─────────────────────────────────
  save         GPT-5 nano (openai)  ~$0.0002/request
  balanced     GPT-5 nano (openai)  ~$0.0002/request ←default
  performance  Claude Fable 5 (anthropic)  ~$0.025/request

  baseline     Claude Opus 5  ~$0.013/request
```

That one message is 65× cheaper than sending it to your default model, and no
worse an answer. Multiply by every "ok", "go on", and "perfect, thanks" in a
week of conversations.

Over a week, `lane stats` reports the same comparison across everything you
sent — spend, the counterfactual, and the difference:

```
$ lane stats --days 7          # shape of the report; your numbers will differ

  requests        1,284
  you spent       $4.11
  claude-opus-5 only   $31.80   (Claude Opus 5 for everything)
  saved           $27.69  (87% less)
```

The third line is a counterfactual, not a measurement: it is what the same
traffic would have cost on your configured baseline model. Change the baseline
to something you would genuinely have used and watch the number move —

```bash
lane config baseline_model claude-sonnet-5
```

A savings figure you can argue with is worth more than one you cannot.

---

## How the routing works

Every request is sorted into one of seven **lanes**. A lane is a statement about
what the request needs, made before anything is known about your keys:

`trivial` · `simple` · `general` · `longform` · `reasoning` · `vision` · `tools`

Four tiers decide it, each allowed to say *I don't know*:

1. **Structural** — an image is attached, or a tool schema is present. Facts, so
   they are checked before a single character of prompt text is read.
2. **Regex** — a stack trace, a fenced code block, "think carefully". Written to
   stay silent rather than be wrong.
3. **Statistical** — nearest-centroid over TF-IDF of words and word pairs, plus
   three domain vocabularies. Reports a margin and declines when it is thin.
4. **Default** — `general`. A deliberate middle, wrong cheaply in both
   directions.

**It never calls a model to decide which model to call.** Classification runs
locally in about 200 microseconds and costs nothing. On short prompts a
classifier call can cost more than the answer, which would defeat the point.

### Measured, on phrasing it has never seen

The training examples and the graded examples share no phrasing, deliberately.
On 52 held-out prompts:

| | |
|---|---|
| Exact lane | **90.4%** |
| **Under-routed** (sent somewhere too weak) | **0.0%** |
| Over-routed (sent somewhere stronger than needed) | 9.6% |

The middle row is the one that matters. Those two errors are not comparable: a
reasoning problem sent to a small model produces a confidently wrong answer you
have to notice, re-ask, and pay for twice; a greeting sent to a large one wastes
a fraction of a cent and nobody notices. So the thresholds were swept to
minimise under-routing rather than to maximise accuracy, and when the top two
lanes are close, the more demanding one wins.

This matters more than the headline number. A previous version of this
classifier — a hand-written keyword list — scored 100% on the examples it was
written against and 35% on real phrasing. `tests/test_classify.py` exists to
make that failure impossible to miss again.

---

## Commands

| | |
|---|---|
| `lane serve` | run the proxy |
| `lane why "<prompt>"` | where would this go, and what would each mode pick |
| `lane keys set <provider>` | store a key in the OS keyring |
| `lane models` | the catalog, and what your keys can actually reach |
| `lane models --sync` | ask each provider which models your key can reach |
| `lane stats --days 7` | what you spent, and what you saved |
| `lane tail` | the last requests, one line each |
| `lane config <key> <value>` | change a setting |
| `lane doctor` | check the installation |

Useful settings: `mode`, `baseline_model`, `max_cost_per_request` (refuse a
request that could cost more than this, before spending anything),
`disabled_models`, `port`.

---

## About the prices

Model prices go stale. LANE handles that structurally rather than by hoping:

- **Anthropic prices are verified** (2026-06-24).
- **OpenAI and Google prices are starting guesses.** `lane models` marks them,
  and any savings figure that depends on them is flagged as an estimate.
- `lane models --sync` asks each provider which models your key can actually
  reach, hides the ones it cannot, and lists any it offers that the catalog
  does not know about.
- Everything is in `lane/models.json`, and your own edits go in
  `~/.lane/models.local.json`, which upgrades never overwrite.

**Please check the two unverified rows against the providers' pricing pages
before trusting a savings number.** Correcting them takes a minute and makes
every figure LANE reports real.

---

## Limitations

- **The front door speaks OpenAI, not Anthropic.** Anything using the OpenAI
  format works today. Tools that speak the Anthropic Messages API directly —
  **Claude Code among them** — cannot use LANE yet, because they need an
  Anthropic-shaped `/v1/messages` endpoint. Adding one is the clearest next
  step; all the translation machinery already exists in `lane/translate.py`,
  pointed the other way.
- **Streaming does not fall back.** Once the first byte is on the wire, quietly
  restarting on a different model would splice two answers together. A stream
  that fails mid-flight fails visibly.
- **Only the last user turn is classified.** Letting a long technical history
  outvote the actual question is how a router bills "thanks" at reasoning rates.
- **Capability scores are judgements, not benchmarks.** `tier` in the catalog is
  an ordering, and yours may differ. It is data, so change it.
- **Prompt caching is not accounted for.** Cached input tokens are billed at a
  lower rate by the providers; the ledger currently counts all input tokens at
  full price, so real spend may be lower than reported.

---

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest tests/ -q
```

54 tests, no network and no API key required — every provider call is stubbed.

```
lane/
  classify.py    four tiers, each able to abstain
  corpus.py      training examples, and a disjoint graded set
  lanes.py       the seven request types and their capability floors
  catalog.py     the model table, and the truth-maintenance around it
  policy.py      lane × mode × constraints → a model
  translate.py   OpenAI ↔ Anthropic wire formats
  providers/     one adapter per API shape
  server.py      the OpenAI-compatible front door
  ledger.py      what it cost, and what it would have cost
  cli.py         the `lane` command
```

Built on the routing work in
[G.I.L.](https://github.com/Omri0202/G.I.L.-Generative-Intelligence-Liaison),
which is where the abstain-when-unsure design and the 100%-on-train /
35%-on-real lesson came from.

## Licence

MIT.
