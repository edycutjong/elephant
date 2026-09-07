#!/usr/bin/env python3
"""Measured QA for the two judge-facing web surfaces. Every gate is run, not asserted.

    pip install playwright pillow numpy && python3 -m playwright install chromium
    python3 scripts/qa_site.py [--out DIR]        # exit 1 on any failing gate

What it checks, per surface (site/index.html and site/pitch/index.html):

- placeholders: none of the tokens that quietly survive into a submission
- network: the only external request is Google Fonts; the page renders with every
  external request blocked
- layout: no horizontal overflow at 375 / 768 / 1440; every anchor and local link resolves;
  every image loads; no JS errors; the mobile height is under budget
- the fold at 1280x720: one h1, one to three CTAs, a visual, at most 40 words
- contrast: every text node >= 4.5:1 (>= 3:1 for large text), minimum reported and gated
- the deck: all slides reachable by ArrowRight, none overflow the 1920x1080 stage,
  ESC opens the overview, P shows the notes
- prefers-reduced-motion: zero running animations, every reveal visible, the split rows
  visible, the inline mark swapped to its static layer, the deck stage in its final state
- interaction: hover feedback on every interactive class, proven by screenshot byte-diff
- links: every link that leaves the site opens a new tab (target=_blank, rel noopener) and
  says so to a screen reader; same-site links stay in the tab
- the map: no token label crosses a dashed guide line, leaves the plot frame, or touches
  another token's label or dot — measured from the rendered boxes at every width
- the FAQ fold: a real 0fr → 1fr transition of 150–250 ms that only ever rises, the keyboard
  toggles it, and under prefers-reduced-motion it snaps with no transition at all
- animation: the staged split on both surfaces is sampled through its whole play with the
  animations paused at fixed times — it must hold the bar alone first, never reverse, never
  jump, and end in exactly the reduced-motion state. The one loop on the page (the inline
  mark) is swept across its full duration: exactly one collapse and one recovery per cycle,
  and zero velocity on both sides of the seam. The lesson behind those two gates is in the
  sibling asset work: a loop that pumps twice or snaps at the seam contradicts its own story.
"""

import io
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright

BUILD = Path(__file__).resolve().parents[1]
SITE = BUILD / "site"
SITE_HOST = "elephant.edycu.dev"
MOBILE_HEIGHT_BUDGET = 9000  # css px at 375 wide; the page measured 12,707 before condensing
CONTRAST_FLOOR = 5.6  # the minimum measured before this harness existed; do not regress it
FAIL = []
NOTES = {}


def ok(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  — {detail}" if detail != "" else ""))
    if not cond:
        FAIL.append(name)
    return cond


def lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


CONTRAST_JS = """
() => {
  function parse(c){ const m = c.match(/rgba?\\(([^)]+)\\)/); if(!m) return null;
    const p = m[1].split(',').map(x=>parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; }
  function bgOf(el){ let e = el; while (e) { const c = parse(getComputedStyle(e).backgroundColor);
    if (c && c.a > 0.85) return [c.r,c.g,c.b]; e = e.parentElement; } return [11,14,20]; }
  const out = []; const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT); let node;
  while ((node = walker.nextNode())) {
    const t = node.textContent.trim(); if (!t || t.length < 2) continue;
    const el = node.parentElement; if (!el) continue;
    if (el.closest('script,style,aside.speaker-notes,#notes,#overview,svg')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    const r = el.getBoundingClientRect(); if (r.width === 0 || r.height === 0) continue;
    const c = parse(cs.color); if (!c) continue;
    const size = parseFloat(cs.fontSize); const weight = parseInt(cs.fontWeight) || 400;
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    out.push({text: t.slice(0,40), fg:[c.r,c.g,c.b], bg: bgOf(el), large,
      tag: el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.split(' ')[0] : '')});
  }
  return out;
}
"""

# pause every animation on the page and scrub to t (ms); returns how many were found
SCRUB_JS = """
(t) => { const a = document.getAnimations(); a.forEach(x => { x.pause(); x.currentTime = t; }); return a.length; }
"""


def contrast_gate(page, name):
    items = page.evaluate(CONTRAST_JS)
    bad, mn = [], 99
    for it in items:
        c = contrast(it["fg"], it["bg"])
        mn = min(mn, c)
        if c < (3.0 if it["large"] else 4.5):
            bad.append((round(c, 2), it["tag"], it["text"]))
    ok(f"{name}: contrast ≥4.5 body / ≥3 large ({len(items)} text nodes)", not bad, bad[:6])
    ok(
        f"{name}: minimum contrast {mn:.2f} ≥ {CONTRAST_FLOOR} (no regression)",
        mn >= CONTRAST_FLOOR,
    )
    NOTES[f"{name}.min_contrast"] = round(mn, 2)


def monotone(seq, direction, tol=1e-6):
    """True if seq never moves against `direction` (+1 rising, -1 falling)."""
    return all((b - a) * direction >= -tol for a, b in zip(seq, seq[1:], strict=False))


def max_step(seq):
    return max((abs(b - a) for a, b in zip(seq, seq[1:], strict=False)), default=0)


def check_static(path, name):
    html = path.read_text()
    for pat in [
        r"TODO",
        r"\[\[FILL\]\]",
        r"lorem",
        r"youtu\.be/xxx",
        r"0x\.\.\.",
        r"\{\{",
        r"placehold\.co",
        r"\[Project Name\]",
        r"<url>",
        r"TBD",
    ]:
        ok(f"{name}: no placeholder {pat!r}", not re.findall(pat, html, flags=re.I))
    old_name = "elephant" + "-tracks"  # split so this file is not itself a hit for the old name
    ok(f"{name}: no stale repo name", old_name not in html)
    ext = set()
    for tag in re.findall(r"<(?:link|script|img)\b[^>]*>", html):
        if 'rel="canonical"' in tag or 'rel="preconnect"' in tag:
            continue
        m = re.search(r'(?:src|href)="(https?://[^"]+)"', tag)
        if m:
            ext.add(m.group(1))
    ok(
        f"{name}: only Google Fonts loaded externally",
        all(h.startswith("https://fonts.googleapis.com") for h in ext),
        sorted(ext),
    )
    honesty = [
        "No, and it says so on every number",
        "Your numbers will differ — the window moves with the market",
    ]
    if name == "landing":
        for h in honesty:
            ok(f"{name}: honesty disclosure intact: {h[:40]!r}", h in html)


LINKS_JS = """
() => [...document.querySelectorAll('a[href]')].map(a => ({
  href: a.getAttribute('href'), target: a.getAttribute('target'), rel: a.getAttribute('rel') || '',
  says: /opens in a new tab/i.test((a.getAttribute('aria-label') || '') + ' ' + a.textContent) }))
"""


def check_links(page, name):
    """Off-site links open a new tab and say so; same-site links keep the tab."""
    seen = set()
    for a in page.evaluate(LINKS_JS):
        href = a["href"]
        if href in seen:
            continue
        seen.add(href)
        external = href.startswith("http") and urlparse(href).netloc != SITE_HOST
        if external:
            ok(
                f"{name}: external {href} opens a new tab and says so",
                a["target"] == "_blank" and "noopener" in a["rel"] and a["says"],
                {k: a[k] for k in ("target", "rel", "says")},
            )
        else:
            ok(f"{name}: same-site {href} stays in the tab", a["target"] != "_blank")


MAP_JS = """
() => {
  const svg = document.querySelector('svg.quadrant'); if (!svg) return null;
  const R = e => { const b = e.getBoundingClientRect(); return {l:b.left, t:b.top, r:b.right, b:b.bottom}; };
  const U = es => es.map(R).reduce((a, b) => ({l:Math.min(a.l,b.l), t:Math.min(a.t,b.t), r:Math.max(a.r,b.r), b:Math.max(a.b,b.b)}));
  return { frame: R(svg.querySelector('rect')),
    mid: [...svg.querySelectorAll('line.mid')].map(R), grid: [...svg.querySelectorAll('line.grid')].map(R),
    pts: [...svg.querySelectorAll('.pt')].map(g => ({ token: g.dataset.token,
      dot: U([...g.children].filter(c => c.tagName !== 'text' && !c.classList.contains('halo'))),
      labels: [...g.querySelectorAll('text')].map(R) })) };
}
"""


def hits(a, b, pad=1.0):
    return (
        a["l"] < b["r"] + pad
        and a["r"] > b["l"] - pad
        and a["t"] < b["b"] + pad
        and a["b"] > b["t"] - pad
    )


def check_map_labels(page, name):
    """The quadrant map: every token label inside the frame, off the dashed guide lines, and
    clear of every other token's label and dot. Measured from the rendered boxes."""
    m = page.evaluate(MAP_JS)
    if not ok(f"{name}: quadrant map present with four labelled points", m and len(m["pts"]) == 4):
        return
    f = m["frame"]
    inside, on_mid, on_other, on_grid = [], [], [], 0
    for p in m["pts"]:
        for lb in p["labels"]:
            if not (
                lb["l"] >= f["l"] and lb["r"] <= f["r"] and lb["t"] >= f["t"] and lb["b"] <= f["b"]
            ):
                inside.append(p["token"])
            if any(hits(lb, ln) for ln in m["mid"]):
                on_mid.append(p["token"])
            on_grid += sum(1 for ln in m["grid"] if hits(lb, ln, 0))
            for q in m["pts"]:
                if q["token"] == p["token"]:
                    continue
                if hits(lb, q["dot"]) or any(hits(lb, ol) for ol in q["labels"]):
                    on_other.append((p["token"], q["token"]))
    ok(f"{name}: every map label inside the plot frame", not inside, inside)
    ok(f"{name}: no map label crosses a dashed guide line", not on_mid, on_mid)
    ok(f"{name}: no map label touches another token's label or dot", not on_other, on_other)
    NOTES[f"{name}.map_grid_crossings"] = on_grid  # the faint 25% grid: reported, not gated


FOLD_JS = """
(sel) => { const d = document.querySelector(sel); const f = d.querySelector('.fold');
  return { open: d.open, rows: parseFloat(getComputedStyle(f).gridTemplateRows), content: f.firstElementChild.scrollHeight,
    anims: document.getAnimations().filter(a => a.effect && a.effect.target === f).map(a => a.effect.getTiming().duration) }; }
"""


def check_fold(browser, path):
    """The FAQ fold: open first, then a 0fr → 1fr transition that only rises; the keyboard
    drives it; the answer is real text once open."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(path.as_uri(), wait_until="load")
    page.evaluate("document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'))")
    page.wait_for_timeout(300)
    sel = "#limits details:nth-of-type(1)"
    page.locator(sel + " > summary").click()
    st = page.evaluate(FOLD_JS, sel)
    ok(
        "landing: clicking a question opens it and starts one fold transition",
        st["open"] and len(st["anims"]) == 1,
        st,
    )
    dur = st["anims"][0] if st["anims"] else 0
    ok("landing: the fold takes 150–250 ms", 150 <= dur <= 250, dur)
    rows = []
    for t in range(0, int(dur) + 1, 25):
        page.evaluate(SCRUB_JS, t)
        rows.append(page.evaluate(FOLD_JS, sel)["rows"])
    ok(
        "landing: the fold only ever opens (no reversal) and ends at its content height",
        monotone(rows, +1) and rows[0] < 2 and abs(rows[-1] - st["content"]) < 2,
        [round(r) for r in rows],
    )
    ok(
        "landing: no snap — no fold sample moves more than 60% of the height",
        max_step(rows) < 0.6 * st["content"],
    )
    page.evaluate("document.getAnimations().forEach(a => a.finish())")
    page.wait_for_timeout(50)
    ok(
        "landing: the opened answer is selectable, findable text",
        page.evaluate(
            "(sel) => { const d = document.querySelector(sel); const b = d.querySelector('.body');"
            " return getComputedStyle(b).visibility === 'visible' && getComputedStyle(b).userSelect !== 'none'"
            " && document.body.innerText.includes('No, and it says so on every number'); }",
            sel,
        ),
    )
    page.locator(sel + " > summary").click()
    page.wait_for_timeout(50)
    st = page.evaluate(FOLD_JS, sel)
    ok(
        "landing: clicking again runs the fold back before the element closes",
        st["open"] and len(st["anims"]) == 1,
        st,
    )
    page.wait_for_timeout(500)
    ok(
        "landing: … and it is closed once the transition ends",
        not page.evaluate(FOLD_JS, sel)["open"],
    )
    sel2 = "#limits details:nth-of-type(2)"
    page.locator(sel2 + " > summary").focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(450)
    opened = page.evaluate(FOLD_JS, sel2)
    page.keyboard.press("Enter")
    page.wait_for_timeout(500)
    closed = page.evaluate(FOLD_JS, sel2)
    ok(
        "landing: Enter on a focused question opens and closes the fold",
        opened["open"] and abs(opened["rows"] - opened["content"]) < 2 and not closed["open"],
        (opened, closed),
    )
    ctx.close()
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(path.as_uri(), wait_until="load")
    page.wait_for_timeout(300)
    page.locator(sel + " > summary").click()
    st = page.evaluate(FOLD_JS, sel)
    ok(
        "landing: under reduced motion the fold snaps open — no transition, full height at once",
        st["open"] and not st["anims"] and abs(st["rows"] - st["content"]) < 2,
        st,
    )
    page.locator(sel + " > summary").click()
    st = page.evaluate(FOLD_JS, sel)
    ok("landing: under reduced motion it snaps closed", not st["open"] and not st["anims"], st)
    ctx.close()


def check_widths(browser, path, name, out, is_deck):
    for width, height in ((375, 740), (768, 1024), (1440, 900)):
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e, errs=errors: errs.append(str(e)))
        page.on(
            "console", lambda m, errs=errors: errs.append(m.text) if m.type == "error" else None
        )
        page.goto(path.as_uri(), wait_until="load")
        page.wait_for_timeout(600)
        sw = page.evaluate(
            "Math.max(document.documentElement.scrollWidth, document.body.scrollWidth)"
        )
        ok(f"{name}@{width}: no horizontal overflow", sw <= width, f"scrollWidth {sw}")
        ok(f"{name}@{width}: no JS errors", not errors, errors[:3])
        for im in page.evaluate(
            "[...document.images].map(i => ({src: i.getAttribute('src'), ok: i.complete && i.naturalWidth > 0}))"
        ):
            ok(f"{name}@{width}: img {im['src']}", im["ok"])
        hrefs = page.evaluate(
            "[...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))"
        )
        for h in sorted(set(hrefs)):
            if h == "#":
                ok(f"{name}: dead '#' link", False)
            elif h.startswith("#"):
                ok(
                    f"{name}: anchor {h} resolves",
                    page.evaluate(f"!!document.getElementById({json.dumps(h[1:])})"),
                )
            elif not h.startswith("http"):
                target = (path.parent / h.split("#")[0]).resolve()
                target = target / "index.html" if target.is_dir() else target
                ok(f"{name}: local link {h} exists", target.exists())
        if width == 1440:
            check_links(page, name)
        if not is_deck:
            check_map_labels(page, f"{name}@{width}")
            if width == 375:
                page.wait_for_timeout(2500)
                h = page.evaluate("document.body.scrollHeight")
                NOTES["landing.mobile_height"] = h
                ok(
                    f"{name}@375: page height {h}px ≤ {MOBILE_HEIGHT_BUDGET}px budget",
                    h <= MOBILE_HEIGHT_BUDGET,
                )
                rails = page.evaluate(
                    "[...document.querySelectorAll('.rail')].map(r => r.scrollWidth > r.clientWidth)"
                )
                ok(
                    f"{name}@375: every rail scrolls horizontally ({len(rails)} rails)",
                    rails and all(rails),
                )
                api = page.evaluate(
                    "(() => { const t = document.querySelector('table.api'); const rows = [...t.querySelectorAll('tr')];"
                    " return {fits: t.scrollWidth <= t.clientWidth + 1, rows: rows.map(r => Math.round(r.getBoundingClientRect().height)),"
                    " text: rows.map(r => r.innerText.trim().length)}; })()"
                )
                ok(
                    f"{name}@375: api table fits the width and every row carries its text",
                    api["fits"] and all(t > 20 for t in api["text"][1:]) and max(api["rows"]) < 220,
                    api,
                )
            page.screenshot(path=str(out / f"{name}-{width}.png"), full_page=True)
            if width == 1440:
                page.set_viewport_size({"width": 1280, "height": 720})
                page.wait_for_timeout(300)
                page.evaluate(
                    SCRUB_JS, 6000
                )  # measure the settled layout, not a mid-animation frame
                r = page.evaluate(
                    """() => {
                  const vis = [...document.body.querySelectorAll('*')].filter(e => { const b = e.getBoundingClientRect();
                    return b.top < 720 && b.bottom > 0 && b.width > 0 && e.children.length === 0 && !e.closest('script,style,[aria-hidden="true"]'); });
                  const words = vis.map(e => (e.textContent||'').trim()).join(' ').split(/\\s+/).filter(Boolean).length;
                  return { words, h1: document.querySelectorAll('h1').length,
                    ctas: [...document.querySelectorAll('a.btn,button')].filter(e => e.getBoundingClientRect().top < 720).length,
                    hasImg: !!document.querySelector('img,svg,canvas,video') }; }"""
                )
                ok(f"{name}: exactly one h1", r["h1"] == 1)
                ok(f"{name}: 1–3 CTAs above the fold", 1 <= r["ctas"] <= 3, r["ctas"])
                ok(f"{name}: visual above the fold", r["hasImg"])
                ok(f"{name}: ≤40 words above the fold", r["words"] <= 40, r["words"])
                page.set_viewport_size({"width": 1440, "height": 900})
                page.evaluate(
                    "document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'));"
                    "document.querySelectorAll('details').forEach(d => d.open = true)"
                )
                page.wait_for_timeout(900)
                contrast_gate(page, name)
        else:
            n = page.evaluate("document.querySelectorAll('.slide').length")
            reached = []
            for i in range(n):
                reached.append(
                    page.evaluate(
                        "[...document.querySelectorAll('.slide')].findIndex(s => s.classList.contains('active'))"
                    )
                )
                if width == 1440:
                    page.wait_for_timeout(1200 if i in (1, 4, 6) else 150)
                    page.screenshot(path=str(out / f"deck-{i + 1:02d}.png"))
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(120)
            ok(
                f"{name}@{width}: all {n} slides reachable by ArrowRight",
                reached == list(range(n)),
                reached,
            )
            over = page.evaluate(
                """() => {
              const st = document.getElementById('stage').getBoundingClientRect();
              const s = Math.min(innerWidth/1920, innerHeight/1080); const out = [];
              document.querySelectorAll('.slide').forEach((sl, i) => {
                document.querySelectorAll('.slide').forEach(x => x.classList.remove('active')); sl.classList.add('active');
                let maxB = 0, maxR = 0;
                sl.querySelectorAll('*').forEach(e => { const b = e.getBoundingClientRect(); if (b.width === 0) return;
                  maxB = Math.max(maxB, (b.bottom - st.top)/s); maxR = Math.max(maxR, (b.right - st.left)/s); });
                out.push({slide: i+1, bottom: Math.round(maxB), right: Math.round(maxR)}); });
              return out; }"""
            )
            bad = [o for o in over if o["bottom"] > 1020 or o["right"] > 1921]
            ok(
                f"{name}@{width}: no slide overflows the stage (bottom ≤1020, right ≤1920)",
                not bad,
                bad,
            )
            if width == 1440:
                page.evaluate(
                    "document.querySelectorAll('.slide').forEach((s, i) => s.classList.toggle('active', i === 6))"
                )
                page.wait_for_timeout(200)
                check_map_labels(page, f"{name}@{width}")
                page.keyboard.press("Home")
                page.keyboard.press("Escape")
                page.wait_for_timeout(100)
                ok(
                    f"{name}: ESC opens overview",
                    page.evaluate("document.body.classList.contains('overview')"),
                )
                page.keyboard.press("Escape")
                page.keyboard.press("p")
                page.wait_for_timeout(100)
                ok(
                    f"{name}: P shows notes",
                    page.evaluate(
                        "getComputedStyle(document.getElementById('notes')).display !== 'none'"
                    ),
                )
                page.keyboard.press("p")
                page.evaluate(
                    "document.querySelectorAll('.slide').forEach(s => s.classList.add('active'))"
                )
                page.wait_for_timeout(300)
                contrast_gate(page, name)
        ctx.close()


def check_reduced_motion(browser, path, name, out, is_deck):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(path.as_uri() + ("#5" if is_deck else ""), wait_until="load")
    page.wait_for_timeout(600)
    css_anim = page.evaluate(
        "[...document.querySelectorAll('*')].filter(e => { const cs = getComputedStyle(e);"
        " return cs.animationName !== 'none' && cs.animationDuration !== '0s'; }).length"
    )
    ok(f"{name}: no CSS animations under prefers-reduced-motion", css_anim == 0, css_anim)
    running = page.evaluate(
        "document.getAnimations().filter(a => a.playState === 'running').length"
    )
    ok(f"{name}: zero running animations under prefers-reduced-motion", running == 0, running)
    if not is_deck:
        rows = page.evaluate(
            "[...document.querySelectorAll('svg.split .row')].map(r => { const cs = getComputedStyle(r); return [cs.opacity, cs.transform]; })"
        )
        ok(
            f"{name}: split rows fully visible under reduced motion",
            all(o == "1" and t in ("none", "matrix(1, 0, 0, 1, 0, 0)") for o, t in rows),
            rows,
        )
        ok(
            f"{name}: reveal elements visible under reduced motion",
            page.evaluate(
                "[...document.querySelectorAll('.reveal')].every(e => getComputedStyle(e).opacity === '1')"
            ),
        )
        still = page.evaluate(
            "(() => { const s = document.querySelector('svg.icon-anim .still'); return s ? getComputedStyle(s).display : null; })()"
        )
        ok(
            f"{name}: inline animated mark swaps to its static layer under reduced motion",
            still == "inline",
            still,
        )
    else:
        st = stage_state(page)
        ok(f"{name}: stage at rest is the final frame under reduced motion", st == FINAL_STAGE, st)
    page.screenshot(path=str(out / f"{name}-reduced.png"))
    ctx.close()


def check_offline(browser, path, name, out):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    blocked = []

    def route(r):
        if r.request.url.startswith("http"):
            blocked.append(r.request.url)
            r.abort()
        else:
            r.continue_()

    page.route("**/*", route)
    page.goto(path.as_uri(), wait_until="load")
    page.wait_for_timeout(500)
    txt = page.evaluate("document.body.textContent.replace(/\\s+/g,' ').length")
    svgs = page.evaluate("document.querySelectorAll('svg').length")
    ok(
        f"{name}: renders with all external requests blocked ({len(blocked)} blocked)",
        txt > 500 and svgs > 0,
        f"{txt} chars, {svgs} svgs",
    )
    page.screenshot(path=str(out / f"{name}-offline.png"))
    ctx.close()


def check_hover(browser, path, name, sels, prep=""):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(path.as_uri(), wait_until="load")
    if prep:
        page.evaluate(prep)
    page.wait_for_timeout(900)
    for sel in sels:
        el = page.query_selector(sel)
        if not ok(f"{name}: hover target {sel} exists", bool(el)):
            continue
        el.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        page.mouse.move(0, 0)
        page.wait_for_timeout(400)
        before = el.screenshot()
        el.hover()
        page.wait_for_timeout(450)
        ok(f"{name}: hover feedback on {sel}", before != el.screenshot())
    ctx.close()


# ── animation gates ──────────────────────────────────────────────────────────

FINAL_STAGE = {
    "bar": 0.0,
    "ghost": 0.6,
    "half_ty": "final",
    "half_op": 0.0,
    "wipe": 0.0,
    "lab": 1.0,
}


def stage_state(page):
    """The deck stage's geometry as numbers: opacities, the halves' travel, the wipe's reveal."""
    st = page.evaluate(
        """() => {
      const g = s => document.querySelector('.stage ' + s);
      const op = s => parseFloat(getComputedStyle(g(s)).opacity);
      const half = g('.half-sell'); const m = getComputedStyle(half).transform;
      const ty = m === 'none' ? 0 : parseFloat(m.split(',')[5]);
      const target = parseFloat(half.style.getPropertyValue('--ty'));
      const clip = getComputedStyle(g('.wallets-buy')).clipPath;
      const mm = clip.match(/inset\\(([^)]+)\\)/); const parts = mm ? mm[1].split(' ') : ['0px','0%'];
      const wipe = parts.length > 1 ? parseFloat(parts[1]) : 0;
      return {bar: op('.bar'), ghost: +op('.ghost').toFixed(3), half_ty: Math.abs(ty - target) < 0.5 ? 'final' : +ty.toFixed(1),
              half_op: op('.half'), wipe: wipe, lab: op('.lab-buy')}; }"""
    )
    return st


def check_deck_stage_animation(browser, path):
    ctx = browser.new_context(viewport={"width": 1440, "height": 810})
    page = ctx.new_page()
    page.goto(path.as_uri() + "#5", wait_until="load")
    page.wait_for_timeout(300)
    n = page.evaluate(SCRUB_JS, 0)
    ok("deck: stage animations found to scrub", n >= 8, n)
    samples = []
    for t in range(0, 4001, 100):
        page.evaluate(SCRUB_JS, t)
        samples.append((t, stage_state(page)))
    tys = [174.0 if s["half_ty"] == "final" else float(s["half_ty"]) for _, s in samples]
    bars = [s["bar"] for _, s in samples]
    ghosts = [s["ghost"] for _, s in samples]
    wipes = [s["wipe"] for _, s in samples]
    labs = [s["lab"] for _, s in samples]
    halves = [s["half_op"] for _, s in samples]
    hold = [s for t, s in samples if t <= 700]
    ok(
        "deck: the sum sits alone for the first 0.7 s (bar solid, halves unmoved, nothing else on)",
        all(
            s["bar"] == 1 and s["half_ty"] == 0 and s["wipe"] == 100 and s["lab"] == 0 for s in hold
        ),
    )
    ok("deck: halves only ever travel down (no reversal)", monotone(tys, +1))
    ok(
        "deck: sum only ever fades, ghost only ever appears",
        monotone(bars, -1) and monotone(ghosts, +1),
    )
    ok("deck: wallets only ever reveal left→right", monotone(wipes, -1))
    ok(
        "deck: labels only ever appear; halves only ever fade",
        monotone(labs, +1) and monotone(halves, -1),
    )
    steps = {
        "ty": max_step(tys) / 174,
        "wipe": max_step(wipes) / 100,
        "bar": max_step(bars),
        "ghost": max_step(ghosts) / 0.6,
        "lab": max_step(labs),
        "half": max_step(halves),
    }
    ok(
        "deck: no snap — no series moves more than 60% of its range in one 100 ms sample",
        max(steps.values()) < 0.6,
        {k: round(v, 2) for k, v in steps.items()},
    )
    ok(
        "deck: the play ends in exactly the reduced-motion state",
        samples[-1][1] == FINAL_STAGE,
        samples[-1][1],
    )
    NOTES["deck.stage_samples"] = len(samples)
    ctx.close()


def check_landing_split_animation(browser, path):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(path.as_uri(), wait_until="load")
    page.wait_for_timeout(300)
    page.evaluate(
        "document.querySelectorAll('.reveal').forEach(e => e.classList.add('in')); document.querySelector('svg.split').classList.add('go')"
    )
    page.wait_for_timeout(50)
    n = page.evaluate(SCRUB_JS, 0)
    ok("landing: split animations found to scrub", n >= 2, n)
    read = """() => [...document.querySelectorAll('svg.split .row')].map(r => { const cs = getComputedStyle(r);
       const m = cs.transform; const sy = m === 'none' ? 1 : parseFloat(m.split(',')[3]); return [parseFloat(cs.opacity), sy]; })"""
    samples = []
    for t in range(0, 3001, 100):
        page.evaluate(SCRUB_JS, t)
        samples.append((t, page.evaluate(read)))
    sell_op = [s[0][0] for _, s in samples]
    buy_op = [s[1][0] for _, s in samples]
    sell_sy = [s[0][1] for _, s in samples]
    ok(
        "landing: the sum sits alone for the first 1.1 s (both rows at zero)",
        all(s[0][0] == 0 and s[1][0] == 0 for t, s in samples if t <= 1100),
    )
    ok(
        "landing: the sell side grows out of the bar before the buy side",
        next(t for t, s in samples if s[0][0] > 0) < next(t for t, s in samples if s[1][0] > 0),
    )
    ok(
        "landing: rows only ever rise (no reversal)",
        monotone(sell_op, +1) and monotone(buy_op, +1) and monotone(sell_sy, +1),
    )
    ok(
        "landing: no jump — largest per-100ms step under 45%",
        max_step(sell_op) < 0.45 and max_step(sell_sy) < 0.45,
    )
    ok(
        "landing: the play ends in exactly the reduced-motion state (opacity 1, scale 1)",
        samples[-1][1] == [[1, 1], [1, 1]],
        samples[-1][1],
    )
    ctx.close()


def amber_mass(png_bytes):
    a = np.asarray(Image.open(io.BytesIO(png_bytes)).convert("RGB"), dtype=np.int32)
    warm = np.clip(
        a[..., 0] - a[..., 2], 0, 255
    )  # amber is red-over-blue; the plate and the bar are not
    return float(warm.mean() / 255)


def check_loop(browser, out):
    """The only loop on either page is the inline mark. Sweep its whole cycle."""
    svg_path = SITE / "assets" / "icon-animated.svg"
    svg = svg_path.read_text()
    html = (SITE / "index.html").read_text()
    start = html.index("<svg", html.index('class="icon-anim"') - 200)
    inline = html[start : html.index("</svg>", start) + 6]
    body = svg[svg.index("<svg") :].strip()
    ok(
        "landing: the inline mark is the committed icon-animated.svg",
        inline.replace(' class="icon-anim"', "")
        == re.sub(r'\swidth="512"\sheight="512"', "", body, count=1),
    )
    dur = float(re.search(r'dur="([\d.]+)s"', svg).group(1))
    ctx = browser.new_context(viewport={"width": 320, "height": 320})
    page = ctx.new_page()
    small = svg.replace('width="512" height="512"', 'width="256" height="256"')
    page.set_content(f'<body style="margin:0;background:#0B0E14">{small}</body>')
    page.wait_for_timeout(200)
    el = page.query_selector("svg")
    masses = []
    ts = [round(i * 0.1, 1) for i in range(int(dur * 10) + 1)]
    for t in ts:
        page.evaluate(
            "t => { const s = document.querySelector('svg'); s.pauseAnimations(); s.setCurrentTime(t); }",
            t,
        )
        masses.append(amber_mass(el.screenshot()))
    peak = max(masses)
    mid = peak / 2
    below = [m < mid for m in masses]
    collapses = sum(1 for a, b in zip(below, below[1:], strict=False) if not a and b)
    recoveries = sum(1 for a, b in zip(below, below[1:], strict=False) if a and not b)
    ok(
        f"loop: exactly one collapse and one recovery per {dur:.0f}s cycle (amber mass)",
        collapses == 1 and recoveries == 1,
        f"{collapses} / {recoveries}",
    )
    d_before = abs(masses[-1] - masses[-2])
    d_after = abs(masses[1] - masses[0])
    ok(
        "loop: zero velocity on both sides of the seam",
        d_before < 1e-3 and d_after < 1e-3,
        f"{d_before:.4f} / {d_after:.4f}",
    )
    ok(
        "loop: frame at dur equals frame 0 (the seam closes)",
        abs(masses[-1] - masses[0]) < 1e-3,
        f"{masses[-1]:.4f} vs {masses[0]:.4f}",
    )
    ok(
        "loop: the split state holds for ≥40% of the cycle",
        sum(1 for m in masses if m >= 0.9 * peak) / len(masses) >= 0.4,
    )
    NOTES["loop.amber_mass"] = [round(m, 4) for m in masses]
    ctx.close()


def main():
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else BUILD / ".qa"
    out.mkdir(parents=True, exist_ok=True)
    landing, deck = SITE / "index.html", SITE / "pitch" / "index.html"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for path, name, is_deck in ((landing, "landing", False), (deck, "deck", True)):
            print(f"\n=== {name} ===")
            check_static(path, name)
            check_widths(browser, path, name, out, is_deck)
            check_reduced_motion(browser, path, name, out, is_deck)
            check_offline(browser, path, name, out)
        print("\n=== interaction ===")
        check_hover(
            browser,
            landing,
            "landing",
            [
                ".btn-primary",
                "a.btn:not(.btn-primary)",
                ".nav-links a",
                ".card",
                "details summary",
                ".copy",
                ".proof a",
                "svg.quadrant .pt",
                "footer .link-quiet",
                ".gh",
            ],
            prep="document.querySelectorAll('.reveal').forEach(e => e.classList.add('in'))",
        )
        check_hover(
            browser,
            deck,
            "deck",
            [".ask .links a"],
            prep="location.hash='#11'; document.querySelectorAll('.slide').forEach((s,i)=>s.classList.toggle('active', i===10))",
        )
        print("\n=== animation ===")
        check_fold(browser, landing)
        check_landing_split_animation(browser, landing)
        check_deck_stage_animation(browser, deck)
        check_loop(browser, out)
        browser.close()
    (out / "notes.json").write_text(json.dumps(NOTES, indent=2))
    total = len(FAIL)
    print(
        f"\n{'ALL GATES PASS' if not total else str(total) + ' FAILING: ' + '; '.join(FAIL[:20])}"
    )
    print("notes:", {k: v for k, v in NOTES.items() if not isinstance(v, list)})
    sys.exit(1 if total else 0)


if __name__ == "__main__":
    main()
