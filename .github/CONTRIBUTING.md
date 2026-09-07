# Contributing

## Run it in 30 seconds — no key, no signup

```bash
git clone <this repo> && cd elephant-tracks
python3 scripts/split_tape.py
```

There is no install step. `split_tape.py` is stdlib-only and calls CoinMarketCap's keyless
`/public-api` surface, so what you see is a live API response, not a fixture.

## Development

```bash
make install   # dev deps only (pytest, ruff, pip-audit)
make lint      # ruff check + format
make test      # pytest with coverage
make demo      # the judged capability, live
make bench     # p50/p95 timings
```

## The one rule that matters here

**Never mock the judged capability.** The point of this project is that the numbers come from real
trades. If a test needs determinism, assert against a recorded response in `tests/fixtures/` — but
the default path, the demo, and CI's `live-api` job must always hit the real API. A pull request
that puts the split behind a `MOCK=` flag will be closed.

## Commits
Conventional commits (`feat:`, `fix:`, `docs:`, `chore:`). Small and iterative.
