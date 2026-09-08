"""The renderer: the only path by which a number reaches a judge-facing page.

site/index.html, site/pitch/index.html and JUDGE.md are generated output. Every figure on
them comes from docs/proof/*.json — real keyless runs — and the render fails closed on an
unfilled slot, a mis-sized card and a page that no longer matches its receipts. These tests
drive the real renderer against the real receipts; the only thing that is faked is the
DESTINATION, so a test can never quietly rewrite the committed site.
"""

import json
import runpy
import shutil
import struct
import sys
from pathlib import Path

import pytest

BUILD = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BUILD / "scripts"))

import render_site  # noqa: E402

REAL_SITE = BUILD / "site"


def _sandbox(tmp_path, monkeypatch):
    """Point the renderer's OUTPUT at a temp tree. TEMPLATES, PROOF and the og-image are
    module constants bound at import and stay real — this changes where the render lands,
    never what it is rendered from."""
    site = tmp_path / "site"
    shutil.copytree(REAL_SITE / "assets", site / "assets")
    monkeypatch.setattr(render_site, "BUILD", tmp_path)
    monkeypatch.setattr(render_site, "SITE", site)
    monkeypatch.setattr(sys, "argv", ["render_site.py"])
    return site


def test_rendering_into_an_empty_tree_reproduces_the_committed_pages_byte_for_byte(
    tmp_path, monkeypatch, capsys
):
    """The claim the whole generator exists to support: nothing on either page was typed by
    hand. Rendering from the committed receipts into a fresh directory must reproduce the
    three committed files exactly — if a single number had ever been edited in the HTML, or
    a receipt changed without a re-render, the bytes would differ here.
    """
    site = _sandbox(tmp_path, monkeypatch)
    render_site.main()
    printed = capsys.readouterr().out

    for rendered, committed in (
        (site / "index.html", REAL_SITE / "index.html"),
        (site / "pitch" / "index.html", REAL_SITE / "pitch" / "index.html"),
        (tmp_path / "JUDGE.md", BUILD / "JUDGE.md"),
    ):
        assert rendered.read_text() == committed.read_text(), f"{committed.name} drifted"
    assert "rendered site/index.html" in printed

    # and the numbers really are the receipt's, not a coincidence of two stale files
    ausd = json.loads((render_site.PROOF / "ausd.json").read_text())["rows"][0]
    page = (site / "index.html").read_text()
    assert render_site.pct(ausd["sell_top_share"]) in page
    assert ausd["sell_top_maker"] in page
    assert "{{" not in page


def test_a_page_that_drifted_from_its_receipts_is_named_and_fails(tmp_path, monkeypatch, capsys):
    """`render_site.py --check` is CI's Stage 2 gate and `make check`'s second half.

    It has to fail on a page that is not what the receipts render — that is the only thing
    standing between a hand-edited headline and a judge — and it has to name the file, since
    "something drifted" across three generated surfaces is not an actionable message.
    """
    site = _sandbox(tmp_path, monkeypatch)
    render_site.main()
    monkeypatch.setattr(sys, "argv", ["render_site.py", "--check"])

    render_site.main()  # in sync: no exit, and it says so
    assert "in sync" in capsys.readouterr().out

    page = site / "index.html"
    page.write_text(page.read_text().replace("62.0%", "99.9%", 1))
    with pytest.raises(SystemExit) as ex:
        render_site.main()
    out = capsys.readouterr().out
    assert ex.value.code == 1
    assert "DRIFT: site/index.html is not what the receipts render" in out
    assert "pitch" not in out, "only the file that drifted is named"


def test_an_unfilled_slot_stops_the_render_rather_than_shipping_the_braces(tmp_path):
    """A template slot with no value in the context is the failure mode this generator was
    built to make impossible: `{{ausd.sell_top_share}}` rendered literally onto a landing
    page is the placeholder that survives into a submission. The render must stop and name
    every slot it could not fill, not ship the braces.
    """
    assert render_site.render("share: {{a.share}}", {"a.share": "62.0%"}) == "share: 62.0%"
    with pytest.raises(SystemExit) as ex:
        render_site.render("{{ausd.sell_top_share}} and {{missing}}", {"missing": "x"})
    assert "unfilled slots: ['ausd.sell_top_share']" in str(ex.value.code)


def test_the_card_is_measured_from_its_own_header_never_from_what_the_page_claims(
    tmp_path, monkeypatch
):
    """Every platform resamples the social card to 1200x630 and caches it by URL, so the
    page declares the dimensions and a hash of the bytes. Both are read out of the file
    itself: a card that is not exactly 1200x630, and a file that is not a PNG at all, stop
    the render rather than reaching a scraper as a broken preview.
    """
    real_card = render_site.OG_IMAGE
    monkeypatch.setattr(render_site, "BUILD", tmp_path)
    ihdr = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"

    wrong = tmp_path / "og-image.png"
    wrong.write_bytes(ihdr + struct.pack(">II", 800, 600) + b"\x08\x06\x00\x00\x00")
    monkeypatch.setattr(render_site, "OG_IMAGE", wrong)
    with pytest.raises(SystemExit) as ex:
        render_site.og_ctx()
    assert "og-image.png is 800x600; the card must be exactly 1200x630" in str(ex.value.code)

    not_a_png = tmp_path / "og-image.jpg"
    not_a_png.write_bytes(b"\xff\xd8\xff\xe0" + b"JFIF" * 5)
    with pytest.raises(SystemExit) as ex:
        render_site.png_size(not_a_png)
    assert str(ex.value.code) == "og-image.jpg is not a PNG"

    # the real card: the size the pages declare, and the hash they cache-bust with
    monkeypatch.setattr(render_site, "OG_IMAGE", real_card)
    ctx = render_site.og_ctx()
    assert (ctx["og.w"], ctx["og.h"]) == render_site.OG_SIZE
    assert f"og-image.png?v={ctx['og.v']}" in (REAL_SITE / "index.html").read_text()


def test_the_committed_site_is_what_the_committed_receipts_render(monkeypatch, capsys):
    """The gate itself, run the way `make check` and CI's Stage 2 job run it: through the
    __main__ guard, against this working tree. It passes only when the three generated
    surfaces in the commit under test are exactly what docs/proof/*.json produces.
    """
    monkeypatch.setattr(sys, "argv", ["render_site.py", "--check"])
    runpy.run_path(str(BUILD / "scripts" / "render_site.py"), run_name="__main__")
    assert "in sync: site/index.html, site/pitch/index.html, JUDGE.md" in capsys.readouterr().out
