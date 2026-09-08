# Demo — a real run, with its receipt

Everything below is a transcript of an actual run against CoinMarketCap's live API on
**2026-09-07**. No fixtures, no flags, no key. Re-run it yourself in one command; the numbers will
differ, because they come from the market rather than from this file.

## Reproduce

```bash
git clone https://github.com/edycutjong/elephant.git && cd elephant
python3 scripts/split_tape.py --address 0x00000000efe302beaa2b3e6e1b18d08d69a9012a --symbol AUSD --pages 8 --json ausd.json
```

That is the whole thing. No `pip install`, no `.env`, no signup — `split_tape.py` is stdlib-only
and the endpoint it calls is keyless. **There is no offline flag on this path, deliberately.** The
one replay mode in the repository (`scripts/bench.py --replay`) measures the aggregation over a
captured tape and is labelled a replay everywhere it appears; it is not the product.

**29.4 s is the clean-path time.** The endpoint is CoinMarketCap's shared anonymous tier, which is
rate-limited per IP. If it is throttling when you run, the script backs off (15 s, 30 s, 60 s) and
the run is slower; if the quota from your IP is exhausted outright, it stops with a message that
says so and names the two ways through — wait a few minutes, or export a free key from
[coinmarketcap.com/api](https://coinmarketcap.com/api) as `CMC_API_KEY`, which moves the identical
call to the keyed endpoint. The key is an escape hatch, never a requirement: the receipt below was
taken with every CMC variable unset, and a keyed run announces itself on its first line, its last
line and in its receipt, so it can never pass as this one.

An exhausted quota exits **75** (`EX_TEMPFAIL`), separately from the exit 1 that any other
failure gives. A rate limit is a fact about the caller's IP at that minute, not about this tool
or about CMC's contract, and a script — or a CI job — that cannot tell the two apart will either
learn to ignore a real break or start treating one as noise. Our own CI reports exit 75 as a
warning and fails on everything else.

## Receipt — live run, 2026-09-07T07:00:52Z

| | |
|---|---|
| **Wall clock** | **29.4 s**, cold start to final line — the clean-path time; no backoff fired on this run |
| **Token** | AUSD on Ethereum, `0x00000000efe302beaa2b3e6e1b18d08d69a9012a` |
| **Swaps aggregated** | 800 (8 pages × 100) |
| **API calls** | 8 |
| **Credits used** | **0** — the endpoint is on the keyless `/public-api` surface |
| **Credentials** | none. Run with `CMC_API_KEY`, `COINMARKETCAP_API_KEY` and `CMC_PRO_API_KEY` explicitly unset |
| **Endpoint** | `https://pro-api.coinmarketcap.com/public-api/v1/dex/tokens/transactions` |
| **Cursor** | `data.lastId` on the response envelope · swaps keyed by `(tx, lgid)` |
| **Raw receipt** | [`docs/proof/ausd.json`](docs/proof/ausd.json) — the row, the rule, and the 12 raw swaps behind the top seller |

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

### Read the AUSD row the way a trader would

Net flow is **+2.1%**. Every flow dashboard in existence renders that as "nothing to see."

The split disagrees. **333 sells came from 111 wallets, and one of those wallets is
62.0% of the sell side** — $25,459,824 across 12 swaps. The **467 buys came from 212 distinct
wallets**, the largest of which is 11.7%. One address distributing to a crowd, and the summed
number cannot contain it — you can always re-add a split into a sum, and nothing recovers the split
from the sum.

### Check it by hand

Three fields in the receipt row: `sell_top_vol` ÷ `sell_vol` = 25,459,823.58 ÷ 41,049,940.76 =
0.6202. The receipt's `hero_evidence` block carries the 12 raw swap records whose
maker is the top seller and whose side is `sell`, verbatim from the API; their `v` fields sum to
`sell_top_vol`. Supporting columns: 467 buys averaging $91,700, 333 sells averaging
$123,273, ticket ratio 1.3× — which is exactly why ticket size was never the story.

### The same wallet, three runs

The AUSD receipt was taken three times on 2026-09-07 — 06:40, 06:45 and 07:00 UTC — and every run
returned the same wallet at the same 62.0% with the same $25,459,824. A stablecoin's 800-swap
window moves slowly; the finding is persistent, not a snapshot artefact.

### The watchlist run, 2026-09-07T07:11:15Z — and the honest branch

```
splitting the tape — keyless, 1 page(s) x 100 swaps per token

token    swaps   avg buy $  avg sell $   ticket   buy w  sell w  top buy  top sell  net flow  note
--------------------------------------------------------------------------------------------------
PEPE       100      890.56      495.60     1.8x      29      27    48.8%     33.7%     50.7%  
LINK       100       65.34      684.73    10.5x      24      45    31.8%     23.0%    -89.8%  
ENA        100      523.52      284.57     1.8x      12      21    38.1%     48.8%    -24.0%  
SHIB       100       90.36        9.66     9.4x      14      63    56.4%     43.4%     24.6%  
UNI        100    1,250.81      208.63     6.0x      43      31    21.6%     37.1%     80.0%  
AAVE       100    3,952.88    1,767.66     2.2x      20      36    84.9%     71.4%     -7.0%  
MKR        100       41.27      166.72     4.0x      25      24    23.8%     18.6%    -73.7%  
CRV        100      350.76      222.87     1.6x      31      24    27.0%     18.2%     24.2%  

no token read balanced (|net flow| < 5.0%) among 8 trusted rows in this window — widening would break the published rule; re-run rather than cherry-pick
```

No token on the default watchlist read balanced in that window, so the tool refused to name a hero
rather than widen the band. That refusal is the product working; see the rule below.

### The SHIB row is the honest part

On an earlier run SHIB scored **772.9×** and was **thrown out**, in public, on screen: its sell side
was 75 wallets trading sub-cent dust, average ticket **$0.255**. Rows carry a confidence reason and
the hero rule selects only from rows clearing both published floors:

| Floor | Value | What it pins |
|---|---|---|
| `DUST_USD` | $1.00 | a side made of spam rather than participants |
| `MIN_SIDE_SWAPS` | 5 | a side too thin for "average" to mean anything |

Showing the disqualified row with its reason is more useful than hiding it. See
`test_dust_sell_side_is_not_reported_as_a_709x_elephant`.

## How the hero row is chosen — a rule, not a pick

> **Highest top-maker share of either side among tokens whose net flow reads balanced
> (|net flow| < 5%) and that clear both confidence floors.**

Taking the global maximum instead would select a token every dashboard *already* flags as lopsided,
which proves nothing. The claim is specifically that **the summed number looks fine and the split
does not**, so the candidate set has to be tokens the summed number calls fine. When none qualify the tool says so and refuses to widen the window — see the
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
| Total tests | **111** (106 offline, 5 live) |
| Regression tests, each named for the defect it pins | 12 |
| Property-based verification of `split()` | **2,000 generated tapes, 0 failing** |
| Malformed-response boundary cases | 6 |
| Coverage of `scripts/` | **100%** of 1,195 statements, gated — `make test` fails under 100% |

```bash
make test        # 106 offline tests, no internet
make test-live   # 5 tests against the real CMC contract
```

**The 2,000 is the number worth reading.** Coverage says we ran the lines we wrote. The property
test says that across 2,000 generated tapes, `split()` never once violated six invariants — the
ratio never dropped below 1, wallet counts never exceeded trade counts, net flow never left ±100%,
the elephant label never disagreed with the arithmetic, the top-maker share never escaped its own
denominator, and **no tape marked `ok` failed to clear both published floors.** That last one is what stops another SHIB reaching a headline. Reproduce:

```bash
pytest tests/test_high_signal.py -k invariants --hypothesis-show-statistics
# → 2000 passing, 0 failing
```

The live tests assert the **external** contract, not a return value: that `tp` is a real side, that
`a0 × t0pu == v` so `v` really is USD, and that the maker address is present — because the wallet
count is worthless without it. They are designed to fail if CoinMarketCap changes the contract.

## Honest limitations

- **A run measures a recent window, not 24 hours.** Depth is `--pages` × 100 swaps. Until 2026-09-07
  the paginator read the cursor off the last swap instead of the envelope's `data.lastId` and never
  advanced; fixed, pinned by `test_cursor_is_read_from_the_envelope_not_from_the_last_swap`, and
  written up in `FEEDBACK.md` #4.
- **A wallet is not an entity.** One entity can span wallets (the share is a floor); a router can
  pool many users into one maker (it inflates). The number is the address-level share, no more.
- **The anonymous tier throttles, per IP, and reports it as HTTP 500 as often as 429.** Running the
  watchlist twice in quick succession hits the short throttle; the tool backs off (15 s, 30 s, 60 s)
  and retries rather than failing the row, so that run is slow rather than broken. On 2026-09-07,
  roughly 3,700 calls from one IP in a day exhausted the quota outright — three backoffs did not
  recover it — and the run stopped with a message that says so and names the way through: wait a
  few minutes, or export a free key as `CMC_API_KEY`. The key is an escape hatch, never a
  precondition; every receipt in this file was taken with every CMC variable unset. Filed as
  `FEEDBACK.md` #2.
- **Wallet counts are per-window.** A maker trading in two windows counts once in each. These are
  distinct-maker counts within the measured tape, not lifetime holders.
- **`24h_buy_volume` / `24h_sell_volume` are deliberately unused.** They reconcile with `volume_24h`
  on only **6 of 200** pairs we sampled; 55 are off by more than 100×. This is why the project
  computes from individual swaps. Full evidence in `FEEDBACK.md` #1.
- **The web surface is a snapshot.** [elephant.edycu.dev](https://elephant.edycu.dev) and `/pitch`
  carry these receipts; CMC sends no `Access-Control-Allow-Origin`, so a static page cannot call the
  API. The live capability is this CLI.
