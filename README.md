<div align="center">

<img src="docs/assets/icon.svg" alt="Elephant Tracks icon" width="144">

<h1>Elephant Tracks 🐘</h1>

<p><em>The tape says balanced. The split says one wallet and a crowd.</em></p>

<img src="docs/assets/hero.svg" alt="Elephant Tracks — net flow reads +2.1% while one wallet is 62.0% of AUSD’s sell side." width="900">

<p>Net flow is a sum, and summing is lossy. Elephant Tracks splits the tape back apart —
per side, how much of it is <strong>one wallet</strong> — from real swaps and their maker addresses.</p>

<p><strong>Live, keyless, 2026-09-07:</strong> 800 swaps of AUSD in <strong>29.4 s</strong>
for <strong>0 credits</strong> and no API key. <strong>One wallet was 62.0% of the sell side —
$25,459,824 in 12 swaps — into 212 buying wallets, while net flow read
+2.1%.</strong> <a href="DEMO.md">Receipt →</a></p>

<p><a href="https://elephant.edycu.dev">elephant.edycu.dev</a> · <a href="https://elephant.edycu.dev/pitch/">pitch deck</a> · <a href="https://youtu.be/I1yOhXSutAk">2:45 demo</a></p>

<br/>

[![Judge Guide](https://img.shields.io/badge/⚖️_Start-Here-06b6d4?style=for-the-badge)](JUDGE.md)
[![Demo video](https://img.shields.io/badge/▶️_2:45-Demo_video-FF0000?style=for-the-badge)](https://youtu.be/I1yOhXSutAk)
[![Landing page](https://img.shields.io/badge/🐘_elephant.edycu.dev-Landing-0B0E14?style=for-the-badge)](https://elephant.edycu.dev)
[![Pitch Deck](https://img.shields.io/badge/📊_Pitch-Deck-f59e0b?style=for-the-badge)](https://elephant.edycu.dev/pitch/)
[![Live Run Receipt](https://img.shields.io/badge/🧾_Live_Run-Receipt-FFB020?style=for-the-badge)](DEMO.md)
[![API Feedback](https://img.shields.io/badge/📮_CMC_API-Feedback-4C9AFF?style=for-the-badge)](FEEDBACK.md)
[![Built for Build with CMC](https://img.shields.io/badge/DoraHacks-Build_with_CMC-8b5cf6?style=for-the-badge)](https://dorahacks.io/hackathon/coinmarketcap-api-202609/detail)

<br/>

![Python](https://img.shields.io/badge/Python_3.11-3776AB?style=flat&logo=python&logoColor=white)
![CoinMarketCap](https://img.shields.io/badge/CoinMarketCap_DEX_API-17181B?style=flat&logo=coinmarketcap&logoColor=white)
![No API key](https://img.shields.io/badge/API_key-not_required-4C9AFF?style=flat)
![Zero dependencies](https://img.shields.io/badge/runtime_deps-zero-5E6C80?style=flat)
[![CI](https://github.com/edycutjong/elephant/actions/workflows/ci.yml/badge.svg)](https://github.com/edycutjong/elephant/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/edycutjong/elephant?sort=semver&color=FFB020)](https://github.com/edycutjong/elephant/releases/latest)
[![License](https://img.shields.io/badge/License-MIT-FFB020?style=flat)](LICENSE)

</div>

---

## 📸 See it in Action

No key. No signup. No install. One command:

```bash
python3 scripts/split_tape.py --address 0x00000000efe302beaa2b3e6e1b18d08d69a9012a --symbol AUSD --pages 8 --json ausd.json
```

```
splitting the tape — keyless, 8 page(s) x 100 swaps per token

token    swaps   avg buy $  avg sell $   ticket   buy w  sell w  top buy  top sell  net flow  note
--------------------------------------------------------------------------------------------------
AUSD       800   91,699.61  123,273.10     1.3x     212     111    11.7%     62.0%      2.1%  

HERO — rule: max top-maker share of either side among |net flow| < 5.0% (1/1 qualified)
  AUSD: one wallet is 62.0% of the sell side while net flow reads +2.1% — a dashboard calls this balanced
  sell: $25,459,824 in 12 swaps from 0x9f681e397f51137215b8240b8bf4e523d898661b
  buy: 467 swaps from 212 distinct wallets, largest 11.7%
  supporting: 467 buys avg $91,700 · 333 sells avg $123,273 · ticket ratio 1.3x

net flow is one number. The split is four.

wrote ausd.json  (29.4s wall clock, 0 credits — keyless)
```

> **That is a live call to CoinMarketCap's keyless `/public-api` surface. Nothing here is a
> fixture.** These exact numbers are from **2026-09-07T07:00:52Z** — run it yourself and they will
> differ, because they come from the market rather than from this file. The full receipt, including
> the 12 raw swap records behind the top seller, is committed at
> [`docs/proof/ausd.json`](docs/proof/ausd.json) and walked through in **[DEMO.md](DEMO.md)**.

**Read the AUSD row.** Net flow is +2.1% — every flow dashboard in existence renders that as
"balanced". Split the same 800 swaps by maker address and the sell side is **62.0% one
wallet** — $25,459,824 across 12 swaps — sold into **212 distinct buying wallets**, the largest
of which is 11.7%. That is one seller distributing to a crowd, and the summed number cannot
contain it.

**The default run is the eight-token watchlist** (`python3 scripts/split_tape.py`, one page each). It
applies the same published rule, and when no token reads balanced it says so on screen rather than
widening the band — on the 2026-09-07T07:11:15Z run, none did. Transcript in [DEMO.md](DEMO.md).

---

## 💡 The Problem & Solution

### The Problem

Every DEX flow tool reduces the tape to one signed number: buy volume minus sell volume.

That number **cannot** distinguish the two situations a trader most needs to tell apart:

| | net flow |
|---|---|
| One desk selling $27,000 clips to 4,000 people buying $180 clips | ≈ 0 |
| 4,000 matched trades of the same size | ≈ 0 |

Same number. Opposite market structures. One is distribution into retail; the other is churn.

### The Solution

**Summing is lossy and cannot be inverted.** You can always re-add a split back into a sum; nothing
recovers the split from the sum. So we never sum — we pull the individual swaps and measure each
side separately.

CoinMarketCap's `/v1/dex/tokens/transactions` returns, per swap: the **side** (`tp`), the **USD
value** (`v`), and the **maker address** (`ma`). That last field is what turns "one desk against a
crowd" from an inference into a **measurement**: per side, sum `v` per `ma`, and the largest
wallet's share of the side is the number.

**The hero row is chosen by a published rule** — highest top-maker share of either side among
tokens whose net flow is within ±5% *and* which clear both confidence floors — so it is a screen,
not a cherry-pick. Taking the global maximum instead would pick a token a dashboard already flags
as lopsided, which proves nothing.

**Why maker share and not ticket size.** The first version headlined average buy ticket ÷ average
sell ticket. At flat net flow buy volume ≈ sell volume, so that ratio collapses to the count ratio
(`n_sells / n_buys`) — one quantity measured twice; across 54 flat tokens the two agreed to within a
median 5.8%, and the best real value was 5.2×. Maker share is a second, independent quantity. The
ticket ratio stays as a supporting column.

---

## 🏗️ Architecture & Tech Stack

```
pull the swaps  →  split by side  →  attribute each side to its makers  →  rank by concentration
```

<img src="docs/assets/architecture.png" alt="Elephant Tracks architecture: two keyless CoinMarketCap endpoints feed a stdlib-only Python pipeline — sweep_universe.py picks a token, then get, pull_swaps, split, _confidence and main turn raw swaps into a ranked row — emitting a table, a JSON receipt, and a site rendered from those receipts." width="100%">

No server, no database, no cache, no model. The product is one arithmetic operation applied to data
only CoinMarketCap publishes, so everything that is not the fetch or the arithmetic was removed.

| Stage | Function | What it does |
|---|---|---|
| Fetch | `get()` | One GET, keyless by default — a key exported as `CMC_API_KEY` is an optional escape hatch for a throttled IP. Backs off on 429/5xx; returns errors instead of swallowing them; explains an exhausted throttle instead of printing a body. |
| Paginate | `pull_swaps()` | Cursor is `data.lastId` on the response envelope; de-duplicates on `(tx, lgid)`; returns `(swaps, meta)`. |
| **Split** | `split()` | **The product.** Partition on `tp`; per side, `Σ v` per `ma` → the top wallet's share, plus `mean(v)` and `|distinct(ma)|`. |
| Gate | `_confidence()` | Is this ratio meaningful at all? Dust floor + minimum swaps per side. |
| Rank | `main()` | Apply the published hero rule, print the table, emit JSON. |

| Layer | Technology |
|---|---|
| Language | Python 3.11, **stdlib only** on the judged path |
| Data | CoinMarketCap DEX API, keyless `/public-api` surface |
| Tests | pytest · **hypothesis** (property-based) · live contract tests |
| Quality | ruff · pip-audit · gitleaks · CodeQL · Dependabot |

Full derivation, including every failure mode and the deliberate non-architecture:
**[ARCHITECTURE.md](ARCHITECTURE.md)**.

---

## 🏆 CoinMarketCap Integration

| Endpoint | Used for | Key? | Called from |
|---|---|---|---|
| `/public-api/v1/dex/tokens/transactions` | per-swap side, USD value, maker address — **the engine** | ❌ none | [`scripts/split_tape.py`](scripts/split_tape.py) |
| `/public-api/v4/dex/spot-pairs/latest` | enumerating a token universe, to choose what to split | ❌ none | [`scripts/sweep_universe.py`](scripts/sweep_universe.py) |
| `/public-api/v4/dex/pairs/quotes/latest` | evaluated and **rejected** — its `24h_buy_volume` / `24h_sell_volume` are the aggregates this project exists to argue against | ❌ none | *nothing — see below* |
| `/v1/dex/holders/count` | how many addresses hold the token — context for the share | ❌ none | [`scripts/split_tape.py`](scripts/split_tape.py) |

The one `Called from` gap is deliberate and worth stating plainly, because a table of endpoint
names proves nothing on its own:

- **`pairs/quotes/latest`** returns volume and trade count per side, which is where this project
  started. [FEEDBACK.md §7](FEEDBACK.md) derives why it was abandoned: at flat net flow the
  ticket ratio those fields produce reduces to the count ratio — the same quantity measured
  twice, exactly where a hidden asymmetry would be worth finding. It is listed because rejecting
  it is a finding, not because we call it.
- **`holders/count`** is called once per run, for the hero row only. It answers keyless — the
  parameter is `tokenAddress` in camelCase, and `address`, which every neighbouring endpoint
  takes, returns error 4002 here. That is why it reads as key-only until you guess the casing.
  It is context, not an input: "one wallet is 62.0% of the sell side" reads differently for a
  token held by 1,150 addresses than for one held by 382,000. The published selection rule
  never sees it — adding a signal to the ranking after publishing the rule would be moving the
  target.

Everything else is runnable right now, with no key:

```bash
make sweep    # /v4/dex/spot-pairs/latest  -> a universe, ~9 s, 0 credits
make demo     # /v1/dex/tokens/transactions -> the split
```

### Why only CoinMarketCap

Most market-data APIs publish volume. Some publish trade count. **CMC publishes the individual
swaps with side, USD value and maker address together, keyless** — and the maker address is the
only reason the wallet count is available at all.

Remove CoinMarketCap and you would need a multi-chain swap indexer, a per-DEX pool registry, a
balance indexer, a wallet-labelling pipeline and a symbol→contract mapping service — five separate
systems — to recompute what one endpoint returns in one call.

We also wrote up **seven dated, evidenced findings** for the CMC product team, including the one that
changed this project's entire mechanism: **[FEEDBACK.md](FEEDBACK.md)**.

---

## 📊 Engineering Rigor

| Measurement | Value |
|---|---|
| Live run wall clock | **29.4 s** — 800 swaps of one token, 8 calls, clean path · **10.0 s** — the 8-token watchlist |
| **Credits used** | **0** — keyless, with every CMC env var explicitly unset |
| Tests | **81** (76 offline, 5 live) |
| Regression tests named for the defect they pin | 12 |
| **Property-based verification of `split()`** | **2,000 generated tapes, 0 failing** |
| Malformed-response boundary cases | 6 |
| Aggregation latency | p50 **0.026 ms**, p95 0.026 ms (n=200) |
| Live fetch latency | p50 **1,403 ms**, p95 17,474 ms (n=8, includes one throttle backoff) |
| Coverage of `scripts/` | **100%** of 1,195 statements — `make test` fails under it |

**The 2,000 is the number worth reading.** Coverage says we ran the lines we wrote. The property
test says that across 2,000 generated tapes `split()` never violated six invariants: the ratio
never dropped below 1, wallet counts never exceeded trade counts, net flow never left ±100%, the
elephant label never disagreed with the arithmetic, **the top-maker share never escaped its own
denominator** (0–1, attributed to a wallet on that side, never more volume than the side), and **no
tape marked `ok` failed to clear both published floors.** That last one is what stops another SHIB
reaching a headline.

```bash
pytest tests/test_high_signal.py -k invariants --hypothesis-show-statistics
# → 2000 passing, 0 failing
```

### The confidence floors, and why they exist

`ticket_ratio` divides two means. A mean over four trades is an anecdote; a mean over sub-cent dust
is spam. Both produce arithmetically correct ratios that mean nothing — and on 2026-09-07 one of
them reached the headline.

| Floor | Value | Pins |
|---|---|---|
| `DUST_USD` | $1.00 | a side made of spam rather than participants |
| `MIN_SIDE_SWAPS` | 5 | a side too thin for "average" to mean anything |

Rows failing either are still printed, **with the reason**, and excluded from hero selection.
Showing a disqualified row is more honest than hiding it. On 2026-09-07 an earlier build printed
SHIB at 772.9× off 75 sub-cent sells; the floors exist because of that row.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11 or newer. That is the entire list.
- **No API key, no account, no `pip install`.** `split_tape.py` is stdlib-only.

### Installation

```bash
git clone https://github.com/edycutjong/elephant.git
cd elephant
python3 scripts/split_tape.py
```

> **For judges:** there is no account to create and no credential to configure — the judged path is
> keyless by design. Start at **[JUDGE.md](JUDGE.md)**.

> **If CoinMarketCap's anonymous tier is throttling your IP**, the script backs off (15 s, 30 s,
> 60 s) and, if the quota is exhausted, stops with a message that says so rather than printing a
> number. Optional escape hatch: a free key from [coinmarketcap.com/api](https://coinmarketcap.com/api)
> exported as `CMC_API_KEY` moves the identical call to the keyed endpoint. Never required — the
> default path is keyless and every receipt here was taken with no key set.

```bash
python3 scripts/split_tape.py --address 0x00000000efe302beaa2b3e6e1b18d08d69a9012a --symbol AUSD --pages 8 --json ausd.json   # the headline, 800 swaps
python3 scripts/split_tape.py --address 0x6982508145454ce325ddbe47a25d4ec3d2311933 --symbol PEPE
python3 scripts/split_tape.py --json run.json      # the watchlist, full result set
```

---

## 🧪 Testing & CI

```bash
make install     # dev deps (pytest, hypothesis, ruff, pip-audit) + the chromium the QA gates drive
make lint        # ruff check + format check
make test        # 76 offline tests, coverage gated at 100%, no internet
make test-live   # 5 tests against the real CoinMarketCap contract
make demo        # the judged capability, live, no key
make bench       # deterministic p50/p95 over the captured tape
make bench-live  # p50/p95 over the real keyless fetch
make site        # re-render the landing page, the deck and JUDGE.md from docs/proof/*.json
python3 scripts/qa_site.py   # 229 measured gates on the web surfaces (needs playwright + pillow)
make check       # refuse to ship a placeholder, or a page that drifted from its receipts
make ci          # lint + test + audit + check
```

| Layer | Tool | Status |
|---|---|---|
| Code quality | ruff (check + format) | ✅ |
| Unit testing | pytest, 76 offline tests | ✅ |
| Property testing | hypothesis, 2,000 cases | ✅ |
| Live contract testing | pytest `-m live` against real CMC | ✅ |
| Security (SAST) | CodeQL | ✅ |
| Security (SCA) | Dependabot + pip-audit | ✅ |
| Secret scanning | gitleaks, full history | ✅ |
| Release automation | semver from Angular commits | ✅ |

CI runs lint, tests, `pip-audit`, CodeQL, gitleaks, a placeholder gate, a deterministic benchmark —
**and a `live-api` job that executes the real split on every push.** It is keyless, so it runs on
forks and PRs too. If CMC changes the contract, it breaks in CI rather than in front of a judge.

**The landing page, the deck and JUDGE.md are generated, never hand-edited.**
`scripts/render_site.py` renders `site/index.html`, `site/pitch/index.html` and `JUDGE.md` from
the templates in `scripts/site_templates/` and the receipts in `docs/proof/`. Every figure on any
of the three is a `{{token}}` filled from a committed JSON receipt; the render aborts if any slot
is left unfilled, and CI re-renders all three and fails on any diff. So no number a judge reads can
be typed in by hand, none can be a placeholder, and none can drift from the run that produced it —
the landing page and the judge guide cannot disagree, because they are the same render.

**The web surfaces are measured, not eyeballed.** `scripts/qa_site.py` drives both pages in headless
Chromium and runs 229 gates: no horizontal overflow at 375 / 768 / 1440, every link and image
resolves, a page height budget on phones, every text node — SVG text included — at or above WCAG AA contrast as actually painted, with
opacity flattened onto the background (minimum 5.65:1, gated against regression), the social card
measured from its own PNG header and description lengths counted, heading levels, prose-link
underlines and table headers checked, every interactive element proven to change on hover by
screenshot byte-diff, all eleven slides reachable by keyboard and inside the stage, the page
rendering with every external request blocked, `prefers-reduced-motion` leaving zero running
animations, and the animation itself sampled with the clock paused — the staged split must hold
the summed bar alone first, never reverse, never snap, and end in exactly the reduced-motion
frame; the one loop on the page must collapse and recover exactly once per cycle with zero
velocity across its seam. The suite drives the whole harness — `tests/test_qa_site.py` runs it
against the committed pages, and against a page built to fail so that every gate is shown able
to fail. Those tests skip where chromium is absent, which is why the browser gates are a local
gate and not a CI one. Installing a browser on the runner was tried and measured (#7): 228 of the
229 gates pass on ubuntu, and the mobile height budget fails there by 9 px — the landing page
shapes to 8,966 px on macOS and 9,009 px on ubuntu, against 34 px of headroom. That is a
text-shaping difference between platforms, and a budget is not something to widen until a runner
fits inside it.

---

## 📁 Project Structure

```
elephant/
├── scripts/
│   ├── split_tape.py                 the product — fetch, split, rank, print
│   ├── bench.py                      p50/p95, network and aggregation timed apart
│   ├── seed.py                       capture a tape for replay (NOT the demo path)
│   ├── render_site.py                renders site/ and JUDGE.md from docs/proof/*.json — no hand-typed numbers
│   ├── qa_site.py                    229 measured gates on the two web surfaces (Playwright)
│   ├── site_templates/               landing.html, deck.html, JUDGE.md — {{token}} slots, fail if unfilled
│   └── check_submission_readiness.py placeholder scanner
├── tests/
│   ├── test_split.py                 the maths + live contract tests
│   ├── test_high_signal.py           regressions · property · boundary
│   ├── test_fetch_contract.py        what get() and pull_swaps() promise their callers
│   ├── test_cli.py                   every main(), through its own __main__ guard
│   ├── test_render_site.py           the generator, against the real receipts
│   ├── test_qa_site.py               the browser harness — and a page built to fail it
│   └── test_published_counts.py      the test count on five surfaces vs the suite
├── site/                             generated: landing page (/) and deck (/pitch), dated snapshots
├── data/seed_tape.json               a recording. Nothing judged reads it.
├── docs/proof/                       ausd/shfl/bingo/gme.json receipts, live_run.json, benchmarks
├── JUDGE.md · DEMO.md · ARCHITECTURE.md · FEEDBACK.md
└── README.md                         you are here
```

---

## 🗺️ Roadmap

- [x] Per-swap aggregation from the keyless `/v1/dex/tokens/transactions`
- [x] Confidence floors so a dust side can never produce a headline
- [x] Backoff across both forms of the anonymous throttle; an exhausted quota explains itself
- [x] Optional keyed escape hatch (`CMC_API_KEY`) for a throttled IP — the default stays keyless
- [x] Live-run receipts, benchmarks, and property verification
- [x] Cursor pagination that actually advances (`data.lastId`), `(tx, lgid)` identity
- [x] Maker attribution per side — the top wallet's share, distribution and top ten
- [x] Landing page and pitch deck (static, dated receipts) at elephant.edycu.dev
- [x] Quadrant map on maker share: distribution · accumulation · wash-shaped · churn
- [ ] Hosted live tool with a token input — **not built, and not just for lack of time.**
      CMC omits `Access-Control-Allow-Origin` ([FEEDBACK.md §6](FEEDBACK.md)), so a browser
      cannot call it and a server-side hop is required. That hop then puts every visitor
      behind one IP against a **per-IP** anonymous rate limit — the same limit that turns
      CI red when several jobs start at once. Run from a clone, every reader gets their own
      quota; run from a shared proxy, the tenth reader in a minute gets a 429. A hosted tool
      would be *less* reliable than the CLI unless it carried our key, which the CLI
      deliberately does not need.

---

## ⚠️ Honest limitations

- **A run measures a recent window, not 24 hours.** Depth is `--pages` × 100 swaps; the published
  receipts use 8 pages. For a stablecoin that window spans days, for a meme coin minutes. (Until
  2026-09-07 our paginator read the cursor off the last swap instead of the envelope's `data.lastId`,
  so every earlier number came from a single 100-swap window. Fixed, pinned by a test, and written
  up in [FEEDBACK.md](FEEDBACK.md) #4.)
- **A wallet is not an entity.** One entity can spread across wallets, which makes the share a
  floor; a router or aggregator can pool many users into one maker, which inflates it. The number
  is "share of the side attributed to one address", exactly as the API reports it.
- **The anonymous tier throttles, per IP, and reports it as HTTP 500 as often as 429.** Run the
  watchlist twice quickly and you hit the short throttle; the tool backs off (15 s, 30 s, 60 s)
  and retries rather than failing the row, so that run is slow rather than broken. On 2026-09-07,
  roughly 3,700 calls from one IP in a day exhausted the quota outright — three backoffs did not
  recover it — and the run stopped with a message that says so and names the way through: wait,
  or export a free key as `CMC_API_KEY`. The key is an escape hatch, never a precondition; every
  receipt here was taken with every CMC variable unset. Filed as [FEEDBACK.md](FEEDBACK.md) #2.
- **Wallet counts are per-window** — a maker trading in two windows counts once in each. These are
  distinct-maker counts within the measured tape, not lifetime holders.
- **The 24h aggregate fields are not used, deliberately.** `24h_buy_volume` / `24h_sell_volume`
  reconcile with `volume_24h` on only **6 of 200** pairs we sampled — 55 are off by more than 100×.
  This project computes from individual swaps instead. Full evidence in
  [FEEDBACK.md](FEEDBACK.md) #1.
- **The web surface is a snapshot, not a live tool.** [elephant.edycu.dev](https://elephant.edycu.dev)
  and its `/pitch` deck carry dated receipts with the command that produced them. CoinMarketCap sends
  no `Access-Control-Allow-Origin`, so a static page cannot call the API; the live capability is the
  CLI in this repository.
- **`/v1/dex/holders/trend/list` is not available on the Startup plan**, so the holder series is
  collected daily by us instead.

---

## 📽️ Demo Materials

| | |
|---|---|
| **Demo video** | **[youtu.be/I1yOhXSutAk](https://youtu.be/I1yOhXSutAk)** — 2:45, captioned. The run at 0:39 is a real keyless execution at real speed; nothing is sped up, and the terminal carries the label saying so. |
| **Landing page** | **[elephant.edycu.dev](https://elephant.edycu.dev)** — the receipt beside its raw swaps. A dated snapshot, and it says so on every number. |
| **Pitch deck** | **[elephant.edycu.dev/pitch](https://elephant.edycu.dev/pitch/)** — 11 slides, arrow keys, `P` for notes. |
| **For judges** | **[JUDGE.md](JUDGE.md)** — the 30-second path. |
| **The receipt** | **[DEMO.md](DEMO.md)** — the live run transcribed, with [`docs/proof/ausd.json`](docs/proof/ausd.json) behind it. |
| **Submission** | **[dorahacks.io/buidl/48344](https://dorahacks.io/buidl/48344)** — the BUIDL page for Build with CMC, Data and Visualisation track. |

The video's numbers and the landing page's differ slightly — 61.7% against 62.0% — because the
800-swap window moved between the two runs. Same wallet, same $25,459,824, same 12 swaps. The video
says so on camera rather than hiding it: a number that moves with the market is the evidence it is
live.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

## 🙏 Acknowledgments

Built for the **[Build with CMC: API Hackathon](https://dorahacks.io/hackathon/coinmarketcap-api-202609/detail)**,
**Data & Visualisation** track.
Thank you to the CoinMarketCap team for exposing per-swap maker addresses on a keyless endpoint —
that single field is what made this measurable, and our feedback on the rest of the API is in
[FEEDBACK.md](FEEDBACK.md).
