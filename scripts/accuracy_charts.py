#!/usr/bin/env python3
"""Draw the README's two results charts from `examples/accuracy.json`.

`ff backtest` needs `data/replay/` (gitignored), so the README cannot regenerate its charts from the replay on another
machine. The numbers it would print are transcribed into `examples/accuracy.json` (each is the row `docs/accuracy.md`
holds), and this script draws them as plain SVG with the standard library alone: no plotting dependency, no Chrome,
and the same bytes every run so `git status` stays quiet. Called by `scripts/screenshots.sh`.

    uv run python scripts/accuracy_charts.py [--data examples/accuracy.json] [--out-dir examples]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# A light surface drawn explicitly, so GitHub's dark theme does not swallow the chart. Three leagues take the first
# three categorical slots of the palette (validated all-pairs for colour-vision deficiency); the pooled series is ink.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
INK3 = "#8a8985"
GRID = "#e6e5e1"
LEAGUE = {"L1": "#2a78d6", "L2": "#eb6834", "L3": "#1baf7a"}
FONT = "font-family='-apple-system, BlinkMacSystemFont, Segoe UI, Helvetica, Arial, sans-serif'"

W, H = 460, 360


def _t(x, y, s, size=12, fill=INK2, anchor="start", weight="normal", extra=""):
    return (f"<text x='{x:.1f}' y='{y:.1f}' font-size='{size}' fill='{fill}' text-anchor='{anchor}' "
            f"font-weight='{weight}' {extra}>{s}</text>")


def _head(title, sub):
    return [f"<svg xmlns='http://www.w3.org/2000/svg' width='{W}' height='{H}' viewBox='0 0 {W} {H}' {FONT}>",
            f"<rect width='{W}' height='{H}' rx='6' fill='{SURFACE}'/>",
            _t(16, 24, title, 14, INK, weight="600"),
            _t(16, 42, sub, 11, INK3)]


def calibration_svg(d: dict) -> str:
    c = d["calibration"]
    # plot area
    x0, x1, y0, y1 = 56, W - 20, 70, H - 56
    sx = lambda p: x0 + p * (x1 - x0)  # noqa: E731
    sy = lambda p: y1 - p * (y1 - y0)  # noqa: E731
    out = _head("Does “win 62%” mean 62%?",
                f"P(win) of the set lineups against who won · {c['season']} weeks {c['weeks']} · three leagues")
    # grid + axes
    for p in (0, 0.25, 0.5, 0.75, 1.0):
        out.append(f"<line x1='{x0}' y1='{sy(p):.1f}' x2='{x1}' y2='{sy(p):.1f}' stroke='{GRID}' stroke-width='1'/>")
        out.append(_t(x0 - 8, sy(p) + 4, f"{p:.2f}", 10, INK3, "end"))
        out.append(_t(sx(p), y1 + 16, f"{p:.2f}", 10, INK3, "middle"))
    out.append(_t((x0 + x1) / 2, H - 12, "predicted P(win), bin mean", 11, INK2, "middle"))
    out.append(_t(14, (y0 + y1) / 2, "share won", 11, INK2, "middle", extra=f"transform='rotate(-90 14 {(y0 + y1) / 2:.1f})'"))
    # the diagonal: perfect calibration
    out.append(f"<line x1='{sx(0)}' y1='{sy(0)}' x2='{sx(1)}' y2='{sy(1)}' stroke='{INK3}' stroke-width='1'/>")
    out.append(_t(sx(0.90), sy(0.84), "calibrated", 10, INK3, "end"))
    # leagues: small markers
    for lg, col in LEAGUE.items():
        for b in c["bins"]:
            if b[lg]:
                n, pred, won = b[lg]
                out.append(f"<circle cx='{sx(pred):.1f}' cy='{sy(won):.1f}' r='4' fill='{col}' fill-opacity='0.55' "
                           f"stroke='{SURFACE}' stroke-width='2'/>")
    # pooled: ink dots sized by n, joined
    pts = [(b["pooled"][1], b["pooled"][2], b["pooled"][0]) for b in c["bins"] if b["pooled"]]
    path = " ".join(f"{'M' if i == 0 else 'L'}{sx(p):.1f},{sy(w):.1f}" for i, (p, w, _) in enumerate(pts))
    out.append(f"<path d='{path}' fill='none' stroke='{INK}' stroke-width='2' stroke-linejoin='round' stroke-linecap='round'/>")
    for p, w, n in pts:
        r = 4 + (n ** 0.5) * 1.6
        out.append(f"<circle cx='{sx(p):.1f}' cy='{sy(w):.1f}' r='{r:.1f}' fill='{INK}' stroke='{SURFACE}' stroke-width='2'/>")
    big = max(pts, key=lambda t: t[2])
    out.append(_t(sx(big[0]) + 16, sy(big[1]) + 4, f"n={big[2]}", 10, INK2))
    # legend + Brier box
    lx, ly = x0 + 12, y0 + 10
    out.append(f"<circle cx='{lx + 5}' cy='{ly}' r='5' fill='{INK}'/>")
    out.append(_t(lx + 16, ly + 4, "pooled, sized by n", 11, INK2))
    s = c["summary"]
    for i, (lg, col) in enumerate(LEAGUE.items()):
        yy = ly + 18 * (i + 1)
        out.append(f"<circle cx='{lx + 5}' cy='{yy}' r='4' fill='{col}' fill-opacity='0.55'/>")
        out.append(_t(lx + 16, yy + 4, f"{lg} · n {s[lg]['n']} · Brier {s[lg]['brier']:.3f}", 11, INK2))
    out.append(_t(lx + 16, ly + 18 * 4 + 4, f"coin flip Brier {c['coin_flip_brier']:.2f}", 11, INK3))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def trade_svg(d: dict) -> str:
    t = d["trade_scan"]
    sample = "every package"
    x0, x1, y0, y1 = 56, W - 20, 70, H - 56
    vals = [v[2] for b in t["bins"] for v in b[sample].values() if v] + [b["mid"] for b in t["bins"]]
    lo, hi = min(-1.0, min(vals)), max(vals) + 0.5
    sy = lambda v: y1 - (v - lo) / (hi - lo) * (y1 - y0)  # noqa: E731
    out = _head("Does a trade row deliver what it promises?",
                f"points a week, promised vs realized, every package · {t['season']} weeks {t['weeks'].split()[0]}")
    ticks = [v for v in range(int(lo) - 1, int(hi) + 2) if lo <= v <= hi and v % 2 == 0]
    for v in ticks:
        col = INK3 if v == 0 else GRID
        out.append(f"<line x1='{x0}' y1='{sy(v):.1f}' x2='{x1}' y2='{sy(v):.1f}' stroke='{col}' stroke-width='1'/>")
        out.append(_t(x0 - 8, sy(v) + 4, f"{v:+d}" if v else "0", 10, INK3, "end"))
    out.append(_t(14, (y0 + y1) / 2, "realized, pts/wk", 11, INK2, "middle", extra=f"transform='rotate(-90 14 {(y0 + y1) / 2:.1f})'"))
    out.append(_t((x0 + x1) / 2, H - 12, "what the row promised, pts/wk", 11, INK2, "middle"))
    groups = t["bins"]
    gw = (x1 - x0) / len(groups)
    bw, gap = 20, 2
    for gi, b in enumerate(groups):
        gx = x0 + gi * gw
        cx = gx + gw / 2
        out.append(_t(cx, y1 + 16, b["bin"], 10, INK3, "middle"))
        # the promise: a hairline across the group at the bin midpoint
        px0, px1 = cx - (bw + gap) * 1.5 - 4, cx + (bw + gap) * 1.5 + 4
        out.append(f"<line x1='{px0:.1f}' y1='{sy(b['mid']):.1f}' x2='{px1:.1f}' y2='{sy(b['mid']):.1f}' "
                   f"stroke='{INK}' stroke-width='1.5' stroke-dasharray='3 3'/>")
        for li, (lg, col) in enumerate(LEAGUE.items()):
            v = b[sample].get(lg)
            bx = cx + (li - 1) * (bw + gap) - bw / 2
            if not v:
                out.append(_t(bx + bw / 2, sy(0) - 6, "—", 10, INK3, "middle"))
                continue
            n, hit, real = v
            top, base = (sy(real), sy(0)) if real >= 0 else (sy(0), sy(real))
            h = max(base - top, 1.0)
            r = min(4, h / 2)
            if real >= 0:
                path = (f"M{bx:.1f},{base:.1f} V{top + r:.1f} Q{bx:.1f},{top:.1f} {bx + r:.1f},{top:.1f} "
                        f"H{bx + bw - r:.1f} Q{bx + bw:.1f},{top:.1f} {bx + bw:.1f},{top + r:.1f} V{base:.1f} Z")
            else:
                path = (f"M{bx:.1f},{top:.1f} V{base - r:.1f} Q{bx:.1f},{base:.1f} {bx + r:.1f},{base:.1f} "
                        f"H{bx + bw - r:.1f} Q{bx + bw:.1f},{base:.1f} {bx + bw:.1f},{base - r:.1f} V{top:.1f} Z")
            out.append(f"<path d='{path}' fill='{col}'/>")
            ly = top - 5 if real >= 0 else base + 12
            out.append(_t(bx + bw / 2, ly, f"{real:+.1f}", 9, INK2, "middle"))
    # legend
    lx, ly = x0 + 12, y0 + 8
    for i, (lg, col) in enumerate(LEAGUE.items()):
        xx = lx + i * 46
        out.append(f"<rect x='{xx}' y='{ly - 8}' width='10' height='10' rx='2' fill='{col}'/>")
        out.append(_t(xx + 14, ly + 1, lg, 11, INK2))
    out.append(f"<line x1='{lx + 142}' y1='{ly - 3}' x2='{lx + 162}' y2='{ly - 3}' stroke='{INK}' stroke-width='1.5' stroke-dasharray='3 3'/>")
    out.append(_t(lx + 166, ly + 1, "promised (bin midpoint)", 11, INK2))
    top3 = t["totals"]["the card's top 3"]["L1"]
    every = t["totals"]["every package"]["L1"]
    out.append(_t(x0 + 12, y0 + 32, f"L1, every package (n {every[0]}): promised {every[2]:+.2f}, realized {every[3]:+.2f}", 10, INK2))
    out.append(_t(x0 + 12, y0 + 46, f"L1, the card's top 3 (n {top3[0]}): promised {top3[2]:+.2f}, realized {top3[3]:+.2f}, hit {top3[1]:.2f}", 10, INK2))
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(ROOT / "examples" / "accuracy.json"))
    ap.add_argument("--out-dir", default=str(ROOT / "examples"))
    a = ap.parse_args()
    d = json.load(open(a.data))
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, fn in (("calibration.svg", calibration_svg), ("trade-reliability.svg", trade_svg)):
        (out / name).write_text(fn(d))
        print(f"  {out / name}")


if __name__ == "__main__":
    main()
