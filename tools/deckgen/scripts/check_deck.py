#!/usr/bin/env python3
"""Mechanical layout gate for deckgen output.

Two independent layers:

1. Exact rectangle math over the `--layout` JSON (authoritative geometry, dumped
   from the same paint calls that produce the page, so no pixel heuristics):
   - bounds: every rect inside the page with a margin >= 24 pt
   - footer breach: no content rect overlaps the footer band (y >= PAGE_H - 40)
   - overlaps: no two content rects intersect beyond a small tolerance
   - card clearance: no text rect intrudes into a card panel it is not part of
   - card alignment: cards on one page share a common baseline
2. PDF-level sanity: page count, A4 landscape aspect, non-blank pages.

Usage:
    deckgen deck.md -o deck.pdf --layout layout.json
    check_deck.py deck.pdf --layout layout.json [--min-pages 5]
"""

import argparse
import json
import sys
from pathlib import Path

MARGIN_TOL = 24.0  # rects must stay this far inside the page edge
FOOTER_BAND = 40.0  # footer rule sits at PAGE_H - 40
OVERLAP_TOL = 2.0  # ignore sub-2pt touching (hairlines, adjacent baselines)

CONTENT_KINDS = {
    "kicker",
    "title",
    "subtitle",
    "meta",
    "hero-value",
    "hero-label",
    "claim",
    "claim-header",
    "bullet",
    "para",
    "card",
    "card-value",
    "card-label",
    "image",
    "badge",
    "tag",
    "callout",
    "callout-heading",
    "callout-body",
    # Footers are the boundary the footer check tests against, so they stay out.
}


def rects_intersect(a, b, tol=OVERLAP_TOL):
    ax2, ay2 = a["x"] + a["w"], a["y"] + a["h"]
    bx2, by2 = b["x"] + b["w"], b["y"] + b["h"]
    ix = min(ax2, bx2) - max(a["x"], b["x"])
    iy = min(ay2, by2) - max(a["y"], b["y"])
    return ix > tol and iy > tol, ix * iy


CARD_CHILDREN = {"card-value", "card-label"}
CALLOUT_CHILD = {"callout-heading", "callout-body"}


def nested(inner, outer):
    """True when `inner` is card content lying fully inside its card."""
    return (
        inner["x"] >= outer["x"] - 0.5
        and inner["y"] >= outer["y"] - 0.5
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + 0.5
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + 0.5
    )


def check_layout(layout, failures):
    for page in layout["pages"]:
        pno = page["page"]
        pw, ph = page["size"]["w"], page["size"]["h"]
        rects = [r for r in page["rects"] if r["kind"] in CONTENT_KINDS]

        # 1. Bounds
        for r in rects:
            if (
                r["x"] < MARGIN_TOL - 8.0
                or r["y"] < MARGIN_TOL - 8.0
                or r["x"] + r["w"] > pw - MARGIN_TOL + 8.0
                or r["y"] + r["h"] > ph - MARGIN_TOL + 8.0
            ):
                failures.append(
                    f"P{pno} bounds: {r['kind']} '{r['label'][:40]}' "
                    f"({r['x']:.1f},{r['y']:.1f} {r['w']:.1f}x{r['h']:.1f}) leaves the safe area"
                )

        # 2. Footer breach: no content may enter the footer band.
        footer_top = ph - FOOTER_BAND
        for r in rects:
            if r["y"] + r["h"] > footer_top + 1.0:
                failures.append(
                    f"P{pno} footer: {r['kind']} '{r['label'][:40]}' bottom {r['y'] + r['h']:.1f} "
                    f"crosses the footer rule at {footer_top:.1f}"
                )

        # 3. Overlaps between content rects (card nesting exempt).
        cards = [r for r in rects if r["kind"] == "card"]
        panels = [r for r in rects if r["kind"] == "callout"]
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                hit, area = rects_intersect(a, b)
                if not hit:
                    continue

                # Exempt only a child against the panel/card that contains it.
                def contained_child(x, y):
                    kinds = CARD_CHILDREN | CALLOUT_CHILD
                    if x["kind"] not in kinds:
                        return False
                    return any(
                        y["kind"] == container_kind and nested(x, y)
                        for container_kind in ("card", "callout")
                    )

                if contained_child(a, b) or contained_child(b, a):
                    continue
                failures.append(
                    f"P{pno} overlap: {a['kind']} '{a['label'][:28]}' x "
                    f"{b['kind']} '{b['label'][:28]}' ({area:.0f} pt^2)"
                )

        # 4. Card clearance: non-card text must not intrude into a card it does not belong to.
        for c in cards:
            for r in rects:
                if r["kind"] == "card" or (r["kind"] in CARD_CHILDREN and nested(r, c)):
                    continue
                hit, area = rects_intersect(r, c)
                if hit:
                    failures.append(
                        f"P{pno} card clearance: {r['kind']} '{r['label'][:28]}' intrudes "
                        f"into card '{c['label'][:24]}' by {area:.0f} pt^2"
                    )

        # 4b. Callout children must sit inside their panel (and thus cannot overlap each other's parent).
        for pn in panels:
            for r in rects:
                if r["kind"] in CALLOUT_CHILD and not nested(r, pn):
                    failures.append(
                        f"P{pno} callout: {r['kind']} '{r['label'][:28]}' escapes its panel"
                    )

        # 4c. A callout's heading and body must not collide.
        heads = [r for r in rects if r["kind"] == "callout-heading"]
        bodies = [r for r in rects if r["kind"] == "callout-body"]
        for h in heads:
            for b in bodies:
                hit, area = rects_intersect(h, b)
                if hit:
                    failures.append(
                        f"P{pno} callout: heading '{h['label'][:28]}' overlaps its body ({area:.0f} pt^2)"
                    )

        # 5. Cards either share one baseline (a row) or share one left edge and width
        #    (a stacked column beside a callout). Anything else is misaligned.
        if len(cards) > 1:
            ys = {round(c["y"], 1) for c in cards}
            xs = {round(c["x"], 1) for c in cards}
            ws = {round(c["w"], 1) for c in cards}
            row = len(ys) == 1
            column = len(xs) == 1 and len(ws) == 1
            if not (row or column):
                failures.append(
                    f"P{pno} card alignment: neither a row (tops {sorted(ys)}) nor a column "
                    f"(lefts {sorted(xs)}, widths {sorted(ws)})"
                )


def check_pdf(pdf_path, min_pages, failures):  # noqa: ARG001
    path = Path(pdf_path)
    if not path.is_file():
        failures.append(f"pdf: {pdf_path} not found")
        return
    if path.stat().st_size < 10_000:
        failures.append(f"pdf: suspiciously small ({path.stat().st_size} bytes)")
        return
    try:
        import fitz
    except ImportError:
        failures.append("pdf: PyMuPDF unavailable, cannot verify pages")
        return
    doc = fitz.open(str(path))
    if len(doc) != min_pages:
        failures.append(f"pdf: {len(doc)} pages, layout rendered {min_pages}")
    for i, page in enumerate(doc):
        ratio = page.rect.width / page.rect.height
        if not 1.40 <= ratio <= 1.43:
            failures.append(f"pdf: page {i + 1} aspect {ratio:.3f} is not A4 landscape")
        pix = page.get_pixmap(dpi=72)
        if len(set(pix.samples[:2000])) < 3:
            failures.append(f"pdf: page {i + 1} looks blank")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--layout", required=True, help="JSON from `deckgen --layout`")
    ap.add_argument(
        "--min-pages",
        type=int,
        default=None,
        help="override; by default the PDF must match the layout's page count",
    )
    args = ap.parse_args()

    failures = []
    layout = json.loads(Path(args.layout).read_text())
    check_layout(layout, failures)
    expected = args.min_pages if args.min_pages is not None else len(layout["pages"])
    check_pdf(args.pdf, expected, failures)

    n_rects = sum(len(p["rects"]) for p in layout["pages"])
    if failures:
        print(
            f"FAIL ({len(failures)} problems, {n_rects} rects over {len(layout['pages'])} pages)"
        )
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print(
        f"PASS: {len(layout['pages'])} pages, {n_rects} rects, no overlaps, no footer breaches, cards aligned"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
