#!/usr/bin/env python3
"""Reproducible benchmark: how long does splitting a tape actually take?

Two things are timed separately, because they have completely different characters:

    fetch   one keyless call to /v1/dex/tokens/transactions (network-bound, variable)
    split   the aggregation itself (CPU-bound, deterministic)

Reporting them together would hide the only interesting fact: the product's own work is
microseconds, and every millisecond a judge waits is network. Keeping them apart is what
makes the number honest.

    python3 scripts/bench.py                 # live fetch + split, 10 iterations
    python3 scripts/bench.py --replay        # split only, against the committed seed tape

--replay needs no network and is therefore deterministic, which makes it the right thing
for CI. It is NOT the product: it measures the aggregation over a captured tape. The live
path above is the judged one.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from split_tape import pull_swaps, split  # noqa: E402

SEED = Path(__file__).resolve().parents[1] / "data" / "seed_tape.json"
UNI = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"


def pct(values, p):
    """Nearest-rank percentile — no interpolation, so a p95 is always a real observation."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def report(label, samples_ms, unit="ms"):
    print(
        f"  {label:22} n={len(samples_ms):<4} "
        f"p50 {pct(samples_ms, 50):9.3f}{unit}   "
        f"p95 {pct(samples_ms, 95):9.3f}{unit}   "
        f"max {max(samples_ms):9.3f}{unit}"
    )
    return {
        "n": len(samples_ms),
        "p50": round(pct(samples_ms, 50), 4),
        "p95": round(pct(samples_ms, 95), 4),
        "max": round(max(samples_ms), 4),
        "unit": unit,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--replay", action="store_true", help="split only, from the seed tape")
    ap.add_argument("--json", metavar="PATH")
    a = ap.parse_args()

    out = {"iterations": a.iterations, "mode": "replay" if a.replay else "live"}

    if a.replay:
        if not SEED.exists():
            sys.exit(f"no seed tape at {SEED} — run: python3 scripts/seed.py")
        tape = json.loads(SEED.read_text())
        swaps = tape["swaps"]
        print(f"replay — {len(swaps)} swaps captured {tape['captured_utc']}, no network\n")
        split_ms = []
        for _ in range(a.iterations):
            t = time.perf_counter()
            split(swaps)
            split_ms.append((time.perf_counter() - t) * 1000)
        out["split"] = report("split (aggregation)", split_ms)
        out["swaps"] = len(swaps)
    else:
        print(f"live — keyless fetch + split, {a.iterations} iterations against UNI\n")
        fetch_ms, split_ms, counts = [], [], []
        for i in range(a.iterations):
            t = time.perf_counter()
            swaps, meta = pull_swaps(UNI, pages=1)
            fetch_ms.append((time.perf_counter() - t) * 1000)
            if meta["error"]:
                print(f"  iteration {i + 1}: API error — {meta['error'][:70]}")
                continue
            t = time.perf_counter()
            split(swaps)
            split_ms.append((time.perf_counter() - t) * 1000)
            counts.append(len(swaps))
        if not split_ms:
            sys.exit("every iteration failed — the keyless surface is rate-limiting")
        out["fetch"] = report("fetch (network)", fetch_ms)
        out["split"] = report("split (aggregation)", split_ms)
        out["swaps"] = int(statistics.median(counts))
        out["credits_used"] = 0

    print(
        f"\n  {out['swaps']} swaps per iteration · "
        f"{'0 credits — keyless' if not a.replay else 'no network'}"
    )

    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=2, sort_keys=True))
        print(f"  wrote {a.json}")


if __name__ == "__main__":
    main()
