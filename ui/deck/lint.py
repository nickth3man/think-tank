#!/usr/bin/env python3
"""Static and laid-out checks for the review deck.

WeasyPrint exposes its box tree; walking it turns "look at 15 PNGs and hope" into
numbers. Run with the interpreter that has weasyprint installed:

    /opt/homebrew/opt/python@3.13/bin/python3.13 ui/deck/lint.py

Exit status is 1 when any check fails, so it can gate a rebuild.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DECK = HERE / "deck.html"

# Slide geometry from deck.css: A4 landscape (297x210mm) with 12/14/14mm margins.
PAGE_W_MM, PAGE_H_MM = 297.0, 210.0
MARGIN_TOP_MM, MARGIN_BOTTOM_MM = 12.0, 14.0
CONTENT_H_MM = PAGE_H_MM - MARGIN_TOP_MM - MARGIN_BOTTOM_MM  # 184mm
CONTENT_W_MM = PAGE_W_MM - 2 * 14.0  # 269mm

# A slide is "empty" if it fills less than this fraction of the content box,
# which is what produced the wasted-page look the deck was rebuilt to avoid.
MIN_FILL = 0.55
# Text must stay above this size to remain legible in print.
MIN_FONT_PT = 6.5


def mm(px: float) -> float:
    return px * 25.4 / 96.0


def walk(box, out=None):
    out = [] if out is None else out
    out.append(box)
    for child in getattr(box, "children", []):
        walk(child, out)
    return out


def tag_of(box):
    return getattr(box, "element_tag", None)


def num(v):
    return isinstance(v, (int, float))


def check_static(html: str) -> list[str]:
    fails: list[str] = []
    sections = len(re.findall(r"<section\b", html))
    referenced = set(re.findall(r'src="(shots/[^"]+)"', html))
    on_disk = {f"shots/{p.name}" for p in (HERE / "shots").glob("*")}
    for ref in sorted(referenced - on_disk):
        fails.append(f"image referenced but missing: {ref}")
    # An image is only readable as text if it has alt text or sits in a <figure>
    # with a <figcaption>. The deck is a document, so this is its a11y contract.
    for m in re.finditer(r"<figure\b[^>]*>(.*?)</figure>", html, re.S):
        body = m.group(1)
        has_img = "<img" in body
        has_caption = "<figcaption" in body
        if has_img and not has_caption:
            src = re.search(r'src="([^"]+)"', body)
            fails.append(
                f"figure without figcaption: {src.group(1) if src else body[:60]}"
            )
    for m in re.finditer(r"<img\b[^>]*>", html):
        img = m.group(0)
        if "alt=" in img:
            continue
        # Not inside a captioned figure?
        start = html.rfind("<figure", 0, m.start())
        end = html.find("</figure>", m.end())
        inside = start != -1 and end != -1 and "<figcaption" in html[start:end]
        if not inside:
            src = re.search(r'src="([^"]+)"', img)
            fails.append(
                f"img with neither alt nor figcaption: {src.group(1) if src else img[:60]}"
            )
    print(f"  sections: {sections}   images referenced: {len(referenced)}")
    return fails


def check_layout(document) -> tuple[list[str], list[dict]]:
    fails: list[str] = []
    rows: list[dict] = []
    for index, page in enumerate(document.pages, 1):
        boxes = walk(page._page_box)
        section = next((b for b in boxes if tag_of(b) == "section"), None)
        if section is None:
            fails.append(f"page {index}: no <section> — content escaped its slide")
            continue
        page_h_mm = mm(page.height)
        slide_bottom = mm(section.position_y + section.height)
        limit = page_h_mm - MARGIN_BOTTOM_MM

        # Overflow: any box that paints below the page's bottom margin.
        spills = [
            b
            for b in boxes
            if tag_of(b)
            and num(getattr(b, "height", None))
            and mm(b.position_y + b.height) > limit + 0.4
        ]
        fill = mm(section.height) / CONTENT_H_MM

        # Images that render larger than the space left for them.
        oversized = []
        for b in boxes:
            if tag_of(b) != "img" or not num(getattr(b, "height", None)):
                continue
            h = mm(b.height)
            if h > CONTENT_H_MM or mm(getattr(b, "width", 0) or 0) > CONTENT_W_MM:
                oversized.append(round(h, 1))

        if spills:
            fails.append(
                f"page {index}: {len(spills)} box(es) below the bottom margin "
                f"(lowest {mm(max(b.position_y + b.height for b in spills)):.1f}mm > {limit:.1f}mm)"
            )
        if oversized:
            fails.append(
                f"page {index}: image taller/wider than the text block {oversized}"
            )

        rows.append(
            {
                "page": index,
                "slide_mm": round(mm(section.height), 1),
                "bottom_mm": round(slide_bottom, 1),
                "fill": round(fill, 3),
                "spills": len(spills),
            }
        )
    return fails, rows


def check_pages(document, sections: int) -> list[str]:
    fails = []
    if len(document.pages) != sections:
        fails.append(
            f"{sections} slides rendered to {len(document.pages)} pages — a slide broke in two"
        )
    return fails


def main() -> int:
    try:
        import weasyprint
    except ImportError:
        print(
            "weasyprint not importable; run with the Homebrew python 3.13",
            file=sys.stderr,
        )
        return 2

    html = DECK.read_text()
    print(f"deck: {DECK}")
    print("static checks")
    fails = check_static(html)

    print("layout checks")
    document = weasyprint.HTML(filename=str(DECK)).render()
    sections = len(re.findall(r"<section\b", html))
    fails += check_pages(document, sections)
    layout_fails, rows = check_layout(document)
    fails += layout_fails

    print(f"  {'page':>4} {'slide':>7} {'bottom':>7} {'fill':>6} {'spills':>6}")
    for r in rows:
        flag = ""
        if r["fill"] < MIN_FILL:
            flag = "  <- sparse"
            fails.append(
                f"page {r['page']}: slide fills {r['fill']:.0%} of the text block"
            )
        print(
            f"  {r['page']:>4} {r['slide_mm']:>7} {r['bottom_mm']:>7} {r['fill']:>6.0%} {r['spills']:>6}{flag}"
        )

    # Fonts actually used, with sizes, so a too-small caption is caught.
    sizes = Counter()
    for page in document.pages:
        for box in walk(page._page_box):
            style = getattr(box, "style", None)
            # ComputedStyle is mapping-like; font_size is in CSS px (96/25.4 mm).
            try:
                px = style["font_size"]
            except (TypeError, KeyError, AttributeError):
                continue
            if isinstance(px, (int, float)):
                sizes[round(px * 0.75, 1)] += 1
    small = sorted(pt for pt in sizes if pt < MIN_FONT_PT)
    print(f"  font sizes used (pt): {sorted(sizes)}")
    if small:
        fails.append(f"text below {MIN_FONT_PT}pt: {small}")

    print()
    if fails:
        print(f"FAIL ({len(fails)})")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
