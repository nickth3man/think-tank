# deckgen iteration log and exit definition

The deck was iterated with a Jev-gated loop: each iteration graded the rendered PDF
(`jev_noul` over a page-by-page visual transcript), formed search queries with
`jev_rerank`, ran them through Firecrawl, re-ranked results with Jev, scraped the top
source, and applied the top rule. Mid-loop, `jev_classify` quantified layout patterns,
`jev_find` located the code knob, and `jev_decide` picked variants (two-column
statements 0.62; hero layout; document-and-close for the text layer at 0.99).

## Frozen grade axes (exit definition)

The composite "would an executive approve" score proved noisy (moved without code
changes), so the exit criterion is five fixed propositions on a frozen transcript
template, graded per iteration:

| axis | iter 6 | final |
|---|---|---|
| space well distributed | 0.77 | 0.84 |
| body size consistent/appropriate | 0.88 | 0.72 |
| layout variety | 0.55 | 0.87 |
| images integrated | 0.73 | 0.84 |
| title composition | 0.78 | 0.83 |

Final layout families: title / list / image-split / two-column statement / big-number hero.

## Rules applied (with sources)

- Body text min 24pt at 1080p-equivalent, never web size; min type sizes across a deck
  (typographymaster.com/guide/typography-for-presentations, brightcarbon.com/presentation-font-size).
- One body size per deck; vary layout, not type size (deckgen measures a deck-wide fit).
- Whitespace distributed between blocks, cards anchored above the footer
  (presentationbase.com minimalist-presentation-design).
- Two-column slides must relate: evidence side + interpretation side
  (theanalystacademy.com/two-column-slide-layout).
- 60-30-10 color proportion (mlcpresentations.com 60-30-10 rule).
- "The big number" layout for single-metric slides (strategyu.co/slide-layouts).

## Generations under the agent-first goal

### Generation 1 — ArtCraft badge + control pill, and a real geometry gate

Capability added (source): ArtCraft `artcraft-native/src/ui/widgets.rs:12-15` (`caps`),
`:36-42` (`badge`), `:56-102` (`pill`) and `theme.rs:19-98` (control/semantic tokens:
`CONTROLS`, `CHROME`, `SUNKEN`, `DIM`, `LINE_STRONG`, `WASH`, `WASH_HOVER`, `BAD`,
`DANGER`, `BADGE_BETA`, `ACCENT_INK`, `CONTROL_H`, `fade`, `shadow`).

Spec: `BADGE: text | tone` (accent / beta / bad / neutral, accent default) and
`TAG: text`. The title slide paints a right-corner stack (pill above badge) and narrows
the display title so it never runs under it; content slides put the badge level with the
kicker. Badge behaviour is ported from the widget: 9 pt mono-bold caps, 2 pt radius,
fill at 12 % and stroke at 40 % of the tone, 10x4 padding, right-edge anchored.

Gate work (blocker fix): the first `check_deck.py` claimed overlap and clearance checks it
did not implement. Replaced with a deterministic route — `page.rs` records every painted
rect into a per-page `LayoutItem` list (deduped across kittest's two paint passes),
`--layout <path>` dumps it as JSON, and `check_deck.py` checks safe-area bounds,
footer-rule breaches, content overlaps, text intruding into cards, and card baseline
alignment, plus PDF page count/aspect/blankness. Negative-controlled by injecting rects:
exit 1. Clean deck: exit 0, 83 rects.

Verification: 4 tests pass (2 parser, 1 badge/tag parse, 1 collector — the collector test
failed first on real behavior, a colon bullet flipping the slide to statement mode).
`jev_noul` frozen axes, A/B against the pre-change baseline re-rendered under the same
transcript: space 0.74→0.77, body 0.75→0.76, variety 0.79→0.80, images 0.75→0.75,
title 0.77→0.80. `jev_review` composite 0.775 → 0.802 after the test gap was closed;
it still escalates on `test_gap` confidence (0.4 / below-review) — recorded as
unresolved rather than re-called, since the two tests it asked for now exist and run.

### Generation 2 — ArtCraft feature section (callout) with corner marks

Capability added (source): ArtCraft's landing-page feature section,
`artcraft-native/src/pages/common.rs:212-224` — a square-cornered panel filled at
`rgba(242,241,238,4)` with an `rgba(242,241,238,51)` inset stroke, 40x52 inner padding,
a display heading and a muted body line — plus `widgets::corner_marks`
(`widgets.rs:228-234`): 5.5 pt registration ticks at all four corners in `LINE_STRONG`.

Spec: `CALLOUT: heading | body`. The callout is its own layout family. Because the deck
already owns a type scale, the section does not mint one: heading at the content-title
size (32 pt display), body at 21 pt. Height comes from measured galleys, never a constant.

Two real defects the gate caught during this generation, both fixed at the cause:
1. The body was placed at a fixed 42 pt offset, so a two-line heading overlapped it. Now
   the offset is the measured heading height. The checker also gained a heading/body
   collision rule that reproduces exactly this bug.
2. When section + cards could not stack, cards were silently dropped. Now they stand in a
   right column beside the section (a stacked column is a legitimate card arrangement, so
   the alignment rule accepts *either* a shared baseline row or a shared left edge/width
   column). A compact-card metric bug — value and label colliding because the value height
   was assumed rather than measured — was caught by the same rule and fixed.

The `CONTENT_KINDS` filter in the checker had been silently excluding every new kind, so
`badge`, `tag`, `callout` and callout children were never checked at all; that is fixed and
both controls now fail as they should (regressed callout body → exit 1, claim intruding into
a card → exit 1, clean deck → exit 0).

Verification: 6 tests pass, including `callout_splits_heading_and_body` and
`callout_and_cards_coexist_without_overlap` (asserts three cards survive, no two content
rects intersect, cards share one left edge/width, each label sits below its value inside
its panel). Frozen axes vs Gen 1: space 0.77→0.78, body 0.76→0.80, variety 0.80→0.82,
images 0.75→0.75, title 0.80→0.80. The first pass graded body size 0.68 (−0.08, over the
regression bar) because the section carried four bespoke sizes; the fix was scale
unification, not a re-grade.

## Measurement caveats

- The title-slide `META:` line only rendered from the late iterations (the parse never
  landed until the statement rework) — every earlier title grade described a line that
  didn't exist yet. The final title grade (0.83) is the first honest one.
- Body-size axis dipped 0.88 → 0.72 in the final grade because the hero page's right-column
  claims are intentionally 18pt (the only sub-scale type in the deck); measured against a
  "one body size per deck" reading. Everything else sits on the deck-wide fitted size.
- tools/ and ui/deckgen/ are untracked in git as of this writing; snapshot before edits.

## Not built

- Selectable text layer: pages are raster. Route: capture galley glyph runs during paint,
  emit an invisible text layer with krilla (font embedding + ToUnicode). Deferred by
  jev_decide (0.99 document_and_close): outside the stated visual-quality objective.

## Loop run 2 (2026-11-02, generations 4-6)

Ran as the `deckgen-loop` workflow (`workflows/deckgen-iteration.md`). Baseline gen3:
[space 0.78, body 0.84, variety 0.79, images 0.80, title 0.81]. Bar: all applicable axes
>= 0.85 (user-set). Instrument: frozen 5-axis `jev_noul` + measured type inventory.

- **Gen4** — title block rebalanced (start 0.32, subtitle width 0.85 -> 2 lines, P1 mid
  void 94->116pt against a 128pt top void) and P3's wide stat band bottom-anchored on the
  shared 531pt closing line. Accepted: [0.78, 0.86, 0.79, 0.80, 0.81]. Body crossed the bar.
- **Gen5** — wide band grown to full card height (112pt), contents optically centred; P3
  pre-band void 79->43pt. Accepted: [0.79, 0.86, 0.79, 0.79, 0.81].
- **Gen6** — statement family gets its own closing element: one full-width raised band
  with hairline column dividers (P4), differentiating it from the list family's card row.
  Accepted: [0.78, 0.83, 0.79, 0.80, 0.82].

**Saturation finding.** Three generations aimed at the weakest axis moved it 0.78 -> 0.79
-> 0.78; variety stayed 0.79 throughout; every measured void is now consistent (closing
line shared at 531pt, rule-to-content gaps 40-68pt). The remaining sub-bar scores are the
design language's ceiling (dark, sparse, generous margins), not fixable defects. Further
generations would chase grader noise, so the run stops early on this evidence; the 0.85
bar stays unmet on space/variety/images and the last accepted generation is kept.

## Loop run 3 (2026-11-02, `/deckgen-loop 10` -> budget 10 generations)

Baseline gates: all three decks PASS before grading (control 79 rects, think-tank 81,
lab 51). Run-start control grade: [space 0.51, body 0.80, variety 0.80, images 0.75,
title 0.45]. Regression-deck starts: think-tank [0.56, 0.88, 0.82, 0.58, 0.47],
lab [0.58, 0.88, 0.74, 0.26 (no IMG:, not applicable), 0.52]. Bar: every applicable
control axis >= 0.85; the images axis applies (control carries `IMG:`).

- **Gen 7 (accepted)** — aimed at title 0.45, the weakest axis. Fix: `paint_title`
  (`tools/deckgen/src/page.rs`) now measures the title block (accent dash + kicker +
  title + subtitle) and centres it in the region above the meta anchor, so the void
  above the dash equals the void below the subtitle. Measured on the render: title
  block voids 190pt top / 116pt middle -> 129pt / 129pt (kicker y190->177, accent dash
  y142->129, subtitle bottom y399->386, meta anchored at y515). Rule source: balanced
  whitespace composition — verdanabold.com/post/presentation-design-101 (top of 7
  candidates via jev_rerank), brightcarbon.com/blog/presentation-whitespace.
  New behavioural test `title_block_is_centred_above_the_meta`; 12 tests pass, clippy
  clean, all three decks re-gate PASS. Grade of the gated render: [space 0.87,
  body 0.87, variety 0.85, images 0.79, title 0.85] — aimed axis cleared the bar, no
  axis regressed more than 0.05 (regression decks: think-tank [0.86, 0.90, 0.84,
  0.74, 0.87], lab [0.83, 0.89, 0.75, 0.33 n/a, 0.85]). Remaining sub-bar axis:
  images 0.79.
