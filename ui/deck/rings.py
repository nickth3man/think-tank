#!/usr/bin/env python3
"""Regenerate the deck's region-ring percentages from the live UI.

The rings are absolutely-positioned boxes drawn over the full-screen screenshot.
Hand-typed percentages drift the moment any panel changes height (they did: a
title fix moved every ring by ~2%). This script measures the real DOM at the
capture viewport and rewrites `deck.html` in place.

Usage, with the UI server running:

    browser-tab> evaluate(MEASURE_JS)          # see below
    python3 ui/deck/rings.py measurements.json

The measurement is taken at 1600x1000 CSS px, the viewport the hero screenshot
uses. Rings are absolutely positioned inside the image's own box, so percentages
must be relative to the IMAGE (1000 px tall), not to the page's scroll height —
dividing by scrollHeight shifts every ring upward by the part of the page below
the fold. Regions that start below the fold are clamped to the image edge and
should be captioned as "top of the strip". Do not edit the numbers by hand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK = HERE / "deck.html"

MEASURE_JS = r"""
(() => {
  const W = 1600, H = 1000;  // the captured image, not the page height
  // The hero image starts at the top of the document (scrollY 0), so a box's
  // viewport y is already its offset inside the image. Clamp to the image box:
  // anything below the fold is only partly captured.
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const box = (el) => {
    const b = el.getBoundingClientRect();
    const top = clamp(b.y, 0, H);
    const bottom = clamp(b.y + b.height, 0, H);
    return {
      l: +(b.x / W * 100).toFixed(2),
      t: +(top / H * 100).toFixed(2),
      w: +(b.width / W * 100).toFixed(2),
      h: +((bottom - top) / H * 100).toFixed(2),
    };
  };
  const cs = [...document.querySelectorAll("main.grid > .center")];
  const right = cs[cs.length - 1].children;
  const header = box(document.querySelector("header.top"));
  const tiles = box(document.querySelector(".tiles"));
  const left = Math.min(header.l, tiles.l), top = Math.min(header.t, tiles.t);
  return {
    H, W,
    1: { l: left, t: top,
         w: +(Math.max(header.l + header.w, tiles.l + tiles.w) - left).toFixed(2),
         h: +(Math.max(header.t + header.h, tiles.t + tiles.h) - top).toFixed(2) },
    2: box(document.querySelector(".rail")),
    3: box(cs[0].children[0]),
    4: box(cs[0].children[1]),
    5: box(right[0]),
    6: box(right[1]),
    7: box(document.querySelector(".bottom")),
  };
})()
"""

# Each deck slide labels its ring with "region N of the full screen"; that ordering
# is the legend order used by the hero figure and by the mini-maps.
SLIDE_ORDER = [1, 3, 4, 2, 5, 7]


def style(n: int, table: dict) -> str:
    r = table[str(n)]
    return f"left:{r['l']}%;top:{r['t']}%;width:{r['w']}%;height:{r['h']}%"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: rings.py <measurements.json>", file=sys.stderr)
        return 2
    table = json.loads(Path(sys.argv[1]).read_text())
    html = DECK.read_text()

    # Hero rings carry their number; mini-map rings do not.
    def hero(m):
        n = int(m.group(1))
        return (
            f'<div class="ring r{n}{m.group(2) or ""}" style="{style(n, table)}"></div>'
        )

    html = re.sub(
        r'<div class="ring r(\d)((?: [ag])?)" style="[^"]*"></div>', hero, html
    )

    counter = {"i": 0}

    def mini(m):
        n = SLIDE_ORDER[counter["i"]]
        counter["i"] += 1
        return f'<div class="ring" style="{style(n, table)}"></div>'

    html = re.sub(r'<div class="ring" style="left:[^"]*"></div>', mini, html)
    DECK.write_text(html)
    print(f"rewrote {html.count('class="ring')} rings; scroll height {table['H']}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
