"""The command line, which is the whole product surface.

`python3 scripts/split_tape.py` is the judged capability; the other four scripts are what
CI, the benchmark and the submission gate run. None of them has a return value a caller
could assert on — what they have is a transcript, an exit code and, sometimes, a file. So
every test here runs the real `main()` and asserts on those three things.

Each script is also run through its `__main__` guard with `runpy`, because "the file a judge
runs" and "the function the tests call" are only the same thing if the guard says so.
"""

import json
import runpy
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[1]
SCRIPTS = BUILD / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bench  # noqa: E402
import check_submission_readiness as readiness  # noqa: E402
import seed  # noqa: E402
import split_tape  # noqa: E402
import sweep_universe  # noqa: E402

ALL_KEY_VARS = (*split_tape.KEY_VARS, "X_CMC_PRO_API_KEY", "API_KEY")


def _unkeyed(monkeypatch):
    for var in ALL_KEY_VARS:
        monkeypatch.delenv(var, raising=False)


def _swap(tp, v, ma):
    return {"tp": tp, "v": str(v), "ma": ma, "tx": f"{tp}-{v}-{ma}", "lgid": "1"}


def _meta(**over):
    m = {"pages": 1, "error": None, "stalled": False, "throttled": False, "credits": 0}
    m.update(over)
    return m


def _argv(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", list(args))


# ── split_tape: the judged capability ────────────────────────────────────────


def test_a_stalled_walk_is_reported_rather_than_passed_off_as_depth(monkeypatch, capsys):
    """`--pages 8` on a token whose cursor stops advancing returns one window, not eight.

    The run is not wrong — the swaps it has are real — but a reader who asked for eight
    pages and reads a 100-swap count will attribute the shallowness to the token. The note
    only appears when more than one page was actually asked for, because on `--pages 1`
    there is no stall to report.
    """
    _unkeyed(monkeypatch)
    tape = [_swap("buy", 100 + i, f"b{i}") for i in range(10)]
    tape += [_swap("sell", 100 + i, f"s{i}") for i in range(10)]
    monkeypatch.setattr(
        split_tape, "pull_swaps", lambda *a, **k: (tape, _meta(pages=2, stalled=True))
    )
    _argv(monkeypatch, "split_tape.py", "--address", "0xdead", "--symbol", "X", "--pages", "2")
    split_tape.main()
    out = capsys.readouterr().out
    assert "pagination stalled" in out
    assert "spend calls on duplicates" in out


def test_a_one_sided_window_is_named_as_such_and_never_ranked(monkeypatch, capsys):
    """A window with buys and no sells has no split in it.

    `split()` returns None there rather than a ratio against zero, and `main()` has to say
    which token that was and then exit non-zero — printing an empty table and exiting 0
    would report "nothing to see" for a run that never measured anything.
    """
    _unkeyed(monkeypatch)
    one_sided = [_swap("buy", 100, f"b{i}") for i in range(6)]
    monkeypatch.setattr(split_tape, "pull_swaps", lambda *a, **k: (one_sided, _meta()))
    _argv(monkeypatch, "split_tape.py", "--address", "0xdead", "--symbol", "X")
    with pytest.raises(SystemExit) as ex:
        split_tape.main()
    out = capsys.readouterr().out
    assert "insufficient swaps on one side" in out
    assert "no token produced a two-sided split" in str(ex.value.code)
    assert ex.value.code != 75, "EX_TEMPFAIL means 'try again' — this run would fail again"


def test_a_window_with_no_balanced_row_refuses_to_widen_the_published_rule(
    monkeypatch, capsys, tmp_path
):
    """The hero rule is published: max top-maker share among rows reading |net flow| < 5%.

    When no row qualifies, the honest outcome is no hero — not the most concentrated row
    the window happens to hold. A lopsided token is already flagged by every dashboard, so
    promoting one would demonstrate nothing the tool claims. The receipt has to agree with
    the transcript: `hero` and `hero_evidence` are both null.
    """
    _unkeyed(monkeypatch)
    lopsided = [_swap("buy", 1000, f"b{i}") for i in range(10)]
    lopsided += [_swap("sell", 100, f"s{i}") for i in range(10)]
    monkeypatch.setattr(split_tape, "pull_swaps", lambda *a, **k: (lopsided, _meta()))
    receipt = tmp_path / "r.json"
    _argv(
        monkeypatch,
        "split_tape.py",
        "--address",
        "0xdead",
        "--symbol",
        "X",
        "--json",
        str(receipt),
    )
    split_tape.main()
    out = capsys.readouterr().out
    assert "no token read balanced (|net flow| < 5.0%)" in out
    assert "1 trusted rows" in out and "re-run rather than cherry-pick" in out
    assert "HERO" not in out
    payload = json.loads(receipt.read_text())
    assert payload["hero"] is None and payload["hero_evidence"] is None
    assert payload["rows"][0]["confidence"] == "ok", "the row is trusted; it is just not balanced"


def test_the_file_a_judge_runs_is_the_file_that_runs(monkeypatch, capsys):
    """README: `python3 scripts/split_tape.py`. Run exactly that way — through the __main__
    guard, not by importing main() — against an endpoint answering HTTP 400.

    A 400 is permanent: it is not retried, and the run must stop with CMC's own message and
    an exit code that is NOT 75. 75 is EX_TEMPFAIL and means "the same command will work in
    a minute"; using it for a broken contract teaches a caller to ignore a real break.
    """
    _unkeyed(monkeypatch)

    class Bad(urllib.error.HTTPError):
        def __init__(self):
            self.code = 400

        def read(self):
            return b'{"status":{"error_code":"400","error_message":"Invalid value for address"}}'

    def always_400(url, timeout=None):
        raise Bad()

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", always_400)
    _argv(monkeypatch, "split_tape.py", "--address", "0xdead", "--symbol", "X")
    with pytest.raises(SystemExit) as ex:
        runpy.run_path(str(SCRIPTS / "split_tape.py"), run_name="__main__")
    assert "every fetch failed" in str(ex.value.code)
    assert "HTTP 400 (error 400): Invalid value for address" in str(ex.value.code)
    assert ex.value.code != 75
    assert "keyless" in capsys.readouterr().out.splitlines()[0]


# ── sweep_universe: the step that chooses what to split ──────────────────────


def test_a_dex_with_no_pairs_is_an_empty_universe_not_an_error(monkeypatch):
    """Trap 2 in the module docstring: a slug that is not on that network answers 200 with
    an empty `data`. That is a fact about the pair, not a failure, and it must come back as
    (no tokens, no error) — the run reports 0 in the count column and keeps going. Returning
    an error there would put "throttled" in the note column of a DEX that answered fine.
    """
    monkeypatch.setattr(sweep_universe, "get", lambda path, **p: {"data": []})
    tokens, err = sweep_universe.sweep_source(199, "uniswap-v3", per_source=60)
    assert tokens == [] and err is None


def test_the_sweep_writes_one_universe_deduped_across_every_source(monkeypatch, capsys, tmp_path):
    """The same token trades on several DEXes: WETH is on all of them.

    The per-source lists are unioned by lowercased contract address, so the count at the
    bottom is a count of TOKENS, not of rows fetched, and each token keeps the label of the
    first network it was seen on. A throttled source is reported in its own note column and
    in the receipt's `errors`, while the tokens the other sources returned still ship.
    """
    _unkeyed(monkeypatch)
    weth = {"symbol": "WETH", "address": "0xC02aaa", "pair": "WETH/USDC", "liquidity": 9.0}

    def fake_source(network_id, dex_slug, per_source):
        if dex_slug == "raydium":
            return [], "HTTP 429 (error 1022): You've reached the limit for anonymous access"
        return [
            dict(weth, platform=None),
            {"symbol": f"T{network_id}", "address": f"0x{network_id:040x}", "platform": None},
        ], None

    monkeypatch.setattr(sweep_universe, "sweep_source", fake_source)
    out_path = tmp_path / "universe.json"
    _argv(monkeypatch, "sweep_universe.py", "--per-source", "2", "--json", str(out_path))
    sweep_universe.main()
    out = capsys.readouterr().out

    assert out.splitlines()[0].startswith("sweeping the universe — keyless")
    assert "429" in out, "the throttled source names itself in the note column"
    assert "1 source(s) errored" in out
    payload = json.loads(out_path.read_text())
    addrs = [t["address"] for t in payload["tokens"]]
    assert addrs.count("0xC02aaa") == 1, "WETH is one token, not one per DEX"
    assert payload["count"] == len(payload["tokens"]) == len({a.lower() for a in addrs})
    assert payload["auth"].startswith("none — CoinMarketCap keyless")
    assert payload["cursor"] == "scroll_id on the response envelope"
    assert [e["dex"] for e in payload["errors"]] == ["raydium"]
    assert {t["platform"] for t in payload["tokens"]} <= {p for _, _, p in sweep_universe.SOURCES}
    assert out.count("python3 scripts/split_tape.py --address") == 3, "three worked examples"


def test_the_sweep_exits_tempfail_when_not_one_source_answers(monkeypatch, capsys):
    """Every source empty is the shape a throttled IP produces, and it is not a universe.

    Exit 75 (EX_TEMPFAIL), the same contract split_tape.py uses, so a caller can tell "wait
    a minute" from "this is broken" without parsing the prose. Run through the __main__
    guard: this is the file `make sweep` executes.
    """
    _unkeyed(monkeypatch)
    calls = []

    def empty(req, timeout=None):
        calls.append(req.full_url)
        import io

        return io.BytesIO(b'{"data": []}')

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", empty)
    _argv(monkeypatch, "sweep_universe.py", "--per-source", "5")
    with pytest.raises(SystemExit) as ex:
        runpy.run_path(str(SCRIPTS / "sweep_universe.py"), run_name="__main__")
    assert ex.value.code == 75
    assert len(calls) == len(sweep_universe.SOURCES), "one call per source, then it stops"
    assert "no source returned a token" in capsys.readouterr().err


# ── seed: the recording, which is not the demo path ──────────────────────────


def test_the_seed_tape_records_its_own_provenance_and_replays_to_the_same_split(
    monkeypatch, capsys, tmp_path
):
    """The tape exists so the benchmark and CI can run with no network. That is only true
    if what it holds is a real capture, so the file carries the endpoint it came from, the
    UTC time, the address and the split as computed AT capture — and re-splitting the
    recorded swaps has to reproduce that split exactly, or the recording is not a recording.

    It also carries a note saying it is not the demo path, because the one substitution that
    sinks a submission is a demo quietly reading a file instead of the API.
    """
    _unkeyed(monkeypatch)
    tape = [_swap("buy", 100 + i, f"b{i}") for i in range(10)]
    tape += [_swap("sell", 50 + i, f"s{i}") for i in range(10)]
    out_path = tmp_path / "seed_tape.json"
    monkeypatch.setattr(seed, "OUT", out_path)
    monkeypatch.setattr(seed, "pull_swaps", lambda *a, **k: (tape, _meta()))
    _argv(monkeypatch, "seed.py", "--address", "0xdead", "--symbol", "X", "--pages", "2")
    seed.main()

    recorded = json.loads(out_path.read_text())
    assert "not the demo path" in recorded["_note"]
    assert recorded["source"] == f"{split_tape.BASE}/v1/dex/tokens/transactions"
    assert "/public-api/" in recorded["source"], "the recording came off the keyless surface"
    assert (recorded["symbol"], recorded["address"], recorded["pages"]) == ("X", "0xdead", 2)
    assert recorded["swap_count"] == len(tape) == len(recorded["swaps"])
    assert split_tape.split(recorded["swaps"]) == recorded["split_at_capture"]
    captured = capsys.readouterr().out
    assert "at capture: 10 buys avg $104 / 10 sells avg $54 (1.9x, ok)" in captured


def test_seed_refuses_to_write_a_tape_it_could_not_capture(monkeypatch, tmp_path):
    """A capture that failed must not overwrite the committed tape with an empty one.

    Both ways it can fail — the API returned an error, or it returned an empty window — end
    the run before the write, because a truncated seed tape is worse than a stale one: the
    benchmark keeps running and reports a number over nothing.
    """
    _unkeyed(monkeypatch)
    out_path = tmp_path / "seed_tape.json"
    monkeypatch.setattr(seed, "OUT", out_path)
    _argv(monkeypatch, "seed.py")

    monkeypatch.setattr(seed, "pull_swaps", lambda *a, **k: ([], _meta(error="HTTP 429")))
    with pytest.raises(SystemExit) as ex:
        seed.main()
    assert "capture failed: HTTP 429" in str(ex.value.code)

    monkeypatch.setattr(seed, "pull_swaps", lambda *a, **k: ([], _meta()))
    with pytest.raises(SystemExit) as ex:
        seed.main()
    assert "no swaps" in str(ex.value.code)
    assert not out_path.exists(), "nothing was written on either failure"


def test_seed_run_as_a_script_stops_before_it_can_overwrite_the_committed_tape(monkeypatch, capsys):
    """`make seed` re-captures data/seed_tape.json in place, so the failure path is the one
    that matters: run through the __main__ guard with the socket broken, and the committed
    tape must be byte-for-byte untouched when the run exits.
    """
    _unkeyed(monkeypatch)
    before = seed.OUT.read_bytes()

    def dead_socket(url, timeout=None):
        raise urllib.error.URLError("nodename nor servname provided")

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", dead_socket)
    _argv(monkeypatch, "seed.py")
    with pytest.raises(SystemExit) as ex:
        runpy.run_path(str(SCRIPTS / "seed.py"), run_name="__main__")
    assert "capture failed: URLError" in str(ex.value.code)
    assert seed.OUT.read_bytes() == before
    assert "capturing UNI from the live keyless endpoint" in capsys.readouterr().out


# ── bench: the reproducible number ───────────────────────────────────────────


def test_p95_is_always_a_real_observation_never_an_interpolation(capsys):
    """Nearest-rank, deliberately: an interpolated p95 is a number no run produced, and the
    published benchmark is meant to be a measurement a reader can find in the samples.
    """
    values = [float(i) for i in range(1, 11)]
    assert bench.pct(values, 50) == 6.0
    assert bench.pct(values, 95) == 10.0
    assert all(bench.pct(values, p) in values for p in range(1, 101))
    assert bench.pct([], 50) != bench.pct([], 50), "no samples is NaN, never 0"
    stats = bench.report("split (aggregation)", values)
    assert (stats["n"], stats["p50"], stats["p95"], stats["max"]) == (10, 6.0, 10.0, 10.0)
    assert "p50     6.000ms" in capsys.readouterr().out


def test_replay_mode_measures_the_aggregation_with_the_socket_unplugged(
    monkeypatch, capsys, tmp_path
):
    """`make bench` is the number CI publishes, so it must be deterministic — which it can
    only be if it never touches the network. The socket is replaced with a landmine here:
    if replay ever grew a fetch, this test is what fails.
    """

    def landmine(url, timeout=None):
        raise AssertionError("--replay must never open a socket")

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", landmine)
    out_path = tmp_path / "bench.json"
    _argv(monkeypatch, "bench.py", "--replay", "--iterations", "3", "--json", str(out_path))
    bench.main()
    out = capsys.readouterr().out
    payload = json.loads(out_path.read_text())
    tape = json.loads(bench.SEED.read_text())

    assert payload["mode"] == "replay" and payload["iterations"] == 3
    assert payload["split"]["n"] == 3 and payload["split"]["unit"] == "ms"
    assert payload["swaps"] == len(tape["swaps"]) > 0
    assert "fetch" not in payload, "replay times the aggregation alone"
    assert f"replay — {payload['swaps']} swaps captured" in out
    assert "no network" in out


def test_replay_without_a_tape_says_how_to_make_one(monkeypatch, tmp_path):
    """A missing seed tape is a setup problem with a one-line fix, and the error has to
    carry that line rather than a traceback from json.loads on a path that does not exist.
    """
    monkeypatch.setattr(bench, "SEED", tmp_path / "not-here.json")
    _argv(monkeypatch, "bench.py", "--replay")
    with pytest.raises(SystemExit) as ex:
        bench.main()
    assert "python3 scripts/seed.py" in str(ex.value.code)


def test_a_throttled_iteration_is_not_timed_as_a_split(monkeypatch, capsys, tmp_path):
    """The live benchmark runs against the anonymous tier, so some iterations WILL be
    throttled. A failed fetch still cost wall-clock time and stays in the fetch samples,
    but there is no aggregation to time — counting it as a 0 ms split would drag the p50
    of the only number this benchmark exists to report.
    """
    _unkeyed(monkeypatch)
    tape = [_swap("buy", 100, "b"), _swap("sell", 50, "s")]
    calls = {"n": 0}

    def flaky(address, pages=1):
        calls["n"] += 1
        if calls["n"] in (2, 4):
            return [], _meta(error="HTTP 429 (error 1022): limit for anonymous access", pages=0)
        return tape, _meta()

    monkeypatch.setattr(bench, "pull_swaps", flaky)
    out_path = tmp_path / "bench.json"
    _argv(monkeypatch, "bench.py", "--iterations", "5", "--json", str(out_path))
    bench.main()
    out = capsys.readouterr().out
    payload = json.loads(out_path.read_text())

    assert payload["fetch"]["n"] == 5, "every attempt is a fetch sample"
    assert payload["split"]["n"] == 3, "only the three that returned a tape are split samples"
    assert payload["swaps"] == 2
    assert "iteration 2: API error — HTTP 429" in out
    assert payload["credits_used"] == 0 and "0 credits — keyless" in out


def test_the_live_bench_stops_when_every_iteration_is_throttled(monkeypatch, tmp_path):
    """With no successful iteration there is nothing to report, and `report()` on an empty
    sample list would print a NaN p50 as if it were a measurement. Stop instead, and say
    which surface did the throttling.
    """
    _unkeyed(monkeypatch)
    monkeypatch.setattr(bench, "pull_swaps", lambda *a, **k: ([], _meta(error="HTTP 429")))
    _argv(monkeypatch, "bench.py", "--iterations", "2")
    with pytest.raises(SystemExit) as ex:
        bench.main()
    assert "rate-limiting" in str(ex.value.code)


def test_a_keyed_bench_reports_the_credits_it_spent(monkeypatch, capsys):
    """The keyless path spends nothing, and "0 credits" is one of the claims this project
    makes. A keyed run must therefore say so on the same line, with the envelope's own
    credit_count summed — the escape hatch cannot be mistaken for the default.
    """
    monkeypatch.setattr(bench, "api_key_var", lambda: "CMC_PRO_API_KEY")
    tape = [_swap("buy", 100, "b"), _swap("sell", 50, "s")]
    monkeypatch.setattr(bench, "pull_swaps", lambda *a, **k: (tape, _meta(credits=1)))
    _argv(monkeypatch, "bench.py", "--iterations", "4")
    bench.main()
    out = capsys.readouterr().out
    assert "keyed fetch via $CMC_PRO_API_KEY (escape hatch)" in out
    assert "4 credits — keyed" in out


def test_the_benchmark_is_executable_as_the_makefile_runs_it(monkeypatch, capsys):
    """`make bench` shells out to `python3 scripts/bench.py --replay --iterations 200`.
    Run through the __main__ guard against the committed tape, which is the exact command
    CI's Stage 3 job runs.
    """

    def landmine(url, timeout=None):
        raise AssertionError("--replay must never open a socket")

    monkeypatch.setattr(split_tape.urllib.request, "urlopen", landmine)
    _argv(monkeypatch, "bench.py", "--replay", "--iterations", "2")
    runpy.run_path(str(SCRIPTS / "bench.py"), run_name="__main__")
    assert "split (aggregation)" in capsys.readouterr().out


# ── check_submission_readiness: the placeholder gate ─────────────────────────


def test_a_placeholder_in_a_judge_facing_file_is_a_finding_and_one_in_source_is_not(
    monkeypatch, tmp_path, capsys
):
    """The scan is deliberately narrow. A TODO in a source comment is ordinary engineering;
    a TODO in the README is an unfinished submission. Widening it to the whole tree is how
    a gate like this gets switched off, so the file list is the gate's real content and is
    asserted here alongside the findings.
    """
    (tmp_path / "README.md").write_text("# X\n\ndeploy to 0x... when ready\nTODO: the demo\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "notes.md").write_text("watch https://youtu.be/VIDEO_ID\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x.py").write_text("# TODO: refactor this later\n")
    monkeypatch.setattr(readiness, "ROOT", tmp_path)

    scanned, findings = readiness.scan()
    assert scanned == ["README.md", "docs/notes.md"], "source files are not judge-facing"
    assert [(f["file"], f["line"], f["kind"]) for f in findings] == [
        ("README.md", 3, "unfilled address"),
        ("README.md", 4, "TODO marker"),
        ("docs/notes.md", 1, "placeholder video"),
    ]

    _argv(monkeypatch, "check_submission_readiness.py")
    assert readiness.main() == 1, "a finding must fail the gate"
    assert "3 placeholder(s) still in the submission" in capsys.readouterr().out

    _argv(monkeypatch, "check_submission_readiness.py", "--json")
    readiness.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["scanned"] == scanned and len(payload["findings"]) == 3


def test_a_line_that_describes_a_placeholder_is_not_itself_a_placeholder(monkeypatch, tmp_path):
    """The gate has to be able to survive its own documentation. README explains what the
    scanner looks for, and DEMO.md quotes its output — without the self-referential skip
    every judge-facing file that mentions the check would fail it, and the honest fix would
    be to stop writing about it.
    """
    (tmp_path / "README.md").write_text(
        "the readiness scanner rejects a TODO marker\n"
        "it also rejects an unfilled 0x... placeholder\n"
        "TODO: this line has no such excuse\n"
    )
    monkeypatch.setattr(readiness, "ROOT", tmp_path)
    _, findings = readiness.scan()
    assert [f["line"] for f in findings] == [3]


def test_this_submission_has_no_placeholders_left_in_it(monkeypatch, capsys):
    """The gate, run through its __main__ guard against this repository — the same command
    `make check` and CI's Stage 2 job run. Exit 0 is the claim that every judge-facing file
    in the commit under test is finished.
    """
    _argv(monkeypatch, "check_submission_readiness.py")
    with pytest.raises(SystemExit) as ex:
        runpy.run_path(str(SCRIPTS / "check_submission_readiness.py"), run_name="__main__")
    assert ex.value.code == 0, capsys.readouterr().out
    assert "clean — no unfilled addresses" in capsys.readouterr().out
