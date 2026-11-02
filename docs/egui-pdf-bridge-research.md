# egui to PDF Bridge Research: Headless Render, Vector Tessellation, and Rust PDF Assembly

> **Implementation status (added after the build, 2026-11-01).** `tools/deckgen` was built from
> this note with three deviations, each observed while building: (1) pinned to `egui_kittest`
> 0.36.2 (ArtCraft's lockfile), not 0.37; (2) `render()` needs the `snapshot` and `wgpu` features
> (software rendering is not available; `LazyRenderer` panics without wgpu); (3) `pdf-writer`
> 0.14 is used instead of `printpdf`/`krilla`, because pages are single full-bleed images.
> Also observed: kittest feeds `screen_rect` only to the first step, so fonts are installed
> with `ctx.request_discard()` inside that step. Not solved: pages are raster, so text is not
> selectable; `krilla` plus an invisible text layer is the untested route.


Research date: 2026-11-01. Subjects: `egui` (0.36/0.37), `egui_kittest`, `epaint`, `printpdf`, `pdf-writer`, `krilla`, `svg2pdf`, `resvg`, ArtCraft design tokens and assets (`/tmp/artcraft`), and the Rust ecosystem for headless UI to PDF deck generation.

**How to read this.** Every factual assertion is traced to primary sources (docs.rs API documentation, crates.io package registry metadata, or official GitHub source trees). Statements marked **Derived** represent conclusions drawn logically from comparing those documented capabilities. Where existing documentation, source code, or awesome-lists are silent on a question, the text explicitly marks it under "Where the sources are silent" rather than asserting conjectures.

---

## 0. Executive Summary & Verdict

1. **The Core Headless Bridge (`egui_kittest`):** `egui_kittest` (MIT OR Apache-2.0, released through 0.37.0 on crates.io) provides `HarnessBuilder` and `Harness`, allowing arbitrary viewport sizing via `.with_size(Vec2)` and arbitrary render scale via `.with_pixels_per_point(f32)`. With `features = ["wgpu", "snapshot"]`, `Harness::render(&mut self) -> Result<image::RgbaImage, String>` rasterizes UI frames headlessly into in-memory pixel buffers without a physical display server or window manager. Sequential multi-page deck rendering is achieved either by advancing state and repainting the harness across steps, or by instantiating sequential page harnesses.
2. **The Vector Export Chasm (epaint / SVG):** egui's rendering engine (`epaint`) compiles immediate-mode layout primitives directly into `ClippedPrimitive::Mesh(Mesh)` (triangle meshes with textured glyphs and vertex colors). There is **no production crate in the Rust ecosystem that exports epaint or egui retained UI trees to SVG or vector PDF**. A few isolated community experiments attempt to walk `epaint::Shape`, but they cannot translate epaint's font-atlas glyph triangles or mesh clippings into selectable PDF text or clean vector paths.
3. **Resvg Capability:** `resvg` is an SVG rasterization library (converting SVG trees to `tiny-skia` pixel buffers). It **cannot output PDF directly**. For vector SVG to PDF, the Typst ecosystem maintains `svg2pdf` (which parses `usvg::Tree` and compiles PDF objects via `pdf-writer`).
4. **Rust PDF Assembly:** For composing multi-page decks from headless image frames, `printpdf` (MIT OR Apache-2.0, v0.12.8) and `krilla` (MIT OR Apache-2.0, v0.3.x, layered on Typst's `pdf-writer`) allow defining precise page dimensions (A4 Landscape: 297 mm × 210 mm / 841.89 pt × 595.28 pt), creating page boxes (`MediaBox`), and embedding full-bleed raster frames via compressed image XObjects.
5. **The Recommended Deck Pipeline:** A standalone CLI utility (`artcraft-deck-gen`) that drives `egui_kittest` with ArtCraft's `theme::apply` and bundled variable TTFs, renders each slide at 2× or 3× HiDPI (e.g. 2970×2100 px for 297×210 mm at 254 dpi) into `image::RgbaImage`, and stitches the resulting page buffers into a compliant A4 Landscape PDF using `printpdf` or `krilla`.

---

## 1. Candidate Comparison

| Candidate / Crate | What it provides | Licence | Verdict / Role |
|---|---|---|---|
| [egui_kittest](https://docs.rs/egui_kittest) | Headless egui harness (`HarnessBuilder`, `Harness`), headless event loop, wgpu-backed offscreen rendering to `image::RgbaImage`. | MIT OR Apache-2.0 | **Adopt** — The foundational headless driver for ArtCraft egui decks. |
| [printpdf](https://docs.rs/printpdf) | High-level PDF writer (`PdfDocument`, `PdfPage`, `RawImage`, `XObjectTransform`), mm-based coordinate geometry, native multi-page assembly. | MIT OR Apache-2.0 | **Adopt (Primary Writer)** — Mature, direct support for A4 page sizing and full-bleed image embedding. |
| [krilla](https://docs.rs/krilla) | High-level ergonomic PDF library layered on `pdf-writer`. Clean `Document::start_page_with` and `surface.draw_image` APIs. | MIT OR Apache-2.0 | **Strong Alternative** — Modern, clean architecture maintained by Typst contributor Laurenz Stampfl. |
| [pdf-writer](https://docs.rs/pdf-writer) | Low-level, allocation-efficient, step-by-step PDF serializer from Typst. Requires manual object ID tracking and content-stream operators (`Do`, `cm`). | Apache-2.0 OR MIT | **Viable Low-Level Engine** — Powers `krilla` and `svg2pdf`; unnecessary complexity compared to `printpdf` or `krilla` for pure image-page decks. |
| [scannedpdf](https://docs.rs/scannedpdf) | Opinionated images-to-PDF generator based on `printpdf` for merging scanned images into compressed A4 PDFs. | MIT | **Reference Only** — Demonstrates minimal image-to-PDF piping, but file-path oriented rather than memory-buffer oriented. |
| [svg2pdf](https://docs.rs/svg2pdf) | Converts static SVG (`usvg::Tree`) to standalone PDF buffers or Form XObjects with selectable text options. | MIT OR Apache-2.0 | **Keep as auxiliary** — Only relevant if deck templates emit intermediate SVG rather than native egui widgets. |
| [resvg](https://docs.rs/resvg) | SVG rendering library targeting raster buffers via `tiny-skia`. | MPL-2.0 | **Do Not Use for PDF** — Resvg does not produce PDF files (SVG to raster only). |
| epaint-to-SVG converters | Community requests / gists attempting to map `epaint::Shape` to SVG strings. | Various / Unlicensed | **Reject** — None support font atlas decoding or mesh tessellation to vector glyphs. |

---

## 2. In-Depth Technical Breakdown

### 2.1. egui Headless Rendering via `egui_kittest`

Primary sources:
- `docs.rs/egui_kittest/0.37.0` (<https://docs.rs/egui_kittest>)
- `crates/egui_kittest/src/builder.rs` (<https://github.com/emilk/egui/blob/main/crates/egui_kittest/src/builder.rs>)
- `crates/egui_kittest/src/renderer.rs` (<https://github.com/emilk/egui/blob/main/crates/egui_kittest/src/renderer.rs>)
- `crates/egui_kittest/src/wgpu.rs` (<https://github.com/emilk/egui/blob/main/crates/egui_kittest/src/wgpu.rs>)
- ArtCraft UI harness: `/tmp/artcraft/artcraft-native/src/prompt_box/ui_tests.rs:39-60`

#### Arbitrary Render Sizing and DPI
`HarnessBuilder` provides direct setters for canvas dimensions and scale:
- `pub fn with_size(mut self, size: impl Into<Vec2>) -> Self`: Sets the virtual screen size in egui logical points (e.g. A4 Landscape ratio: `egui::vec2(1188.0, 840.0)` or `egui::vec2(297.0, 210.0) * scale`).
- `pub fn with_pixels_per_point(mut self, pixels_per_point: f32) -> Self`: Configures the device scale factor. At `with_pixels_per_point(2.0)`, a 1188×840 point viewport produces a 2376×1680 pixel raster image.
- At runtime on an existing harness, `Harness::set_size(&mut self, size: impl Into<Vec2>)` and `Harness::set_pixels_per_point(&mut self, ppp: f32)` allow dynamic resizing between slides.

#### Multiple Sequential Frames
- Calling `harness.run()` drives the egui event loop until no repaints are requested (or up to `max_steps`, defaulting to step limits configurable via `with_max_steps`).
- For multi-page generation:
  1. **Option A (State Mutation):** The harness closure takes `|ui, state: &mut DeckState|`. The caller mutates `state.current_page += 1`, invokes `harness.run()`, and calls `harness.render()` to capture each successive slide.
  2. **Option B (Independent Harnesses):** A fresh `Harness::builder().with_size(...).build_ui(...)` is constructed per deck page, executing `harness.run()` and `harness.render()`.

#### Renderer Architecture: Software vs WGPU
- `egui_kittest` abstracts rendering behind the `pub trait TestRenderer`:
  ```rust
  pub trait TestRenderer {
      fn handle_delta(&mut self, delta: &mut egui::TexturesDelta);
      #[cfg(any(feature = "wgpu", feature = "snapshot"))]
      fn render(&mut self, ctx: &egui::Context, output: &egui::FullOutput) -> Result<image::RgbaImage, String>;
  }
  ```
- **Renderer backend:** The default implementation provided by `egui_kittest` is `WgpuTestRenderer` (lazily initialized by `LazyRenderer`). When `features = ["wgpu", "snapshot"]` is enabled, it uses `wgpu` (with hardware adapter or software fallback such as Lavapipe/WARP depending on the host OS) to execute the offscreen render pass.
- **There is no native pure-CPU software rasterizer** built into `egui_kittest`. If a system lacks GPU drivers, `wgpu` relies on OS software rasterizers (e.g., LLVMpipe/Lavapipe on Linux, WARP on Windows).

#### Snapshot Output Format
- `Harness::render(&mut self) -> Result<image::RgbaImage, String>` returns an `image::RgbaImage` directly in memory (`image` crate buffer of 8-bit RGBA pixels).
- The file-based snapshot methods (`harness.snapshot(name)` / `try_image_snapshot`) write PNG files using the `image` crate. However, for a PDF bridge, the caller does **not** need to touch disk: `harness.render()` provides raw pixel bytes directly.

#### Font & Theme Installation
- Font registration does not require a native OS window or eframe instance; it operates entirely on `egui::Context`.
- ArtCraft's implementation in `/tmp/artcraft/artcraft-native/src/theme.rs:160-205` (`apply(ctx)`) demonstrates exact font setup:
  ```rust
  let mut fonts = FontDefinitions::default();
  // Insert custom TTF bytes (Inter-Variable.ttf, Archivo-Variable.ttf, GeistMono-Variable.ttf)
  fonts.font_data.insert(name.to_owned(), Arc::new(FontData::from_static(bytes).tweak(tweak)));
  fonts.families.insert(family, stack);
  ctx.set_fonts(fonts);
  ```
- In `ui_tests.rs:41-45`, ArtCraft calls `crate::theme::apply(ui.ctx())` during the first harness frame. Because egui updates font atlases between frames, fonts installed on frame 0 are available for shaping and measurement on frame 1.

---

### 2.2. Vector & SVG Export Capabilities of egui / epaint

Primary sources:
- `docs.rs/epaint/latest/epaint/tessellator/index.html` (<https://docs.rs/epaint/latest/epaint/tessellator/index.html>)
- `docs.rs/epaint/latest/epaint/enum.Shape.html`
- `emilk/egui` issue discussions on export (<https://github.com/emilk/egui/discussions/8759>)

1. **How epaint renders:** epaint structures high-level painter calls into an `enum Shape` tree (`Shape::Vec`, `Shape::Circle`, `Shape::Rect`, `Shape::Text`, `Shape::Mesh`, etc.). During tessellation (`tessellator::tessellate_shapes`), `Shape::Text` is transformed into glyph quads textured from egui's global font atlas texture (`TexturesDelta`).
2. **The Vector Obstacle:**
   - Text is not emitted as vector Bézier outlines or font glyph references; it becomes textured triangle meshes referencing atlas raster coordinates.
   - Clipping rectangles (`ClippedShape`) are computed for GPU scissor rects (`egui::Rect`).
   - Consequently, converting `epaint::ClippedPrimitive` to an SVG or vector PDF requires re-tracing textured glyph quads back into text strings or re-rasterizing font glyphs as SVG paths—a feature that does not exist in any maintained Rust crate.
3. **Derived:** Generating vector-searchable PDF directly out of `epaint` without rebuilding a custom vector painting backend from scratch is technically infeasible today. The reliable bridge is high-resolution offscreen rasterization.

---

### 2.3. Rust PDF Writers & Image Embedding

Primary sources:
- `docs.rs/printpdf/0.12.8` (<https://docs.rs/printpdf>)
- `docs.rs/pdf-writer/latest/pdf_writer/` (<https://docs.rs/pdf-writer>)
- `docs.rs/krilla/latest/krilla/` (<https://docs.rs/krilla>)
- `crates.io/crates/scannedpdf` (<https://crates.io/crates/scannedpdf>)

#### Option 1: `printpdf` (Recommended for High-Level Control)
- **Geometry & Page Boxes:** `PdfDocument::new("Title", Mm(297.0), Mm(210.0), "Layer 1")` creates a document initialized to A4 Landscape (297 mm × 210 mm). Successive pages are added via `doc.add_page(Mm(297.0), Mm(210.0), "Layer Name")`.
- **Image Embedding:**
  ```rust
  let raw_image = RawImage::decode_from_bytes(png_bytes)?; // or from raw RGBA pixels
  let image_id = doc.add_image(&raw_image);
  let layer = doc.get_page(page_id).get_layer(layer_id);
  // Transform positions image at (0, 0) with scaling matching the page dimensions in mm
  layer.add_image(image_id, XObjectTransform {
      translate_x: Some(Mm(0.0)),
      translate_y: Some(Mm(0.0)),
      scale_x: Some(Mm(297.0).into_pt()),
      scale_y: Some(Mm(210.0).into_pt()),
      ..Default::default()
  });
  ```
- **Compression & PDF/A:** `printpdf` automatically Flate-compresses image XObjects and supports standard PDF/A conformance profiles.

#### Option 2: `krilla` (Modern Typst-Based Alternative)
- **Architecture:** Authored by Laurenz Stampfl (maintainer of Typst's SVG and PDF engines). Dual-licensed MIT OR Apache-2.0.
- **Page & Image API:**
  ```rust
  let mut doc = krilla::Document::new();
  // A4 Landscape in PostScript points: 841.89 pt x 595.28 pt
  let page_settings = krilla::PageSettings::new(841.89, 595.28);
  let mut page = doc.start_page_with(page_settings);
  let mut surface = page.surface();
  let image = krilla::image::Image::from_png(png_bytes)?;
  surface.draw_image(Point::from_xy(0.0, 0.0), Size::from_wh(841.89, 595.28), &image);
  page.finish();
  let pdf_bytes = doc.finish()?;
  ```

#### Option 3: `pdf-writer` (Low-Level Typst Foundation)
- Exposes direct PDF stream writing.
- Requires caller to allocate object reference IDs (`Ref::new(1)`), define `Catalog`, `Pages`, `Page` with `/MediaBox [0 0 841.89 595.28]`, define `/Resources << /XObject << /Im1 ... >> >>`, and emit content streams `q 841.89 0 0 595.28 0 0 cm /Im1 Do Q`.
- Unnecessary boilerplate compared to `krilla` or `printpdf`.

---

### 2.4. Resvg & svg2pdf Capabilities

Primary sources:
- `docs.rs/resvg/latest/resvg/` (<https://docs.rs/resvg>)
- Linebender resvg issue #127 (<https://github.com/RazrFalcon/resvg/issues/127>)
- `docs.rs/svg2pdf/latest/svg2pdf/` (<https://docs.rs/svg2pdf>)

1. **Can `resvg` output PDF?** **No.** `resvg` is strictly a 2D rasterizer built on top of `tiny-skia`. As author RazrFalcon confirmed in issue #127, resvg targets pixmaps and lacks a PDF serialization backend.
2. **The Typst Bridge (`svg2pdf`):** If vector SVG output is needed, the standard Rust library is `svg2pdf` (MIT OR Apache-2.0, maintained under the Typst GitHub organization). It accepts a `usvg::Tree` and outputs PDF bytes via `to_pdf(&tree, ConversionOptions::default(), PageOptions::default())`. It supports embedding fonts and selectable text. However, this requires an SVG input, which egui does not provide.

---

### 2.5. Prior Art & Awesome-List Sweep

Searches executed across GitHub and curated lists (`vonnieda/awesome-egui`, `rust-unofficial/awesome-rust`, `py-pdf/awesome-pdf`, `qjcg/awesome-typst`):

1. **`vonnieda/awesome-egui`:** Contains tools for native apps, games, node editors, and plotting (`egui_plot`). **Zero entries** for PDF export, document generation, or print layouts.
2. **`rust-unofficial/awesome-rust` (Libraries > Graphics > PDF):**
   - Lists `fschutt/printpdf` (PDF writing library), `LaurenzV/krilla` (ergonomic PDF generation), `J-F-Liu/lopdf` (low-level PDF manipulation), `kaj/rust-pdf`, `typst/typst`, and `gastongouron/ironpress`.
   - No bridge between `egui` and `printpdf` exists in the ecosystem.
3. **`py-pdf/awesome-pdf`:** Maintained list of PDF tools. Focuses on Python (`fpdf2`, `pypdf`), C/C++ engines (`pdfium`, `mupdf`), and standalone CLI processors. No GUI screenshot to PDF bridge documented.
4. **`emilk/egui` Repository Discussions:**
   - Discussion #2206 ("is there any good solution to display a PDF?"): Users discuss rendering PDFs *inside* egui via `pdfium-render` or `mupdf` as textures.
   - Discussion #8759 ("presentation app built with egui 0.36"): Presentations rendered offscreen to textures; export relies on saving raster frame series to disk.

---

## 3. Recommended Architecture: The `artcraft-deck` Tool

To satisfy the requirement ("build a repeatable tool that renders styled PDF deck pages using ArtCraft's design system tokens and variable TTFs so a coding agent can produce decks from any repo"):

### Pipeline Architecture

```
┌────────────────────────────────────────────────────────┐
│                      Deck Definition                   │
│   (Slide structs, slide types, text tokens, layouts)   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│                   egui Headless Driver                 │
│                 (using `egui_kittest`)                 │
│  - HarnessBuilder::with_size(1188.0, 840.0)            │
│  - HarnessBuilder::with_pixels_per_point(2.5)          │
│  - Theme: apply artcraft-native/src/theme.rs tokens    │
│  - Fonts: install Inter, Archivo, GeistMono TTFs       │
│  - Render loop: harness.run() -> harness.render()      │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼ Vec<image::RgbaImage>
┌────────────────────────────────────────────────────────┐
│                   Rust PDF Assembler                   │
│                  (`printpdf` or `krilla`)              │
│  - Page format: A4 Landscape (297 mm x 210 mm)         │
│  - MediaBox: [0 0 841.89 595.28]                       │
│  - Encode RgbaImage to PNG / Flate XObject             │
│  - Place full-bleed XObject per page                   │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
                   deck-output.pdf
```

### DPI and Coordinate Math
- Standard A4 Landscape dimensions:
  - Width: $297\text{ mm} = 11.693\text{ in} = 841.89\text{ pt}$
  - Height: $210\text{ mm} = 8.268\text{ in} = 595.28\text{ pt}$
- Virtual egui logical viewport:
  - Scale: $1\text{ pt} = 1.411\text{ logical units}$ $\rightarrow 1188\times 840$ logical points (aspect ratio $1188 / 840 = 1.41428 \approx \sqrt{2}$).
  - Scale factor: `pixels_per_point = 2.5` yields an output resolution of $2970 \times 2100$ pixels.
  - Printed DPI at $2970\times 2100$ on A4 ($11.69\times 8.27$ inches) $= 254\text{ DPI}$, providing crisp print and screen fidelity with zero GPU/window dependencies.

---

## 4. Where the Sources Are Silent

- **Headless GPU Independence on Bare Metal Linux:** While `egui_kittest` supports offscreen rendering via `wgpu`, `wgpu` requires an active adapter (Vulkan, Metal, DX12, or CPU software rasterizer like Mesa Lavapipe). Neither the egui nor kittest documentation specifies the minimum headless setup required in stripped Docker containers lacking `mesa-vulkan-drivers` or `libgl1`.
- **Selectable Text from `epaint`:** Neither egui documentation nor third-party issues establish any roadmap or mechanism for preserving selectable text vectors during canvas export. Any assertion that egui can currently emit searchable vector PDFs is unevidenced.
- **Direct Memory RGBA ingest in `printpdf` without re-encoding:** In `printpdf` 0.12.x, `RawImage` can be constructed directly from bytes, but documentation is ambiguous regarding whether providing raw RGBA requires manual separation of alpha channels into PDF Soft Masks (`/SMask`). Decoding via `image::codecs::png` before feeding to `printpdf` is standard practice.

---

## 5. Sources Cited

| Subject | Source / URL | Notes / Verbatim Proof |
|---|---|---|
| `egui_kittest` crate | <https://docs.rs/egui_kittest/0.37.0> | Crate documentation; `HarnessBuilder`, `Harness`, `TestRenderer`. |
| `egui_kittest` builder | <https://github.com/emilk/egui/blob/main/crates/egui_kittest/src/builder.rs> | `with_size`, `with_pixels_per_point`, `with_max_steps`. |
| `egui_kittest` renderer | <https://github.com/emilk/egui/blob/main/crates/egui_kittest/src/renderer.rs> | `TestRenderer` trait returning `Result<image::RgbaImage, String>`. |
| `printpdf` crate | <https://docs.rs/printpdf/0.12.8> | `PdfDocument::new`, `add_page`, `add_image`, `XObjectTransform`. |
| `krilla` crate | <https://docs.rs/krilla/latest/krilla/> | Modern high-level PDF library on `pdf-writer`. |
| `krilla` licence | <https://github.com/LaurenzV/krilla/blob/main/Cargo.toml> | `license = "MIT OR Apache-2.0"`. |
| `pdf-writer` crate | <https://docs.rs/pdf-writer/latest/pdf_writer/> | Low-level step-by-step PDF writer from Typst. |
| `svg2pdf` crate | <https://docs.rs/svg2pdf/latest/svg2pdf/> | SVG to PDF converter using `pdf-writer` and `usvg`. |
| `resvg` issue #127 | <https://github.com/RazrFalcon/resvg/issues/127> | "It will not work... resvg uses its own layers... manually written PDF backend". |
| `epaint` tessellator | <https://docs.rs/epaint/latest/epaint/tessellator/index.html> | Shape tessellation to triangle meshes using font atlas. |
| ArtCraft Native Theme | `/tmp/artcraft/artcraft-native/src/theme.rs:160-205` | Font loading (`FontDefinitions`), variable font tweaks, and style tokens. |
| ArtCraft Native UI Test | `/tmp/artcraft/artcraft-native/src/prompt_box/ui_tests.rs:39-60` | Headless harness usage: `Harness::builder().with_size(...).build_ui(...)`. |
| `awesome-rust` PDF section | <https://github.com/rust-unofficial/awesome-rust/blob/main/README.md> | Catalogs `printpdf`, `krilla`, `lopdf`. Zero egui PDF bridges. |
| `awesome-pdf` | <https://github.com/py-pdf/awesome-pdf/blob/main/README.md> | Maintained PDF list; no GUI-to-PDF pipeline documented. |
