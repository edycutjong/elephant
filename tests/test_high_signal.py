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

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import split_tape  # noqa: E402
import sweep_universe  # noqa: E402
from split_tape import DUST_USD, MIN_SIDE_SWAPS, pull_swaps, split  # noqa: E402

UNI = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"

# Published case count — keep this in sync with README.md and DEMO.md.
PROPERTY_CASES = 2000
# Every credential the judged path could conceivably read. The three the tool honours as an
# escape hatch, plus two it must never honour. Unset in every boundary test below.
ALL_KEY_VARS = (*split_tape.KEY_VARS, "X_CMC_PRO_API_KEY", "API_KEY")


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


def test_cursor_is_read_from_the_envelope_not_from_the_last_swap(monkeypatch):
    """Sweep 2026-09-07: every number in the repo had come from a single 100-swap window.

    The next-page cursor is `data.lastId` on the RESPONSE ENVELOPE. The first paginator
    read `batch[-1]["txId"]` — a per-swap index — so the cursor never advanced and page 2
    silently re-fetched page 1. Reading the envelope reached 864 swaps over 10 pages on
    one token. The second call must carry the envelope's cursor, verbatim.
    """
    calls = []

    def fake_get(path, **params):
        calls.append(params)
        n = len(calls)
        return {
            "data": {
                "lastId": f"cursor-{n}",
                "swaps": [
                    {"tx": f"0x{n}", "lgid": str(i), "txId": "7", "tp": "buy", "v": "1", "ma": "a"}
                    for i in range(3)
                ],
            }
        }

    monkeypatch.setattr(split_tape, "get", fake_get)
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    swaps, meta = pull_swaps("0xdead", pages=3)
    assert len(swaps) == 9, "three pages of three distinct swaps each"
    assert meta["pages"] == 3 and not meta["stalled"]
    assert "lastId" not in calls[0]
    assert calls[1]["lastId"] == "cursor-1", "page 2 must send the ENVELOPE cursor"
    assert calls[2]["lastId"] == "cursor-2"


def test_swaps_are_keyed_by_tx_and_log_index_together(monkeypatch):
    """Live page 2026-09-07: 100 swaps carried 89 distinct `tx` and 91 distinct `lgid`.

    A multi-hop route emits several swaps under one tx hash; log ids repeat across
    transactions. De-duplicating on either field alone throws away real swaps. The
    key is the pair — and the same (tx, lgid) seen twice across pages counts once.
    """
    pages = [
        [
            {"tx": "0xA", "lgid": "1", "tp": "buy", "v": "1", "ma": "a"},
            {"tx": "0xA", "lgid": "2", "tp": "buy", "v": "1", "ma": "a"},  # same tx, hop 2
            {"tx": "0xB", "lgid": "1", "tp": "sell", "v": "1", "ma": "b"},  # same lgid, other tx
        ],
        [
            {"tx": "0xB", "lgid": "1", "tp": "sell", "v": "1", "ma": "b"},  # overlap: drop
            {"tx": "0xC", "lgid": "1", "tp": "sell", "v": "1", "ma": "c"},
        ],
    ]
    it = iter(pages)
    monkeypatch.setattr(
        split_tape, "get", lambda path, **q: {"data": {"lastId": "x", "swaps": next(it)}}
    )
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    swaps, _ = pull_swaps("0xdead", pages=2)
    assert len(swaps) == 4


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


def test_transient_throttle_is_retried_before_the_row_is_failed(monkeypatch):
    """Live run 2026-09-07: the full 8-token watchlist failed on every single token.

    The anonymous tier throttles hard and expresses it TWO ways — HTTP 429 (error_code
    1022) and HTTP 500 ("The system is busy"). The first version of this backoff retried
    only on 429 and the very next live run failed with eight 500s, so both must be
    treated as transient. A 400 must NOT be retried: it is permanent, and retrying it
    only wastes the judge's time.
    """
    calls = {"n": 0}

    class Boom(urllib.error.HTTPError):
        def __init__(self, code):
            self.code, self._body = code, b'{"error_code":"1022"}'

        def read(self):
            return self._body

    def flaky(url, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise Boom(429)  # "reached the limit for anonymous access"
        if calls["n"] == 2:
            raise Boom(500)  # "The system is busy, please try again later!"
        return io.BytesIO(b'{"data": {"swaps": []}}')

    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    monkeypatch.setattr(split_tape.urllib.request, "urlopen", flaky)
    assert "_err" not in split_tape.get("/x")  # recovered on the third attempt
    assert calls["n"] == 3

    calls["n"] = 0

    def always_400(url, timeout=None):
        calls["n"] += 1
        raise Boom(400)

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", always_400)
    assert "_err" in split_tape.get("/x")
    assert calls["n"] == 1, "a 400 is permanent — retrying it only wastes time"


def test_exhausted_throttle_explains_itself_instead_of_dumping_a_truncated_body(
    monkeypatch, capsys
):
    """Live run 2026-09-07, roughly 3,700 anonymous calls into the day from one IP.

    Backoffs of 15 s, 30 s and 60 s, then exit 1 with the first 160 bytes of the response —
    a JSON body cut off mid-string — as the only explanation. 105 seconds of waiting for a
    message a judge could not act on. The failure must name the tier, both ways CMC reports
    it, and the two ways through: wait, or export a free key. Never a raw body.

    It must also exit 75 (EX_TEMPFAIL) rather than 1, so a caller can tell a rate limit from a
    genuine break without parsing prose.
    """
    body = (
        b'{"status":{"timestamp":"2026-09-07T10:00:00.000Z","error_code":"1022",'
        b'"error_message":"You\'ve reached the limit for anonymous access, please try again '
        b'later!","elapsed":0,"credit_count":0}}'
    )

    class Limit(urllib.error.HTTPError):
        def __init__(self):
            self.code = 429

        def read(self):
            return body

    def always_limited(url, timeout=None):
        raise Limit()

    for var in ALL_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    monkeypatch.setattr(split_tape.urllib.request, "urlopen", always_limited)
    monkeypatch.setattr(sys, "argv", ["split_tape.py", "--address", "0xdead", "--symbol", "X"])
    with pytest.raises(SystemExit) as ex:
        split_tape.main()
    captured = capsys.readouterr()
    msg, out = captured.err, captured.out

    assert ex.value.code == 75, "EX_TEMPFAIL — a rate limit is not the exit code of a real break"
    assert "HTTP 429 (error 1022)" in msg, "the status and CMC's own error code, parsed"
    assert "anonymous" in msg and "per IP" in msg, "name the tier"
    assert "HTTP 500" in msg, "name the other way the same throttle is reported"
    assert "CMC_API_KEY" in msg and split_tape.KEY_URL in msg, "name the escape hatch"
    assert "never a" in msg and "keyless" in msg, "and say the default stays keyless"
    for text in (msg, out):
        assert "{" not in text and "}" not in text, "never a raw response body"
    assert "error 1022" in out, "the row line carries the parsed message too"
    assert "keyless" in out.splitlines()[0], "the mode is on the first line"


def test_http_error_is_described_by_its_message_never_by_its_body():
    """Both shapes CMC uses, and a non-JSON body from a proxy: the description is the status,
    the API's error code and the API's message. A body is never quoted."""

    class Err(urllib.error.HTTPError):
        def __init__(self, code, body, reason=None):
            self.code, self._body, self._reason = code, body, reason

        def read(self):
            return self._body

        @property
        def reason(self):
            return self._reason

    busy = Err(
        500, b'{"error_code":500,"error_message":"The system is busy, please try again later!"}'
    )
    assert split_tape.describe_http_error(busy) == (
        "HTTP 500 (error 500): The system is busy, please try again later!"
    )
    nested = Err(
        429, b'{"status":{"error_code":"1022","error_message":"You\'ve reached the limit"}}'
    )
    assert (
        split_tape.describe_http_error(nested) == "HTTP 429 (error 1022): You've reached the limit"
    )
    html = Err(502, b"<html><body>Bad Gateway from the edge</body></html>", reason="Bad Gateway")
    assert split_tape.describe_http_error(html) == "HTTP 502: Bad Gateway"
    assert "<html" not in split_tape.describe_http_error(html)


def test_a_partly_throttled_watchlist_names_the_missing_tokens_and_the_way_through(
    monkeypatch, capsys
):
    """One token answers, seven are throttled: the table must show the row it has, and the
    run must say which tokens are missing and why, rather than end as if it had run clean."""
    tape = [_swap("buy", 100 + i, f"b{i}") for i in range(10)] + [
        _swap("sell", 100 + i, f"s{i}") for i in range(10)
    ]

    def fake_pull(address, platform="ethereum", pages=1):
        if address == split_tape.WATCHLIST[0][1]:
            return tape, {
                "pages": 1,
                "error": None,
                "stalled": False,
                "throttled": False,
                "credits": 0,
            }
        return [], {
            "pages": 0,
            "error": "HTTP 429 (error 1022): You've reached the limit for anonymous access",
            "stalled": False,
            "throttled": True,
            "credits": 0,
        }

    for var in ALL_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(split_tape, "pull_swaps", fake_pull)
    monkeypatch.setattr(sys, "argv", ["split_tape.py"])
    split_tape.main()
    out = capsys.readouterr().out
    assert "7 token(s) missing above" in out
    assert "anonymous tier throttled them" in out
    assert "CMC_API_KEY" in out and split_tape.KEY_URL in out
    assert split_tape.WATCHLIST[1][0] in out.split("missing above")[1]


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

    Six invariants that must hold for ANY tape, not just the ones we thought to write down:

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

    # 6. Maker concentration is a share: inside [0, 1], attributed to a wallet that is on
    #    that side, with at most as many swaps as the side has, and never more volume
    #    than the side. The headline number cannot escape its own denominator.
    for side, n in (("buy", r["buys"]), ("sell", r["sells"])):
        assert 0.0 <= r[f"{side}_top_share"] <= 1.0 + 1e-9
        assert 1 <= r[f"{side}_top_swaps"] <= n
        assert r[f"{side}_top_vol"] <= r[f"{side}_vol"] * (1 + 1e-9)
        if r[f"{side}_wallets"] == 1:
            assert r[f"{side}_top_share"] == pytest.approx(1.0) or r[f"{side}_vol"] == 0
    assert r["top_share"] == max(r["buy_top_share"], r["sell_top_share"])


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


def _capture_request(monkeypatch):
    """Replace the socket with a recorder: the URL and headers the tool would have sent."""
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["headers"] = {k.lower(): v for k, v in req.header_items()}
        return io.BytesIO(b'{"data": {"swaps": []}}')

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", fake_urlopen)
    return seen


def test_default_path_sends_no_key_and_uses_the_public_surface(monkeypatch):
    """The R10 gate as a test: with every credential unset, the request is the bare keyless
    one — the /public-api base, no X-CMC_PRO_API_KEY header, nothing read from disk."""
    for var in ALL_KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    seen = _capture_request(monkeypatch)
    assert split_tape.api_key() is None and split_tape.api_key_var() is None
    assert split_tape.active_base() == split_tape.BASE
    assert "_err" not in split_tape.get("/v1/dex/tokens/transactions", address="0xdead")
    assert seen["url"].startswith(split_tape.BASE + "/v1/dex/tokens/transactions?")
    assert "/public-api/" in seen["url"]
    assert "x-cmc_pro_api_key" not in seen["headers"]


# The literal is deliberate: ast.literal_eval in the count test below cannot resolve a name.
# The assertion inside keeps it honest against the tool's own list.
@pytest.mark.parametrize("var", ["CMC_API_KEY", "COINMARKETCAP_API_KEY", "CMC_PRO_API_KEY"])
def test_an_exported_key_is_sent_as_the_pro_header_to_the_keyed_base(monkeypatch, var):
    """The escape hatch for a throttled IP. Any of the three names moves the identical call
    to the keyed base with the key in X-CMC_PRO_API_KEY. Exercised with a fake key against a
    recorder: no real credential is needed to prove the wiring, and none is committed."""
    assert var in split_tape.KEY_VARS
    for v in ALL_KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv(var, "not-a-real-key")
    seen = _capture_request(monkeypatch)
    assert split_tape.api_key() == "not-a-real-key" and split_tape.api_key_var() == var
    assert split_tape.active_base() == split_tape.BASE_KEYED
    split_tape.get("/v1/dex/tokens/transactions", address="0xdead")
    assert seen["url"].startswith(split_tape.BASE_KEYED + "/v1/dex/tokens/transactions?")
    assert "/public-api/" not in seen["url"]
    assert seen["headers"]["x-cmc_pro_api_key"] == "not-a-real-key"


def test_a_blank_key_variable_does_not_switch_the_path(monkeypatch):
    """`export CMC_API_KEY=` (empty, or whitespace) is not a key. The tool must stay on the
    keyless surface rather than send an empty header to the keyed one and fail on auth."""
    for v in ALL_KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("CMC_API_KEY", "   ")
    seen = _capture_request(monkeypatch)
    split_tape.get("/v1/dex/tokens/transactions", address="0xdead")
    assert "/public-api/" in seen["url"]
    assert "x-cmc_pro_api_key" not in seen["headers"]


def test_the_receipt_says_which_path_produced_it(monkeypatch, tmp_path, capsys):
    """A keyed run can never pass itself off as the keyless default: the first line, the last
    line and the JSON receipt all say keyed, and credits are the envelope's own count."""
    envelope = b'{"status":{"credit_count":1},"data":{"lastId":null,"swaps":['
    envelope += b",".join(
        f'{{"tx":"0x{i}","lgid":"{lg}","tp":"{tp}","v":"100","ma":"{tp}{i}"}}'.encode()
        for i in range(12)
        for lg, tp in ((1, "buy"), (2, "sell"))
    )
    envelope += b"]}}"
    for v in ALL_KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("CMC_PRO_API_KEY", "not-a-real-key")
    monkeypatch.setattr(
        split_tape.urllib.request, "urlopen", lambda req, timeout=None: io.BytesIO(envelope)
    )
    out_path = tmp_path / "r.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["split_tape.py", "--address", "0xdead", "--symbol", "X", "--json", str(out_path)],
    )
    split_tape.main()
    out = capsys.readouterr().out
    assert "keyed via $CMC_PRO_API_KEY" in out.splitlines()[0]
    assert "1 credit — keyed via $CMC_PRO_API_KEY" in out.splitlines()[-1]
    receipt = json.loads(out_path.read_text())
    assert receipt["credits_used"] == 1
    assert receipt["auth"].startswith("X-CMC_PRO_API_KEY from $CMC_PRO_API_KEY")
    assert (
        receipt["endpoint"].startswith(split_tape.BASE_KEYED)
        and "/public-api/" not in receipt["endpoint"]
    )
    assert "not-a-real-key" not in out_path.read_text(), "the key itself never enters a receipt"


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


@pytest.mark.live
def test_keyed_escape_hatch_reaches_the_keyed_endpoint_when_a_key_is_exported():
    """The fallback for a throttled IP, proven against the real keyed endpoint.

    Skipped, not failed, when no key is exported: the default path needs none and CI
    configures none. With one exported it must answer with the same contract and carry the
    envelope's own `credit_count` — which CMC reports as 1, or as 0 on a cached hit (observed
    2026-09-07: one of three identical keyed calls came back `credit_count: 0`). The receipt
    mirrors the envelope rather than asserting a price CMC does not always charge.
    """
    key, var = split_tape.api_key(), split_tape.api_key_var()
    if not key:
        pytest.skip("no CMC key exported — the keyless default is the tested path")
    swaps, meta = pull_swaps(UNI, pages=1)
    assert meta["error"] is None, f"keyed fetch via ${var} failed: {meta['error']}"
    assert swaps and any(s.get("tp") in ("buy", "sell") for s in swaps)
    assert isinstance(meta["credits"], int) and meta["credits"] >= 0


# ── the sweep: the step that chooses what to split ───────────────────────────────────


def _pair(sym, addr, scroll=None):
    row = {
        "base_asset_symbol": sym,
        "base_asset_contract_address": addr,
        "name": f"{sym}/WETH",
        "quote": [{"liquidity": 1.0, "volume_24h": 2.0}],
    }
    if scroll:
        row["scroll_id"] = scroll
    return row


def test_sweep_follows_the_envelope_cursor_and_never_repeats_a_token(monkeypatch):
    """The pagination trap, pinned.

    `spot-pairs/latest` puts `scroll_id` on the response ENVELOPE, not on the last row — the
    same shape that cost a day on `data.lastId` in pull_swaps. A sweep that reads the cursor
    off the row stops after one page and silently returns a short universe, which looks like
    a thin DEX rather than like a bug. The same token also trades in several pairs on one
    DEX, so without dedup by contract address a universe is mostly duplicates.
    """
    pages = [
        {"data": [_pair("AAA", "0xaaa"), _pair("BBB", "0xbbb")], "scroll_id": "p2"},
        {"data": [_pair("BBB", "0xBBB"), _pair("CCC", "0xccc")]},  # repeat, different case
    ]
    seen_params = []

    def fake_get(path, retries=3, **params):
        seen_params.append(params)
        return pages[len(seen_params) - 1] if len(seen_params) <= len(pages) else {"data": []}

    monkeypatch.setattr(sweep_universe, "get", fake_get)
    tokens, err = sweep_universe.sweep_source(1, "uniswap-v3", per_source=10)

    assert err is None
    assert [t["symbol"] for t in tokens] == ["AAA", "BBB", "CCC"], "deduped by address, in order"
    assert "scroll_id" not in seen_params[0], "the first page asks for no cursor"
    assert seen_params[1]["scroll_id"] == "p2", "the second page uses the ENVELOPE's cursor"


def test_sweep_returns_a_throttle_instead_of_blaming_the_dex(monkeypatch):
    """A rate-limited source and a source with no pairs are different facts.

    The error travels back to the caller rather than raising, so the run reports six good
    sources and one throttled one instead of dying on the seventh — and so the note column
    can say which it was.
    """
    monkeypatch.setattr(
        sweep_universe, "get", lambda path, retries=3, **p: {"_err": "HTTP 429 (error 1022)"}
    )
    tokens, err = sweep_universe.sweep_source(1, "uniswap-v3", per_source=10)
    assert tokens == []
    assert "429" in err, "the caller is told it was throttled, not that the DEX was empty"


def test_sweep_stops_at_per_source_even_when_the_page_is_bigger(monkeypatch):
    """A budget is a budget: the API's page size does not get to decide the universe size."""
    monkeypatch.setattr(
        sweep_universe,
        "get",
        lambda path, retries=3, **p: {"data": [_pair(f"T{i}", f"0x{i:040x}") for i in range(100)]},
    )
    tokens, _ = sweep_universe.sweep_source(1, "uniswap-v3", per_source=7)
    assert len(tokens) == 7


# ── a throttle that arrives late must not discard the pages that already landed ──────


def _paged_envelope(n_swaps, last_id=None):
    """One page of alternating buy/sell swaps, each with a distinct maker."""
    swaps = ",".join(
        f'{{"tx":"0x{i}","lgid":"{i}","tp":"{"buy" if i % 2 else "sell"}",'
        f'"v":"{100 + i}","ma":"0xmaker{i}"}}'
        for i in range(n_swaps)
    )
    tail = f',"lastId":"{last_id}"' if last_id else ""
    return f'{{"data":{{"swaps":[{swaps}]{tail}}}}}'.encode()


def test_a_throttle_after_page_one_keeps_page_one_instead_of_reporting_a_failure(
    monkeypatch, capsys, tmp_path
):
    """The rate limit is per IP, so it is the likeliest thing to meet a reader on a first run.

    Until 2026-09-08 any error discarded the whole token: `pull_swaps` broke out of the page
    loop and returned the swaps it had, and main() threw them away and printed "API error".
    Three good pages became a failed run because the fourth was throttled. A smaller window is
    a result; only an empty one is a failure — and the short window has to be stated, because
    a number over 200 swaps is not the same claim as one over 800.
    """
    calls = {"n": 0}

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return io.BytesIO(_paged_envelope(40, last_id="page2"))
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    for v in ALL_KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    monkeypatch.setattr(split_tape.urllib.request, "urlopen", flaky)
    out_json = tmp_path / "r.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "split_tape.py",
            "--address",
            "0xdead",
            "--symbol",
            "X",
            "--pages",
            "4",
            "--json",
            str(out_json),
        ],
    )
    split_tape.main()
    out = capsys.readouterr().out

    assert "API error" not in out, "a late throttle is not a failed token"
    assert "40" in out, "the 40 swaps that did land are measured"
    assert "partial" in out, "the row is marked partial"
    assert "1 of 4 requested page(s)" in out, "the run states how short the window was"
    assert "throttled" in out, "and why it was short"

    receipt = json.loads(out_json.read_text())
    assert receipt["partial_rows"], "a JSON consumer must not read a partial window as complete"
    assert receipt["partial_rows"][0] == {
        "symbol": "X",
        "pages_fetched": 1,
        "pages_requested": 4,
        "throttled": True,
    }


def test_a_throttle_before_any_page_is_still_a_failure_not_an_empty_result(monkeypatch, capsys):
    """The other half of the same rule. With nothing fetched there is nothing to report, and
    the run must exit 75 rather than print a confident row built on zero swaps."""

    def always_limited(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

    for v in ALL_KEY_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    monkeypatch.setattr(split_tape.urllib.request, "urlopen", always_limited)
    monkeypatch.setattr(sys, "argv", ["split_tape.py", "--address", "0xdead", "--symbol", "X"])

    with pytest.raises(SystemExit) as ex:
        split_tape.main()
    assert ex.value.code == 75, "EX_TEMPFAIL — nothing landed, so this is a rate limit not a row"
    assert "API error" in capsys.readouterr().out


# ── holder count: context for the share, and never able to break the run ─────────────


def test_holder_count_reads_the_camelcase_parameter_the_endpoint_actually_wants():
    """`address` is what every neighbouring DEX endpoint takes. This one wants `tokenAddress`,
    and answers `address` with error 4002 "Missing required parameter" — which reads exactly
    like an endpoint that needs a key. That casing is why the holder series was collected with
    a keyed cron for days before anyone tried it unkeyed."""
    seen = {}

    def fake_get(path, retries=3, **params):
        seen.update({"path": path, "params": params})
        return {"data": {"count": "1150"}}

    import split_tape as st

    real, st.get = st.get, fake_get
    try:
        n = st.holders_count("0xabc", "ethereum")
    finally:
        st.get = real
    assert n == 1150
    assert seen["path"] == "/v1/dex/holders/count"
    assert seen["params"] == {"platform": "ethereum", "tokenAddress": "0xabc"}, (
        "tokenAddress, camelCase — not address"
    )


@pytest.mark.parametrize(
    "response",
    [
        {"_err": "HTTP 429 (error 1022)"},  # throttled
        {"data": None},  # answered, no payload
        {"data": {"count": None}},  # payload, no count
        {"data": {"count": "not-a-number"}},  # count that will not parse
    ],
)
def test_a_holder_count_that_does_not_answer_returns_none_and_never_raises(response):
    """The share is the product; the holder count is context beside it. A run that has already
    computed its number must not die because a second, optional call was rate-limited — the
    rate limit is per IP and this call is made after the expensive one has succeeded."""
    import split_tape as st

    real, st.get = st.get, lambda path, retries=3, **p: response
    try:
        assert st.holders_count("0xabc") is None
    finally:
        st.get = real
