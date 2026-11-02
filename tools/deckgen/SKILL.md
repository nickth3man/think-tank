---
name: deckgen
description: Create executive-ready presentation decks as styled A4 landscape PDFs from Markdown specifications using ArtCraft design tokens and typography.
---

# deckgen: Agent-First PDF Deck Generator

`deckgen` transforms structured Markdown slide decks into executive-grade A4 landscape PDFs using ArtCraft's brutalist design system (dark theme, high-contrast typography, crisp borders, and balanced whitespace).

## When to Use

Use `deckgen` whenever an agent needs to create a presentation, executive briefing, technical report, or architecture overview for stakeholders. It runs deterministically, requires no browser or headless Chrome, and produces publication-quality output.

## CLI Invocation

```bash
cargo run --release --manifest-path tools/deckgen/Cargo.toml -- <input.md> -o <output.pdf>
```

- Input: Markdown file structured by slide blocks separated by `---`.
- Output: Single A4 landscape PDF file.

## Slide Syntax Reference

Slides are delimited by lines containing only `---`. Blank slides (only empty lines between dividers) are automatically ignored.

### Slide Directives

| Directive | Description | Placement / Behavior |
| :--- | :--- | :--- |
| `# Title` | Slide display heading | Primary title set in Archivo Display face. |
| `KICKER: text` | Category / tracker label | Tracked uppercase monospace label above title. |
| `SUBTITLE: text` | Secondary summary line | Used on title slide or section dividers. |
| `META: text` | Metadata footer anchor | Placed just above the footer line on the title slide. |
| `HERO: 1.00 \| label` | Giant focal statistic | Giant accent-colored number with descriptive label and right-column claims. |
| `STAT: 42 \| label` | Metric summary card | Up to 4, sharing the content width equally and closing the page. A lone stat with an image renders as one full-width band. |
| `IMG: path/to/img.png`| Embedded visual asset | Path relative to the Markdown file; the frame fills half the content width, is centred in the band, and sits inside a hairline border. |
| `TAG: text` | Control pill, top-right | ArtCraft toolbar-pill frame (3 pt radius, controls fill, hairline). |
| `BADGE: text \| tone` | Status badge, top-right | Tones: `accent` (default), `beta`, `bad`, `neutral`. Sits under the tag. |
| `CALLOUT: heading \| body` | Feature section | Bordered panel with corner registration marks; card metrics stand beside it. |
| `- Bullet text` | Unordered list item | Painted at the deck-wide body size fitted from the tightest slide, so every slide shares one size. |
| `HEADER: Claim` | Two-column claim pair | Slides without images with `": "` split into two-column structured pairs. |

### Layout Families

`deckgen` selects the optimal layout family automatically based on slide content:

1. **Title Slide**: Contains kicker, oversized title, subtitle, and anchored bottom metadata.
2. **Section Divider**: A block containing only `# Title` (no body, stats, or images).
3. **List Slide**: 2–4 bulleted items paired with bottom metric cards.
4. **Image Split Slide**: Text / bullet points on the left; structured aspect-ratio framed image on the right.
5. **Statement / Two-Column Slide**: Splits bullet lines with `HEADER: Claim` into paired columns (left strong, right muted interpretation), closing with one banded stat row divided by hairlines.
6. **Hero Metric Slide**: Focuses on a single standout number (`HERO: ...`) with companion qualitative claims.

## Agent Workflow Guidelines

1. **Keep text concise**: Slides communicate concepts, not paragraphs. Limit bullets to 2–3 lines maximum.
2. **Use stat cards for key metrics**: Keep labels short (1–3 words) and numbers bold.
3. **Always specify KICKER**: KICKERs provide immediate context and orientation across slides.
4. **Gate, then look**: pass `--layout` and run `scripts/check_deck.py` (exit 1 on overlap, footer breach, card intrusion, misalignment, or a page-count mismatch). Geometry passing is not quality passing — render the pages to PNG (e.g. `fitz`/PyMuPDF) and read them too.
5. **Keep body sizes single**: adding copy to one slide shrinks the deck-wide body size for every slide; shorten the slide instead of letting the whole deck shrink.
