"""The browser QA harness, run against the real pages and against a broken one.

`scripts/qa_site.py` is 40-odd measured gates over site/index.html and site/pitch/index.html.
Two things have to be true of it and only one of them is usually tested:

  1. every gate passes on the committed site — that is the first test below, which runs the
     whole harness the way `python3 scripts/qa_site.py` runs it, in a real chromium;
  2. every gate can FAIL. A harness that reports PASS on a page built to break it is not a
     harness, it is 300 lines of decoration. The second test builds exactly that page — an
     off-origin image, a dead '#' link, text a shade off its own background, a social card
     pointing at a file that does not exist, four map labels stacked on each other outside
     the plot frame — and asserts the harness names every one of them.

Skipped, never faked, when playwright or its chromium is not installed: `make install` puts
both in place (`python3 -m playwright install chromium`).
"""

import json
import re
import runpy
import sys
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILD / "scripts"))

pytest.importorskip("numpy", reason="the QA harness measures screenshots with numpy")
pytest.importorskip("PIL", reason="the QA harness measures screenshots with pillow")
sync_api = pytest.importorskip("playwright.sync_api", reason="the QA harness drives a browser")

import qa_site  # noqa: E402

CARD = "https://elephant.edycu.dev/assets/{}?v=deadbeef"

# A page built to fail: every defect below is one the harness claims to catch.
BROKEN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>built to fail</title>
<meta name="description" content="A page built to fail every measured gate in the harness, so the harness can be shown to fail.">
<meta property="og:description" content="Built to fail.">
<meta name="twitter:description" content="Built to fail.">
<meta property="og:site_name" content="Elephant">
<meta name="twitter:card" content="summary_large_image">
<meta name="author" content="Edy Cu">
<meta name="twitter:creator" content="@edycutjong">
<meta name="twitter:site" content="@edycutjong">
<meta property="og:image" content="{card}">
<meta name="twitter:image" content="{card}">
<meta property="og:image:alt" content="a card that is not there">
<link rel="canonical" href="https://elephant.edycu.dev/">
<style>
  body {{ margin:0; background:#0B0E14; color:#E6EDF3; font:16px/1.5 system-ui, sans-serif; }}
  .low {{ color:#0D1017; }}
  line.mid {{ stroke:#5E6C80; stroke-dasharray:6 5; }}
  line.grid {{ stroke:#243044; }}
  text {{ fill:#E6EDF3; font-size:13px; }}
</style></head>
<body>
  <h1>Built to fail</h1>
  <p class="low">This sentence is one shade away from its own background, which is the
  defect the contrast gate exists to measure rather than to eyeball.</p>
  <p><a href="#">a link that goes nowhere</a>, and
  <a href="https://example.com/elsewhere">one that leaves the site in the same tab</a>.</p>
  <img src="https://127.0.0.1:9/off-origin.png" alt="an image loaded from somewhere else">
  <table class="api"><thead><tr><th>endpoint</th></tr></thead>
  <tbody><tr><td>/v1/dex/tokens/transactions</td></tr></tbody></table>
  <svg class="quadrant" viewBox="0 0 720 560" width="720" height="560">
    <rect x="100" y="100" width="200" height="200" fill="#141A24"/>
    <line class="mid" x1="500" y1="0" x2="500" y2="560"/>
    <line class="grid" x1="0" y1="20" x2="720" y2="20"/>
    {points}
  </svg>
</body></html>
"""

POINT = (
    '<g class="pt" data-token="{t}" transform="translate(500,400)">'
    '<circle r="13" fill="#FFB020"/><text x="0" y="0" text-anchor="middle">{t}</text></g>'
)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except sync_api.Error as e:  # chromium not installed on this machine
            pytest.skip(f"chromium is not installed: {str(e).splitlines()[0]}")
        yield b
        b.close()


def test_every_gate_the_harness_publishes_passes_on_the_committed_site(
    browser, monkeypatch, tmp_path
):
    """The harness, run exactly as `python3 scripts/qa_site.py` runs it — through the
    __main__ guard, in a real chromium, against the committed pages over HTTP.

    Every gate it prints is a claim the submission makes about those two surfaces: the card,
    the contrast floor, the mobile height budget, the reduced-motion state, the deck's stage
    animation, the loop's seam. One FAIL is one broken claim, and the exit code is 0 only
    when there are none.

    The `browser` fixture is requested only so that this skips, rather than errors, on a
    machine where chromium was never installed; the run below launches its own.
    """
    monkeypatch.setattr(sys, "argv", ["qa_site.py", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as ex:
        runpy.run_path(str(BUILD / "scripts" / "qa_site.py"), run_name="__main__")
    assert ex.value.code == 0, "qa_site.py reported a failing gate — run it for the list"

    notes = json.loads((tmp_path / "notes.json").read_text())
    assert notes["landing.min_contrast"] >= qa_site.CONTRAST_FLOOR
    assert notes["deck.min_contrast"] >= qa_site.CONTRAST_FLOOR
    assert notes["landing.mobile_height"] <= qa_site.MOBILE_HEIGHT_BUDGET
    assert notes["landing.text_nodes"]["total"] > 100, "the contrast gate measured a real page"
    assert len(notes["loop.amber_mass"]) > 10, "the loop was swept, not sampled once"
    assert (tmp_path / "landing-375.png").is_file() and (tmp_path / "deck-01.png").is_file()


def test_a_page_built_to_fail_is_failed_by_every_gate_that_covers_it(
    browser, monkeypatch, tmp_path, capsys
):
    """The gates, proven able to fail. Six defects, each one the harness names:

    an image fetched from another origin; a link whose href is '#'; body text one shade off
    its own background; a social card whose file is not in the tree; and a quadrant map whose
    four labels sit on top of each other, on a dashed guide line, outside the plot frame.

    A page like this can never exist in site/, which is exactly why the failure paths need
    driving here — without it, "ALL GATES PASS" is unfalsifiable.
    """
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    page_path = site / "broken.html"
    page_path.write_text(
        BROKEN_PAGE.format(
            card=CARD.format("no-such-card.png"),
            points="".join(POINT.format(t=t) for t in ("AAA", "BBB", "CCC", "DDD")),
        )
    )
    out = tmp_path / "qa"
    out.mkdir()
    monkeypatch.setattr(qa_site, "SITE", site)
    monkeypatch.setattr(qa_site, "FAIL", [])
    monkeypatch.setattr(qa_site, "NOTES", {})

    with qa_site.serving(site):
        qa_site.check_static(page_path, "broken")
        qa_site.check_widths(browser, page_path, "broken", out, is_deck=False)
        qa_site.check_offline(browser, page_path, "broken", out)
        qa_site.check_hover(browser, page_path, "broken", [".no-such-element"])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.set_content("<body><h1>a page with no map on it</h1></body>")
        qa_site.check_map_labels(page, "mapless")
        ctx.close()

    printed = capsys.readouterr().out
    failed = qa_site.FAIL

    def named(fragment):
        return [f for f in failed if fragment in f]

    assert named("broken: no externally loaded assets at all"), "the off-origin image"
    assert named("broken: dead '#' link"), "the link that goes nowhere"
    assert named("og:image /assets/no-such-card.png is a file under site/"), "the missing card"
    assert not named("og-image.png is exactly"), "the card gates stop at the missing file"
    assert named("broken: contrast"), "the shade-off-background paragraph"
    assert named("broken@1440: every map label inside the plot frame")
    assert named("broken@1440: no map label crosses a dashed guide line")
    assert named("broken@1440: no map label touches another token's label or dot")
    assert named("broken: hover target .no-such-element exists")
    assert named("mapless: quadrant map present with four labelled points")

    # the placeholder scan is not what is broken here, and it must not fire
    assert not named("no placeholder"), failed
    # every off-origin request really was blocked, and the harness counted them
    assert int(re.search(r"\((\d+) blocked\)", printed).group(1)) >= 1
    assert qa_site.ok("a gate that holds", True) is True and len(failed) == len(qa_site.FAIL)


def test_a_card_that_is_not_a_png_is_measured_as_one_rather_than_believed(
    monkeypatch, tmp_path, capsys
):
    """The og-image gates read the file, never the page's claims about it. A file that is
    not a PNG at all — a JPEG saved with the wrong extension is the way this happens — has
    no IHDR to read, so the size is None and the gate that compares it with the declared
    width and height fails instead of passing on two matching strings.
    """
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    junk = site / "assets" / "not-a-card.png"
    junk.write_bytes(b"\xff\xd8\xff\xe0" + b"JFIF" * 64)
    monkeypatch.setattr(qa_site, "SITE", site)
    monkeypatch.setattr(qa_site, "FAIL", [])

    assert qa_site.png_size(junk) is None
    html = BROKEN_PAGE.format(card=CARD.format("not-a-card.png"), points="")
    qa_site.check_card(html, "junk")

    assert any("og-image.png is exactly 1200x630 (None)" in f for f in qa_site.FAIL)
    assert any("declare the file's own size" in f for f in qa_site.FAIL)
    assert any("?v= is the hash of the bytes shipped" in f for f in qa_site.FAIL)
    assert "FAIL junk: og:image:alt present" not in capsys.readouterr().out, (
        "the gates after the size check still run — the card is only skipped when absent"
    )
