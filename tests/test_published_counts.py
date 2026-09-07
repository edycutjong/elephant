"""The published test counts, checked against the suite itself.

Found 2026-09-07: README, DEMO and JUDGE said 25 tests (21 offline, 4 live), the landing page
said 21 (17 offline) and the deck said 21. Three answers to one question, all typed by hand.
This file reads the suite the way pytest collects it and asserts every judge-facing surface
states that count — so the number a judge reads is the number the suite has.
"""

import ast
import re
from pathlib import Path

BUILD = Path(__file__).resolve().parents[1]


def _suite_counts():
    """(total, offline, live), read from the test files the way pytest would collect them:
    every test_* function, a parametrize multiplies by its literal list, @pytest.mark.live
    marks live. Static, so it needs no second pytest session and cannot drift from the files."""
    total = live = 0
    for path in sorted((BUILD / "tests").glob("test_*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                continue
            n, is_live = 1, False
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "parametrize":
                    n *= len(ast.literal_eval(d.args[1]))
                if isinstance(d, ast.Attribute) and d.attr == "live":
                    is_live = True
            total += n
            live += n if is_live else 0
    return total, total - live, live


def test_every_surface_publishes_the_same_test_count_as_the_suite():
    """Found 2026-09-07: README, DEMO and JUDGE said 25 (21 offline, 4 live), the landing
    page said 21 (17 offline) and the deck said 21. Three answers to one question, all typed
    by hand. Every judge-facing surface must state the count this suite actually has."""
    total, offline, live = _suite_counts()
    expect = {
        "README.md": [
            f"**{total}** ({offline} offline, {live} live)",
            f"pytest, {offline} offline tests",
        ],
        "DEMO.md": [f"**{total}** ({offline} offline, {live} live)", f"# {offline} offline tests"],
        "scripts/site_templates/JUDGE.md": [f"**{total}** ({offline} offline, {live} live)"],
        "scripts/site_templates/landing.html": [
            f"{total} tests ({offline} offline, {live} against the live contract)"
        ],
        "scripts/site_templates/deck.html": [
            f'<div class="v">{total}</div><div class="k">tests · {live} against live CMC</div>'
        ],
    }
    for rel, phrases in expect.items():
        text = (BUILD / rel).read_text()
        for phrase in phrases:
            assert phrase in text, f"{rel} does not say {phrase!r}"
        # and no stale count survives beside the right one
        for stale in re.findall(r"\b(\d+)\s+offline", text):
            assert int(stale) == offline, f"{rel} still says {stale} offline"
