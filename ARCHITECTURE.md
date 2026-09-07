# Architecture

Derived from the code in this repository, not from a design document. Every function named
below exists in `scripts/`; every line reference was read out of the file.

## Shape of the thing

Elephant Tracks is a **single-pass aggregation over a paginated feed**. There is no server, no
database, no cache and no model. That is a deliberate consequence of the mechanism: the product
is one arithmetic operation applied to data that only CoinMarketCap publishes, so everything
that is not the fetch or the arithmetic has been removed.

```
                       CoinMarketCap keyless /public-api
                                    │
                    /v1/dex/tokens/transactions?limit=100
                                    │
                                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  get()          one HTTP GET, backoff on 429 / 5xx          │
  │                 errors RETURNED, never swallowed            │
  └─────────────────────────────────────────────────────────────┘
                                    │  raw JSON
                                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  pull_swaps()   paginate by lastId, de-duplicate on `tx`,    │
  │                 stop when the cursor stops advancing         │
  │                 returns (swaps, {pages, error})              │
  └─────────────────────────────────────────────────────────────┘
                                    │  list[swap]
                                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  split()        THE PRODUCT. Partition on `tp`, then per     │
  │                 side: mean(`v`) and |distinct(`ma`)|         │
  │                 -> avg ticket, wallet count, ratio, net flow │
  └─────────────────────────────────────────────────────────────┘
                                    │  row
                                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  _confidence()  is this row's ratio meaningful at all?       │
  │                 dust floor + minimum swaps per side          │
  └─────────────────────────────────────────────────────────────┘
                                    │  row + confidence
                                    ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  main()         rank, apply the published hero rule,         │
  │                 print the table, optionally emit JSON        │
  └─────────────────────────────────────────────────────────────┘
```

## The three fields the whole product rests on

`/v1/dex/tokens/transactions` returns one object per swap. Three of its fields carry the entire
mechanism:

| Field | Type | What it makes possible |
|---|---|---|
| `tp` | `"buy"` \| `"sell"` | The **side, per swap**. Without a per-swap side there is nothing to split. |
| `v` | USD volume | The **ticket size**. Verified live: `a0 × t0pu == v` (tested in `test_live_v_really_is_usd`). |
| `ma` | maker address | The **wallet count**. This is the field that turns "one desk against a crowd" from an inference into a measurement. |

`ts`, `tx`, `en` (timestamp, tx hash, exchange) are carried through for provenance and
de-duplication but do not enter the arithmetic.

## The arithmetic, in full

There is no hidden step. For a list of swaps:

```
buys   = [v for swap in swaps if tp == "buy"]
sells  = [v for swap in swaps if tp == "sell"]

avg_buy       = mean(buys)
avg_sell      = mean(sells)
buy_wallets   = |{ma for swap in swaps if tp == "buy"}|
sell_wallets  = |{ma for swap in swaps if tp == "sell"}|

ticket_ratio  = max(avg_buy / avg_sell, avg_sell / avg_buy)      # always >= 1
net_flow_pct  = (sum(buys) - sum(sells)) / (sum(buys) + sum(sells)) * 100
```

`net_flow_pct` is computed **only so it can be shown losing**. It is the number every other tool
reports; printing it beside the ratio is what makes the disagreement visible in one row.

## Why the confidence gate exists

`ticket_ratio` divides two means. A mean over four trades is an anecdote, and a mean over
sub-cent dust is spam. Both produce arithmetically correct ratios that mean nothing, and on
2026-09-07 one of them (SHIB, 709.1x off 96 sells averaging $0.375) reached the headline.

`_confidence()` gates every row on two published floors:

| Floor | Value | Pins |
|---|---|---|
| `MIN_SIDE_SWAPS` | 5 swaps | a side too thin to average |
| `DUST_USD` | $1.00 | a side made of spam rather than participants |

A row that fails either is still printed, with its reason, and is **excluded from hero
selection**. Showing it and disqualifying it is more honest than hiding it.

## Failure handling

Every failure mode maps to a distinct outcome, because conflating them is how a tool ends up
blaming a token for an outage:

| Condition | Behaviour |
|---|---|
| HTTP 429 / any 5xx | Transient. Retried up to `RETRIES` times with exponential backoff (15s, 30s, 60s). |
| Any other 4xx | Permanent. Returned immediately — retrying a 400 wastes the reader's time. |
| Transport error / bad JSON | Returned as `meta["error"]`. |
| Well-formed 200, unusable body | `split()` returns `None`. Never a fabricated number. |
| One side empty | `split()` returns `None`. |

`pull_swaps` returns `(swaps, meta)` specifically so an API error can never be reported as a
property of the token.

## Repository layout

```
scripts/
  split_tape.py                 the product — fetch, split, rank, print
  bench.py                      p50/p95, network and aggregation timed separately
  seed.py                       capture a real tape for offline replay (NOT the demo path)
  check_submission_readiness.py placeholder scanner
tests/
  test_split.py                 the maths, plus live tests against the real contract
  test_high_signal.py           regressions, one property-based verification, the boundary
data/
  seed_tape.json                a recording. Nothing on the judged path reads it.
docs/proof/
  live_run.json                 receipt from a real run
  bench_live.json               timings, live
  bench_replay.json             timings, deterministic
```

## Deliberate non-architecture

| Not present | Why |
|---|---|
| Database | Every number is recomputed from a live fetch. There is nothing to persist. |
| Cache | A cached tape is a stale tape; the whole claim is about the current window. |
| Server | The judged capability is a CLI. A web surface is planned but not built, and claiming one would be a lie. |
| Auth | The endpoint is keyless. Adding auth would remove the best property this project has. |
| Runtime dependencies | `split_tape.py` is stdlib-only, so `python3 scripts/split_tape.py` works on a clean machine with no install step. |
