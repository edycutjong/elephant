"""Tests for the split.

LESSONS R11: assert the EXTERNAL side effect, not the return value. A function returning
{"success": true} proves the function returned; it does not prove the API answered. So the
live tests below assert against a real response, and they are meant to fail if CMC changes
the contract — that is the point of them.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from split_tape import PAGE, pull_swaps, split  # noqa: E402

UNI = "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984"


# ---------- pure logic: the maths, on known inputs ----------


def _swap(tp, v, ma):
    return {"tp": tp, "v": str(v), "ma": ma, "tx": f"{tp}{v}{ma}"}


def test_split_computes_average_ticket_per_side():
    swaps = [_swap("buy", 100, "a"), _swap("buy", 300, "b"), _swap("sell", 50, "c")]
    r = split(swaps)
    assert r["avg_buy"] == 200.0  # (100+300)/2
    assert r["avg_sell"] == 50.0
    assert r["ticket_ratio"] == 4.0  # 200/50
    assert r["elephant_side"] == "buy"


def test_split_counts_distinct_wallets_not_trades():
    """The claim is 'one desk', so the same maker trading twice must count once."""
    swaps = [_swap("buy", 100, "same"), _swap("buy", 100, "same"), _swap("sell", 10, "x")]
    r = split(swaps)
    assert r["buys"] == 2
    assert r["buy_wallets"] == 1


def test_top_maker_share_attributes_volume_per_wallet():
    """The headline: how much of one side is ONE wallet. 90 of the 100 sell dollars
    below belong to `desk`, across two swaps, against three retail sellers."""
    swaps = [
        _swap("sell", 60, "desk"),
        _swap("sell", 30, "desk"),
        _swap("sell", 5, "r1"),
        _swap("sell", 3, "r2"),
        _swap("sell", 2, "r3"),
        _swap("buy", 50, "x"),
        _swap("buy", 50, "y"),
    ]
    r = split(swaps)
    assert r["sell_top_maker"] == "desk"
    assert r["sell_top_share"] == pytest.approx(0.90)
    assert r["sell_top_swaps"] == 2
    assert r["sell_top_vol"] == 90.0
    assert r["sell_wallets"] == 4
    assert r["buy_top_share"] == pytest.approx(0.50)
    assert r["top_share"] == pytest.approx(0.90)
    assert r["concentrated_side"] == "sell"


def test_maker_share_separates_what_ticket_ratio_cannot_at_flat_flow():
    """At flat net flow the ticket ratio collapses to the count ratio. One desk selling
    $1M in ten $100k clips into 1,000 $1k buyers and 1,000 matched $1k sellers/buyers
    both read net flow 0 — and here the desk's clips are deliberately no larger than a
    crowd's, so the ticket ratio is ~1 in BOTH cases. Maker share still tells them apart."""
    retail_buys = [_swap("buy", 1000, f"b{i}") for i in range(1000)]
    desk = [_swap("sell", 1000, "desk") for _ in range(1000)]
    crowd = [_swap("sell", 1000, f"s{i}") for i in range(1000)]
    one_seller, matched = split(desk + retail_buys), split(crowd + retail_buys)
    assert one_seller["ticket_ratio"] == pytest.approx(1.0)
    assert matched["ticket_ratio"] == pytest.approx(1.0)  # the ticket ratio cannot tell
    assert one_seller["sell_top_share"] == pytest.approx(1.0)  # the maker share can
    assert matched["sell_top_share"] == pytest.approx(0.001)


def test_net_flow_is_degenerate_where_the_split_is_not():
    """The thesis, as a test: two opposite structures, identical net flow."""
    retail = [_swap("buy", 1000, f"r{i}") for i in range(1000)]
    one_seller = [_swap("sell", 1_000_000, "desk"), *retail]
    matched = [_swap("sell", 1000, f"s{i}") for i in range(1000)] + [
        _swap("buy", 1000, f"b{i}") for i in range(1000)
    ]
    a, b = split(one_seller), split(matched)
    assert abs(a["net_flow_pct"]) < 1e-9
    assert abs(b["net_flow_pct"]) < 1e-9  # net flow cannot tell them apart
    assert a["ticket_ratio"] > 100  # the split can
    assert b["ticket_ratio"] == pytest.approx(1.0)


def test_split_returns_none_when_one_side_is_empty():
    assert split([_swap("buy", 1, "a")]) is None


def test_page_cap_is_the_documented_hundred():
    assert PAGE == 100  # limit=200 and 500 both return HTTP 400


# ---------- live: assert the API actually answers with the contract we rely on ----------


@pytest.mark.live
def test_live_swaps_carry_the_three_fields_we_depend_on():
    swaps, _ = pull_swaps(UNI, pages=1)
    assert swaps, "no swaps returned — the keyless endpoint or the address changed"
    for s in swaps[:20]:
        assert s.get("tp") in ("buy", "sell"), "side field 'tp' missing or unexpected"
        assert s.get("v") is not None, "USD value field 'v' missing"
        assert s.get("ma"), "maker address 'ma' missing — the wallet count depends on it"


@pytest.mark.live
def test_live_v_really_is_usd():
    """v must equal amount * unit price. If CMC changes denomination, every number is wrong."""
    swaps, _ = pull_swaps(UNI, pages=1)
    checked = 0
    for s in swaps:
        try:
            a0, p0, v = float(s["a0"]), float(s["t0pu"]), float(s["v"])
        except (KeyError, TypeError, ValueError):
            continue
        if v <= 0:
            continue
        assert abs(a0 * p0 - v) / v < 0.05, f"v is not USD: a0*t0pu={a0 * p0} vs v={v}"
        checked += 1
        if checked >= 5:
            break
    assert checked >= 1, "could not verify the denomination on any swap"


@pytest.mark.live
def test_live_split_produces_a_two_sided_result():
    swaps, _ = pull_swaps(UNI, pages=1)
    r = split(swaps)
    assert r is not None
    assert r["buys"] > 0 and r["sells"] > 0
    assert r["buy_wallets"] <= r["buys"]  # wallets can never exceed trades
    assert r["sell_wallets"] <= r["sells"]
    assert r["ticket_ratio"] >= 1.0  # it is a max(x, 1/x)
