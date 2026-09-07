# Feedback on the CoinMarketCap API

Written for the CMC product team, who asked for exactly this. Every item below was hit while
building [Elephant Tracks](README.md) against the live API — nothing here is speculative, and
each finding carries the date it was observed and the evidence that produced it.

The headline: **`/v1/dex/tokens/transactions` is the best endpoint in the DEX catalogue and it
is the one nobody seems to know about.** Two of the five items below are about protecting it.

---

## 1. `24h_buy_volume` / `24h_sell_volume` do not reconcile with `volume_24h`

**Observed 2026-09-03 · 200 Ethereum pairs (uniswap-v2 + v3) · severity: high**

This is the finding that changed the whole project. We sampled 200 pairs and compared
`24h_buy_volume + 24h_sell_volume` against the same object's `volume_24h`:

| Check | Result |
|---|---|
| buy/sell **counts** populated | 189 / 200 |
| buy/sell **volumes** populated | 112 / 200 |
| volumes **reconcile** to `volume_24h` (within 0.8–1.25×) | **6 / 200** |

The distribution is not a rounding problem — **55 of 200 pairs are off by more than 100×**:

| `(buyVol + sellVol) / volume_24h` | Pairs |
|---|---|
| `< 0.01` | 55 |
| `0.01 – 0.1` | 14 |
| `0.1 – 0.8` | 37 |
| `≈ 1.0` | 6 |

Concretely: **WETH/USDT reports `buyVol + sellVol = 243` against `volume_24h = 47,649,031`.**
No unit or denomination conversion produces that gap.

**Why it matters:** the counts are trustworthy and the volumes are not, which is the worst
possible combination — the pair looks internally consistent, so a developer computes
`volume ÷ count` for an average ticket and ships a wrong number without ever seeing a warning.
We nearly did. **Either populate these fields consistently or document that they are partial**;
right now they read as authoritative.

---

## 2. Throttling is reported as HTTP 500, which is indistinguishable from an outage

**Observed 2026-09-07 · anonymous/keyless tier · severity: high**

The anonymous tier expresses one condition — you are going too fast — in two different ways:

```
HTTP 429   error_code 1022   "You've reached the limit for anonymous access..."
HTTP 500   error_code 500    "The system is busy, please try again later!"
```

We implemented backoff on 429 first. The very next run failed with **eight consecutive HTTP
500s**, because under sustained load the same throttle surfaces as a 5xx instead.

**Why it matters:** 429 means "retry with backoff" and 500 means "we broke, this is not your
fault." Returning the first condition with the second status code teaches every client to do the
wrong thing — either give up on a recoverable error, or hammer a genuinely failing service. It
also makes the API look less reliable than it is: our first instinct was "CMC is down," and it
was not. **A 429 with `Retry-After` would let clients behave correctly with no guesswork.**

---

## 3. `limit` silently caps at 100, and exceeding it is a 400 rather than a clamp

**Observed 2026-09-03 · `/v1/dex/tokens/transactions` · severity: medium**

`limit=200` and `limit=500` both return HTTP 400. The working maximum is 100. Most paginated
APIs clamp an over-large `limit` to the maximum and return what they can; this one rejects the
call. The cap is also not stated on the endpoint's own documentation page, so it is found by
trial. **Document the cap, or clamp instead of rejecting.**

---

## 4. Cursor pagination on the swaps endpoint is hard to use correctly

**Observed 2026-09-03 and 2026-09-07 · severity: medium**

There is a cursor, but the parameter name and the field it should be fed from are not obvious.
We pass `lastId` and read the next cursor from the last swap in the batch, trying `txId` then
`lgid`, because no single documented field pairs with the request parameter. Our first
implementation did not advance the cursor at all and silently re-fetched page one — which we
only caught because we de-duplicate on `tx`.

**Why it matters:** a paginator that silently repeats page one produces a plausible-looking
result set that is wrong. **Name the request parameter and the response field it comes from on
the same documentation page, or return an explicit `next_cursor`.**

---

## 5. `/v1/dex/holders/trend/list` is not available on the Startup plan

**Observed 2026-09-03 · severity: low**

Not a bug — a packaging note. The endpoint is visible in the catalogue and returns a plan error
in use, so the plan requirement is discovered at integration time rather than at read time.
Marking plan requirements on the endpoint listing would save the round trip.

---

## What is genuinely excellent, and worth protecting

`/v1/dex/tokens/transactions` returns, **per swap, keyless**:

| Field | Value |
|---|---|
| `tp` | the side of that individual trade |
| `v` | its USD value — and `a0 × t0pu == v` holds exactly, which is rarer than it sounds |
| `ma` | **the maker address** |

`ma` is the one we want to single out. Side and USD value give an average ticket; the maker
address turns "one desk against a crowd" from an inference into a **count**. We are not aware of
another major market-data API that returns per-swap side, USD value and maker identity together
in one call, with no key.

Elephant Tracks exists because of that field. Two independent idea-adjudication panels
flagged this endpoint as the largest under-used surface in the catalogue, and we agree — **the
issue is discovery, not capability.** The aggregate pair fields in item 1 are prominent and
unreliable; this endpoint is obscure and correct. Swapping their prominence would materially
improve what developers build on CMC.

---

*Filed by [@edycutjong](https://x.com/edycutjong) for the Build with CMC: API Hackathon.
Reproduce any item above with `python3 scripts/split_tape.py` — no key required.*
