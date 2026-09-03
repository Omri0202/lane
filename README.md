# L.A.N.E.

**Language Agent Network Exchange** — it reads what you are about to ask and
tells you which model should answer it.

You pick a model from the dropdown once, in the morning, and then forget. Every
message for the rest of the day goes to it — including "thanks", which costs
the same as a debugging session.

LANE reads each request locally — in about 200 microseconds, without calling a
model to decide which model to call — and picks the one that should answer it.

It comes in two shapes. **A browser panel** that sits over claude.ai,
chatgpt.com or gemini and tells you which model to pick before you send, while
you are still using those sites normally. And **a local proxy** that any
OpenAI-compatible app can point at, which does the picking for you.

```
   you typing in claude.ai          any OpenAI-compatible app
            │                                  │
            ▼                                  ▼
   ┌─────────────────┐                ┌─────────────────┐
   │  advisor panel  │                │   local proxy   │
   │ "use Sonnet 5,  │                │  picks for you  │
   │  5x cheaper"    │                │  and calls it   │
   └─────────────────┘                └─────────────────┘
            └──────────────┬───────────────────┘
                           ▼
              classified locally, ~200µs, free
```

---

## Two variations

Every message gets read locally — in about 200 microseconds, without calling a
model to decide which model to call — and sorted into one of ten kinds of
request. Then you choose what to optimise for.

### SAVE — the cheapest model that still does the job

The reason most people install this. You pick a model from the dropdown once,
in the morning, and forget; every "thanks" for the rest of the day is billed at
frontier rates.

```
SIMPLE                       ~4 in · ~120 out
CHEAPEST THAT FITS ON CLAUDE
Claude Haiku 4.5                      $0.0006
saves $0.0054 · 10x cheaper than Fable 5

This is recall, not reasoning. Every model knows
it; only one of them charges 10x more to say so.
```

The important word is **still**. Save mode may go as cheap as it likes above a
capability floor set per request type, and not one point below it. Without that
rail, "cheapest wins" quietly degrades everything to your worst model — which
is how cost routers get uninstalled in week two.

It keeps a running total, and calls it what it is:

```
could have saved $2.41              184 messages
```

Potential, not measured. LANE cannot see which model you actually picked, and a
tool that counts its own advice as though it were always taken is flattering
itself with the number it is selling on.

### BEST — the model that actually fits

Not the biggest. The one whose strengths match the job.

```
REASONING                  ~15 in · ~1,200 out
BEST FIT ON CLAUDE
Claude Fable 5                         $0.060
thinks before answering, which is the whole
difference on a problem like this

5x the price of the cheapest model that would
cope. Worth it when the answer matters more than
the bill; switch to SAVE when it does not.
```

Ask it about a greeting and BEST returns **Haiku 4.5**, the same model SAVE picks —
because a larger model would produce the same reply more slowly. That is the
test of whether this mode is doing anything: a version that returned the top of
the price list every time would be a rate card wearing a recommendation's
clothes, and you can read a price list without installing anything.

Models declare what they are good AT — `depth`, `prose`, `speed`, `vision`,
`web`, `code` — and each kind of request declares what it wants. Tier still
decides within the fitting group, so "fits" never means "worse".

| On claude.ai | SAVE | BEST |
|---|---|---|
| Greeting | Haiku 4.5 | Haiku 4.5 — *same; nothing bigger would help* |
| Look something up | Haiku 4.5 | Fable 5 — *can search rather than answer from memory* |
| Translate a letter | Haiku 4.5 | Fable 5 — *handles idiom and register* |
| Write an article | Sonnet 5 | Fable 5 — *the strongest writing voice you have* |
| Debug a query | Sonnet 5 | Fable 5 — *thinks before answering* |
| Draw a picture | *Claude cannot. ChatGPT, ~$0.04* | *same* |

---

## Install

```bash
git clone https://github.com/Omri0202/lane.git
cd lane
python -m pip install -e .
```

```bash
lane serve
```

Then **open http://127.0.0.1:8080/setup** and do two things.

### 1. Give it your keys

One box per provider — Anthropic, OpenAI, Google, Groq, OpenRouter. Paste,
click Connect, and LANE asks the provider whether the key works before it
stores anything. "Connected" means stored **and** accepted, never just stored.

Keys go to your operating system's credential store — Windows Credential
Manager, macOS Keychain, Secret Service on Linux. Never a file, never off the
machine.

You only need keys for the **proxy**, the part that calls models for you. The
browser panel advises perfectly well without any key at all.

**No budget, or under 18?** Google AI Studio requires an account holder aged
18+, and the paid providers need credits. **Groq has a free tier** with no such
gate, and it is the cheapest way to run the whole thing.

### 2. Tell it which models you can actually pick

This is the part that makes the advice worth reading.

If your plan has no Opus, being told to use Opus is not a recommendation — it
is a chore with an extra step. The setup page lists every model with its price
and what it is good at; untick anything you cannot reach, and every
recommendation afterwards comes from what is genuinely in front of you.

Until you do, the panel says so rather than pretending:

> *Assuming you can use every Claude model. Tell LANE which ones you actually
> have and this gets sharper.*

Ticking everything is the same as ticking nothing — both mean "assume the whole
catalog", so the setting cannot trap you with an empty list.

### The setup page cannot be reached from a website

It is the only place that writes credentials, and the same browser has
claude.ai open in another tab. So none of those endpoints carries a CORS
header, all of them require a JSON body — which forces a preflight a website
cannot pass — and any request arriving with a foreign `Origin` is refused
outright. claude.ai may ask LANE which model to use. It can never read or
replace a key.

### Prefer a terminal?

```bash
lane keys set anthropic
```

```bash
lane doctor
```

`lane keys set --visible` shows the key as you paste it, for terminals that
will not paste into a hidden prompt.

---

## Use it

```bash
lane serve
```

Then **open http://127.0.0.1:8080 in a browser and start typing.** LANE serves
its own chat page — no other client to install, no keys to configure twice.
Under every reply it shows which model answered, which lane it was sorted into,
and what it cost; the header keeps a running total against your baseline. The
routing is visible while you use it rather than in a log you have to go looking
for.

Switch between Save / Balanced / Performance with the buttons in the header to
watch the same question get answered by different models.

### Or point your own client at it

Anything OpenAI-compatible works. Use `auto` as the model:

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

## The advisor — a panel over claude.ai, chatgpt.com, gemini

A small card in the corner of the page you are already using. It reads what you
are typing, on your machine, and tells you which model this message wants —
**before you send it**, while there is still time to act on it. Advice that
arrives after you press send is a report.

The SAVE / BEST toggle lives in its header, and the choice is remembered.

### One click to take the suggestion

Naming a model and leaving you to go and find it is where advice gets ignored.
The card has a button:

```
  USE ON CLAUDE
  Claude Sonnet 5                          $0.012
  saves $0.048 - 5x cheaper than Fable 5

  [        Use Claude Sonnet 5        ]
```

Click it and the page switches. It finds the model picker by BEHAVIOUR rather
than by selector - a small clickable thing whose visible text is the name of a
model - because these are React apps whose class names change weekly and
`.model-selector` is a bet on somebody else's refactor.

When it cannot do it, it says so and copies the name instead:

| | |
|---|---|
| already on that model | *already on Claude Sonnet 5* - nothing is clicked |
| model not in the dropdown | *Claude Fable 5 is not in this page's list* |
| no picker on the page | *no model picker found on this page* |

In every failure the page is left exactly as it was found, dropdown closed. A
button that silently does nothing is worse than no button, because you believe
you switched.

```
┌────────────────────────────────────┐
│ L.A.N.E.                         × │
├────────────────────────────────────┤
│ REASONING       ~15 in · ~1,200 out│
│ ────────────────────────────────── │
│ USE ON CLAUDE                      │
│ Claude Sonnet 5              $0.012│
│ saves $0.048 · 5x cheaper          │
│                                    │
│ SAVE         Sonnet 5        $0.012│
│ BALANCED     Sonnet 5        $0.012│
│ PERFORMANCE  Fable 5         $0.060│
│ ────────────────────────────────── │
│ This one is worth capability, so   │
│ the floor is high. Even so, you do │
│ not need the very top.             │
└────────────────────────────────────┘
```

Every number is for **that message**: the prompt is measured, the reply length
is estimated from the kind of request, and both are priced. Output is billed
four to five times higher than input everywhere, so an estimate that counted
only what you typed would understate every request — always in the direction
that flatters the tool.

### It knows what kind of request it is, not just how hard

Ask Claude for a picture and the honest answer is not "use Opus":

```
┌────────────────────────────────────┐
│ MAKE AN IMAGE      priced per image│
│ ────────────────────────────────── │
│ CLAUDE CAN'T DO THIS               │
│ ChatGPT   GPT Image 1        $0.040│
│ Gemini    Imagen 4           $0.040│
│ ────────────────────────────────── │
│ No Claude model draws pictures — it│
│ can only read them.                │
└────────────────────────────────────┘
```

No Claude model generates images, so the catalog contains no Anthropic image
model and the advisor names the site that can. Recommending the strongest chat
model here would not be a slightly worse answer, it would be an impossible one
— and obviously so within seconds.

The distinction is the verb, not the noun. "describe this picture", "the image
is blurry" and "write a function that resizes images" all stay where they
belong.

Everywhere else it recommends only models **that site can actually give you** —
advising Gemini Flash to somebody sitting in claude.ai is not a saving, it is a
chore.

### Installing it

**No Python. No server. No terminal.**

In Chrome or Edge, open `chrome://extensions`, turn on **Developer mode**,
click **Load unpacked**, and select the `extension` folder. Open claude.ai and
type. That is the whole install.

The classifier, the model catalog and the pricing all ship inside the
extension — about 50KB, generated from the Python so the two can never
disagree. Everything runs in the page: nothing is sent anywhere, nothing is
intercepted, and your message reaches Claude exactly as it always did.

Verified with the server deliberately killed: the panel still classified,
priced, and switched the model.

A local `lane serve`, if you happen to run one, adds two things and is
required for neither — the running savings total, and the model selection from
`/setup`. When it is not there the counter simply hides.

### Keeping the two brains identical

`extension/core/lane-core.js` is **generated**, never hand-edited:

```bash
python tools/build_core.py
```

Two copies of a classifier drift, and advice that differs depending on which
half of the product you asked is worse than advice that is merely wrong. So the
corpus, the regexes, the lane table and the catalog are all read out of the
Python at build time. `tests/test_core_parity.py` fails if the file is stale,
and `/dev/parity` runs every prompt through both brains in a browser — 317 of
317 matching, at 0.73ms each.

### Working on the panel

```
http://127.0.0.1:8080/dev/advisor?site=claude
```

A fake composer served by LANE itself, so the panel can be developed without
side-loading an unpacked extension into a real chat site every time. Swap
`site=` for `chatgpt` or `gemini` to see what each one would recommend.

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

`trivial` · `simple` · `general` · `longform` · `reasoning` · `translate` ·
`web_search` · `vision` · `tools` · `image_gen`

The last four are about **capability**, not difficulty, and that difference is
the point. A slightly-too-cheap model still answers a `general` question. A
chat model asked for a picture produces no picture; a model without web access
answers a question about today from a stale memory, confidently. So those four
are detected deterministically and the capability is a hard filter no mode can
trade away.

`translate` earns its own lane for the opposite reason: translation into a
major language is close to solved, so the gap between models is unusually
small. It carries a **lower** floor than long-form, which is where the saving
comes from.

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

## Proving it — the quality report

Every cost router makes the same claim and none of them proves it: that the
smaller model answered as well as the expensive one would have. The claim is
unfalsifiable in normal use, because the expensive answer never existed. So the
question that decides whether anyone adopts cost routing — **"will quality
drop?"** — can only be met with assurances, and assurances are worth nothing to
somebody signing off a budget.

LANE measures it, on your own traffic.

```bash
lane config audit_sample_rate 0.02
```

From then on, 2% of proxy requests are answered **twice**: once by the routed
model, once by the baseline it is being compared against. Both answers are
kept. Then:

```bash
lane quality --judge
```

```
── quality audit ─────────────────────────────────────────────
  sampled       412 requests  (2% of traffic)
  judged        412

  as good or better   94%   (31 better, 356 same)
  worse                6%   (25 of 412)
  cost                8.1x less than the baseline on the same requests

── by request type ───────────────────────────────────────────
  simple         188   99% acceptable
  general        121   96% acceptable
  reasoning       74   81% acceptable  <-- check this
  longform        29   93% acceptable
```

That last column is the useful part. It does not just say "routing is fine" —
it says **where** it is fine and where it is not, so the floor for that one
lane can be raised instead of the whole idea being abandoned.

### Why the number is worth trusting

Four things, all of which cost accuracy in the direction that makes LANE look
worse:

**The judge is the expensive model.** It grades its own replacement. Asking a
cheap model whether a cheap model did well is not evidence.

**Position is alternated.** Judges favour whichever answer they read first by a
margin wide enough to manufacture this result, so which side the routed answer
sits on flips per row and the bias cancels across the sample.

**The judge is told to ignore length, tone and confidence** — the three things
that make a bigger model *look* better without being more useful — and told
that SAME is the expected answer, not a cop-out.

**"Acceptable" is better-or-same, and worse is reported separately.** A router
does not need to win. It needs to not lose, far more cheaply.

**Your answer is never the experiment.** The routed answer is returned exactly
as it would have been; the baseline call happens afterwards, for the record
only. Nobody is served a slower or worse answer because an audit is running.

The shadow calls are real money and appear in the ledger under their own
source, so the audit's cost is never mistaken for traffic you asked for and
never quietly netted off the savings it is measuring.

---

## When your models cannot do it

The loop this is really built around.

You give LANE keys for the models you want to use. You type. When a request
needs something none of your models can do, LANE does not fail — it names the
model that can, tells you what it costs, and takes the key right there:

```
  None of your models can do this.
  It needs a model that makes images. These can:

  OpenAI          GPT Image 1 · $0.040/image · DALL-E 3 · $0.040/image
                  [ paste your OpenAI key ]  [ Add key and retry ]   get one ↗

  Google Gemini   Imagen 4 · $0.040/image
                  [ paste your Google Gemini key ]  [ Add key and retry ]
```

Paste the key and **the message you already typed goes through** — no retyping,
no documentation, no leaving the conversation. Next time it just works, because
the key is stored.

It never offers a provider you already have, and when adding a key would not
help either it says so plainly instead of sending you shopping.

### The same thing on somebody else's site

In the browser panel the answer is different, because on claude.ai you are
spending a subscription rather than a key. There LANE names the **site** that
can do it:

```
  MAKE AN IMAGE                    priced per image
  ─────────────────────────────────────────────────
  CLAUDE CAN'T DO THIS
  ChatGPT   GPT Image 1                      $0.040
  Gemini    Imagen 4                         $0.040
  ─────────────────────────────────────────────────
  No model here draws pictures - it can only read
  them. ChatGPT does this with GPT Image 1.
```

Same detection, two answers, because the useful next step is different in each
place. It covers every capability, not only images — a site whose models cannot
search the web is told so before the answer comes back from a stale memory.

---

## Teams, budgets and attribution

The change that makes LANE something a company can sign for rather than a tool
one person runs.

One LANE serves the whole company. Each team gets a key LANE issued:

```bash
lane team add Engineering 500
```

```
  created Engineering  (engineering)
  budget  $500.00 monthly  hard - requests are refused at the limit

── their key - shown once, never again ───────────────────────

  lane-sk-VaT5jKQyy8kTpT1uMaCsDl5jxjsIQeqACV4wvliihLk

── what they do with it ──────────────────────────────────────
  OPENAI_BASE_URL=http://127.0.0.1:8080/v1
  OPENAI_API_KEY=lane-sk-VaT5jKQyy8kTpT1uMaCsDl5jxjsIQeqACV4wvliihLk
```

### Key isolation

The provider keys live in exactly one place — the machine running LANE, in its
OS credential store. **Developers never hold one.** What they hold is a LANE
key scoped to their team, revocable in one command without rotating anything
upstream.

Today a leaked provider key means an emergency rotation and every team's
integration breaking at once. Here it means `lane team rotate engineering`,
and nobody else notices.

Keys are stored as SHA-256 digests. A stolen `teams.json` is a list of team
names and budgets, not a set of working credentials — LANE itself cannot show
you a key after the moment it was created.

### Budgets that actually stop

```
  Support has used $4.02 of its $4.00 budget this month.
  Raise it with `lane team budget support <amount>`.
```

Returned as **402** before the request is sent, so the money is not spent. The
estimated cost of the request is charged against the budget *before* the
comparison — a ceiling that can be crossed once per period is not a ceiling.

`--soft` warns instead of refusing, for a team that must never be
interrupted but should still be visible when it goes over.

### Where the money went

```bash
lane spend --days 30
```

```
── spend · last 30 days ──────────────────────────────────────
  Engineering
        1,284 requests      $31.40   saved $118.60
      ████████████░░░░░░░░░░ 63% of $50.00 monthly
  Support
          212 requests       $2.90   saved $18.10
      ██░░░░░░░░░░░░░░░░░░░░ 12% of $25.00 monthly

  total     $34.30
  audit      $0.71  shadow calls, billed separately
  saved    $136.70  vs claude-opus-5 throughout
```

Creating the first team is what switches authentication on. Before that LANE is
a personal tool on a laptop and demanding a key would be friction for nobody;
after it, an unauthenticated request is refused — otherwise every budget in the
system could be sidestepped by omitting a header.

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
| `lane audit` | what the routing cost in quality, measured |
| `lane quality --judge` | grade the sampled pairs |
| `lane team` | issue keys, set budgets, see who spent what |
| `lane team add <name> <budget>` | create a team and mint its key |
| `lane team rotate <id>` | new key, old one dead immediately |
| `lane spend` | what each team spent, against what budget |
| `lane doctor` | check the installation |

Useful settings: `mode`, `baseline_model`, `max_cost_per_request` (refuse a
request that could cost more than this, before spending anything),
`disabled_models`, `port`.

---

## About the prices

Model prices go stale. LANE handles that structurally rather than by hoping:

- **Anthropic prices are verified** (2026-06-24).
- **OpenAI, Google, and Groq prices are starting guesses.** `lane models` marks
  them, and any savings figure that depends on them is flagged as an estimate.
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
- **Fallback stops once content is on the wire.** A bad key, an empty credit
  balance, or a suspended account is a fact about the *provider*, not the
  request, so LANE excludes that provider and re-picks — you get
  `x-lane-degraded: anthropic unavailable` and an answer. This works for
  streaming too, because the upstream connection is opened and its first frame
  pulled *before* any response goes back. But once real content has reached the
  client, restarting on another model would splice two different answers
  together, so a stream that dies mid-flight surfaces the error in-band and
  keeps the partial text.
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
