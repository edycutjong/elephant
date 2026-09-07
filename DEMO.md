# Demo — a real run, with its receipt

Everything below is a transcript of an actual run against CoinMarketCap's live API on
**2026-09-07**. No fixtures, no flags, no key. Re-run it yourself in one command; the numbers will
differ, because they come from the market rather than from this file.

## Reproduce

```bash
git clone <this repo> && cd elephant-tracks
python3 scripts/split_tape.py
```

That is the whole thing. No `pip install`, no `.env`, no signup — `split_tape.py` is stdlib-only
and the endpoint it calls is keyless. **There is no offline flag on this path, deliberately.** The
one replay mode in the repository (`scripts/bench.py --replay`) measures the aggregation over a
captured tape and is labelled a replay everywhere it appears; it is not the product.

## Receipt — live run, 2026-09-07T05:09:23Z

| | |
|---|---|
| **Wall clock** | **9.43 s**, cold start to final line |
| **Tokens measured** | 8 |
| **Swaps aggregated** | 800 (100 per token) |
| **API calls** | 8 |
| **Credits used** | **0** — the endpoint is on the keyless `/public-api` surface |
| **Credentials** | none. Run with `CMC_API_KEY`, `COINMARKETCAP_API_KEY` and `CMC_PRO_API_KEY` explicitly unset |
| **Endpoint** | `https://pro-api.coinmarketcap.com/public-api/v1/dex/tokens/transactions` |
| **Raw receipt** | [`docs/proof/live_run.json`](docs/proof/live_run.json) — every row, the rule, the hero |

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

### Read the CRV row the way a trader would

Net flow is **−0.1%**. That is as balanced as a number gets; every flow dashboard in existence
renders that as "nothing to see."

The split disagrees. **69 sells averaging $296 came from 40 wallets. 31 buys averaging $657 came
from 22 wallets.** The buy side is trading at 2.2× the sell side's ticket while being the smaller,
more concentrated crowd. That is a shape, and the summed number cannot contain it — you can always
re-add a split into a sum, and nothing recovers the split from the sum.

### The SHIB row is the honest part

SHIB scored **772.9×** and was **thrown out**, in public, on screen.

Its sell side was 75 wallets trading sub-cent dust — average ticket **$0.255**. Divide a $197 buy
ticket by that and you get a headline that is arithmetically perfect and completely meaningless.
An earlier build printed exactly that number as a finding. Rows now carry a confidence reason and
the hero rule selects only from rows clearing both published floors:

| Floor | Value | What it pins |
|---|---|---|
| `DUST_USD` | $1.00 | a side made of spam rather than participants |
| `MIN_SIDE_SWAPS` | 5 | a side too thin for "average" to mean anything |

Showing the disqualified row with its reason is more useful than hiding it. See
`test_dust_sell_side_is_not_reported_as_a_709x_elephant`.

## How the hero row is chosen — a rule, not a pick

> **Highest ticket asymmetry among tokens whose net flow reads balanced (|net flow| < 5%) and that
> clear both confidence floors.**

Taking the global maximum instead would select a token every dashboard *already* flags as lopsided,
which proves nothing. The claim is specifically that **the summed number looks fine and the split
does not**, so the candidate set has to be tokens the summed number calls fine. On this run, 2 of 8
qualified. When none qualify the tool says so and refuses to widen the window — see the
`no token read balanced` branch in `main()`.

## Benchmarks

```bash
make bench        # deterministic, replays the captured tape, no network
make bench-live   # the real keyless fetch
```

Fetch and aggregation are timed **separately**, because averaging them together would hide the only
interesting fact: the product's own work is microseconds and everything a judge waits for is
network.

| Measurement | n | p50 | p95 |
|---|---|---|---|
| Aggregation, replay ([`bench_replay.json`](docs/proof/bench_replay.json)) | 200 | **0.026 ms** | 0.026 ms |
| Fetch, live network ([`bench_live.json`](docs/proof/bench_live.json)) | 8 | **1,403 ms** | 17,474 ms |
| Aggregation, live | 8 | 0.166 ms | 2.803 ms |

That live p95 of 17.5 s is not a typo and it is not smoothed away: **one of the eight iterations hit
CMC's anonymous throttle and sat through a 15-second backoff.** That is the honest cost of a keyless
demo, and it is why the backoff exists — see the limitations below.

## Tests

| | Count |
|---|---|
| Total tests | **21** (17 offline, 4 live) |
| Regression tests, each named for the defect it pins | 5 |
| Property-based verification of `split()` | **2,000 generated tapes, 0 failing** |
| Malformed-response boundary cases | 6 |
| Coverage of `scripts/split_tape.py` | 58% (the uncovered remainder is CLI printing) |

```bash
make test        # 17 offline tests, no network
make test-live   # 4 tests against the real CMC contract
```

**The 2,000 is the number worth reading.** Coverage says we ran the lines we wrote. The property
test says that across 2,000 generated tapes, `split()` never once violated five invariants — the
ratio never dropped below 1, wallet counts never exceeded trade counts, net flow never left ±100%,
the elephant label never disagreed with the arithmetic, and **no tape marked `ok` failed to clear
both published floors.** That last one is what stops another SHIB reaching a headline. Reproduce:

```bash
pytest tests/test_high_signal.py -k invariants --hypothesis-show-statistics
# → 2000 passing, 0 failing
```

The live tests assert the **external** contract, not a return value: that `tp` is a real side, that
`a0 × t0pu == v` so `v` really is USD, and that the maker address is present — because the wallet
count is worthless without it. They are designed to fail if CoinMarketCap changes the contract.

## Honest limitations

- **A run measures a recent window, not 24 hours.** The `lastId` cursor does not advance on this
  endpoint, so page 2 returns the same 100 swaps as page 1. `--pages` exists for when that is fixed;
  today the effective depth is 100 swaps per token. Filed as `FEEDBACK.md` #4.
- **The anonymous tier throttles, and it says so with an HTTP 500.** Running the watchlist twice in
  quick succession will hit it. The tool backs off and retries rather than failing the row, but a
  throttled run is slow rather than instant. Filed as `FEEDBACK.md` #2.
- **Wallet counts are per-window.** A maker trading in two windows counts once in each. These are
  distinct-maker counts within the measured tape, not lifetime holders.
- **`24h_buy_volume` / `24h_sell_volume` are deliberately unused.** They reconcile with `volume_24h`
  on only **6 of 200** pairs we sampled; 55 are off by more than 100×. This is why the project
  computes from individual swaps. Full evidence in `FEEDBACK.md` #1.
- **There is no web interface.** The judged capability is the CLI in this repository. A hosted
  surface is planned and not built, and claiming one would be a lie.
