# ArtCraft, awesome lists, and what actually renders `ui/deck/deck.pdf`

Research date: 2026-11-01. Subjects: `/tmp/artcraft` (shallow clone of
<https://github.com/storytold/artcraft>, MIT OR Apache-2.0) and the deck at
`ui/deck/deck.html` + `ui/deck/deck.css` → `ui/deck/deck.pdf`.

**How to read this.** Every claim is traced to a file (path + line range), a first-party
document, or a repository page, and each is marked with the source that owns it. Statements
marked **Derived** are conclusions drawn from those sources, not quotations. Where no source
in hand answers a question, the text says so under "Where the sources are silent" instead of
filling the gap by inference.

---

## 0. The three answers

1. **ArtCraft is a design-system donor, not a generator.** Its two apps (a pure-egui native
   app, a Tauri/React app) share one visual language written down twice — as Rust constants
   and as CSS custom properties. There is **no PDF, print, or document-export path of any
   kind** in the repository. What is reusable is the token values, the *shape* of five
   primitives, and three OFL fonts that ship as binaries.
2. **No awesome list covers print CSS.** There is no curated list for CSS Paged Media, and the
   maintained PDF list (`py-pdf/awesome-pdf`) indexes file-format libraries, not HTML→PDF
   engines, and does not mention WeasyPrint at all.
3. **WeasyPrint stays.** Measured here: a full 15-page rebuild in 0.75 s (three runs:
   0.75 / 0.75 / 0.74), page count and body text matching Chrome's output after normalisation,
   against a 2.4 % type-and-geometry shrink that Chrome's `printToPDF` applies unless
   `preferCSSPageSize` is set. The alternative engines are either browser wrappers
   (reintroducing the dependency WeasyPrint was chosen to avoid) or alpha-stage Rust engines.

The rest of this document is the evidence for those three sentences, plus the exact diff the
deck received.

---

## 1. ArtCraft has no PDF path — verified four ways

1. **No functional `pdf` match anywhere.** The only hits are the literal string
   `"pdfViewerEnabled−true"` inside a browser *fingerprint* payload
   (`crates/api_clients/openai_sora_client/src/requests/auth_sentinel/config.rs:77,92,95,388,391`
   and its Python twin `auth_sentinel_2/metadata/python_impl/config.py:75,90,93`) plus base64
   integrity hashes in `frontend/package-lock.json`.
2. **No print CSS.** A search for `@media print|@page|window\.print|print-color-adjust` across
   `frontend/` returns no matches.
3. **No PDF dependency.** `artcraft-native/Cargo.toml:27-50` lists `eframe`, `egui`,
   `egui_extras`, `env_logger`, `image`, `log`, `open`, `reqwest`, `resvg`, `rfd`, `rodio`,
   `serde`, `arboard`, `wry` — no PDF crate; `Cargo.lock` has `resvg` (`:6969`) and
   `tiny-skia` (`:9223`) and no `printpdf`/`lopdf`/`pdf`. `frontend/package.json` has no
   `jspdf`/`pdf-lib`/`react-to-print`/`html2pdf`/`puppeteer`; the only browser automation is
   `@playwright/test 1.63.0` (`:74`), used by `frontend/tools/performance/run.mjs:2,42` and
   `frontend/tools/testing/desktop-session.mjs:5,12` to *time the app*, with a single
   `page.screenshot({ path: … "drawing.png" })` at `run.mjs:91`.
4. **No export UI.** The nearest features are image- or media-shaped:
   `ARTCRAFT_SCREENSHOT=<file.png>` writes one PNG of the egui window after a fixed 8 s settle
   (`artcraft-native/src/app.rs:902-947`; `SETTLE_SECS = 8.0` at `:913`;
   `ViewportCommand::Screenshot` at `:925`), and the README states it "shows egui only, not the
   sign-in webview" (`artcraft-native/README.md:102-105`). Media download goes through an
   `rfd` save dialog (`app.rs:456-465`); canvas `toDataURL` calls serve thumbnails.

**Derived:** ArtCraft cannot replace WeasyPrint and offers no renderer that could. The one
architecturally transferable idea is its headless render harness —
`egui_kittest::Harness::builder().with_size(egui::vec2(1100.0, 600.0))` with `theme::apply` on
the first frame (`artcraft-native/src/prompt_box/ui_tests.rs:39-46`) — which is how it produces
reproducible UI frames without a window. That is not a PDF path.

---

## 2. What is actually reusable, and what is not

ArtCraft's design system exists as **tokens + conventions, not layout components**. Of the 46
packages under `frontend/libs/components/`, only `badge` and `label` are typography primitives;
there is no `Panel`, `Card`, `Section`, `Stack`, `Grid`, `Heading` or `Text` package. Panel and
card styling is written inline as Tailwind utility strings at each call site (e.g.
`apps/PageApps/AppsIndexPage.tsx:71-74`). 26 of the 46 ship a stub stylesheet beginning
`/* Replace this with your own classes` (e.g. `button/src/lib/button.module.css:1-5`).
**Derived:** there is nothing structural to import.

| Artefact | Path | Reuse |
|---|---|---|
| Colour, type, radius, shadow tokens | `artcraft-native/src/theme.rs:21-98` | **copy** (values) |
| Token CSS variables | `frontend/apps/artcraft/app/src/styles/base.css:133-185` | **copy** (values) |
| Global 3 px control radius | `.../styles/tailwind.css:10-18` | **copy** (rule) |
| `.glass`, `.filter-tab` | `.../styles/tailwind.css:21-45` | **copy** (classes) |
| Corner registration marks (CSS twin) | `base.css:838-850` | **copy** (print-safe CSS) |
| Three variable TTFs + OFL texts | `artcraft-native/assets/fonts/` | **copy** |
| Every widget in `artcraft-native/src/ui/` | `widgets.rs` | **ignore** — egui paint code |
| `theme.rs::apply`, `install_fonts` | `theme.rs:125-192` | **ignore** — egui API; the *numbers* transcribe |
| All 46 React components | `frontend/libs/components/**` | **ignore** — `modal.tsx` alone is 1194 lines |
| Motion tokens, five themes, `base.css` wholesale | `base.css:197-309,764-829` | **ignore** — invisible in print |

The token scale that matters, quoted:

| Token | Value | Source |
|---|---|---|
| page background | `#121316` | `theme.rs:22`; `--st-bg` `base.css:134` |
| panel | `#101014` | `theme.rs:24`; `--st-panel` `base.css:135` |
| body ink | `#f2f1ee` | `theme.rs:33`; `--st-fg` `base.css:143` |
| hairline | `#ffffff` α38 ≈ white/15 | `theme.rs:45`; `--st-panel-border` `base.css:136` |
| brand blue / blue 400 / focus ring | `#2d81ff` / `#59a7ff` / `#74aaff` | `theme.rs:58,60,62`; `tailwind.config.ts:95-96` |
| control radius | **3 px** | `theme.rs:76`; `tailwind.css:10-18` |
| large surfaces | **square — 0** | `theme.rs:1-5`; `other.rs:52` passes `0.0` |
| control height | 34 px | `theme.rs:79` |
| display face | Archivo 620 / 118 % width / −0.03 em | `theme.rs:169,185`; `base.css:66,73-74` |
| HUD label | 11 px Geist Mono 500, +0.15 em, uppercase | `theme.rs:81-82`; `base.css:106-113` |
| body | 14 px Inter | `theme.rs:169` |

**Derived — the one deliberate radius rule:** *3 px on anything pressable, square on anything
large.* Variable-font axes transcribe directly: `theme.rs:184` records Inter
`wght 400/500/600 @ opsz 14`, Archivo `wght 620, wdth 118`, Geist Mono `wght 400/500/650`, which
is exactly what `@font-face { font-variation-settings: … }` needs.

Licensing — with one gap on **our** side. ArtCraft is MIT OR Apache-2.0 (`README.md:145-149`,
`NOTICE:3-4`); the fonts are OFL-1.1 with licences beside them; Lucide geometry is ISC.
`OFL-Inter.txt:73-77` states that "the requirement for fonts to remain under this license does
not apply to any document created using the Font Software", so embedding the faces in the
exported PDF imposes nothing on the PDF. The ArtCraft wordmark and provider logos are
trademarks and are **not** licensed (`NOTICE:6-7,31-35`) — do not copy them.

**This repository declares no licence**: there is no `LICENSE*` file at the root and no
`license` field in `rust/Cargo.toml`. So while the vendored assets' own terms permit
redistribution, there is no outbound licence to say what the *combination* is. That is a
pre-existing question for the repo owner, not something this change introduces or settles —
and it is not a legal opinion either way.

---

## 3. The awesome-list sweep: no print-CSS list exists

Verified against the GitHub API and raw READMEs (all counts and dates as read on 2026-11-01):

- `topic:paged-media` returns 34 repositories, every one an application or library, none a
  curated list.
- `awesome-css-group/awesome-css`, `troxler/awesome-css-frameworks` and
  `sindresorhus/awesome` contain **no** print section; `sindresorhus/awesome` links only
  `klaufel/awesome-design-systems` at `readme.md:327`.
- `py-pdf/awesome-pdf` (163★, BSD-3, pushed 2026-10-25) is the maintained PDF list, and its
  `Generators` section stops at `mpdf`/`react-pdf`; a `grep -i` for
  `weasy|paged\.js|vivliostyle|prince|typst` over its raw README returns nothing.

The candidates the sweep did surface, with the property that decides them:

| Candidate | Licence | Offline | Verdict |
|---|---|---|---|
| [WeasyPrint](https://github.com/Kozea/WeasyPrint) | BSD-3 | yes, no browser | **keep** — already in use |
| [paged.js](https://github.com/pagedjs/pagedjs) | MIT | no — browser | rejected: reintroduces the browser |
| [Vivliostyle CLI](https://github.com/vivliostyle/vivliostyle-cli) | AGPL-3.0 | optional Playwright/docker (`README.md:141-157`) | rejected: browser wrapper + AGPL |
| [Ironpress](https://github.com/gastongouron/ironpress) | MIT | yes — "No browser, subprocess, or system dependencies" (`README.md:127-128`) | watch: CSS coverage unestablished; ships a Chromium-oracle parity suite (`README.md:504-528`) |
| [Fullbleed](https://github.com/fullbleed-engine/fullbleed-official) | MIT | yes | rejected: self-declared 2.6 **alpha** (`v2.6.0a14`) |
| [Typst](https://github.com/typst/typst) | Apache-2.0 | yes, single binary | escape hatch only: a native document model, not HTML. Its `typst.app/docs/reference/html/` page documents **HTML export** (Typst→HTML), and states it "is currently under active development… only available for experimentation behind a feature flag. Do not use this feature for production use cases." No HTML-*input* path is established. |
| wkhtmltopdf | — | yes | rejected: archived 2023-01-02 |

Rejected as lists or as sources of truth, with the evidence: `vonnieda/awesome-egui` (archived
2026-10-16), both `awesome-typst-cn` forks (archived / pushed 2023-10-07, unlicensed),
`sturobson/Awesome-Design-Tokens` (README is a redirect notice), `awesome-css-group/awesome-css`
(pushed 2024-10-30, no print section), and `awesome-print/awesome_print` — a Ruby
pretty-printer, a pure name collision that poisons `awesome+print+css` searches.

**No entry in any egui list emits a paginated document.** egui's ceiling is
`ViewportCommand::Screenshot` of one viewport, which is the wrong shape for 15 paginated A4
pages: no page breaks, no text selection, no vector typography. Its only sensible role here is
as the *source* of screenshots that HTML then lays out — which is what `ui/deck/shots/` already
is.

---

## 4. Measured: WeasyPrint vs Chrome on this deck

Both PDFs were regenerated from the current `deck.html` for this comparison (old renders were
stale). Chrome command (cwd `ui/deck`):

```
'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' --headless \
  --disable-gpu --no-pdf-header-footer --virtual-time-budget=15000 \
  --print-to-pdf=/tmp/cmp-chrome.pdf "file://$PWD/deck.html"
```

| Observation | WeasyPrint 70 | Chrome `printToPDF` |
|---|---|---|
| page count | 15 | 15 |
| word tokens, page 2 | 250 | 247 |
| alphabetic content after stripping digits, page header and footer | identical | identical, except one extra/absent letter on pages 2, 13 and 14 |
| extraction order | header/footer interleaved | header/footer extracted **first** |
| nested `.cols` / `.row3` / `.headrow` flexboxes | laid out correctly | laid out correctly |
| uniform scale | 14 mm bar = 39.69 pt; 9.0 pt text = 9.0 pt | 38.74 pt; 8.8 pt — a **2.4 %** shrink absent `preferCSSPageSize` |
| wall time, three runs | 0.75 s, 0.75 s, 0.74 s | several seconds |

The comparison is a **deterministic diff**, not a model judgement: `pymupdf` text per page,
whitespace and digits normalised, then compared. Every remaining difference traced to
letter-spacing splitting or joining a token (`D ESIGN` vs `DESIGN`, `cross-\nreferenced` vs
`cross-referenced`) and to page-counter digits landing inside the text run. **Derived:** the two
engines agree on this deck's text; only order and the uniform scale differ.

(The earlier `jev_compare` result — `same_fact` p = 0.97 — was dropped from this document: both
passages passed to it were my own summary prose, so it measured agreement between two sentences
I wrote, not between the two PDFs. The measurement above replaces it.)

**Derived:** the 2.4 % shrink is the deciding number. It silently changes every type size and
every measured geometry on the page, against a WeasyPrint rebuild that is faster and produces
the same text. Do not migrate.

### The `table.figs` wrappers: incidental, not load-bearing

The two `<table class="figs">` wrappers on the four-detail-panel slide (`deck.html:270,274`)
carry `max-width:100%; max-height:47mm; width:auto` on their images (`deck.css:144`). An
earlier note here claimed that rule "cannot be expressed on a flex child" — **that was wrong**,
and the test that produced it was confounded: it substituted `.row2` (which sets
`width: 100%` with no cap), so the images grew and the slide overflowed to a 16th page. The
cause was the missing height cap, not flex.

Retested in a scratch copy with the **same image rule** on the flex cells
(`max-width:100%; max-height:47mm; width:auto; margin:0 auto`): 15 pages, and the rendered slide
is visually identical to the table version. **Derived:** the table markup is incidental here;
the height cap is what matters. It is left as-is because there is no reason to churn working
markup, not because flex fails.

---

## 5. What the deck received

Confined to `ui/deck/`, no new dependency, no build step.

1. **Fonts.** `ui/deck/fonts/` holds `Inter-Variable.ttf`, `Archivo-Variable.ttf`,
   `GeistMono-Variable.ttf` and the three `OFL-*.txt` files, declared with
   `@font-face` in `deck.css:1-6`. `h1`/`h2` now use `font-variation-settings: "wght" 620,
   "wdth" 118` with negative tracking (`deck.css:32-33`).

   **Verified, because a `@font-face` declaring a variable file can silently render only its
   default instance.** Rendered one 20 pt line of Archivo at three axis values and measured ink
   coverage (dark pixels at 150 dpi, same text each time): `wght 400` → 3038, `wght 620` → 4011,
   `wght 900` → 6083. Monotonic, so the arbitrary 620 is honoured rather than snapped.
   `wdth 118` likewise produced a distinct `A-Semi-Expanded` instance. The deck's own PDF lists
   `ArchivoV-Semi-Expanded` and `ArchivoV-Bold-Semi-Expanded`, matching the two weight/width
   pairs the CSS asks for. **Conclusion: no static instances need to be built with
   `fontTools.varLib.instancer`.**
2. **Accent.** GitHub's `#58a6ff`/`#1f6feb` replaced throughout by ArtCraft's
   `#2d81ff`/`#1f66d0`; the ring glow became `rgba(45,129,255,.16)`.
3. **Radius rule.** `.card`, `.bignum` and `figure.plain img` are square; `.chip` and the
   region ring are `0.8 mm`, which is ≈3 px at 96 dpi (2.27 pt) — the control radius.
   **Note:** only the *blue* was swapped. GitHub's status colours (`#d29922` amber,
   `#3fb950` green, `#f85149` red) are still in `deck.css`; they were deliberately left
   alone, since they encode outcome (agreed / forced) rather than brand.
4. **Rings.** `rings.py` measures the live page and rewrites thirteen percentage-positioned
   rings. Its divisor is the **captured image** (1000 CSS px), not the page's scroll height —
   dividing by `scrollHeight` shifted every ring upward, which was a real bug caught and
   fixed; boxes below the fold are now clamped to the image edge.
5. **Corner registration marks.** Transcribed from `base.css:838-850`, then **removed**: at
   this page margin the top-left mark collided with the accent bar and the effect read as
   decoration, not registration. Recorded here so it is not re-attempted blindly.

Screenshots: `ui/deck/shots/` holds 19 `.jpg` files, `deck.html` references 19 unique paths,
and every referenced path resolves — no missing, no unreferenced. They are 1600×1000 CSS px
captured at device scale 2 (3200×2000). They were re-captured during this work; a set of
unreferenced shots from an earlier draft was deleted at the same time.

### Honesty check on printed numbers

The **deterministic** check is a shell assertion: the report JSON, formatted by the app's own
rounding rule (`ui/web/app.js:40`, `n2 = (v) => Number(v).toFixed(2)`), must equal the strings
in the deck's extracted text. That comparison covers the headline values the deck prints:

| Deck prints | Source of record | Result |
|---|---|---|
| `1.00` final score, `0.65` target, `2/6` rounds | `final.alignment_score` = 1, `config.alignment_threshold`, `rounds_taken`/`max_rounds` | ok |
| `0.15` / `0.1536` / `1.01` / `2/2` (forced run) | `final.alignment_score` = 0.1536, `config` target 1.01, max 2 | ok |
| `392` tokens | Σ every span's `in_tok` + `out_tok` = 336 + 56 | ok |
| `5.20 ms` | `telemetry.wall_clock_s` = 0.0052 × 1000 | ok |
| `2` claims / `2` challenges / `2` ideas / `2` merges | `final.claims_total` etc. | ok |

`jev_audit` was run as a **secondary** signal and escalated one record (`1.00`, p_wrong 0.99)
while the formatting rule was absent from the supplied source; with the derivation chain stated
explicitly, the same record returns `pass` at p_wrong 0.08. That is a property of how much the
source text spells out, not independent evidence — which is why the assertion above, not the
audit, is the check that counts. The deck and the app print identical strings for the same run,
verified by reading both.

This does **not** cover every number in the document: prose figures (the 2.4 % scale, the
0.75 s build time, page counts) come from the measurements in §4.

---

## 6. Where the sources are silent

- **Whether WeasyPrint supports any given modern CSS feature** is not established by anything
  in the ArtCraft tree. Two facts do hold: the deck uses none of `gradient`, `color-mix`,
  `backdrop` or `filter:` in `deck.css`, and it already relies on `@page` margin boxes and
  `counter(pages)` (`deck.css:10-15`). Treat "WeasyPrint will not render X" as a conservative
  assumption, not a citation.
- **Ironpress's real CSS coverage** is not established — its README documents a parity harness
  against a Chromium oracle rather than a supported-feature list.
- **`pushed_at` for paged.js, Vivliostyle, Mermaid, D2, Typst, egui, printpdf, resvg,
  chromiumoxide, svg2pdf** is not established: the GitHub core API quota was exhausted mid-run,
  so for those repositories only stars and licence were read from the repository page.
- **`argyleink/open-props` licence** is not established by the sources (no licence statement in
  its README; the API call failed on quota).
- **Whether Chrome's output is text-identical to WeasyPrint's beyond ordering** was not
  established: the comparison diff contained only tokenisation artefacts (letter-spaced
  uppercase headings splitting into `D ESIGN`, bullet glyphs, footer tokens moved) and no
  substituted words, but no saved diff file exists to prove it.

## Sources

| Claim area | Owning document |
|---|---|
| No PDF path; native deps; screenshot env var; fonts + licensing | `artcraft-native/README.md`, `artcraft-native/Cargo.toml`, `artcraft-native/src/app.rs:902-960` |
| Tokens, type, radius, shadow | `artcraft-native/src/theme.rs:21-192` |
| Widgets, corner marks, popover | `artcraft-native/src/ui/widgets.rs` |
| CSS token block, HUD label, display face, corner twin, five themes | `frontend/apps/artcraft/app/src/styles/base.css` |
| 3 px control rule, `.glass`, `.filter-tab` | `frontend/apps/artcraft/app/src/styles/tailwind.css` |
| Palette ramps, `ui.*` aliases | `frontend/apps/artcraft/tailwind.config.ts` |
| 46 component packages; `modal.tsx` 1194 lines | `frontend/libs/components/**` |
| Headless render harness | `artcraft-native/src/prompt_box/ui_tests.rs:39-46` |
| Licences, notices, trademarks | `LICENSE-MIT`, `LICENSE-APACHE`, `NOTICE:1-51`, `README.md:145-149` |
| Lucide ISC | <https://github.com/lucide-icons/lucide/blob/main/LICENSE> |
| SIL OFL 1.1 terms | `artcraft-native/assets/fonts/OFL-Inter.txt`; <https://openfontlicense.org> |
| Tailwind 3.4 defaults (not overridden) | <https://v3.tailwindcss.com/docs/font-size>, <https://v3.tailwindcss.com/docs/customizing-spacing> |
| No print-CSS awesome list; candidate metadata | `https://api.github.com/search/repositories?q=topic:paged-media`; raw READMEs of `py-pdf/awesome-pdf`, `sindresorhus/awesome`, `awesome-css-group/awesome-css` |
| paged.js browser dependency; Vivliostyle CLI flags; Ironpress no-browser claim; Fullbleed alpha | the respective repositories' raw `README.md` |
| egui's `ViewportCommand::Screenshot` | <https://docs.rs/egui/latest/egui/viewport/enum.ViewportCommand.html> |
| Typst HTML import | <https://typst.app/docs/reference/html/> |
| Our deck: geometry, type, radii, accents | `ui/deck/deck.css`; `ui/deck/lint.py` |
| Our deck: slide and figure markup | `ui/deck/deck.html`, `ui/deck/rings.py` |
| Report JSON the deck's numbers come from | `ui/web/app.js:40,123-129`; `/api/report?scenario=…` |
