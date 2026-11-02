# Notes

## The deckgen iteration loop (as practiced in this repo, 2026-11)

- **Artefacts**: `tools/deckgen/` (Rust renderer, ArtCraft design tokens) and the decks it
  renders: `ui/deckgen/think-tank.control.md` → `think-tank.pdf` (the control group — only
  adopts capabilities that measurably improve it), `ui/deckgen/lab.md` → `lab.pdf` (scratch
  deck where new directives land first), `ui/deckgen/think-tank.md` (the working deck).
- **Render**: `cargo run --release --manifest-path tools/deckgen/Cargo.toml -- deck.md -o
  deck.pdf --layout layout.json`. `--layout` dumps every painted rect; the mechanical gate
  is `tools/deckgen/scripts/check_deck.py deck.pdf --layout layout.json` (safe-area,
  footer breaches, overlaps, card clearance, card alignment, PDF pages == layout pages).
  Exit 1 on failure; a FAIL is a stop, not a note.
- **Grade**: five frozen axes, judged with `jev_noul` against an honest transcript of the
  current render that always includes a **measured type inventory** (e.g. "body 20pt on
  every slide, one size deck-wide"):
  1. space distributed well · 2. body text consistent · 3. layout variety ·
  4. images/charts integrated · 5. title slide composed.
  The transcript describes the render as it is; wording that hides real spread inflates
  scores and was rejected (inventory made body drop 0.80 → 0.48, exposing five type sizes).
- **Noise floor**: same transcript grades ±0.02; transcript wording itself moves scores
  more than that, hence the frozen inventory section.
- **Decision rule used**: fix the weakest axis; a generation is accepted only if no axis
  regresses more than 0.05 vs the last accepted one. Axes irrelevant to a deck's purpose
  (images on the lab deck) are recorded, not chased.
- **Verification hierarchy**: mechanical gate first (rect math), then Jev grade, then human
  eyes on rendered PNGs for the pages a change touched.
- **Foreign-deck proof**: the tool claims "any repo's data → deck"; a deck with content the
  renderer has never seen (`/tmp/foreign.md`) must gate PASS before the claim stands.

## User's world (to extend while grilling)

- Works in this repo (`think-tank`): a multi-agent deliberation system in Rust, plus
  `ui/deck*` (deck.html/css/pdf) and `tools/deckgen`.
- Uses `make check` as the repo's CI-shaped command; `.venv/bin/python` for Python tools.
- Comfortable with agents running long autonomous loops; wants a single late checkpoint
  with a decision-ready brief rather than per-step approval.
