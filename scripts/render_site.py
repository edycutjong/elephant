#!/usr/bin/env python3
"""Render site/index.html, site/pitch/index.html and JUDGE.md from the committed receipts.

    python3 scripts/render_site.py            # write site/ and JUDGE.md (churn token: gme)
    python3 scripts/render_site.py --check    # exit 1 if what is on disk is not this render

Every number on either surface comes from docs/proof/*.json, which are real keyless runs of
scripts/split_tape.py. The templates in scripts/site_templates/ use {{token}} slots and the
render fails if any slot is left unfilled, so a placeholder can never reach the committed HTML
and a number can never be typed in by hand. The HTML under site/ is generated output: edit the
template or the receipt, never the page.
"""

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

BUILD = Path(__file__).resolve().parents[1]
TEMPLATES = BUILD / "scripts" / "site_templates"
PROOF = BUILD / "docs" / "proof"
SITE = BUILD / "site"

REPO = "https://github.com/edycutjong/elephant"
SITE_URL = "https://elephant.edycu.dev"
EVENT = "https://dorahacks.io/hackathon/coinmarketcap-api-202609/detail"
VERSION = "v0.0.0-dev"
SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'
MONO = "JetBrains Mono, monospace"
# no platform tag exists yet for these — an honest fallback, never faked
# the GitHub mark, once: the nav glyph, the repository CTA and the deck all draw this path
GH_PATH = (
    "M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49"
    "-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 "
    "1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59"
    ".82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 "
    "1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 "
    "3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0"
    "-4.42-3.58-8-8-8z"
)
# every link that leaves the site opens a new tab, says so to a screen reader, and carries the
# ↗ glyph so the convention is visible; same-site navigation keeps → and stays in the tab
BLANK = 'target="_blank" rel="noopener noreferrer"'
EXT = (
    '<span class="arrow arrow-ext" aria-hidden="true">↗</span>'
    '<span class="sr-only"> (opens in a new tab)</span>'
)
PLATFORM_FALLBACK = {
    "AUSD": "ethereum",
    "SHFL": "ethereum",
    "BINGO": "solana",
    "GME": "solana",
    "cbETH": "base",
}


def load(sym):
    return json.loads((PROOF / f"{sym.lower()}.json").read_text())


def money(x, dp=0):
    return f"${x:,.{dp}f}"


def pct(x, dp=1):
    return f"{x * 100:.{dp}f}%"


def signed_pct(x, dp=1):
    s = f"{x:+.{dp}f}%"
    return s.replace("-", "−")  # true minus


def short_addr(a):
    return a[:6] + "…" + a[-4:]


def utc_short(ts):
    return ts.replace("T", " ").replace("Z", " UTC")


def row_of(d):
    return d["rows"][0]


def fmt_ts_ms(ms, seconds=True):
    fmt = "%m-%d %H:%M:%S" if seconds else "%m-%d %H:%M"
    return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).strftime(fmt)


# ── SVG builders ─────────────────────────────────────────────────────────────


AMBER, BLUE, GREY, RED, INK = "#FFB020", "#4C9AFF", "#5E6C80", "#FF5C5C", "#0B0E14"
REST_OPACITY = "0.42"  # every wallet on a side except the one the label names


def segments(shares, x0, y, width, row_h, hue):
    """One rect per wallet, widest first. The first wallet is solid; the rest are the same
    hue at REST_OPACITY, so a side owns exactly one colour and blue can never mean 'buy'
    inside the sell row."""
    out = []
    x = x0
    for i, s in enumerate(shares):
        w = s * width
        if w < 0.6:
            # sub-pixel wallets still exist: draw them as a hairline so the count is honest
            w = 0.6
        gap = 1.5 if w > 3 else 0
        rest = "" if i == 0 else f' fill-opacity="{REST_OPACITY}"'
        out.append(
            f'<rect class="seg{"" if i == 0 else " rest"}" x="{x:.2f}" y="{y}" '
            f'width="{max(w - gap, 0.5):.2f}" height="{row_h}" rx="{3 if w > 8 else 0}" '
            f'fill="{hue}"{rest}/>'
        )
        x += w
    return "\n".join(out)


def split_aria(r):
    nf = signed_pct(r["net_flow_pct"])
    return (
        f"{r['symbol']}: net flow reads {nf}. Split by maker, one wallet is "
        f"{pct(r['sell_top_share'])} of the sell side while the buy side is {r['buy_wallets']} "
        f"wallets, the largest {pct(r['buy_top_share'])}."
    )


def split_svg(r, width=1200):
    """The landing hero: one flat grey bar (the sum) and, under it, both sides attributed to
    the wallets that made them. Each row is the full width: a share of its own side."""
    W = width
    bar_h, row_h = 26, 44
    y_sum, y_sell, y_buy, H = 34, 170, 290, 360
    nf = signed_pct(r["net_flow_pct"])
    sell_label = f"sell · {r['sells']} swaps · {r['sell_wallets']} wallets"
    buy_label = f"buy · {r['buys']} swaps · {r['buy_wallets']} wallets"
    top_label_sell = (
        f"one wallet · {pct(r['sell_top_share'])} · {money(r['sell_top_vol'])} "
        f"in {r['sell_top_swaps']} swaps"
    )
    top_label_buy = f"largest wallet · {pct(r['buy_top_share'])}"
    pill_w, pill_h = 232, bar_h + 8
    return f"""<svg class="split" viewBox="0 0 {W} {H}" role="img" aria-label="{split_aria(r)}" \
{SVG_NS}>
  <g class="sum">
    <text x="0" y="{y_sum - 14}" class="lbl">what every dashboard prints</text>
    <rect x="0" y="{y_sum}" width="{W}" height="{bar_h}" rx="13" fill="{GREY}"/>
    <g transform="translate({W - pill_w},{y_sum - 4})">
      <rect width="{pill_w}" height="{pill_h}" rx="{pill_h / 2}" fill="{INK}" \
stroke="{RED}" stroke-width="1.5"/>
      <text x="{pill_w // 2}" y="{pill_h / 2 + 5}" class="flag" text-anchor="middle">\
net flow {nf}</text>
    </g>
  </g>
  <g class="row row-sell">
    <text x="0" y="{y_sell - 12}" class="lbl">{sell_label}</text>
    {segments(r["sell_maker_shares"], 0, y_sell, W, row_h, AMBER)}
    <text x="14" y="{y_sell + row_h / 2 + 5}" class="inbar">{top_label_sell}</text>
  </g>
  <g class="row row-buy">
    <text x="0" y="{y_buy - 12}" class="lbl">{buy_label}</text>
    {segments(r["buy_maker_shares"], 0, y_buy, W, row_h, BLUE)}
    <text x="0" y="{y_buy + row_h + 22}" class="lbl">{top_label_buy}</text>
  </g>
</svg>"""


def split_stage_svg(r):
    """The deck's peak, on a 1680x640 stage: the sum bar is drawn to volume, forks into its
    sell and buy halves — nearly equal, which is what "balanced" looks like — and each half
    then resolves into the wallets that made it. Geometry only ever moves bar -> split; the
    static state (reduced motion, print) is the final frame."""
    W, H = 1680, 640
    bar_x, bar_w, bar_y, bar_h = 320, 1040, 56, 36
    row_y, row_h, row_gap = 230, 110, 120
    sell_v, buy_v = r["sell_vol"], r["buy_vol"]
    sell_frac = sell_v / (sell_v + buy_v)
    half_sell_w = bar_w * sell_frac
    half_buy_w = bar_w - half_sell_w
    scale_x = (W - row_gap) / bar_w
    scale_y = row_h / bar_h
    sell_w = half_sell_w * scale_x
    buy_x = W - half_buy_w * scale_x
    nf = signed_pct(r["net_flow_pct"])
    pill_w, pill_h = 300, bar_h + 8

    def half(cls, x, w, tx):
        return (
            f'<rect class="half {cls}" x="{x:.2f}" y="{bar_y}" width="{w:.2f}" height="{bar_h}" '
            f'fill="{GREY}" style="--tx:{tx:.2f}px;--ty:{row_y - bar_y}px;'
            f'--sx:{scale_x:.4f};--sy:{scale_y:.4f}"/>'
        )

    aria = split_aria(r)
    return f"""<svg class="stage-svg" viewBox="0 0 {W} {H}" role="img" aria-label="{aria}" {SVG_NS}>
  <text x="{bar_x}" y="{bar_y - 14}" class="lbl">what every dashboard prints</text>
  <rect class="ghost" x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="18" \
fill="none" stroke="{GREY}" stroke-width="1.5" stroke-dasharray="6 5"/>
  <rect class="bar" x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="18" fill="{GREY}"/>
  {half("half-sell", bar_x, half_sell_w, -bar_x)}
  {half("half-buy", bar_x + half_sell_w, half_buy_w, buy_x - (bar_x + half_sell_w))}
  <g class="wallets wallets-sell">
    {segments(r["sell_maker_shares"], 0, row_y, sell_w, row_h, AMBER)}
  </g>
  <g class="wallets wallets-buy">
    {segments(r["buy_maker_shares"], buy_x, row_y, W - buy_x, row_h, BLUE)}
  </g>
  <g class="pill" transform="translate({bar_x + bar_w - pill_w},{bar_y - 4})">
    <rect width="{pill_w}" height="{pill_h}" rx="{pill_h / 2}" fill="{INK}" stroke="{RED}" \
stroke-width="1.5"/>
    <text x="{pill_w // 2}" y="{pill_h / 2 + 7}" class="flag" text-anchor="middle">\
net flow {nf}</text>
  </g>
</svg>"""


def quadrant_svg(points):
    """Top-maker share of the sell side (x) vs the buy side (y). Four live tokens."""
    W, H = 720, 560
    L, R, T, B = 74, 700, 26, 486
    pw, ph = R - L, B - T

    def X(v):
        return L + v * pw

    def Y(v):
        return B - v * ph

    grid = ""
    for t in (0.25, 0.5, 0.75, 1.0):
        grid += f'<line x1="{X(t):.1f}" y1="{T}" x2="{X(t):.1f}" y2="{B}" class="grid"/>'
        grid += f'<line x1="{L}" y1="{Y(t):.1f}" x2="{R}" y2="{Y(t):.1f}" class="grid"/>'
        grid += (
            f'<text x="{X(t):.1f}" y="{B + 22}" class="tick" text-anchor="middle">'
            f"{int(t * 100)}%</text>"
        )
        grid += (
            f'<text x="{L - 10}" y="{Y(t) + 4:.1f}" class="tick" text-anchor="end">'
            f"{int(t * 100)}%</text>"
        )
    grid += f'<text x="{L - 10}" y="{B + 4}" class="tick" text-anchor="end">0</text>'

    def quad(x, y1, y2, title, sub):
        return (
            f'\n  <text x="{x:.1f}" y="{y1}" class="quad" text-anchor="middle">{title}</text>'
            f'\n  <text x="{x:.1f}" y="{y2}" class="quad sub" text-anchor="middle">{sub}</text>'
        )

    lo1, lo2 = f"{Y(0.5) + 26:.1f}", f"{Y(0.5) + 44:.1f}"
    hi1, hi2 = f"{T + 24}", f"{T + 42}"
    quads = (
        f'\n  <line x1="{X(0.5):.1f}" y1="{T}" x2="{X(0.5):.1f}" y2="{B}" class="mid"/>'
        f'\n  <line x1="{L}" y1="{Y(0.5):.1f}" x2="{R}" y2="{Y(0.5):.1f}" class="mid"/>'
        + quad(X(0.75), lo1, lo2, "distribution to retail", "one seller, many buyers")
        + quad(X(0.25), hi1, hi2, "accumulation from a crowd", "one buyer, many sellers")
        + quad(X(0.75), hi1, hi2, "wash-shaped symmetry", "one wallet on both sides")
        + quad(X(0.25), lo1, lo2, "churn", "crowds on both sides")
        + "\n"
    )
    dots = ""
    for p in points:
        x, y = X(p["sx"]), Y(p["by"])
        kind = p["kind"]
        if kind == "sell":
            fill = '<circle r="13" fill="#FFB020"/>'
        elif kind == "buy":
            fill = '<circle r="13" fill="#4C9AFF"/>'
        elif kind == "both":
            fill = (
                '<path d="M0 -13 A13 13 0 0 0 0 13 Z" fill="#FFB020"/>'
                '<path d="M0 -13 A13 13 0 0 1 0 13 Z" fill="#4C9AFF"/>'
            )
        else:
            fill = '<circle r="13" fill="#0B0E14" stroke="#8B98A9" stroke-width="3"/>'
        lx = p.get("lx", 20)
        ly = p.get("ly", 5)
        anchor = p.get("anchor", "start")
        aria = (
            f"{p['symbol']}: top seller {pct(p['sx'])}, top buyer {pct(p['by'])}, "
            f"net flow {signed_pct(p['net'])}"
        )
        dots += f"""
  <g class="pt" data-token="{p["symbol"]}" transform="translate({x:.1f},{y:.1f})" \
tabindex="0" role="button" aria-label="{aria}">
    <circle r="22" class="halo"/>
    {fill}
    <text x="{lx}" y="{ly}" class="ptlbl" text-anchor="{anchor}">{p["symbol"]}</text>
    <text x="{lx}" y="{ly + 16}" class="ptsub" text-anchor="{anchor}">net \
{signed_pct(p["net"])}</text>
  </g>"""

    aria = (
        "Quadrant map: top-maker share of the sell side against top-maker share of the buy "
        "side, for four tokens whose net flow reads within five percent of balanced."
    )
    return f"""<svg class="quadrant" viewBox="0 0 {W} {H}" role="img" aria-label="{aria}" {SVG_NS}>
  <rect x="{L}" y="{T}" width="{pw}" height="{ph}" fill="#141A24" stroke="#243044"/>
  {grid}{quads}{dots}
  <text x="{(L + R) / 2:.1f}" y="{H - 16}" class="axis" text-anchor="middle">\
top maker's share of the SELL side →</text>
  <text transform="translate(18,{(T + B) / 2:.1f}) rotate(-90)" class="axis" \
text-anchor="middle">top maker's share of the BUY side →</text>
</svg>"""


def struct_svg(kind):
    """Structure A (one desk vs a crowd) or B (crowd vs crowd) — shared by both surfaces."""

    def grid(x0, hue):
        out = []
        for row in range(6):
            for col in range(18):
                out.append(
                    f'<rect x="{x0 + col * 14}" y="{16 + row * 14}" width="10" height="10" rx="2"/>'
                )
        return f'<g fill="{hue}" fill-opacity="{REST_OPACITY}">' + "".join(out) + "</g>"

    def caption(x, text):
        return (
            f'<text x="{x}" y="114" text-anchor="middle" font-family="{MONO}" font-size="12" '
            f'fill="#8B98A9">{text}</text>'
        )

    if kind == "A":
        # the block spans the same rows as the dot grid (y 16..96), so the one mass and the
        # thousand small ones sit level and the label reads below it like the other three
        left = '<rect x="0" y="16" width="250" height="80" rx="8" fill="#FFB020"/>'
        label = "One large seller block against many small buyer blocks"
        left_cap = caption(125, "sell · 1 wallet · $1,000,000")
    else:
        left = grid(0, AMBER)
        label = "Many small seller blocks against many small buyer blocks"
        left_cap = caption(125, "sell · 1,000 wallets · $1,000 each")
    return (
        f'<svg viewBox="0 0 520 120" role="img" aria-label="{label}" {SVG_NS}>'
        f"{left}{grid(268, BLUE)}{left_cap}"
        f"{caption(392, 'buy · 1,000 wallets · $1,000 each')}</svg>"
    )


def gh_icon(cls=""):
    c = f' class="{cls}"' if cls else ""
    return (
        f'<svg{c} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true" focusable="false">'
        f'<path d="{GH_PATH}"/></svg>'
    )


def icon_inline(cls="icon-anim"):
    svg = (SITE / "assets" / "icon-animated.svg").read_text()
    return re.sub(r'\swidth="512"\sheight="512"', f' class="{cls}"', svg, count=1)


def escape(txt):
    return txt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mark_keys(txt, keys, cls=False):
    for key in keys:
        open_tag = f'<mark class="k-{key}">' if cls else "<mark>"
        txt = re.sub(
            rf'^(\s*)"{key}": (.+?)(,?)$',
            rf'\1{open_tag}"{key}": \2</mark>\3',
            txt,
            flags=re.M,
        )
    return re.sub(r'^(\s*)("[a-z_0-9]+"):', r'\1<span class="key">\2</span>:', txt, flags=re.M)


def json_panel(row, keep_top10="sell"):
    """The hero row, verbatim, with the two long share arrays elided and three keys marked."""
    r = dict(row)
    n_b, n_s = len(r["buy_maker_shares"]), len(r["sell_maker_shares"])
    r["buy_maker_shares"] = "__ELIDE_B__"
    r["sell_maker_shares"] = "__ELIDE_S__"
    other = "buy" if keep_top10 == "sell" else "sell"
    r[f"{other}_top10"] = r[f"{other}_top10"][:2] + ["__ELIDE_T__"]
    txt = json.dumps(r, indent=2, sort_keys=True)
    txt = txt.replace('"__ELIDE_B__"', f"[ /* {n_b} shares, largest first — see the receipt */ ]")
    txt = txt.replace('"__ELIDE_S__"', f"[ /* {n_s} shares, largest first — see the receipt */ ]")
    txt = txt.replace('"__ELIDE_T__"', "/* … 8 more in the receipt */")
    side = keep_top10
    keys = (f"{side}_top_vol", f"{side}_vol", f"{side}_top_share")
    return mark_keys(escape(txt), keys, cls=True)


def json_panel_short(row):
    keys = [
        "symbol",
        "platform",
        "swaps",
        "net_flow_pct",
        "sells",
        "sell_wallets",
        "sell_vol",
        "sell_top_maker",
        "sell_top_swaps",
        "sell_top_vol",
        "sell_top_share",
        "buys",
        "buy_wallets",
        "buy_top_share",
        "confidence",
    ]
    r = {k: row.get(k, PLATFORM_FALLBACK.get(row["symbol"])) for k in keys}
    txt = json.dumps(r, indent=2)
    return mark_keys(escape(txt), ("sell_top_vol", "sell_vol", "sell_top_share"))


def sorted_swaps(ev):
    return sorted(ev["swaps"], key=lambda s: int(s.get("ts", 0)))


def evidence_table(ev):
    rows = []
    running = 0.0
    for i, s in enumerate(sorted_swaps(ev), 1):
        v = float(s["v"])
        running += v
        rows.append(
            f'<tr><td class="n">{i}</td><td class="mono">{fmt_ts_ms(s["ts"], seconds=False)}</td>'
            f'<td class="mono addr" title="{s["tx"]}">{short_addr(s["tx"])}</td>'
            f'<td class="mono">{s["en"].replace(" (Ethereum)", "")}</td>'
            f'<td class="mono num">{money(v, 2)}</td>'
            f'<td class="mono num run">{money(running, 2)}</td></tr>'
        )
    return "\n".join(rows), running


def evidence_table_short(ev):
    rows = []
    running = 0.0
    for i, s in enumerate(sorted_swaps(ev), 1):
        running += float(s["v"])
        rows.append(
            f'<tr><td class="n">{i}</td><td class="mono">{fmt_ts_ms(s["ts"])}</td>'
            f'<td class="mono" title="{s["tx"]}">{short_addr(s["tx"])}</td>'
            f'<td class="mono">{s["en"].replace(" (Ethereum)", "")}</td>'
            f'<td class="mono num">{money(float(s["v"]), 2)}</td>'
            f'<td class="mono num" style="color:var(--elephant)">{money(running, 2)}</td></tr>'
        )
    return "".join(rows)


def top10_rows(makers):
    return "".join(
        f'<tr><td class="n">{i}</td><td class="mono addr">{short_addr(m["maker"])}</td>'
        f'<td class="mono num">{money(m["vol"])}</td><td class="mono num">{m["swaps"]}</td>'
        f'<td class="mono num">{pct(m["share"])}</td></tr>'
        for i, m in enumerate(makers, 1)
    )


def render(template, ctx):
    out = template
    for k, v in ctx.items():
        out = out.replace("{{" + k + "}}", str(v))
    left = sorted(set(re.findall(r"\{\{([a-zA-Z0-9_.]+)\}\}", out)))
    if left:
        sys.exit(f"unfilled slots: {left}")
    return out


def token_ctx(p, d, r):
    """Every slot for one token, prefixed `p.` — the only way a number reaches a page."""
    top_vol = r["sell_top_vol"]
    return {
        f"{p}.symbol": r["symbol"],
        f"{p}.platform": r.get("platform") or PLATFORM_FALLBACK[r["symbol"]],
        f"{p}.platform_title": (r.get("platform") or PLATFORM_FALLBACK[r["symbol"]]).title(),
        f"{p}.address": r["address"],
        f"{p}.addr_short": short_addr(r["address"]),
        f"{p}.swaps": r["swaps"],
        f"{p}.sells": r["sells"],
        f"{p}.buys": r["buys"],
        f"{p}.sell_wallets": r["sell_wallets"],
        f"{p}.buy_wallets": r["buy_wallets"],
        f"{p}.sell_top_share": pct(r["sell_top_share"]),
        f"{p}.sell_top_share_int": f"{r['sell_top_share'] * 100:.0f}",
        f"{p}.sell_top_share_raw": f"{r['sell_top_share']:.6f}",
        f"{p}.buy_top_share": pct(r["buy_top_share"]),
        f"{p}.buy_top_share_int": f"{r['buy_top_share'] * 100:.0f}",
        f"{p}.sell_top_vol": money(top_vol),
        f"{p}.sell_top_vol_2": money(top_vol, 2),
        f"{p}.sell_top_vol_m": f"${top_vol / 1e6:.1f}M" if top_vol >= 1e6 else money(top_vol),
        f"{p}.buy_top_vol": money(r["buy_top_vol"]),
        f"{p}.sell_vol": money(r["sell_vol"]),
        f"{p}.sell_vol_2": money(r["sell_vol"], 2),
        f"{p}.buy_vol": money(r["buy_vol"]),
        f"{p}.sell_top_swaps": r["sell_top_swaps"],
        f"{p}.buy_top_swaps": r["buy_top_swaps"],
        f"{p}.sell_top_maker": r["sell_top_maker"],
        f"{p}.buy_top_maker": r["buy_top_maker"],
        f"{p}.sell_top_maker_short": short_addr(r["sell_top_maker"]),
        f"{p}.buy_top_maker_short": short_addr(r["buy_top_maker"]),
        f"{p}.net": signed_pct(r["net_flow_pct"]),
        f"{p}.avg_buy": money(r["avg_buy"]),
        f"{p}.avg_sell": money(r["avg_sell"]),
        f"{p}.ticket": f"{r['ticket_ratio']:.1f}×",
        f"{p}.captured": d["captured_utc"],
        f"{p}.captured_short": utc_short(d["captured_utc"]),
        f"{p}.wall": f"{d['wall_clock_s']:.1f}",
        f"{p}.pages": d["pages_per_token"],
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    churn = args[0] if args else "gme"
    ausd, shfl, bingo, churn_d = load("ausd"), load("shfl"), load("bingo"), load(churn)
    A = row_of(ausd)
    S = row_of(shfl)
    Bg = row_of(bingo)
    C = row_of(churn_d)
    ev = ausd["hero_evidence"]
    assert ev["side"] == "sell" and ev["maker"] == A["sell_top_maker"]
    ev_rows, ev_sum = evidence_table(ev)
    assert abs(ev_sum - A["sell_top_vol"]) < 0.01, (ev_sum, A["sell_top_vol"])
    assert len(ev["swaps"]) == A["sell_top_swaps"]

    def point(r, kind, **kw):
        return dict(
            symbol=r["symbol"],
            sx=r["sell_top_share"],
            by=r["buy_top_share"],
            net=r["net_flow_pct"],
            kind=kind,
            **kw,
        )

    # label offsets are chosen against the 50% dashed lines (x=387, y=256 in svg units) and the
    # plot frame; qa_site.py measures the result rather than trusting these numbers
    points = [
        point(A, "sell", lx=0, ly=-38, anchor="middle"),  # centred above: clear of x=387
        point(S, "buy", lx=22, ly=-14),  # right, raised: the sub-label clears y=256
        point(Bg, "both", lx=-26, ly=66, anchor="end"),
        point(C, "none", lx=22, ly=-12),  # right, raised: the sub-label stays above the frame
    ]

    ctx = {}
    for p, d, r in (
        ("ausd", ausd, A),
        ("shfl", shfl, S),
        ("bingo", bingo, Bg),
        ("churn", churn_d, C),
    ):
        ctx.update(token_ctx(p, d, r))

    head = (
        f"{'token':7}{'swaps':>7}{'avg buy $':>12}{'avg sell $':>12}{'ticket':>9}"
        f"{'buy w':>8}{'sell w':>8}{'top buy':>9}{'top sell':>10}{'net flow':>10}  note"
    )
    head_short = (
        f"{'token':7}{'swaps':>7}{'buy w':>8}{'sell w':>8}{'top buy':>9}{'top sell':>10}"
        f"{'net flow':>10}"
    )
    share = A["sell_top_vol"] / A["sell_vol"]
    replay = json.loads((PROOF / "bench_replay.json").read_text())["split"]
    live = json.loads((PROOF / "bench_live.json").read_text())["fetch"]
    ctx.update(
        {
            "bench.replay_p50": f"{replay['p50']:.3f}",
            "bench.replay_p95": f"{replay['p95']:.3f}",
            "bench.replay_n": replay["n"],
            "bench.live_p50": f"{live['p50']:,.0f}",
            "bench.live_p95": f"{live['p95']:,.0f}",
            "repo": REPO,
            "site": SITE_URL,
            "blank": BLANK,
            "ext": EXT,
            "gh_icon": gh_icon(),
            "gh_icon_btn": gh_icon("gh-mark"),
            "event": EVENT,
            "version": VERSION,
            "split_svg": split_svg(A),
            "split_stage_svg": split_stage_svg(A),
            "ausd.total_vol": money(A["sell_vol"] + A["buy_vol"]),
            "ausd.sell_frac": pct(A["sell_vol"] / (A["sell_vol"] + A["buy_vol"])),
            "ausd.buy_frac": pct(A["buy_vol"] / (A["sell_vol"] + A["buy_vol"])),
            "ausd.captured_date": ausd["captured_utc"][:10],
            "quadrant_svg": quadrant_svg(points),
            "json_panel": json_panel(A, "sell"),
            "evidence_rows": ev_rows,
            "evidence_sum": money(ev_sum, 2),
            "evidence_n": len(ev["swaps"]),
            "ausd.share_calc": f"{A['sell_top_vol']:,.2f} ÷ {A['sell_vol']:,.2f} = {share:.4f}",
            "ausd.ratio_check": f"{share:.4f}",
            "endpoint": ausd["endpoint"],
            "ausd.table_head": head,
            "ausd.table_row": (
                f"{A['symbol']:7}{A['swaps']:7}{A['avg_buy']:12,.2f}{A['avg_sell']:12,.2f}"
                f"{A['ticket_ratio']:8.1f}x{A['buy_wallets']:8}{A['sell_wallets']:8}"
            ),
            "ausd.table_row_hi": (
                f"{A['buy_top_share'] * 100:8.1f}%{A['sell_top_share'] * 100:9.1f}%"
            ),
            "ausd.table_row_tail": f"{A['net_flow_pct']:9.1f}%",
            "ausd.table_head_short": head_short,
            "ausd.table_row_short": (
                f"{A['symbol']:7}{A['swaps']:7}{A['buy_wallets']:8}{A['sell_wallets']:8}"
            ),
            "struct_a": struct_svg("A"),
            "struct_b": struct_svg("B"),
            "icon_anim": icon_inline(),
            "json_panel_short": json_panel_short(A),
            "evidence_rows_short": evidence_table_short(ev),
            "total_swaps": A["swaps"] + S["swaps"] + Bg["swaps"] + C["swaps"],
            "bingo.same_wallet": "yes" if Bg["sell_top_maker"] == Bg["buy_top_maker"] else "no",
            "bingo.wallet_short": short_addr(Bg["buy_top_maker"]),
            "churn.same_wallet": "yes" if C["sell_top_maker"] == C["buy_top_maker"] else "no",
            "churn.file": f"{churn}.json",
            "ausd.buy_top10_rows": top10_rows(A["buy_top10"]),
            "ausd.sell_top10_rows": top10_rows(A["sell_top10"]),
        }
    )

    # JUDGE.md carries the same claim, number and command as the landing page. Rendering it
    # from the same receipts is what stops the judge-facing document freezing on day one
    # while the product moves on.
    outputs = {
        SITE / "index.html": render((TEMPLATES / "landing.html").read_text(), ctx),
        SITE / "pitch" / "index.html": render((TEMPLATES / "deck.html").read_text(), ctx),
        BUILD / "JUDGE.md": render((TEMPLATES / "JUDGE.md").read_text(), ctx),
    }
    if check:
        stale = [p for p, out in outputs.items() if not p.exists() or p.read_text() != out]
        for p in stale:
            print(f"DRIFT: {p.relative_to(BUILD)} is not what the receipts render")
        if stale:
            sys.exit(1)
        print("in sync: site/index.html, site/pitch/index.html, JUDGE.md match docs/proof/*.json")
        return
    (SITE / "pitch").mkdir(parents=True, exist_ok=True)
    for path, out in outputs.items():
        path.write_text(out)
    print(
        "rendered " + ", ".join(f"{p.relative_to(BUILD)} ({len(o)}B)" for p, o in outputs.items())
    )


if __name__ == "__main__":
    main()
