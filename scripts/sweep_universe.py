#!/usr/bin/env python3
"""Enumerate a token universe from CoinMarketCap's keyless DEX pair listing.

    python3 scripts/sweep_universe.py                      # 7 sources, 60 pairs each
    python3 scripts/sweep_universe.py --per-source 100 --json universe.json

This is the step BEFORE `split_tape.py`: it answers "which tokens are worth splitting?".
`/v4/dex/spot-pairs/latest` returns the pairs trading on one DEX on one network, ranked by
liquidity; the tokens behind those pairs are the universe. The four worked examples in
`docs/proof/` were found by sweeping this way on 2026-09-03 and then splitting the result.

It is separate from split_tape.py on purpose. The split is the product and runs on one token
in ten seconds; the sweep is how you choose that token, costs a request per DEX per page, and
nobody should have to run it to see the demo.

THREE UNDOCUMENTED TRAPS, all found by testing against the live API and all still true:

  1. `spot-pairs/latest` REQUIRES a `dex_slug` as well as a network. The documentation says
     "at least one" of the network id-or-slug parameters is enough. It is not — without a DEX
     the call is rejected, so a universe build is a loop over DEXes, never one global request.
  2. DEX slugs are per-network and the obvious guess is often wrong: `pancakeswap-v3` is
     unsupported on BSC where v2 works, `uniswap-v3` returns zero rows on Base where
     `baseswap` works, and `aerodrome` is unsupported outright.
  3. The pagination cursor is `scroll_id` on the response ENVELOPE, not on the last row —
     the same shape trap `pull_swaps` documents for `data.lastId`.

Keyless, standard library only, and it prints what it is doing as it goes.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from split_tape import PAGE, get, is_keyed  # noqa: E402

# (network_id, dex_slug, label) — every tuple verified live 2026-09-03 and re-verified
# 2026-09-08. A slug that returns zero rows is a slug for a DEX that is not on that network,
# not an empty DEX; see trap 2.
SOURCES = [
    (1, "uniswap-v3", "ethereum"),
    (1, "uniswap-v2", "ethereum"),
    (14, "pancakeswap-v2", "bsc"),
    (16, "raydium", "solana"),
    (16, "orca", "solana"),
    (51, "uniswap-v3", "arbitrum"),
    (199, "baseswap", "base"),
]


def sweep_source(network_id, dex_slug, per_source):
    """Every base asset trading on one DEX on one network, most liquid first.

    Returns (tokens, error). The error travels back rather than raising, for the same reason
    pull_swaps returns its errors: a throttled source and a source with no pairs are different
    facts, and a sweep that cannot tell them apart blames the DEX for the rate limit.
    """
    out, seen, cursor, err = [], set(), None, None
    while len(out) < per_source:
        params = {"network_id": network_id, "dex_slug": dex_slug, "limit": min(PAGE, per_source)}
        if cursor:
            params["scroll_id"] = cursor
        res = get("/v4/dex/spot-pairs/latest", **params)
        if "_err" in res:
            err = res["_err"]
            break
        rows = res.get("data") or []
        if not rows:
            break
        for r in rows:
            addr = (r.get("base_asset_contract_address") or "").strip()
            sym = (r.get("base_asset_symbol") or "").strip()
            if not addr or addr.lower() in seen:
                continue
            seen.add(addr.lower())
            q = (r.get("quote") or [{}])[0]
            out.append(
                {
                    "symbol": sym,
                    "address": addr,
                    "platform": None,  # filled by the caller, which knows the label
                    "pair": r.get("name"),
                    "liquidity": q.get("liquidity"),
                    "volume_24h": q.get("volume_24h"),
                }
            )
            if len(out) >= per_source:
                break
        # trap 3: the cursor is on the envelope, not on the last row
        cursor = rows[-1].get("scroll_id") or res.get("scroll_id")
        if not cursor:
            break
    return out, err


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--per-source", type=int, default=60, help="tokens per DEX (default 60)")
    ap.add_argument("--json", help="write the universe to this path")
    a = ap.parse_args()

    keyed = is_keyed()
    mode = "keyed (escape hatch — the default is keyless)" if keyed else "keyless"
    print(f"sweeping the universe — {mode}, {len(SOURCES)} source(s) x {a.per_source} tokens\n")
    print(f"{'network':10}{'dex':17}{'tokens':>8}  note")
    print("-" * 62)

    started, universe, errors = time.time(), {}, []
    for net_id, dex, label in SOURCES:
        tokens, err = sweep_source(net_id, dex, a.per_source)
        for t in tokens:
            t["platform"] = label
            universe.setdefault(t["address"].lower(), t)
        note = "" if not err else err[:34]
        print(f"{label:10}{dex:17}{len(tokens):>8}  {note}")
        if err:
            errors.append({"network": label, "dex": dex, "error": err})

    elapsed = time.time() - started
    print(
        f"\n{len(universe)} distinct token(s) across {len(SOURCES)} source(s) "
        f"({elapsed:.1f}s wall clock, {'keyed' if keyed else 'keyless'})"
    )
    if errors:
        print(f"  note: {len(errors)} source(s) errored — see the note column above")
    if not universe:
        print(
            "\nno source returned a token. If every note above is a 429 this is the anonymous "
            "tier, not the endpoint: wait a few minutes and re-run.",
            file=sys.stderr,
        )
        sys.exit(75)  # EX_TEMPFAIL, same contract as split_tape.py

    print("\nsplit any of them:")
    for t in list(universe.values())[:3]:
        print(f"  python3 scripts/split_tape.py --address {t['address']} --symbol {t['symbol']}")

    if a.json:
        payload = {
            "swept_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "auth": "keyed — escape hatch, not the default path"
            if keyed
            else "none — CoinMarketCap keyless /public-api surface",
            "endpoint": "https://pro-api.coinmarketcap.com/public-api/v4/dex/spot-pairs/latest",
            "cursor": "scroll_id on the response envelope",
            "sources": [{"network_id": n, "dex_slug": d, "platform": p} for n, d, p in SOURCES],
            "count": len(universe),
            "errors": errors,
            "tokens": list(universe.values()),
        }
        Path(a.json).write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(f"\nwrote {a.json}  ({len(universe)} tokens)")


if __name__ == "__main__":
    main()
