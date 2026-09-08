#!/usr/bin/env python3
"""Cut the web fonts down to the glyphs these two pages actually render.

    python3 scripts/subset_fonts.py            # regenerate site/assets/fonts/
    python3 scripts/subset_fonts.py --check    # fail if the served fonts are stale

WHY THIS EXISTS. The fonts are self-hosted, preloaded and `font-display: swap`, which is the
right shape — but swap means every glyph on the page is painted twice when the font arrives
late: once in the fallback, once for real. On a throttled connection that second paint lands
well after the largest element, and Speed Index measures exactly that: how long the viewport
keeps changing. Measured 2026-09-08 on PageSpeed (Slow 4G, Moto G Power): FCP 0.94 s,
LCP 1.66 s, Speed Index 4.10 s — the only metric not scoring full marks, and the gap between
LCP and SI is the font swap.

The shipped fonts carried a full latin subset. These pages render 101 distinct characters.

Source of truth is assets/fonts-src/ — the full latin files, committed but never served. The
served files in site/assets/fonts/ are generated from them, so a future page that needs a
glyph gets it back by re-running this, rather than having been quietly cut out of a file
nobody kept a copy of.

`unicode-range` is rewritten to match what is really in each file: a declaration that claims
coverage the font does not have is a lie the browser then has to work around per character.
"""

import argparse
import re
import subprocess
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "fonts-src"
OUT = ROOT / "site" / "assets" / "fonts"
PAGES = (ROOT / "site" / "index.html", ROOT / "site" / "pitch" / "index.html")
TEMPLATES = (
    ROOT / "scripts" / "site_templates" / "landing.html",
    ROOT / "scripts" / "site_templates" / "deck.html",
)


def rendered_charset():
    """Every character the two pages put on screen — copy only, never code.

    Script and style bodies are stripped first: a CSS selector or a JS identifier is not
    something a reader ever sees, and keeping those glyphs would inflate the subset with
    characters that exist only in the source.
    """
    chars = set()
    for page in PAGES:
        t = page.read_text(encoding="utf-8")
        t = re.sub(r"<(script|style)\b.*?</\1>", " ", t, flags=re.S | re.I)
        t = re.sub(r"<[^>]+>", " ", t)
        chars |= set(unescape(t))
    return {c for c in chars if c.isprintable()}


def keep_set():
    """What the subset must contain: everything rendered, plus all printable ASCII.

    The ASCII headroom is deliberate. Copy changes more often than fonts get regenerated, and
    a new sentence that introduces a `;` should not be able to fall back to a system font for
    that one character.
    """
    return sorted(rendered_charset() | {chr(c) for c in range(0x20, 0x7F)})


def unicode_range(chars):
    """A compact, honest `unicode-range` — contiguous runs collapsed to U+A-B."""
    pts, out, start, prev = sorted(ord(c) for c in chars), [], None, None
    for cp in pts:
        if start is None:
            start = prev = cp
        elif cp == prev + 1:
            prev = cp
        else:
            out.append((start, prev))
            start = prev = cp
    if start is not None:
        out.append((start, prev))
    return ", ".join(f"U+{a:04X}" if a == b else f"U+{a:04X}-{b:04X}" for a, b in out)


def subset_one(src, dst, chars, check):
    codes = ",".join(f"U+{ord(c):04X}" for c in chars)
    tmp = dst.with_suffix(".tmp.woff2")
    subprocess.run(
        [
            "pyftsubset",
            str(src),
            f"--output-file={tmp}",
            "--flavor=woff2",
            f"--unicodes={codes}",
            "--layout-features=*",
            "--no-hinting",
            "--desubroutinize",
            "--drop-tables+=DSIG",
        ],
        check=True,
    )
    new = tmp.read_bytes()
    stale = (not dst.exists()) or dst.read_bytes() != new
    if check:
        tmp.unlink()
        return stale, src.stat().st_size, len(new)
    tmp.replace(dst)
    return stale, src.stat().st_size, len(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="verify, do not write")
    a = ap.parse_args()

    chars = keep_set()
    rng = unicode_range(chars)
    named = sum(1 for c in chars if not c.isascii())
    print(
        f"subsetting to {len(chars)} glyph(s) — {len(rendered_charset())} rendered, "
        f"ASCII headroom, {named} non-ASCII\n"
    )

    stale, before, after = False, 0, 0
    for src in sorted(SRC.glob("*.woff2")):
        s, b, n = subset_one(src, OUT / src.name, chars, a.check)
        stale |= s
        before += b
        after += n
        print(
            f"  {src.name:38}{b / 1024:7.1f} -> {n / 1024:5.1f} KiB"
            f"{'   STALE' if s and a.check else ''}"
        )
    print(
        f"  {'TOTAL':38}{before / 1024:7.1f} -> {after / 1024:5.1f} KiB "
        f"({(before - after) / 1024:.0f} KiB off the critical path)"
    )

    # Keep the declaration honest about what the file holds.
    for tpl in TEMPLATES:
        t = tpl.read_text(encoding="utf-8")
        new = re.sub(r"unicode-range:[^;}]*;", f"unicode-range:{rng};", t)
        if new != t:
            stale = True
            if not a.check:
                tpl.write_text(new, encoding="utf-8")
                print(f"  unicode-range rewritten in {tpl.name}")

    if a.check and stale:
        print("\nThe served fonts or the unicode-range are stale. Run: make fonts", file=sys.stderr)
        sys.exit(1)
    if not a.check:
        print("\nNow re-render so the pages pick up the new range:  make site")


if __name__ == "__main__":
    main()
