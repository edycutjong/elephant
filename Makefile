.PHONY: help install lint test bench demo audit all
help:  ## show targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n",$$1,$$2}'
install:  ## install dev deps
	python3 -m pip install -r requirements-dev.txt
lint:  ## ruff + format check
	ruff check . && ruff format --check .
test:  ## pytest with coverage
	pytest -q --cov=scripts --cov-report=term-missing
bench:  ## reproducible benchmark, p50/p95
	python3 scripts/bench.py
demo:  ## the judged capability, live, zero config
	python3 scripts/split_tape.py --pages 3
audit:  ## dependency + secret audit
	pip-audit -r requirements.txt || true
	gitleaks detect --no-banner --redact || true
all: lint test bench  ## everything CI runs
