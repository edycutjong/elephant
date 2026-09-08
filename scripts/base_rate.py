#!/usr/bin/env python3
"""How often does a balanced net flow hide one wallet owning half a side?

    python3 scripts/base_rate.py                       # 30 tokens, 2 pages each
    python3 scripts/base_rate.py --tokens 60 --json docs/proof/base_rate.json

`split_tape.py` shows that net flow *can* hide concentration, on four worked tokens. That is a
demonstration. This measures how often it happens across a population, which is a different and
much harder claim to wave away — the four tokens were chosen by a published rule, but they were
still four tokens somebody chose.

METHOD, stated before the number so it cannot be tuned afterwards:

  population   the most liquid pairs on 7 (network, DEX) sources, via
               /v4/dex/spot-pairs/latest — the same universe `sweep_universe.py` builds.
  measured     each token's swaps via /v1/dex/tokens/transactions, split by maker.
  denominator  tokens whose net flow reads BALANCED (|net flow| < 5%) AND clear the same
               confidence floors the product uses (>= 5 swaps a side, no dust side). A token
               that fails those is excluded, not counted as a negative — the ratio would not
               have been trustworthy either way.
  numerator    of those, the ones where a single wallet holds more than HALF of either side.

WHAT THIS IS NOT. The population is liquidity-ranked, so it is a base rate *among actively
traded tokens on major DEXes*, not among all tokens. A run measures a window, not 24 hours. A
wallet is not an entity. All three are stated in the receipt beside the number.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from split_tape import BALANCED, is_keyed, pull_swaps, split  # noqa: E402
from sweep_universe import SOURCES, sweep_source  # noqa: E402

HALF = 0.50  # "one wallet owns more of this side than everyone else combined"


def build_population(per_source, verbose=True):
    """Distinct tokens across every source, most liquid first."""
    universe, errors = {}, []
    for net_id, dex, label in SOURCES:
        tokens, err = sweep_source(net_id, dex, per_source)
        for t in tokens:
            t["platform"] = label
            universe.setdefault(t["address"].lower(), t)
        if err:
            errors.append({"network": label, "dex": dex, "error": err})
        if verbose:
            print(f"  {label:10}{dex:17}{len(tokens):>5} token(s){'  ' + err[:30] if err else ''}")
    return list(universe.values()), errors


def measure(tokens, pages, verbose=True):
    """Split every token. Returns (rows, skipped) — skipped says why, so nothing vanishes."""
    rows, skipped = [], []
    for i, t in enumerate(tokens, 1):
        swaps, meta = pull_swaps(t["address"], t["platform"], pages)
        if not swaps:
            skipped.append({"symbol": t["symbol"], "why": meta.get("error") or "no swaps"})
            if verbose:
                print(f"  [{i:>3}/{len(tokens)}] {t['symbol']:12} — skipped")
            continue
        r = split(swaps)
        if not r:
            skipped.append({"symbol": t["symbol"], "why": "one side empty"})
            continue
        r["symbol"], r["platform"] = t["symbol"], t["platform"]
        r["swaps_measured"], r["pages_fetched"] = len(swaps), meta["pages"]
        r["partial"] = bool(meta.get("error")) and bool(swaps)
        rows.append(r)
        if verbose:
            top = max(r["sell_top_share"], r["buy_top_share"])
            print(
                f"  [{i:>3}/{len(tokens)}] {t['symbol']:12}{len(swaps):>5} swaps  "
                f"net {r['net_flow_pct']:+7.1f}%  top maker {top * 100:5.1f}%"
                f"{'  ' + r['confidence'] if r['confidence'] != 'ok' else ''}"
            )
    return rows, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tokens", type=int, default=30, help="tokens to measure (default 30)")
    ap.add_argument("--per-source", type=int, default=8, help="tokens per DEX in the sweep")
    ap.add_argument("--pages", type=int, default=2, help="pages of 100 swaps per token")
    ap.add_argument("--json", help="write the receipt here")
    a = ap.parse_args()

    started = time.time()
    print(
        f"base rate — {'keyed' if is_keyed() else 'keyless'}, |net flow| < {BALANCED}% "
        f"is 'balanced', one wallet > {HALF * 100:.0f}% of a side is 'concentrated'\n"
    )

    print("building the population")
    population, sweep_errors = build_population(a.per_source)
    population = population[: a.tokens]
    print(f"\nmeasuring {len(population)} token(s), {a.pages} page(s) each\n")
    rows, skipped = measure(population, a.pages)

    # The denominator is decided by the SAME gates the product uses, not by anything chosen here.
    trusted = [r for r in rows if r["confidence"] == "ok"]
    balanced = [r for r in trusted if abs(r["net_flow_pct"]) < BALANCED]
    concentrated = [r for r in balanced if max(r["sell_top_share"], r["buy_top_share"]) > HALF]

    shares = sorted(max(r["sell_top_share"], r["buy_top_share"]) for r in balanced)
    median = shares[len(shares) // 2] if shares else None
    rate = len(concentrated) / len(balanced) if balanced else None

    # A single threshold is one number and it is tunable — move HALF and the headline moves
    # with it. The distribution is not: it shows the whole shape and lets a reader pick their
    # own line. If the tail is thin, that is the finding, and it is reported either way.
    def pct(q):
        return shares[min(int(q * len(shares)), len(shares) - 1)] if shares else None

    dist = {f"p{int(q * 100)}": pct(q) for q in (0.5, 0.75, 0.9, 0.95, 0.99)}
    dist["max"] = shares[-1] if shares else None

    # A denominator in the tens deserves an interval, not a bare percentage. Wilson rather than
    # the normal approximation: at these counts the normal interval runs past 0 and 1 and
    # reports a precision the sample does not have.
    def wilson(k, n, z=1.96):
        if not n:
            return None
        ph, z2 = k / n, z * z
        centre = (ph + z2 / (2 * n)) / (1 + z2 / n)
        half = z * ((ph * (1 - ph) / n + z2 / (4 * n * n)) ** 0.5) / (1 + z2 / n)
        return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]

    ci = wilson(len(concentrated), len(balanced))

    print(f"\n{'-' * 66}")
    print(f"  measured                     {len(rows):>4}")
    print(f"  trusted (confidence gates)   {len(trusted):>4}")
    print(f"  of those, reading balanced   {len(balanced):>4}   <- the denominator")
    print(f"  with one wallet over {HALF * 100:.0f}%     {len(concentrated):>4}   <- the numerator")
    if rate is not None:
        print(
            f"\n  BASE RATE: {rate * 100:.0f}% of balanced tokens hide a wallet holding "
            f"more than half a side"
        )
        print(
            f"             {len(concentrated)}/{len(balanced)}, 95% CI "
            f"{ci[0] * 100:.0f}-{ci[1] * 100:.0f}% — a denominator this size is a signal, "
            f"not a measurement"
        )
        print(f"  median top-maker share among balanced tokens: {median * 100:.1f}%")
        print("\n  distribution of the top maker's share, among balanced tokens:")
        for k, v in dist.items():
            if v is not None:
                print(f"    {k:>4}  {v * 100:5.1f}%")
    else:
        print("\n  no token read balanced in this window — the rate is undefined, not zero.")

    elapsed = time.time() - started
    print(f"\n  {elapsed:.0f}s wall clock, {'keyed' if is_keyed() else '0 credits — keyless'}")

    if a.json:
        payload = {
            "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "auth": "keyed" if is_keyed() else "none — CoinMarketCap keyless /public-api surface",
            "method": {
                "population": "most liquid pairs on 7 (network, DEX) sources"
                " via /v4/dex/spot-pairs/latest",
                "measured_with": "/v1/dex/tokens/transactions, split by maker address",
                "pages_per_token": a.pages,
                "balanced_pct": BALANCED,
                "concentrated_threshold": HALF,
                "denominator": "tokens reading balanced that also clear the"
                " product's confidence floors",
            },
            "counts": {
                "measured": len(rows),
                "trusted": len(trusted),
                "balanced": len(balanced),
                "concentrated": len(concentrated),
                "skipped": len(skipped),
            },
            "base_rate": rate,
            "base_rate_95ci_wilson": ci,
            "median_top_share_among_balanced": median,
            "top_share_distribution_among_balanced": dist,
            "limitations": [
                "The population is liquidity-ranked, so this is a base rate among actively traded "
                "tokens on major DEXes, not among all tokens.",
                "Each token is measured over a window of pages x 100 swaps, not 24 hours.",
                "A wallet is not an entity: the share is a floor when one entity holds many "
                "wallets, and inflated when a router pools many users.",
            ],
            "balanced_rows": [
                {
                    "symbol": r["symbol"],
                    "platform": r["platform"],
                    "swaps": r["swaps_measured"],
                    "net_flow_pct": round(r["net_flow_pct"], 3),
                    "top_share": round(max(r["sell_top_share"], r["buy_top_share"]), 4),
                    "side": "sell" if r["sell_top_share"] >= r["buy_top_share"] else "buy",
                    "partial": r["partial"],
                }
                for r in sorted(
                    balanced, key=lambda x: -max(x["sell_top_share"], x["buy_top_share"])
                )
            ],
            "skipped": skipped,
            "sweep_errors": sweep_errors,
        }
        Path(a.json).write_text(json.dumps(payload, indent=2, sort_keys=True))
        print(f"  wrote {a.json}")

    if rate is None:
        sys.exit(75)


if __name__ == "__main__":
    main()
