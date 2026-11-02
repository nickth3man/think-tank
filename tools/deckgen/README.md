# deckgen

Renders a Markdown slide spec to a styled A4-landscape PDF using ArtCraft's design tokens
(`artcraft-native/src/theme.rs`, values transcribed in `src/tokens.rs`) and its three OFL
fonts (`assets/fonts`). Pipeline: headless `egui_kittest` render (wgpu) -> RGBA page ->
flate-compressed full-page image -> `pdf-writer`.

```bash
cargo run --release --manifest-path tools/deckgen/Cargo.toml -- deck.md -o deck.pdf
# mechanical gate: exact rect math over the render's own geometry
cargo run --release --manifest-path tools/deckgen/Cargo.toml -- deck.md -o deck.pdf --layout /tmp/layout.json
.venv/bin/python tools/deckgen/scripts/check_deck.py deck.pdf --layout /tmp/layout.json
```

`--layout` dumps every painted rect (kind, label, x/y/w/h) per page from the same paint
calls that produce the PDF, so `check_deck.py` verifies geometry by rectangle math rather
than pixel heuristics: safe-area bounds, footer-rule breaches, overlapping content rects,
text intruding into stat cards, and card baseline alignment. Exit 1 on any failure.

Spec (`src/spec.rs`): slides separated by a line of `---`; first block is the title slide.
Blank blocks (e.g. a trailing `---`) are skipped. Per slide: `# Title`, `KICKER: text`, `SUBTITLE: text`, `META: text` (title-slide bottom anchor),
`- bullet`, plain paragraphs, `STAT: value | LABEL` (max 4, bottom-anchored),
`HERO: value | context label` (one big number with claims in a right column),
`IMG: path` (relative to the spec file's directory).

Layout families (chosen per slide from content):
1. **Title** (first block): kicker, huge display title, subtitle, bottom meta anchor.
2. **List**: bullets at a deck-wide fitted size (varies layout, not type size), stat cards.
3. **Image split**: text column + image whose frame fills its half of the content width,
   vertically centred in the band and capped above the card row.
4. **Statement** (deliberate, loose trigger): a slide with no `IMG:` whose body text
   contains `": "` anywhere renders as two-column tracked-header claims. Each claim line
   splits at its **first** colon — text before it becomes a tracked header, after it the
   claim; headered claims pair into two columns (left INK_STRONG, right MUTED — the
   evidence/interpretation reading), an odd unheadered claim spans full width. This means prose colons silently switch a foreign deck's slide
   to this layout — by design, but know it. Worked example (`ui/deckgen/think-tank.md` P4):
   the bullet `One Rust crate, no reducers: every node clones the state...` splits into
   the header "One Rust crate, no reducers" + claim.
   Block kinds: a block with only `# Title` (no bullets, paragraphs, stats, or image)
   renders as a Section divider.
5. **Hero**: `HERO:` renders one oversized number with the remaining claims stacked at right.
6. **Feature section** (`CALLOUT: heading | body`): ArtCraft's bordered landing-page
   section with corner registration marks; stat cards stand in a column beside it when the
   section and cards cannot stack.

**Invariants the renderer enforces** (each has a test in `src/page.rs`):

- **One body size, deck-wide.** Pass one fits every body path (list bullets, statement
  claims, hero-column claims, callout body) against the tightest slide and records the
  result; pass two paints that size everywhere. `DECKGEN_VERBOSE=1` prints the chosen value.
  A slide that cannot hold it steps down rather than overflowing, and a test asserts that
  crowding one slide shrinks the whole deck.
- **Cards close the composition.** The card row hangs 26 pt under the last line of copy and
  falls back to the anchored band only when the copy already reaches it. A lone stat on a
  slide with an image becomes one full-width band with its value left and label right,
  instead of a chip beside a void.
- **The hero claim column clears the card row.** It compresses its gaps, then steps the body
  size down 1 pt at a time, so a crowded hero never overprints the cards.

`TAG: text` (control pill) and `BADGE: text | tone` (tone: `accent` default, `beta`, `bad`,
`neutral`) anchor to the top-right; on the title slide they stack as a pill over a badge.

Example: `ui/deckgen/think-tank.md`.

## Known limits

- Pages are raster images: **text is not selectable or searchable** and file size is ~1 MB.
  Future route (see docs/deckgen-iterations.md): krilla text layer from galley glyph runs.
- egui 0.36 gives `screen_rect` only to the first kittest step; fonts are activated with
  `request_discard` inside that step. Painting in later passes ghosts the page.
- Textures must outlive `render()` (the `keep` handle in `page.rs`).
- The deck is dark-only, like ArtCraft.
