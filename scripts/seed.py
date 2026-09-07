#!/usr/bin/env python3
"""Capture a real tape to data/seed_tape.json for deterministic replay.

WHAT THIS IS: a recording of real swaps, fetched live from CoinMarketCap and written to
disk with its provenance (endpoint, timestamp, address). It exists so `bench.py --replay`
and the offline tests can run without network — in CI, on a plane, behind a rate limit.

WHAT THIS IS NOT: the demo path. Nothing in the judged flow reads this file. The product
is `scripts/split_tape.py`, which always fetches live. If you ever find yourself pointing
the demo at the seed tape, stop — that is the exact substitution that sinks submissions.

    python3 scripts/seed.py                    # capture the default token
    python3 scripts/seed.py --address 0x... --pages 3
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from split_tape import active_base, api_key, pull_swaps, split  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "data" / "seed_tape.json"
UNI = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--address", default=UNI)
    ap.add_argument("--symbol", default="UNI")
    ap.add_argument("--platform", default="ethereum")
    ap.add_argument("--pages", type=int, default=1)
    a = ap.parse_args()

    surface = "keyed endpoint (escape hatch)" if api_key()[0] else "keyless endpoint"
    print(f"capturing {a.symbol} from the live {surface}...")
    swaps, meta = pull_swaps(a.address, a.platform, a.pages)
    if meta["error"]:
        sys.exit(f"capture failed: {meta['error']}")
    if not swaps:
        sys.exit("capture returned no swaps — nothing to seed")

    result = split(swaps)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "_note": "A RECORDING, not the demo path. scripts/split_tape.py always "
                "fetches live. This file exists only for offline replay in bench "
                "and tests.",
                "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "source": f"{active_base()}/v1/dex/tokens/transactions",
                "symbol": a.symbol,
                "address": a.address,
                "platform": a.platform,
                "pages": a.pages,
                "swap_count": len(swaps),
                "split_at_capture": result,
                "swaps": swaps,
            },
            indent=2,
            sort_keys=True,
        )
    )
    print(f"wrote {OUT} — {len(swaps)} swaps")
    if result:
        print(
            f"  at capture: {result['buys']} buys avg ${result['avg_buy']:,.0f} / "
            f"{result['sells']} sells avg ${result['avg_sell']:,.0f} "
            f"({result['ticket_ratio']:.1f}x, {result['confidence']})"
        )


if __name__ == "__main__":
    main()
