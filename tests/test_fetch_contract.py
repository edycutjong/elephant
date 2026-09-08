"""The fetch contract: what `get()` and `pull_swaps()` promise their callers.

Everything above the network in this project rests on one rule — a fetch failure is
RETURNED, never raised and never swallowed. `pull_swaps` decides what happened with
`if "_err" in d`, `main()` decides an exit code from `meta["throttled"]`, and the sweep
decides whether a DEX was empty or throttled from the same shape. Each test below pins one
edge of that contract; several are named for a defect a real run produced.
"""

import io
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import split_tape  # noqa: E402
from split_tape import pull_swaps  # noqa: E402

ALL_KEY_VARS = (*split_tape.KEY_VARS, "X_CMC_PRO_API_KEY", "API_KEY")


def _unkeyed(monkeypatch):
    for var in ALL_KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def test_is_keyed_answers_the_question_without_ever_holding_the_key(monkeypatch):
    """2026-09-08: the sweep printed its mode from `api_key_var()`, so a script whose only
    question is "keyed or not?" had to reach for the credential-shaped half of the API.

    `is_keyed()` is the answer to that question and nothing else: a bool, derived from the
    same three variables, carrying neither the key nor the variable's name.
    """
    _unkeyed(monkeypatch)
    assert split_tape.is_keyed() is False
    monkeypatch.setenv("COINMARKETCAP_API_KEY", "not-a-real-key")
    assert split_tape.is_keyed() is True
    monkeypatch.setenv("COINMARKETCAP_API_KEY", "   ")  # blank is not a key, here too
    assert split_tape.is_keyed() is False


def test_a_transport_failure_is_returned_as_an_error_rather_than_raised(monkeypatch):
    """A DNS failure, a timeout and a 200 whose body is not JSON are all "no contract came
    back", and none of them is an exception the caller should have to catch: `main()` prints
    a row per token and must reach the next token. The error travels in `_err`, named by the
    exception type so a reader can tell a socket problem from a malformed body.
    """
    _unkeyed(monkeypatch)
    for exc, name in (
        (urllib.error.URLError("nodename nor servname provided"), "URLError"),
        (TimeoutError("timed out"), "TimeoutError"),
    ):

        def raiser(url, timeout=None, exc=exc):
            raise exc

        monkeypatch.setattr(split_tape.urllib.request, "urlopen", raiser)
        d = split_tape.get("/v1/dex/tokens/transactions", address="0xdead")
        assert d["_err"].startswith(name)
        assert "_throttled" not in d, "a socket failure is not a rate limit"

    monkeypatch.setattr(
        split_tape.urllib.request,
        "urlopen",
        lambda url, timeout=None: io.BytesIO(b"<html>Bad Gateway from a proxy</html>"),
    )
    swaps, meta = pull_swaps("0xdead", pages=1)
    assert swaps == []
    assert "JSONDecodeError" in meta["error"], "a non-JSON 200 must not read as an empty tape"
    assert meta["throttled"] is False


def test_get_returns_a_mapping_even_when_the_retry_budget_is_gone(monkeypatch):
    """`pull_swaps` asks `if "_err" in d` — so every path out of `get()` has to be a mapping.

    The one path that never runs a request at all is a spent retry budget; it must still
    come back as a described, throttled error rather than as `None`, which would fail as a
    TypeError three frames away from the fetch that caused it.
    """
    _unkeyed(monkeypatch)

    def never_called(url, timeout=None):
        raise AssertionError("no request should be made with no attempts left")

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", never_called)
    d = split_tape.get("/v1/dex/tokens/transactions", retries=-1, address="0xdead")
    assert "_err" in d and d["_throttled"] is True


def test_a_page_of_only_duplicates_stops_the_walk_instead_of_spinning(monkeypatch):
    """The other half of the cursor bug (2026-09-07).

    When the cursor does not advance — CMC hands back a page whose every (tx, lgid) was
    already seen — the paginator must stop and say so. Without the stall flag a run spends
    its whole page budget re-fetching one window and reports the count as if it were depth.
    """
    page = [{"tx": "0xA", "lgid": str(i), "tp": "buy", "v": "1", "ma": "a"} for i in range(3)]
    monkeypatch.setattr(
        split_tape, "get", lambda path, **q: {"data": {"lastId": "never-moves", "swaps": page}}
    )
    monkeypatch.setattr(split_tape.time, "sleep", lambda s: None)
    swaps, meta = pull_swaps("0xdead", pages=8)
    assert len(swaps) == 3, "the duplicates are dropped, not counted as depth"
    assert meta["stalled"] is True
    assert meta["pages"] == 2, "it stopped on the second page, not after all eight"
    assert meta["error"] is None, "a stall is not an API error"


def test_the_throttle_advice_for_a_keyed_run_names_the_variable_never_the_key(monkeypatch):
    """A keyed 429 is a different fact from a keyless one: it is the key's own quota, and
    telling that reader to "export a free key" is advice they have already taken.

    The keyed branch must name the exported variable and offer the keyless surface as the
    way back — and it must print the variable's NAME, never its value.
    """
    _unkeyed(monkeypatch)
    monkeypatch.setenv("CMC_API_KEY", "not-a-real-key")
    msg = split_tape.throttle_advice("HTTP 429 (error 1022): You've reached the limit")
    assert "$CMC_API_KEY is exported" in msg
    assert "unset CMC_API_KEY" in msg and "keyless surface" in msg
    assert "not-a-real-key" not in msg, "the key itself never reaches a message"
    assert split_tape.KEY_URL not in msg, "do not send a keyed reader to go and get a key"
    assert "15 s + 30 s + 60 s" in msg, "the reader is told how long they already waited"
