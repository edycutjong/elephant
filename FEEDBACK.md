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

The limit itself is undocumented, and it has two horizons. The short one clears in under a
minute — a 15 s backoff usually rides it out. The long one does not: on 2026-09-07, after
**roughly 3,700 calls from one IP in a day**, backoffs of 15 s + 30 s + 60 s did not recover the
anonymous surface, while the identical request with a key succeeded immediately. In that state the
same exhausted quota came back sometimes as the 429/1022 above and sometimes as the 500. Nothing
in a successful response lets a client see this coming: the keyless 200 carries **no rate-limit
headers at all** (no `X-RateLimit-*`, no `Retry-After`), and its envelope reports
`credit_count: 1` on every call — a charge against an account that does not exist, which reads as
"this is metered" to a developer trying to work out whether the surface is free.

For a keyless integration this matters more than it sounds: our judged demo is one command with
no credential, and a reader whose IP has spent the day's quota cannot tell an exhausted tier from
an outage. We now detect the condition and say so — and we added an optional key as an escape
hatch — but the API could make that unnecessary.

**Why it matters:** 429 means "retry with backoff" and 500 means "we broke, this is not your
fault." Returning the first condition with the second status code teaches every client to do the
wrong thing — either give up on a recoverable error, or hammer a genuinely failing service. It
also makes the API look less reliable than it is: our first instinct was "CMC is down," and it
was not. **A 429 with `Retry-After` would let clients behave correctly with no guesswork; a
published anonymous quota (per minute and per day) would let a keyless client budget for it.**

---

## 3. `limit` silently caps at 100, and exceeding it is a 400 rather than a clamp

**Observed 2026-09-03 · `/v1/dex/tokens/transactions` · severity: medium**

`limit=200` and `limit=500` both return HTTP 400. The working maximum is 100. Most paginated
APIs clamp an over-large `limit` to the maximum and return what they can; this one rejects the
call. The cap is also not stated on the endpoint's own documentation page, so it is found by
trial. **Document the cap, or clamp instead of rejecting.**

---

## 4. The pagination cursor is on the envelope, and nothing says so

**Observed 2026-09-03 and 2026-09-07 · severity: medium**

The request parameter is `lastId`. The value to feed it is `data.lastId` on the **response
envelope** — not a field on the last swap. Every swap carries a `txId` and an `lgid`, both of which
look like cursors and neither of which is one. Our first paginator read `txId` off the last swap,
the server accepted it without complaint, and page 2 quietly returned page 1 again. Every number in
this project before 2026-09-07 came from a single 100-swap window because of that. Read from the
envelope, the cursor advances cleanly: 864 unique swaps over 10 pages on one token.

A second identity trap sits next to it: **neither `tx` nor `lgid` is a unique swap key.** One page
of 100 swaps carried 89 distinct `tx` (a routed trade emits several swaps under one hash) and 91
distinct `lgid` (log indexes repeat across transactions). De-duplicating on `tx` alone silently
discards ~11% of real swaps. The pair `(tx, lgid)` is the identity.

**Why it matters:** an accepted-but-wrong cursor produces a plausible-looking result set that is
wrong, with no error to catch. **Document `data.lastId` beside the `lastId` parameter on the same
page, reject a cursor value that is not one of yours, and state which field pair identifies a
swap.**

---

## 5. `/v1/dex/holders/trend/list` is not available on the Startup plan

**Observed 2026-09-03 · severity: low**

Not a bug — a packaging note. The endpoint is visible in the catalogue and returns a plan error
in use, so the plan requirement is discovered at integration time rather than at read time.
Marking plan requirements on the endpoint listing would save the round trip.

## 6. Three of the four CORS headers are sent; `Access-Control-Allow-Origin` is not

**Observed 2026-09-08 · `/public-api/v1/dex/tokens/transactions` · severity: medium**

A successful keyless `200` carries three CORS headers and omits the only one browsers gate on:

```
access-control-allow-headers:  origin, accept, DNT, ... X-CMC_PRO_API_KEY
access-control-allow-methods:  OPTIONS, HEAD, GET, POST, PUT, DELETE, PATCH
access-control-max-age:        600
access-control-allow-origin:   (absent)
```

The `OPTIONS` preflight answers `200` with the same three. So the preflight succeeds, the
request goes out, the response arrives — and the browser then discards it, because without
`Access-Control-Allow-Origin` there is no origin it is allowed to hand the body to. Verified
from a real page rather than inferred from the headers: a `fetch()` for that exact URL from
`https://elephant.edycu.dev` fails with `TypeError: Failed to fetch`.

**Why it matters:** this does not read like a policy decision to keep browsers out. A service
that meant to refuse cross-origin reads would not publish `allow-methods`, `allow-headers` and
a ten-minute `max-age` — that is a CORS configuration with one header missing. The cost falls
on exactly the integrations the keyless surface seems designed to invite: anyone building a
web page on it must stand up a server-side hop whose only job is to copy the response and add
one header, which also puts every one of their visitors behind a single IP against a per-IP
anonymous rate limit.

**What would fix it:** `Access-Control-Allow-Origin: *` on the `/public-api` surface. The data
is already public and unauthenticated; the header would let it be read where it is already
being served. If the concern is the keyed surface, sending it only on `/public-api` would be
enough to unblock every keyless browser integration without touching authenticated traffic.

## 7. Volume and count per side collapse to one number exactly where it matters

**Derived, then confirmed against the DEX pair object · severity: low (a docs note, not a bug)**

`24h_buy_volume` / `24h_sell_volume` and `24h_no_of_buys` / `24h_no_of_sells` look like two
independent signals, and the obvious thing to do with them is divide: volume over count is an
average ticket per side, and the buy:sell ticket ratio should say whether one side trades in
bigger clips than the other. That is the metric this project set out to build.

It is the same number twice, and the algebra says so:

```
ticket_ratio = (buyVol / nBuy) / (sellVol / nSell)
             = (buyVol / sellVol) x (nSell / nBuy)
```

The first factor is net flow expressed as a quotient. So **whenever net flow is flat — the one
case where a hidden asymmetry is worth finding — `buyVol ≈ sellVol`, the first factor goes to 1,
and the ticket ratio degenerates to `nSell / nBuy`: the count ratio.** The two field families
carry one signal between them precisely where a consumer needs two.

**Why it matters:** this is not a defect, and nothing needs to change in the response. But it is
the sort of thing a consumer discovers only after building on it, and one sentence in the field
reference — that the aux volume and count fields are not independent at flat net flow — would
save that trip. It is also why this project reads the per-swap feed instead: `maker address` on
`/v1/dex/tokens/transactions` is a genuinely independent axis, and it is the reason the product
exists in the form it does.

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
