# Contributing

## Run it in 30 seconds — no key, no signup

```bash
git clone <this repo> && cd elephant
python3 scripts/split_tape.py
```

There is no install step. `split_tape.py` is stdlib-only and calls CoinMarketCap's keyless
`/public-api` surface, so what you see is a live API response, not a fixture.

## Development

```bash
make install     # dev deps only (pytest, ruff, hypothesis, pip-audit)
make lint        # ruff check + format check
make test        # pytest with coverage, offline only
make test-live   # the tests that hit the real CoinMarketCap API
make demo        # the judged capability, live, no key
make bench       # p50/p95 against the captured tape (deterministic)
make bench-live  # p50/p95 against the real keyless fetch
make check       # refuse to ship a placeholder to a judge
make ci          # lint + test + audit + check
```

## The one rule that matters here

**Never mock the judged capability.** The point of this project is that the numbers come from real
trades. If a test needs determinism, replay the recorded tape in `data/seed_tape.json` (capture a
fresh one with `make seed`) — but the default path, `make demo`, and CI's `live-api` job must always
hit the real API. A pull request that puts the split behind a `MOCK=` flag will be closed.

`scripts/bench.py --replay` is the one sanctioned offline path, and it is labelled as a replay
everywhere it appears. It measures the aggregation, not the product.

## Tests

Three categories carry more weight than coverage here, and PRs are expected to keep them:

- **Regression tests are named after the defect they pin**, with the date it was observed —
  `test_dust_sell_side_is_not_reported_as_a_709x_elephant`, not `test_split_4`. The test list is
  meant to read as a changelog of real bugs.
- **`split()` is verified by property, not by example** (`test_high_signal.py`). If you change the
  maths, the invariants must still hold across the generated input space.
- **A malformed API response must never become a number.** Adding a new response shape that could
  reach `split()` means adding it to the boundary test.

## Commits

Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `style:`). Small and iterative.
`release.yml` derives the version from these, so the prefix decides the version bump.
