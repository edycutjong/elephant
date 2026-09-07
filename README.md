<div align="center">

<h1>Elephant Tracks 🐘</h1>

<p><em>The tape says balanced. The split says one desk and a crowd.</em></p>

<p>Net flow is a sum, and summing is lossy. Elephant Tracks splits the tape back apart —
per-side ticket size and per-side wallet count, from real swaps.</p>

<p><strong>Live, keyless, 2026-09-07:</strong> 800 swaps across 8 tokens in <strong>9.43 s</strong>
for <strong>0 credits</strong> and no API key. CRV showed a <strong>2.2× ticket asymmetry while its
net flow read −0.1%</strong>. <a href="DEMO.md">Receipt →</a></p>

<br/>

[![Judge Guide](https://img.shields.io/badge/⚖️_Start-Here-06b6d4?style=for-the-badge)](JUDGE.md)
[![Live Run Receipt](https://img.shields.io/badge/🧾_Live_Run-Receipt-FFB020?style=for-the-badge)](DEMO.md)
[![API Feedback](https://img.shields.io/badge/📮_CMC_API-Feedback-4C9AFF?style=for-the-badge)](FEEDBACK.md)
[![Built for Build with CMC](https://img.shields.io/badge/DoraHacks-Build_with_CMC-8b5cf6?style=for-the-badge)](https://dorahacks.io/hackathon/coinmarketcap-api-202609/detail)

<br/>

![Python](https://img.shields.io/badge/Python_3.11-3776AB?style=flat&logo=python&logoColor=white)
![CoinMarketCap](https://img.shields.io/badge/CoinMarketCap_DEX_API-17181B?style=flat&logo=coinmarketcap&logoColor=white)
![No API key](https://img.shields.io/badge/API_key-not_required-4C9AFF?style=flat)
![Zero dependencies](https://img.shields.io/badge/runtime_deps-zero-5E6C80?style=flat)
[![CI](https://github.com/edycutjong/elephant-tracks/actions/workflows/ci.yml/badge.svg)](https://github.com/edycutjong/elephant-tracks/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-MIT-FFB020?style=flat)](LICENSE)

</div>

---

## 📸 See it in Action

No key. No signup. No install. One command:

```bash
python3 scripts/split_tape.py
```

```
splitting the tape — keyless, 1 page(s) x 100 swaps per token

token    swaps   avg buy $  avg sell $   ticket   buy w  sell w  net flow  note
-------------------------------------------------------------------------------
PEPE       100    1,046.74    1,039.40     1.0x      24      34     -1.6%
LINK       100    1,066.64      678.68     1.6x      34      32     40.4%
ENA        100      259.35      197.37     1.3x      25      14     27.1%
SHIB       100      197.09        0.26   772.9x       7      75     96.6%  ⚠ dust side (avg $0.255 < $1.00)
UNI        100    1,036.83      275.53     3.8x      70      19     87.5%
AAVE       100    1,102.81      310.72     3.5x      47      19     81.1%
MKR        100       90.07      341.85     3.8x      26      32    -70.1%
CRV        100      657.35      296.05     2.2x      22      40     -0.1%

HERO — rule: max ticket asymmetry among |net flow| < 5.0% (2/8 qualified)
  CRV at 2.2x while net flow reads -0.1% — a dashboard calls this balanced
  31 buys avg $657 from 22 wallets
  69 sells avg $296 from 40 wallets

net flow is one number. The split is four.
```

> **That is a live call to CoinMarketCap's keyless `/public-api` surface. Nothing here is a
> fixture.** These exact numbers are from **2026-09-07T05:09:23Z** — run it yourself and they will
> differ, because they come from the market rather than from this file. Full receipt, including the
> raw JSON: **[DEMO.md](DEMO.md)**.

**Read the CRV row.** Net flow is −0.1% — as balanced as a number gets. The split disagrees:
69 sells averaging $296 came from 40 wallets, while 31 buys averaging $657 came from 22. The buy
side is trading at 2.2× the ticket while being the smaller, more concentrated crowd.

**And read the SHIB row, which was thrown out.** It scored 772.9× off a sell side of sub-cent dust
averaging $0.255. Arithmetically perfect, completely meaningless. An earlier build printed that as
a finding; it is now disqualified on screen, with its reason. See
[Engineering Rigor](#-engineering-rigor).

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
crowd" from an inference into a **count**.

**The hero row is chosen by a published rule** — highest ticket asymmetry among tokens whose net
flow is within ±5% *and* which clear both confidence floors — so it is a screen, not a cherry-pick.
Taking the global maximum instead would pick a token a dashboard already flags as lopsided, which
proves nothing.

---

## 🏗️ Architecture & Tech Stack

```
pull the swaps  →  split by side  →  count wallets + average tickets  →  rank by asymmetry
```

No server, no database, no cache, no model. The product is one arithmetic operation applied to data
only CoinMarketCap publishes, so everything that is not the fetch or the arithmetic was removed.

| Stage | Function | What it does |
|---|---|---|
| Fetch | `get()` | One keyless GET. Backs off on 429/5xx; returns errors instead of swallowing them. |
| Paginate | `pull_swaps()` | De-duplicates on `tx`, stops when the cursor stalls, returns `(swaps, meta)`. |
| **Split** | `split()` | **The product.** Partition on `tp`; per side, `mean(v)` and `|distinct(ma)|`. |
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

| Endpoint | Used for | Key? |
|---|---|---|
| `/public-api/v1/dex/tokens/transactions` | per-swap side, USD value, maker address | ❌ none |
| `/public-api/v4/dex/spot-pairs/latest` | universe enumeration | ❌ none |
| `/public-api/v4/dex/pairs/quotes/latest` | liquidity context | ❌ none |
| `/v1/dex/holders/count` | offline holder series (not on the demo path) | ✅ |

### Why only CoinMarketCap

Most market-data APIs publish volume. Some publish trade count. **CMC publishes the individual
swaps with side, USD value and maker address together, keyless** — and the maker address is the
only reason the wallet count is available at all.

Remove CoinMarketCap and you would need a multi-chain swap indexer, a per-DEX pool registry, a
balance indexer, a wallet-labelling pipeline and a symbol→contract mapping service — five separate
systems — to recompute what one endpoint returns in one call.

We also wrote up **five dated, evidenced findings** for the CMC product team, including the one that
changed this project's entire mechanism: **[FEEDBACK.md](FEEDBACK.md)**.

---

## 📊 Engineering Rigor

| Measurement | Value |
|---|---|
| Live run wall clock | **9.43 s** — 800 swaps, 8 tokens, 8 calls |
| **Credits used** | **0** — keyless, with every CMC env var explicitly unset |
| Tests | **21** (17 offline, 4 live) |
| Regression tests named for the defect they pin | 5 |
| **Property-based verification of `split()`** | **2,000 generated tapes, 0 failing** |
| Malformed-response boundary cases | 6 |
| Aggregation latency | p50 **0.026 ms**, p95 0.027 ms (n=200) |
| Live fetch latency | p50 **1,403 ms**, p95 17,474 ms (n=8, includes one throttle backoff) |
| Coverage of `scripts/split_tape.py` | 58% — the remainder is CLI printing |

**The 2,000 is the number worth reading.** Coverage says we ran the lines we wrote. The property
test says that across 2,000 generated tapes `split()` never violated five invariants: the ratio
never dropped below 1, wallet counts never exceeded trade counts, net flow never left ±100%, the
elephant label never disagreed with the arithmetic, and **no tape marked `ok` failed to clear both
published floors.** That last one is what stops another SHIB reaching a headline.

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
Showing a disqualified row is more honest than hiding it.

---

## 🚀 Getting Started

### Prerequisites

- Python 3.11 or newer. That is the entire list.
- **No API key, no account, no `pip install`.** `split_tape.py` is stdlib-only.

### Installation

```bash
git clone https://github.com/edycutjong/elephant-tracks.git
cd elephant-tracks
python3 scripts/split_tape.py
```

> **For judges:** there is no account to create and no credential to configure — the judged path is
> keyless by design. Start at **[JUDGE.md](JUDGE.md)**.

```bash
python3 scripts/split_tape.py --address 0x6982508145454ce325ddbe47a25d4ec3d2311933 --symbol PEPE
python3 scripts/split_tape.py --json run.json      # write the full result set
```

---

## 🧪 Testing & CI

```bash
make install     # dev deps (pytest, hypothesis, ruff, pip-audit)
make lint        # ruff check + format check
make test        # 17 offline tests with coverage, no network
make test-live   # 4 tests against the real CoinMarketCap contract
make demo        # the judged capability, live, no key
make bench       # deterministic p50/p95 over the captured tape
make bench-live  # p50/p95 over the real keyless fetch
make check       # refuse to ship a placeholder to a judge
make ci          # lint + test + audit + check
```

| Layer | Tool | Status |
|---|---|---|
| Code quality | ruff (check + format) | ✅ |
| Unit testing | pytest, 17 offline tests | ✅ |
| Property testing | hypothesis, 2,000 cases | ✅ |
| Live contract testing | pytest `-m live` against real CMC | ✅ |
| Security (SAST) | CodeQL | ✅ |
| Security (SCA) | Dependabot + pip-audit | ✅ |
| Secret scanning | gitleaks, full history | ✅ |
| Release automation | semver from Angular commits | ✅ |

CI runs lint, tests, `pip-audit`, CodeQL, gitleaks, a placeholder gate, a deterministic benchmark —
**and a `live-api` job that executes the real split on every push.** It is keyless, so it runs on
forks and PRs too. If CMC changes the contract, it breaks in CI rather than in front of a judge.

---

## 📁 Project Structure

```
elephant-tracks/
├── scripts/
│   ├── split_tape.py                 the product — fetch, split, rank, print
│   ├── bench.py                      p50/p95, network and aggregation timed apart
│   ├── seed.py                       capture a tape for replay (NOT the demo path)
│   └── check_submission_readiness.py placeholder scanner
├── tests/
│   ├── test_split.py                 the maths + live contract tests
│   └── test_high_signal.py           regressions · property · boundary
├── data/seed_tape.json               a recording. Nothing judged reads it.
├── docs/proof/                       live_run.json + both benchmark receipts
├── JUDGE.md · DEMO.md · ARCHITECTURE.md · FEEDBACK.md
└── README.md                         you are here
```

---

## 🗺️ Roadmap

- [x] Per-swap aggregation from the keyless `/v1/dex/tokens/transactions`
- [x] Confidence floors so a dust side can never produce a headline
- [x] Backoff across both forms of the anonymous throttle
- [x] Live-run receipt, benchmarks, and property verification
- [ ] Hosted surface (`/`, `/app`, `/pitch`) — designed, **not built**
- [ ] Log-log ticket map with the symmetry diagonal drawn
- [ ] Quadrant classifier from the self-collected holder-count delta

---

## ⚠️ Honest limitations

- **A run measures a recent window, not 24 hours.** The `lastId` cursor does not advance on this
  endpoint, so page 2 returns the same 100 swaps as page 1. Effective depth is 100 swaps per token.
  Filed as [FEEDBACK.md](FEEDBACK.md) #4.
- **The anonymous tier throttles, and reports it as an HTTP 500** rather than a 429. Run the
  watchlist twice quickly and you will hit it. The tool backs off and retries rather than failing
  the row, so a throttled run is slow rather than broken. Filed as [FEEDBACK.md](FEEDBACK.md) #2.
- **Wallet counts are per-window** — a maker trading in two windows counts once in each. These are
  distinct-maker counts within the measured tape, not lifetime holders.
- **The 24h aggregate fields are not used, deliberately.** `24h_buy_volume` / `24h_sell_volume`
  reconcile with `volume_24h` on only **6 of 200** pairs we sampled — 55 are off by more than 100×.
  This project computes from individual swaps instead. Full evidence in
  [FEEDBACK.md](FEEDBACK.md) #1.
- **There is no web interface.** The judged capability is the CLI in this repository. A hosted
  surface is designed and not built, and claiming one would be a lie.
- **`/v1/dex/holders/trend/list` is not available on the Startup plan**, so the holder series is
  collected daily by us instead.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

## 🙏 Acknowledgments

Built for the **[Build with CMC: API Hackathon](https://dorahacks.io/hackathon/coinmarketcap-api-202609/detail)**.
Thank you to the CoinMarketCap team for exposing per-swap maker addresses on a keyless endpoint —
that single field is what made this measurable, and our feedback on the rest of the API is in
[FEEDBACK.md](FEEDBACK.md).
