.PHONY: help install lint test test-live bench bench-live demo sweep base-rate seed site fonts audit check ci all

help:  ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n",$$1,$$2}'

install:  ## install dev deps + the chromium the browser QA gates drive
	python3 -m pip install -r requirements-dev.txt
	python3 -m playwright install chromium

lint:  ## ruff check + format check
	ruff check . && ruff format --check .

test:  ## pytest with coverage, offline only (no internet), gated at 100% of scripts/
	pytest -q -m "not live" --cov=scripts --cov-report=term-missing --cov-fail-under=100

test-live:  ## the live tests — hits the real CoinMarketCap API
	pytest -q -m live

bench:  ## deterministic benchmark against the captured tape, p50/p95
	python3 scripts/bench.py --replay --iterations 200

bench-live:  ## benchmark the real keyless fetch, p50/p95
	python3 scripts/bench.py --iterations 8

demo:  ## the judged capability, live, zero config, no key
	python3 scripts/split_tape.py

sweep:  ## enumerate a token universe from the keyless DEX pair listing
	python3 scripts/sweep_universe.py

base-rate:  ## measure how often a balanced net flow hides one wallet (slow, keyless)
	python3 scripts/base_rate.py --tokens 110 --per-source 22 --pages 2 --json docs/proof/base_rate.json

seed:  ## re-capture the offline replay tape from the live API
	python3 scripts/seed.py

site:  ## re-render the landing page, the deck and JUDGE.md from docs/proof/*.json
	python3 scripts/render_site.py

fonts:  ## re-cut the web fonts to the glyphs the pages actually render
	python3 scripts/subset_fonts.py
	python3 scripts/render_site.py

audit:  ## dependency + secret audit
	pip-audit -r requirements.txt || true
	gitleaks detect --no-banner --redact || true

check:  ## refuse to ship a placeholder to a judge, or a page that drifted from its receipts
	python3 scripts/check_submission_readiness.py
	python3 scripts/render_site.py --check

ci: lint test audit check  ## everything CI runs, offline
all: ci bench  ## ci plus the deterministic benchmark
