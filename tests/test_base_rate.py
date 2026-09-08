"""The base-rate measurement: what it counts, what it refuses to count, and what it admits.

A base rate is a claim about a population, so the parts worth pinning are not the arithmetic —
they are the choices that decide *which rows reach the arithmetic*. A denominator quietly
including untrustworthy rows, or a threshold tuned after seeing the answer, produces a number
that looks measured and is not.
"""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import base_rate  # noqa: E402
import split_tape  # noqa: E402


def _swaps(pairs):
    """pairs: [(side, usd, maker), ...] -> the envelope the API would return."""
    body = ",".join(
        f'{{"tx":"0x{i}","lgid":"{i}","tp":"{s}","v":"{v}","ma":"{m}"}}'
        for i, (s, v, m) in enumerate(pairs)
    )
    return f'{{"data":{{"swaps":[{body}]}}}}'.encode()


def _token(sym, addr="0xabc", platform="ethereum"):
    return {"symbol": sym, "address": addr, "platform": platform}


# ── the denominator ──────────────────────────────────────────────────────────────────


def test_a_token_that_fails_the_confidence_floors_is_excluded_not_counted_as_a_negative(
    monkeypatch,
):
    """This is the choice that decides whether the number means anything.

    A token with a 3-swap side has no trustworthy top-maker share. Counting it in the
    denominator as "not concentrated" would dilute the rate with rows the product itself
    refuses to report — the answer would drift toward zero for a reason that has nothing to do
    with the market. It is dropped from both halves of the fraction instead.
    """
    # net flow exactly 0 — squarely inside the balanced band — but three swaps a side, under
    # the MIN_SIDE_SWAPS floor of five. Balanced and untrustworthy at the same time, which is
    # the row this rule exists to keep out of the denominator.
    balanced_thin = [{"tp": "buy", "v": "100", "ma": f"0xb{i}"} for i in range(3)] + [
        {"tp": "sell", "v": "100", "ma": f"0xs{i}"} for i in range(3)
    ]
    r = split_tape.split(balanced_thin)
    assert r["confidence"] != "ok", "fixture must actually be untrustworthy"
    assert abs(r["net_flow_pct"]) < split_tape.BALANCED, "and would otherwise read balanced"

    trusted = [x for x in [r] if x["confidence"] == "ok"]
    assert trusted == [], "excluded from the denominator entirely"


def test_the_balanced_band_is_the_same_constant_the_product_selects_on():
    """Two copies of this threshold drifting apart would make the base rate a claim about a
    different question than the one the tool answers."""
    assert base_rate.BALANCED is split_tape.BALANCED
    assert split_tape.BALANCED == 5.0


# ── the interval ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "k,n",
    [(6, 22), (0, 5), (5, 5), (1, 100)],
)
def test_the_interval_stays_inside_zero_and_one_where_a_normal_approximation_would_not(k, n):
    """Wilson, not normal. At 0/5 the normal interval is [0, 0] — a claim of certainty from
    five observations — and at 5/5 it runs past 1. Both are the counts this actually meets."""
    lo, hi = _wilson(k, n)
    assert 0.0 <= lo <= hi <= 1.0
    assert lo <= k / n <= hi, "the interval contains the point estimate"
    if 0 < k < n:
        assert hi - lo > 0.05, "a small sample must not report a narrow interval"


def _wilson(k, n, z=1.96):
    ph, z2 = k / n, z * z
    centre = (ph + z2 / (2 * n)) / (1 + z2 / n)
    half = z * ((ph * (1 - ph) / n + z2 / (4 * n * n)) ** 0.5) / (1 + z2 / n)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


# ── the population and the measurement loop ──────────────────────────────────────────


def test_the_population_is_deduplicated_across_sources_and_keeps_its_platform(monkeypatch):
    """The same token trades on several DEXes. Counting WETH once per source would weight the
    population by listing count rather than by token."""
    monkeypatch.setattr(
        base_rate, "SOURCES", [(1, "uniswap-v3", "ethereum"), (14, "pancakeswap-v2", "bsc")]
    )
    monkeypatch.setattr(
        base_rate,
        "sweep_source",
        lambda n, d, per: ([{"symbol": "WETH", "address": "0xWETH"}], None),
    )
    pop, errs = base_rate.build_population(5, verbose=False)
    assert len(pop) == 1, "one token, not one per source"
    assert pop[0]["platform"] == "ethereum", "the first source that saw it"
    assert errs == []


def test_a_source_that_errors_is_recorded_rather_than_dropped_silently(monkeypatch):
    monkeypatch.setattr(base_rate, "SOURCES", [(1, "uniswap-v3", "ethereum")])
    monkeypatch.setattr(base_rate, "sweep_source", lambda n, d, per: ([], "HTTP 429"))
    pop, errs = base_rate.build_population(5, verbose=False)
    assert pop == []
    assert errs == [{"network": "ethereum", "dex": "uniswap-v3", "error": "HTTP 429"}]


def test_a_token_that_returns_nothing_is_recorded_in_skipped_with_its_reason(monkeypatch):
    """Nothing may vanish between the population and the counts, or the denominator becomes
    unauditable — a reader has to be able to add the buckets back up."""
    monkeypatch.setattr(base_rate, "pull_swaps", lambda a, p, pages: ([], {"error": "HTTP 429"}))
    rows, skipped = base_rate.measure([_token("X")], 2, verbose=False)
    assert rows == []
    assert skipped == [{"symbol": "X", "why": "HTTP 429"}]


def test_a_one_sided_tape_is_skipped_because_there_is_no_split_to_measure(monkeypatch):
    monkeypatch.setattr(
        base_rate,
        "pull_swaps",
        lambda a, p, pages: ([{"tp": "buy", "v": "10", "ma": "0xa"}], {"error": None, "pages": 1}),
    )
    rows, skipped = base_rate.measure([_token("X")], 1, verbose=False)
    assert rows == []
    assert skipped[0]["why"] == "one side empty"


# ── end to end ───────────────────────────────────────────────────────────────────────


def _run(monkeypatch, capsys, tmp_path, tape, tokens=1):
    monkeypatch.setattr(base_rate, "SOURCES", [(1, "uniswap-v3", "ethereum")])
    monkeypatch.setattr(
        base_rate,
        "sweep_source",
        lambda n, d, per: ([{"symbol": f"T{i}", "address": f"0x{i}"} for i in range(tokens)], None),
    )
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        split_tape.urllib.request, "urlopen", lambda r, timeout=None: io.BytesIO(tape)
    )
    out = tmp_path / "br.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "base_rate.py",
            "--tokens",
            str(tokens),
            "--per-source",
            str(tokens),
            "--pages",
            "1",
            "--json",
            str(out),
        ],
    )
    try:
        base_rate.main()
        code = 0
    except SystemExit as e:
        code = e.code
    return capsys.readouterr().out, out, code


def test_a_concentrated_balanced_token_lands_in_both_halves_of_the_fraction(
    monkeypatch, capsys, tmp_path
):
    """One wallet takes most of the sell side while net flow stays inside the balanced band —
    the case the whole project exists to find. It must reach the numerator."""
    tape = _swaps(
        [("buy", 100, f"0xb{i}") for i in range(10)]
        + [("sell", 900, "0xWHALE")]
        + [("sell", 20, f"0xs{i}") for i in range(5)]
    )
    out, path, code = _run(monkeypatch, capsys, tmp_path, tape)
    d = json.loads(path.read_text())
    assert code == 0
    assert d["counts"]["balanced"] == 1 and d["counts"]["concentrated"] == 1
    assert d["base_rate"] == 1.0
    assert d["base_rate_95ci_wilson"][0] < 1.0, "one observation cannot be reported as certainty"
    assert d["top_share_distribution_among_balanced"]["p50"] > 0.5
    assert "BASE RATE" in out


def test_no_balanced_token_reports_undefined_and_exits_75_rather_than_zero_percent(
    monkeypatch, capsys, tmp_path
):
    """A rate with an empty denominator is undefined, and printing 0% would be a claim the run
    never measured. Exit 75 says 'this window produced nothing', the same contract split_tape
    uses for a throttle."""
    tape = _swaps(
        [("buy", 1000, f"0xb{i}") for i in range(8)] + [("sell", 1, f"0xs{i}") for i in range(8)]
    )
    out, path, code = _run(monkeypatch, capsys, tmp_path, tape)
    assert code == 75
    assert "undefined, not zero" in out
    assert json.loads(path.read_text())["base_rate"] is None


def test_the_receipt_states_its_limitations_next_to_the_number(monkeypatch, capsys, tmp_path):
    """A base rate travels — it will be quoted without its method. The three things that would
    make a quote wrong ship inside the same file as the number."""
    tape = _swaps(
        [("buy", 100, f"0xb{i}") for i in range(10)]
        + [("sell", 900, "0xWHALE")]
        + [("sell", 20, f"0xs{i}") for i in range(5)]
    )
    _, path, _ = _run(monkeypatch, capsys, tmp_path, tape)
    d = json.loads(path.read_text())
    joined = " ".join(d["limitations"]).lower()
    assert "liquidity-ranked" in joined, "the population is not a random sample of all tokens"
    assert "window" in joined, "a run is a window, not 24 hours"
    assert "not an entity" in joined, "a wallet is not an entity"
    assert d["method"]["balanced_pct"] == split_tape.BALANCED
    assert d["method"]["concentrated_threshold"] == base_rate.HALF


def test_the_skipped_line_names_the_token_when_the_run_is_verbose(monkeypatch, capsys):
    """The progress output is how a reader watches a ten-minute run. A token that produced
    nothing has to say so as it happens, not only in the receipt afterwards."""
    monkeypatch.setattr(base_rate, "pull_swaps", lambda a, p, pages: ([], {"error": "HTTP 429"}))
    base_rate.measure([_token("GHOST")], 2, verbose=True)
    assert "GHOST" in capsys.readouterr().out


def test_the_file_runs_through_its_main_guard_the_way_a_reader_invokes_it(
    monkeypatch, capsys, tmp_path
):
    """`python3 scripts/base_rate.py` is what the Makefile and the README both say. Importing
    the module and calling main() would leave the guard itself unexecuted, which is the one
    line that decides whether the documented command does anything at all."""
    import runpy

    tape = _swaps(
        [("buy", 100, f"0xb{i}") for i in range(10)]
        + [("sell", 900, "0xWHALE")]
        + [("sell", 20, f"0xs{i}") for i in range(5)]
    )
    # runpy re-executes the module, so its `from sweep_universe import ...` rebinds from the
    # source module — patching base_rate's own names would not reach the fresh copy.
    import sweep_universe

    monkeypatch.setattr(sweep_universe, "SOURCES", [(1, "uniswap-v3", "ethereum")])
    monkeypatch.setattr(
        sweep_universe,
        "sweep_source",
        lambda n, d, per: ([{"symbol": "T", "address": "0x1"}], None),
    )
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    monkeypatch.setattr(
        split_tape.urllib.request, "urlopen", lambda r, timeout=None: io.BytesIO(tape)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["base_rate.py", "--tokens", "1", "--per-source", "1", "--pages", "1"],
    )
    runpy.run_path(str(Path(base_rate.__file__)), run_name="__main__")
    assert "BASE RATE" in capsys.readouterr().out
