#!/usr/bin/env python3
"""Split the tape: per-side average ticket and distinct wallet count, from real swaps.

Net flow is a sum, and summing is lossy. This pulls the individual swaps behind a token and
reports what the sum destroys — how large each side's trades are, and how many distinct wallets
are on each side.

Runs entirely on CoinMarketCap's KEYLESS surface. No API key, no signup — a judge runs this
file unmodified.

    python3 scripts/split_tape.py                      # default watchlist
    python3 scripts/split_tape.py --address 0x... --pages 10

Verified fields (live, 2026-09-03), /v1/dex/tokens/transactions:
    tp   'buy' | 'sell'      the side, per swap
    v    USD volume          verified: a0 * t0pu == v
    ma   maker address       lets "one desk vs a crowd" be COUNTED, not inferred
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://pro-api.coinmarketcap.com/public-api"
PAGE = 100  # hard cap: limit=200 and 500 both return HTTP 400

# ── Confidence floors (published rule — see README "Honest limitations") ──────────────
# A ratio is only as trustworthy as the two averages it divides. Both floors below were
# added after a real run put a nonsense headline on screen; each has a regression test
# named for the defect it pins.
MIN_SIDE_SWAPS = 5  # SHIB 2026-09-07: a 4-swap side is not an "average ticket"
DUST_USD = 1.00  # SHIB 2026-09-07: 96 sub-cent sells averaged $0.375 -> a fake 709x

WATCHLIST = [
    ("PEPE", "0x6982508145454ce325ddbe47a25d4ec3d2311933"),
    ("LINK", "0x514910771af9ca656af840dff83e8264ecf986ca"),
    ("ENA", "0x57e114b691db790c35207b2e685d4a43181e6061"),
    ("SHIB", "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce"),
    ("UNI", "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"),
    ("AAVE", "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9"),
    ("MKR", "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2"),
    ("CRV", "0xd533a949740bb3306d119cc777fa900ba034cd52"),
]


def get(path, **params):
    """One keyless GET. Errors are RETURNED, never swallowed — see pull_swaps."""
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=60))
    except urllib.error.HTTPError as e:
        return {"_err": f"HTTP {e.code}: {e.read().decode()[:160]}"}
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {"_err": f"{type(e).__name__}: {e}"}


def pull_swaps(address, platform="ethereum", pages=3):
    """Paginate the swap feed.

    Returns (swaps, meta). meta['error'] is None on a clean run and a string otherwise.

    The error MUST travel back to the caller. An earlier version returned a bare empty
    list on HTTP 429, so a rate-limited fetch was indistinguishable from a token that
    genuinely had no swaps — the tool blamed the token for an infrastructure failure.
    """
    seen, out, cursor, fetched, err = set(), [], None, 0, None
    for _ in range(pages):
        q = {"platform": platform, "address": address, "limit": PAGE}
        if cursor:
            q["lastId"] = cursor
        d = get("/v1/dex/tokens/transactions", **q)
        if "_err" in d:
            err = d["_err"]
            break
        batch = (d.get("data") or {}).get("swaps") or []
        if not batch:
            break
        fresh = [s for s in batch if s.get("tx") not in seen]
        for s in fresh:
            seen.add(s.get("tx"))
        out += fresh
        if not fresh:  # cursor did not advance — stop rather than spin
            break
        cursor = batch[-1].get("txId") or batch[-1].get("lgid")
        fetched += 1
        time.sleep(0.15)
    return out, {"pages": fetched, "error": err}


def _confidence(n_buy, n_sell, avg_buy, avg_sell):
    """Why this row's ratio may not mean what it appears to mean. 'ok' or a reason."""
    if min(n_buy, n_sell) < MIN_SIDE_SWAPS:
        return f"thin side ({min(n_buy, n_sell)} swaps < {MIN_SIDE_SWAPS})"
    if min(avg_buy, avg_sell) < DUST_USD:
        return f"dust side (avg ${min(avg_buy, avg_sell):.3f} < ${DUST_USD:.2f})"
    return "ok"


def split(swaps):
    """The whole product: split by side, then measure each side."""
    sides = {"buy": {"v": [], "makers": set()}, "sell": {"v": [], "makers": set()}}
    for s in swaps:
        tp = str(s.get("tp", "")).lower()
        if tp not in sides:
            continue
        try:
            v = float(s.get("v"))
        except (TypeError, ValueError):
            continue
        sides[tp]["v"].append(v)
        sides[tp]["makers"].add(s.get("ma"))

    b, s_ = sides["buy"], sides["sell"]
    if not b["v"] or not s_["v"]:
        return None
    avg_b = sum(b["v"]) / len(b["v"])
    avg_s = sum(s_["v"]) / len(s_["v"])
    total = sum(b["v"]) + sum(s_["v"])
    # Guard the division itself: a side can average exactly 0.0 if every swap is priced
    # below float resolution. The confidence gate already rejects that row, but the
    # ratio must not raise before the gate is read.
    ratio = max(avg_b / avg_s, avg_s / avg_b) if min(avg_b, avg_s) > 0 else float("inf")
    return {
        "buys": len(b["v"]),
        "sells": len(s_["v"]),
        "avg_buy": avg_b,
        "avg_sell": avg_s,
        "buy_wallets": len(b["makers"]),
        "sell_wallets": len(s_["makers"]),
        "ticket_ratio": ratio,
        "elephant_side": "buy" if avg_b > avg_s else "sell",
        "wallet_ratio": max(
            len(b["makers"]) / max(len(s_["makers"]), 1),
            len(s_["makers"]) / max(len(b["makers"]), 1),
        ),
        "net_flow_pct": (sum(b["v"]) - sum(s_["v"])) / total * 100 if total else 0.0,
        "confidence": _confidence(len(b["v"]), len(s_["v"]), avg_b, avg_s),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--address")
    ap.add_argument("--symbol", default="TOKEN")
    ap.add_argument("--platform", default="ethereum")
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--json", metavar="PATH", help="also write the full result set here")
    a = ap.parse_args()

    targets = [(a.symbol, a.address)] if a.address else WATCHLIST
    started = time.time()
    print(f"splitting the tape — keyless, {a.pages} page(s) x {PAGE} swaps per token\n")
    print(
        f"{'token':7}{'swaps':>7}{'avg buy $':>12}{'avg sell $':>12}{'ticket':>9}"
        f"{'buy w':>8}{'sell w':>8}{'net flow':>10}  note"
    )
    print("-" * 79)

    rows, errors = [], []
    for sym, addr in targets:
        swaps, meta = pull_swaps(addr, a.platform, a.pages)
        if meta["error"]:
            # An API failure is an API failure. Never let it read as a property of the token.
            errors.append((sym, meta["error"]))
            print(f"{sym:7}{'':>7}   API error — {meta['error'][:44]}")
            continue
        r = split(swaps)
        if not r:
            print(f"{sym:7}{len(swaps):7}   insufficient swaps on one side")
            continue
        r["symbol"], r["address"], r["swaps"] = sym, addr, len(swaps)
        rows.append(r)
        note = "" if r["confidence"] == "ok" else f"⚠ {r['confidence']}"
        print(
            f"{sym:7}{r['swaps']:7}{r['avg_buy']:12,.2f}{r['avg_sell']:12,.2f}"
            f"{r['ticket_ratio']:8.1f}x{r['buy_wallets']:8}{r['sell_wallets']:8}"
            f"{r['net_flow_pct']:9.1f}%  {note}"
        )

    elapsed = time.time() - started
    if not rows:
        if errors:
            sys.exit(f"\nno token produced a split — every fetch failed. First: {errors[0][1]}")
        sys.exit("no token produced a two-sided split")

    # PUBLISHED SELECTION RULE (README "How the hero row is chosen"):
    #   highest ticket asymmetry AMONG tokens that (a) read balanced (|net flow| < 5%)
    #   and (b) pass the confidence floors.
    # Taking the global max instead would pick a token a dashboard ALREADY flags as lopsided —
    # which proves nothing. The claim is that the summed number looks fine and the split does not.
    # Condition (b) exists because SHIB once scored 709x on 96 sub-cent dust sells.
    BALANCED = 5.0
    trusted = [r for r in rows if r["confidence"] == "ok"]
    balanced = [r for r in trusted if abs(r["net_flow_pct"]) < BALANCED]
    hero = None
    if not balanced:
        print(
            f"\nno token read balanced (|net flow| < {BALANCED}%) among "
            f"{len(trusted)} trusted rows in this window — widening would break the "
            "published rule; re-run rather than cherry-pick"
        )
    else:
        hero = max(balanced, key=lambda r: r["ticket_ratio"])
        print(
            f"\nHERO — rule: max ticket asymmetry among |net flow| < {BALANCED}% "
            f"({len(balanced)}/{len(rows)} qualified)"
        )
        print(
            f"  {hero['symbol']} at {hero['ticket_ratio']:.1f}x while net flow reads "
            f"{hero['net_flow_pct']:+.1f}% — a dashboard calls this balanced"
        )
        print(
            f"  {hero['buys']} buys avg ${hero['avg_buy']:,.0f} from {hero['buy_wallets']} wallets"
        )
        print(
            f"  {hero['sells']} sells avg ${hero['avg_sell']:,.0f} "
            f"from {hero['sell_wallets']} wallets"
        )
        print("\nnet flow is one number. The split is four.")

    if a.json:
        payload = {
            "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
            "wall_clock_s": round(elapsed, 2),
            "credits_used": 0,
            "auth": "none — CoinMarketCap keyless /public-api surface",
            "endpoint": f"{BASE}/v1/dex/tokens/transactions",
            "pages_per_token": a.pages,
            "page_size": PAGE,
            "rule": {
                "balanced_pct": BALANCED,
                "min_side_swaps": MIN_SIDE_SWAPS,
                "dust_usd": DUST_USD,
            },
            "rows": rows,
            "hero": hero,
            "errors": [{"symbol": s, "error": e} for s, e in errors],
        }
        with open(a.json, "w") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        print(f"\nwrote {a.json}  ({elapsed:.1f}s wall clock, 0 credits — keyless)")


if __name__ == "__main__":
    main()
