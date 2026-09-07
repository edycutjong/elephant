"""The three high-signal tests.

Not three suites — three tests, each answering a question coverage cannot.

(a) Regression tests named for the defect they pin. The test list is a changelog of real
    bugs found in real runs against the live API, with the date they were observed.
(b) One property-based verification of the core decision function, over its whole input
    space rather than on examples. The case count is published in README.md and DEMO.md.
(c) A credential-boundary test. This project has no auth, so the boundary is the opposite
    of the usual one: the judged path must require NO credential, and must refuse to turn
    a broken response into a number.
"""

import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import split_tape  # noqa: E402
from split_tape import DUST_USD, MIN_SIDE_SWAPS, pull_swaps, split  # noqa: E402

# Published case count — keep this in sync with README.md and DEMO.md.
PROPERTY_CASES = 2000


def _swap(tp, v, ma):
    return {"tp": tp, "v": str(v), "ma": ma, "tx": f"{tp}-{v}-{ma}"}


# ─────────────────────────────────────────────────────────────────────────────
# (a) Regression tests — each named for the defect it pins
# ─────────────────────────────────────────────────────────────────────────────


def test_dust_sell_side_is_not_reported_as_a_709x_elephant():
    """SHIB, live run 2026-09-07.

    96 sub-cent sells (min $0.0011, avg $0.375) against 4 real buys produced a headline
    'SHIB 709.1x'. Arithmetically correct, completely meaningless: the denominator was
    spam, not a market participant. The ratio is still reported, but the row must carry a
    confidence reason so it can never be selected as the hero.
    """
    dust = [_swap("sell", 0.375, f"d{i}") for i in range(96)]
    real = [_swap("buy", 267.0, f"b{i}") for i in range(20)]
    r = split(dust + real)
    assert r["ticket_ratio"] > 700  # the maths is unchanged
    assert r["confidence"] != "ok"  # but the row is disqualified
    assert "dust" in r["confidence"]


def test_four_swap_side_is_not_reported_as_an_average_ticket():
    """SHIB, live run 2026-09-07: the buy side had FOUR swaps.

    An 'average ticket' over 4 trades is an anecdote. Below MIN_SIDE_SWAPS the row must be
    flagged even when both averages are far above the dust floor.
    """
    r = split(
        [_swap("buy", 5000, f"b{i}") for i in range(4)]
        + [_swap("sell", 100, f"s{i}") for i in range(50)]
    )
    assert r["confidence"] != "ok"
    assert "thin side" in r["confidence"]


def test_rate_limited_fetch_is_not_reported_as_an_empty_tape(monkeypatch):
    """Live run 2026-09-07: the keyless surface returns HTTP 429 under repeated calls.

    pull_swaps used to `break` on the error and return a bare empty list, so a rate-limited
    fetch was indistinguishable from a token with no swaps — the tool blamed the token for
    an infrastructure failure. The error must travel back to the caller.
    """
    monkeypatch.setattr(
        split_tape, "get", lambda *a, **k: {"_err": "HTTP 429: reached the limit for anon"}
    )
    swaps, meta = pull_swaps("0xdead", pages=2)
    assert swaps == []
    assert meta["error"] is not None, "a 429 must not read as 'this token has no swaps'"
    assert "429" in meta["error"]


def test_zero_average_side_does_not_raise_before_the_confidence_gate():
    """A side can average exactly 0.0 if every swap is priced below float resolution.

    The old ratio expression divided unconditionally and would ZeroDivisionError before the
    caller ever got to read the confidence reason.
    """
    r = split([_swap("sell", 0.0, f"s{i}") for i in range(10)] + [_swap("buy", 100, "b")])
    assert r["ticket_ratio"] == float("inf")
    assert r["confidence"] != "ok"


# ─────────────────────────────────────────────────────────────────────────────
# (b) Property-based verification of the core decision function
# ─────────────────────────────────────────────────────────────────────────────

_usd = st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False)
_side = st.lists(st.tuples(_usd, st.integers(min_value=0, max_value=40)), min_size=1, max_size=60)


@settings(max_examples=PROPERTY_CASES, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(buys=_side, sells=_side)
def test_split_invariants_hold_over_the_whole_input_space(buys, sells):
    """The core decision function, verified across {PROPERTY_CASES} generated tapes.

    Five invariants that must hold for ANY tape, not just the ones we thought to write down:

    1. The ratio is never below 1 — it is defined as max(x, 1/x), so a "0.4x asymmetry"
       is impossible by construction.
    2. Distinct wallets can never exceed trades on either side. A maker trading twice is
       one wallet; if this inverts, the "one desk vs a crowd" claim is unsupported.
    3. Net flow stays inside +/-100%. It is a share of total volume, so a value outside
       that range means the denominator was built wrong.
    4. The elephant side is the side with the larger average ticket. The label and the
       number can never disagree.
    5. A row marked "ok" genuinely clears BOTH published floors — the confidence gate
       cannot pass a tape it should have rejected. This is the one that matters: it is
       what stops another SHIB reaching the headline.
    """
    swaps = [_swap("buy", v, f"b{m}") for v, m in buys] + [
        _swap("sell", v, f"s{m}") for v, m in sells
    ]
    r = split(swaps)
    assert r is not None  # both sides are non-empty by construction

    assert r["ticket_ratio"] >= 1.0
    assert r["buy_wallets"] <= r["buys"]
    assert r["sell_wallets"] <= r["sells"]
    assert -100.0 <= r["net_flow_pct"] <= 100.0

    if r["avg_buy"] != r["avg_sell"]:
        larger = "buy" if r["avg_buy"] > r["avg_sell"] else "sell"
        assert r["elephant_side"] == larger

    if r["confidence"] == "ok":
        assert min(r["buys"], r["sells"]) >= MIN_SIDE_SWAPS
        assert min(r["avg_buy"], r["avg_sell"]) >= DUST_USD


# ─────────────────────────────────────────────────────────────────────────────
# (c) Credential boundary — the keyless claim, tested rather than asserted
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "garbage",
    [
        {},  # empty object
        {"data": None},  # null payload
        {"data": {"swaps": None}},  # null swap list
        {"data": {"swaps": [{"tp": "buy"}]}},  # side present, USD value missing
        {"data": {"swaps": [{"v": "1.0", "ma": "0x1"}]}},  # value present, side missing
        {"status": {"error_code": 1001}},  # an error envelope with no data at all
    ],
)
def test_malformed_response_is_refused_rather_than_turned_into_a_number(monkeypatch, garbage):
    """The boundary this project actually has.

    There is no auth to escalate, so the boundary is between "the API answered with the
    contract we verified" and "the API answered with something else". Every shape below
    must yield no result — never a plausible-looking ticket ratio a judge could quote.
    """
    monkeypatch.setattr(split_tape, "get", lambda *a, **k: garbage)
    swaps, meta = pull_swaps("0xdead", pages=1)
    assert meta["error"] is None  # these are well-formed HTTP 200s, not transport errors
    assert split(swaps) is None, f"produced a number from {garbage}"


@pytest.mark.live
def test_judged_path_requires_no_credential_at_all(monkeypatch):
    """Unset every credential the project could possibly read, then run the real thing.

    The README claims "no API key, no signup". This is that claim as a test: if a key ever
    leaks into the judged path, the run below is what fails.
    """
    for var in (
        "CMC_API_KEY",
        "COINMARKETCAP_API_KEY",
        "CMC_PRO_API_KEY",
        "X_CMC_PRO_API_KEY",
        "API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    swaps, meta = pull_swaps("0x1f9840a85d5af5bf1d1762f925bdaddc4201f984", pages=1)
    if meta["error"] and "429" in meta["error"]:
        pytest.skip("keyless surface is rate-limiting right now; not a credential failure")
    assert meta["error"] is None, f"keyless fetch failed: {meta['error']}"
    assert swaps, "no swaps returned with every credential unset"
    assert any(s.get("tp") in ("buy", "sell") for s in swaps)
