# For judges

Everything you need in one page. No setup, no key, no account.

## The claim

**Net flow is a sum, and summing is lossy. Elephant Tracks splits the tape back apart — per-side
average ticket and per-side wallet count — and shows you the market structure the summed number
mathematically cannot contain.**

## The 30-second path

There is no hosted app to click. This is a command-line tool, and that is the whole install:

```bash
git clone <this repo> && cd elephant-tracks
python3 scripts/split_tape.py
```

1. **Nothing else is required.** No `pip install` (the file is stdlib-only), no `.env`, no API key,
   no signup. If either step above needs more than what is printed, that is a bug — file it.
2. **Watch the `note` column.** One token per run typically gets thrown out, on screen, with its
   reason. That is the product refusing to hand you a number it does not trust.
3. **Read the HERO block.** It names a token whose net flow reads balanced and whose split does not.
   The selection rule is printed above it, so you can check that it is a screen rather than a pick.

Full annotated transcript with the receipt: **[DEMO.md](DEMO.md)**.

## Receipt — live run, 2026-09-07T05:09:23Z

| | |
|---|---|
| Wall clock | **9.43 s** |
| Swaps aggregated | **800** across 8 tokens |
| API calls | 8 |
| **Credits used** | **0** — keyless `/public-api` surface |
| Credentials | none; run with every CMC env var explicitly unset |
| Tests | **21** (17 offline, 4 live), 5 named after the defect they pin |
| **Property verification** | **2,000 generated tapes, 0 failing** — `split()` never violated five invariants |
| Aggregation latency | p50 **0.026 ms** (p95 0.027 ms, n=200) |
| Live fetch latency | p50 **1,403 ms** (p95 17,474 ms — one iteration sat through a throttle backoff) |
| Raw receipts | [`docs/proof/live_run.json`](docs/proof/live_run.json) · [`bench_live.json`](docs/proof/bench_live.json) · [`bench_replay.json`](docs/proof/bench_replay.json) |

The headline from that run: **CRV showed a 2.2× ticket asymmetry while its net flow read −0.1%.**
69 sells averaging $296 from 40 wallets, against 31 buys averaging $657 from 22. Every flow
dashboard renders −0.1% as "balanced."

## Reproduce

```bash
python3 scripts/split_tape.py                    # the product, live, keyless
make test                                        # 17 offline tests
make test-live                                   # 4 tests against the real CMC contract
pytest tests/test_high_signal.py -k invariants --hypothesis-show-statistics   # the 2,000
```

**CI / deterministic replay — this is not the product:**

```bash
make bench    # scripts/bench.py --replay, measures aggregation over a captured tape
```

`--replay` reads `data/seed_tape.json`, a recording made by `scripts/seed.py`. It exists so the
benchmark is comparable across runs and so CI works behind a rate limit. **Nothing on the judged
path reads it.** `scripts/split_tape.py` always fetches live and has no offline flag.

## Why only CoinMarketCap

`/v1/dex/tokens/transactions` returns, per individual swap and with no key: the **side** (`tp`), the
**USD value** (`v`, verified as `a0 × t0pu == v`), and the **maker address** (`ma`).

`ma` is the one that matters. Side and value give an average ticket, which is an inference about
"one desk versus a crowd." The maker address makes it a **count**. Remove CoinMarketCap and
reproducing this needs a multi-chain swap indexer, a per-DEX pool registry, a wallet-labelling
pipeline and a symbol-to-contract mapping service — four systems to recover what one keyless call
returns.

## Honest limitations

- **Effective depth is 100 swaps per token, not 24 hours.** The `lastId` cursor does not advance on
  this endpoint, so page 2 returns page 1's swaps. `--pages` is there for when that is fixed.
- **The anonymous tier throttles**, and reports it as an HTTP 500 rather than a 429. Run the
  watchlist twice quickly and you will hit it; the tool backs off and retries instead of failing,
  so a throttled run is slow rather than broken.
- **There is no web interface.** The judged capability is this CLI. A hosted surface is designed
  (`/`, `/app`, `/pitch`) and not built — claiming one would be a lie.
- **The 24h aggregate buy/sell volume fields are unusable** and deliberately unused: they reconcile
  with `volume_24h` on 6 of 200 sampled pairs. That finding is the reason this project computes from
  individual swaps, and it is written up for the CMC team in [FEEDBACK.md](FEEDBACK.md).

## Links

| | |
|---|---|
| **Run it** | [DEMO.md](DEMO.md) — annotated transcript + receipt |
| **How it works** | [ARCHITECTURE.md](ARCHITECTURE.md) — derived from the code, not the design notes |
| **API feedback for CMC** | [FEEDBACK.md](FEEDBACK.md) — five dated, evidenced findings |
| **The product** | [`scripts/split_tape.py`](scripts/split_tape.py) — 200 lines, stdlib only |
| **The tests** | [`tests/test_high_signal.py`](tests/test_high_signal.py) |
| Live demo · video · BUIDL | not yet published — see the README for current status |
