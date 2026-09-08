"""The font cutter: what it keeps, what it declares, and how it fails.

Subsetting is a lossy, silent operation. A glyph dropped by mistake does not raise — the
browser falls back to a system font for that one character and the page looks very slightly
wrong forever. So the interesting assertions here are about *refusing to lose things*: the
ASCII headroom, the honesty of the `unicode-range` it writes, and the --check mode that makes
a stale font a build failure rather than a rendering one.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import subset_fonts  # noqa: E402


def test_the_kept_set_is_never_smaller_than_printable_ascii():
    """The headroom is the whole reason this is safe to run unattended.

    Copy changes far more often than anyone thinks to re-cut a font. If the subset were
    exactly the characters currently on the page, the first sentence to introduce a semicolon
    would lose it. ASCII is the floor regardless of what the pages happen to say today.
    """
    keep = set(subset_fonts.keep_set())
    ascii_printable = {chr(c) for c in range(0x20, 0x7F)}
    assert ascii_printable <= keep
    assert subset_fonts.rendered_charset() - {c for c in keep} == set(), (
        "everything the pages render must survive the cut"
    )


def test_the_charset_is_taken_from_copy_and_never_from_code(tmp_path, monkeypatch):
    """A CSS selector is not something a reader sees. Counting `{`, `#` or a JS identifier
    would inflate the subset with glyphs that exist only in the source — and, worse, make the
    font depend on the implementation rather than on the words."""
    page = tmp_path / "index.html"
    page.write_text(
        "<style>.zzz{content:'QQQ'}</style><script>var jjj = 'WWW';</script><p>Hello</p>",
        encoding="utf-8",
    )
    monkeypatch.setattr(subset_fonts, "PAGES", (page,))
    got = subset_fonts.rendered_charset()
    assert set("Helo") <= got
    assert not (set("QWZJ") & got), "style and script bodies are not copy"


@pytest.mark.parametrize(
    "chars,expected",
    [
        ("abc", "U+0061-0063"),
        ("ac", "U+0061, U+0063"),
        ("a", "U+0061"),
        ("abcx", "U+0061-0063, U+0078"),
    ],
)
def test_the_declared_range_collapses_runs_and_matches_the_file(chars, expected):
    """`unicode-range` is a promise about what is inside the file. Declaring a range the font
    does not cover makes the browser select it and then fall back per character anyway —
    slower and less predictable than telling the truth."""
    assert subset_fonts.unicode_range(chars) == expected


def test_an_empty_set_declares_an_empty_range():
    assert subset_fonts.unicode_range("") == ""


def test_check_mode_writes_nothing_and_reports_the_committed_fonts_are_current():
    """The gate CI runs. It re-cuts into a temp file, compares the two cmaps, and deletes it —
    so a passing check means the served fonts really do carry what this script would put in
    them, not that somebody remembered to run it. The comparison is glyph coverage rather than
    bytes because brotli output differs between this mac and the ubuntu runner; see the module
    docstring of scripts/subset_fonts.py."""
    root = Path(__file__).resolve().parents[1]
    served = sorted((root / "site" / "assets" / "fonts").glob("*.woff2"))
    before = {p: p.read_bytes() for p in served}

    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "subset_fonts.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert {p: p.read_bytes() for p in served} == before, "--check must not write"
    assert not list((root / "site" / "assets" / "fonts").glob("*.tmp.woff2")), "no temp left"
    assert "off the critical path" in r.stdout, "it reports what it saved"


def test_check_mode_fails_when_the_pages_need_a_glyph_the_served_font_lacks(tmp_path, monkeypatch):
    """The failure that matters: someone edits copy, does not re-cut, and ships a page whose
    font is quietly missing a character. --check must exit non-zero and name the fix."""
    page = tmp_path / "index.html"
    # a glyph no latin subset carries, so the re-cut cannot match the committed bytes
    page.write_text("<p>coverage 中</p>", encoding="utf-8")
    monkeypatch.setattr(subset_fonts, "PAGES", (page,))
    monkeypatch.setattr(sys, "argv", ["subset_fonts.py", "--check"])

    with pytest.raises(SystemExit) as ex:
        subset_fonts.main()
    assert ex.value.code == 1


def test_running_it_for_real_is_idempotent(capsys, monkeypatch):
    """Twice in a row must be a no-op. If it were not, `make fonts` would churn the repo and
    every run would show up as a diff, which is how a gate stops being believed."""
    root = Path(__file__).resolve().parents[1]
    served = sorted((root / "site" / "assets" / "fonts").glob("*.woff2"))
    before = {p: p.read_bytes() for p in served}

    monkeypatch.setattr(sys, "argv", ["subset_fonts.py"])
    subset_fonts.main()
    out = capsys.readouterr().out

    assert {p: p.read_bytes() for p in served} == before, "a second run changed the fonts"
    assert "make site" in out, "it tells the reader the next step"


def test_a_font_the_repo_has_never_carried_is_written_out(tmp_path, monkeypatch, capsys):
    """The write half of the same decision. Everything above runs against fonts that are
    already current, which never reaches the line that installs a new cut — so point OUT at an
    empty directory, where every source font is missing and all three must be produced."""
    monkeypatch.setattr(subset_fonts, "OUT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["subset_fonts.py"])

    subset_fonts.main()

    cut = sorted(tmp_path.glob("*.woff2"))
    src = sorted(subset_fonts.SRC.glob("*.woff2"))
    assert [p.name for p in cut] == [p.name for p in src], "every source font was cut"
    assert not list(tmp_path.glob("*.tmp.woff2")), "no temp file survived"
    for f in cut:
        assert subset_fonts.codepoints(f) >= {ord(c) for c in "abcXYZ0189"}, f"{f.name} is real"
    assert "make site" in capsys.readouterr().out


def test_a_template_whose_declared_range_drifted_is_rewritten(tmp_path, monkeypatch, capsys):
    """The `unicode-range` and the bytes in the font are one fact stated twice. If a copy
    change grows the subset, a template still declaring the old range would claim coverage the
    file no longer matches — so the script owns both halves and rewrites the declaration."""
    tpl = tmp_path / "landing.html"
    tpl.write_text("@font-face{src:url(x.woff2);unicode-range:U+0041-005A;}", encoding="utf-8")
    monkeypatch.setattr(subset_fonts, "TEMPLATES", (tpl,))
    monkeypatch.setattr(sys, "argv", ["subset_fonts.py"])

    subset_fonts.main()

    after = tpl.read_text(encoding="utf-8")
    assert "U+0041-005A;" not in after, "the stale declaration is gone"
    assert "unicode-range:U+0020" in after, "and replaced by what is really in the file"
    assert "unicode-range rewritten in landing.html" in capsys.readouterr().out


def test_the_file_runs_through_its_main_guard_the_way_the_makefile_invokes_it(monkeypatch, capsys):
    """`make fonts` shells out to `python3 scripts/subset_fonts.py`. Calling main() from an
    import leaves the guard itself unexecuted — the one line that decides whether the
    documented command does anything at all."""
    import runpy

    monkeypatch.setattr(sys, "argv", ["subset_fonts.py", "--check"])
    # The committed fonts are current, so --check completes rather than exiting 1. A clean
    # run returns normally from the guard; the stale path is covered by its own test above.
    runpy.run_path(str(Path(subset_fonts.__file__)), run_name="__main__")
    assert "off the critical path" in capsys.readouterr().out
