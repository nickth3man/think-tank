//! Page renderer: paints one slide into a fixed A4-landscape canvas with raw
//! painter ops, using only ArtCraft token values (see tokens.rs).

use crate::spec::{Deck, Slide, SlideKind};
use crate::tokens::*;
use egui::{vec2, Color32, Context, Pos2, Rect, Sense, Stroke, Vec2};

/// A4 landscape in PostScript points.
pub const PAGE: Vec2 = vec2(842.0, 595.0);
const MARGIN: f32 = 56.0;
const CONTENT_W: f32 = PAGE.x - 2.0 * MARGIN;

/// One painted rectangle, recorded during the authoritative render pass so
/// `--layout` can dump exact geometry for the mechanical overlap check.
pub struct LayoutItem {
    pub kind: &'static str,
    pub label: String,
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}

thread_local! {
    static LAYOUT: std::cell::RefCell<Vec<Vec<LayoutItem>>> = const { std::cell::RefCell::new(Vec::new()) };
}

/// Record a painted rect on the current page (no-op outside a render pass).
fn record(kind: &'static str, label: impl Into<String>, rect: Rect) {
    LAYOUT.with(|l| {
        if let Some(page) = l.borrow_mut().last_mut() {
            page.push(LayoutItem {
                kind,
                label: label.into(),
                x: rect.min.x,
                y: rect.min.y,
                w: rect.width(),
                h: rect.height(),
            });
        }
    });
}

thread_local! {
    static BODY_SIZE: std::cell::Cell<f32> = const { std::cell::Cell::new(0.0) };
}

/// The deck-wide body size chosen by the second pass (0 when no body slide exists).
pub fn deck_body_size() -> f32 {
    BODY_SIZE.with(|b| b.get())
}

/// Geometry of the last render pass, one vec per page.
pub fn layout() -> Vec<Vec<LayoutItem>> {
    LAYOUT.with(|l| {
        l.borrow()
            .iter()
            .map(|page| {
                // kittest paints each page twice (request_discard to activate fonts);
                // only the geometry of the last pass differs in nothing but repeats.
                let mut seen = std::collections::HashSet::new();
                page.iter()
                    .filter(|it| {
                        seen.insert((
                            it.kind,
                            it.label.clone(),
                            it.x.to_bits(),
                            it.y.to_bits(),
                            it.w.to_bits(),
                            it.h.to_bits(),
                        ))
                    })
                    .map(|it| LayoutItem {
                        kind: it.kind,
                        label: it.label.clone(),
                        x: it.x,
                        y: it.y,
                        w: it.w,
                        h: it.h,
                    })
                    .collect()
            })
            .collect()
    })
}

/// Paint a galley and record its rect (geometry only; kind/label for the check).
fn paint_text(
    p: &egui::Painter,
    pos: Pos2,
    g: std::sync::Arc<egui::Galley>,
    kind: &'static str,
    label: &str,
) {
    let rect = Rect::from_min_size(pos, g.size());
    record(kind, label, rect);
    p.galley(pos, g, INK);
}

/// ArtCraft `divider_with_label` (overlays/account.rs:205-213): a hairline broken by a
/// 10 pt mono caps label tracked 1.5 pt, both sides drawn at the row's vertical centre.
fn paint_divider(p: &egui::Painter, ctx: &Context, y: f32, left: f32, width: f32, label: &str) {
    let g = caps_galley(
        ctx,
        label,
        HUD_SIZE,
        mono_med(HUD_SIZE),
        HUD_SIZE * 0.15,
        FAINT,
    );
    let gap = g.size().x / 2.0 + 10.0;
    let cx = left + width / 2.0;
    p.hline(left..=cx - gap, y, hairline());
    p.hline(cx + gap..=(left + width), y, hairline());
    let pos = Pos2::new(cx - g.size().x / 2.0, y - g.size().y / 2.0);
    record(
        "divider",
        label,
        Rect::from_min_size(Pos2::new(left, y - 0.5), vec2(width, 1.0)),
    );
    paint_text(p, pos, g, "divider-label", label);
}

/// ArtCraft `widgets::corner_marks` (widgets.rs:228-234): 5.5 pt registration ticks
/// at a rect's four corners, in the strong line color.
fn corner_marks(p: &egui::Painter, rect: Rect) {
    let stroke = Stroke::new(1.0, LINE_STRONG);
    for c in [
        rect.left_top(),
        rect.right_top(),
        rect.left_bottom(),
        rect.right_bottom(),
    ] {
        p.hline(c.x - 5.5..=c.x + 5.5, c.y, stroke);
        p.vline(c.x, c.y - 5.5..=c.y + 5.5, stroke);
    }
}

/// ArtCraft's landing-page feature section (pages/common.rs:217-223): a square-cornered
/// panel with a 4/255 ink fill, a 51/255 ink stroke, corner registration marks, 40x52
/// inner padding, a display heading and a muted body line.
/// Callout type is the deck's own scale: the content title size (32 pt display) for the
/// heading and the deck body size for the text, so a section never mints a new size.
pub const CALLOUT_BODY: f32 = 21.0;
pub const CALLOUT_HEAD: f32 = 32.0;

fn callout_height(ctx: &Context, width: f32, heading: &str, body: &str) -> f32 {
    let inner_w = width - 80.0;
    let hh = text_galley(
        ctx,
        heading,
        display(CALLOUT_HEAD),
        INK_STRONG,
        inner_w,
        CALLOUT_HEAD * 1.25,
    )
    .size()
    .y;
    let bh = if body.is_empty() {
        0.0
    } else {
        16.0 + text_galley(
            ctx,
            body,
            inter(CALLOUT_BODY),
            MUTED,
            inner_w,
            CALLOUT_BODY * 1.5,
        )
        .size()
        .y
    };
    hh + bh + 104.0
}

/// Shrink the section's type until it fits `max_h`, in the deck's own scale steps. The
/// panel is drawn to its measured height, so a clamp can never leave text outside it.
fn callout_sizes(
    ctx: &Context,
    width: f32,
    heading: &str,
    body: &str,
    max_h: f32,
    deck_body: Option<f32>,
) -> (f32, f32) {
    let bodies: [f32; 4] = deck_body.map_or([21.0, 19.0, 18.0, 16.0], |d| [d, 21.0, 19.0, 18.0]);
    for head in [32.0f32, 28.0, 24.0, 21.0, 18.0] {
        for body_sz in bodies {
            let inner_w = width - 80.0;
            let hh = text_galley(
                ctx,
                heading,
                display(head),
                INK_STRONG,
                inner_w,
                head * 1.25,
            )
            .size()
            .y;
            let bh = if body.is_empty() {
                0.0
            } else {
                16.0 + text_galley(ctx, body, inter(body_sz), MUTED, inner_w, body_sz * 1.5)
                    .size()
                    .y
            };
            if hh + bh + 104.0 <= max_h {
                return (head, body_sz);
            }
        }
    }
    (18.0, 16.0)
}

fn paint_callout(
    p: &egui::Painter,
    ctx: &Context,
    rect: Rect,
    heading: &str,
    body: &str,
    head_sz: f32,
    body_sz: f32,
) {
    p.rect(
        rect,
        egui::CornerRadius::ZERO,
        SECTION_FILL,
        Stroke::new(1.0, SECTION_STROKE),
        egui::StrokeKind::Inside,
    );
    corner_marks(p, rect);
    let inner = rect.shrink2(vec2(40.0, 52.0));
    let hg = text_galley(
        ctx,
        heading,
        display(head_sz),
        INK_STRONG,
        inner.width(),
        head_sz * 1.25,
    );
    let hh = hg.size().y;
    paint_text(
        p,
        Pos2::new(inner.left() - 1.0, inner.top()),
        hg,
        "callout-heading",
        heading,
    );
    if !body.is_empty() {
        let by = inner.top() + hh + 16.0;
        let bg = text_galley(
            ctx,
            body,
            inter(body_sz),
            MUTED,
            inner.width(),
            body_sz * 1.5,
        );
        paint_text(p, Pos2::new(inner.left(), by), bg, "callout-body", body);
    }
    record("callout", heading, rect);
}

/// Badge tone -> ArtCraft color (BADGE_BETA / BAD / ACCENT / DIM).
fn tone_color(tone: crate::spec::Tone) -> Color32 {
    use crate::spec::Tone;
    match tone {
        Tone::Accent => ACCENT_INK,
        Tone::Beta => BADGE_BETA,
        Tone::Bad => BAD,
        Tone::Neutral => DIM,
    }
}

/// ArtCraft `widgets::badge` (artcraft-native/src/ui/widgets.rs:36-42): 9 px mono-bold
/// caps on a tinted chip, 2 pt radius, fill at 12 % and stroke at 40 % of the tone,
/// 10x4 padding, anchored by its right edge.
fn paint_badge(
    p: &egui::Painter,
    ctx: &Context,
    right_center: Pos2,
    text: &str,
    tone: Color32,
) -> Rect {
    let g = caps_galley(ctx, text, 9.0, mono_bold(), 0.9, tone);
    let size = g.size() + vec2(10.0, 4.0);
    let rect = Rect::from_min_size(
        Pos2::new(right_center.x - size.x, right_center.y - size.y / 2.0),
        size,
    );
    p.rect(
        rect,
        egui::CornerRadius::same(2),
        fade(tone, 0.12),
        Stroke::new(1.0, fade(tone, 0.4)),
        egui::StrokeKind::Inside,
    );
    p.galley(rect.center() - g.size() / 2.0, g, INK);
    rect
}

/// ArtCraft `widgets::pill` frame (widgets.rs:56-77) as a static chip: 3 pt radius,
/// CONTROLS fill, LINE stroke, 12 pt side padding, CONTROL_H tall. Returns its rect.
fn pill_rect(p: &egui::Painter, ctx: &Context, left_center_y: Pos2, label: &str) -> Rect {
    let g = text_galley(ctx, label, inter(14.0), INK, CONTENT_W, CONTROL_H);
    let size = vec2(12.0 + g.size().x + 12.0, CONTROL_H);
    let rect = Rect::from_min_size(
        Pos2::new(left_center_y.x, left_center_y.y - size.y / 2.0),
        size,
    );
    p.rect(
        rect,
        RADIUS,
        CONTROLS,
        Stroke::new(1.0, LINE),
        egui::StrokeKind::Inside,
    );
    p.galley(
        Pos2::new(rect.left() + 12.0, rect.center().y - g.size().y / 2.0),
        g,
        INK,
    );
    rect
}

/// One harness per page: each slide paints once into a fresh context.
pub fn render_deck(deck: &Deck) -> Vec<image::RgbaImage> {
    // Pass 1 measures the smallest body size any list slide needs; pass 2 paints
    // every list slide at that size (vary layout, not type size).
    let fit = std::cell::Cell::new(f32::MAX);
    render_pass(deck, &fit, None);
    let forced = fit.get();
    if std::env::var("DECKGEN_VERBOSE").is_ok() {
        eprintln!("deckgen: deck-wide body size {forced} pt");
    }
    BODY_SIZE.with(|b| b.set(if forced < f32::MAX { forced } else { 0.0 }));
    render_pass(
        deck,
        &fit,
        if forced < f32::MAX {
            Some(forced)
        } else {
            None
        },
    )
}

pub fn render_pass(
    deck: &Deck,
    fit: &std::cell::Cell<f32>,
    forced: Option<f32>,
) -> Vec<image::RgbaImage> {
    use egui_kittest::Harness;
    let n = deck.slides.len();
    let title = deck.slides[0].title.clone().unwrap_or_default();
    LAYOUT.with(|l| l.borrow_mut().clear());
    deck.slides
        .iter()
        .enumerate()
        .map(|(i, slide)| {
            LAYOUT.with(|l| l.borrow_mut().push(Vec::new()));
            let mut primed = false;
            // Handle drop frees the texture; keep it alive until render().
            let mut keep: Option<egui::TextureHandle> = None;
            let mut harness = Harness::builder()
                .with_size(PAGE)
                .with_pixels_per_point(3.0)
                .build_ui(|ui| {
                    let ctx = ui.ctx().clone();
                    // kittest feeds real input (screen_rect) to the first step
                    // only, and set_fonts activates on the next pass. A discard
                    // re-runs this pass inside the same step with input intact.
                    if !primed {
                        primed = true;
                        install_fonts(&ctx);
                        ctx.request_discard("activate deck fonts");
                        return;
                    }
                    paint_slide(
                        ui,
                        &ctx,
                        slide,
                        Footer {
                            page: i + 1,
                            total: n,
                            deck_title: &title,
                        },
                        &mut keep,
                        fit,
                        forced,
                    );
                });
            harness.step();
            harness.render().expect("kittest render")
        })
        .collect()
}

/// The footer line: which page, out of how many, under which deck title.
struct Footer<'a> {
    page: usize,
    total: usize,
    deck_title: &'a str,
}

fn paint_slide(
    ui: &mut egui::Ui,
    ctx: &Context,
    slide: &Slide,
    footer: Footer<'_>,
    keep: &mut Option<egui::TextureHandle>,
    fit: &std::cell::Cell<f32>,
    forced: Option<f32>,
) {
    let Footer {
        page,
        total,
        deck_title,
    } = footer;
    let p = ui.painter().clone();
    p.rect_filled(Rect::from_min_size(Pos2::ZERO, PAGE), 0.0, BG);

    match slide.kind {
        SlideKind::Title => paint_title(&p, ctx, slide),
        SlideKind::Section => paint_section(&p, ctx, slide),
        SlideKind::Content => paint_content(ui, &p, ctx, slide, &mut Pass { keep, fit, forced }),
    }

    // Footer: hairline, deck kicker left, page counter right (mono, tracked).
    let fy = PAGE.y - 40.0;
    p.line_segment(
        [Pos2::new(MARGIN, fy), Pos2::new(PAGE.x - MARGIN, fy)],
        hairline(),
    );
    let g = hud_galley(ctx, deck_title, FAINT, 0.12);
    paint_text(&p, Pos2::new(MARGIN, fy + 10.0), g, "footer", deck_title);
    let counter = hud_galley(ctx, &format!("{:02} / {:02}", page, total), FAINT, 0.12);
    let cw = counter.size().x;
    paint_text(
        &p,
        Pos2::new(PAGE.x - MARGIN - cw, fy + 10.0),
        counter,
        "footer",
        "counter",
    );
}

fn paint_title(p: &egui::Painter, ctx: &Context, s: &Slide) {
    // Centre the block in the space above the meta anchor so the empty areas above
    // and below it are equal: balanced whitespace reads as intentional
    // (verdanabold.com/post/presentation-design-101,
    //  brightcarbon.com/blog/presentation-whitespace).
    let dash_gap = 48.0; // accent bar sits this far above the kicker
    let mut block_h = dash_gap;
    if s.kicker.is_some() {
        block_h += HUD_SIZE + 22.0;
    }
    if let Some(t) = &s.title {
        block_h += text_galley(ctx, t, display(76.0), INK_STRONG, CONTENT_W, 84.0)
            .size()
            .y
            + 24.0;
    }
    if let Some(sub) = &s.subtitle {
        block_h += text_galley(ctx, sub, inter(24.0), MUTED, CONTENT_W * 0.85, 34.0)
            .size()
            .y;
    }
    let region_bottom = if s.meta.is_some() { PAGE.y - 80.0 } else { PAGE.y - 60.0 };
    let mut y = (((region_bottom - block_h) / 2.0) + dash_gap).max(MARGIN);
    // Accent bar.
    p.rect_filled(
        Rect::from_min_size(Pos2::new(MARGIN, y - dash_gap), vec2(48.0, 4.0)),
        0.0,
        ACCENT,
    );
    // Right corner stack: the control pill first, the status badge under it.
    let mut stack_bottom: Option<f32> = None;
    if let Some(tag) = &s.tag {
        let g = text_galley(ctx, tag, inter(14.0), INK, CONTENT_W, CONTROL_H);
        let w = 12.0 + g.size().x + 12.0;
        let r = pill_rect(
            p,
            ctx,
            Pos2::new(PAGE.x - MARGIN - w, y + CONTROL_H / 2.0),
            tag,
        );
        record("tag", tag, r);
        stack_bottom = Some(r.bottom() + 14.0);
    }
    let badge_rect = s.badge.as_ref().map(|b| {
        let tone = tone_color(b.tone);
        let cy = stack_bottom.map_or(y + HUD_SIZE * 0.5, |b| b + 9.0);
        let r = paint_badge(p, ctx, Pos2::new(PAGE.x - MARGIN, cy), &b.text, tone);
        record("badge", &b.text, r);
        stack_bottom = Some(r.bottom() + 14.0);
        r
    });
    let mut title_w = CONTENT_W;
    if let Some(r) = badge_rect {
        title_w = (r.left() - 24.0) - MARGIN;
    }
    if let Some(k) = &s.kicker {
        let g = hud_galley(ctx, k, ACCENT_400, 0.15);
        paint_text(p, Pos2::new(MARGIN, y), g, "kicker", k);
        y += HUD_SIZE + 22.0;
    }
    if let Some(t) = &s.title {
        let g = text_galley(ctx, t, display(76.0), INK_STRONG, title_w, 84.0);
        let h = g.size().y;
        paint_text(p, Pos2::new(MARGIN - 2.0, y), g, "title", t);
        y += h + 24.0;
    }
    if let Some(sub) = &s.subtitle {
        let g = text_galley(ctx, sub, inter(24.0), MUTED, CONTENT_W * 0.85, 34.0);
        paint_text(p, Pos2::new(MARGIN, y), g, "subtitle", sub);
    }
    // Anchor the bottom: deck meta just above the footer rule.
    if let Some(m) = &s.meta {
        let g = hud_galley(ctx, m, ACCENT_400, 0.15);
        paint_text(p, Pos2::new(MARGIN, PAGE.y - 40.0 - 40.0), g, "meta", m);
    }
}

fn paint_section(p: &egui::Painter, ctx: &Context, s: &Slide) {
    let y = PAGE.y * 0.40;
    p.rect_filled(
        Rect::from_min_size(Pos2::new(MARGIN, y - 40.0), vec2(48.0, 4.0)),
        0.0,
        ACCENT,
    );
    if let Some(k) = &s.kicker {
        let g = hud_galley(ctx, k, ACCENT_400, 0.15);
        paint_text(p, Pos2::new(MARGIN, y), g, "kicker", k);
    }
    if let Some(t) = &s.title {
        let g = text_galley(ctx, t, display(40.0), INK_STRONG, CONTENT_W, 48.0);
        paint_text(p, Pos2::new(MARGIN - 2.0, y + 30.0), g, "title", t);
    }
}

/// Per-pass state shared by the layout paths: the texture the image branch allocates, the
/// deck-wide body size being fitted, and the size a previous pass settled on.
struct Pass<'a> {
    keep: &'a mut Option<egui::TextureHandle>,
    fit: &'a std::cell::Cell<f32>,
    forced: Option<f32>,
}

fn paint_content(
    ui: &mut egui::Ui,
    p: &egui::Painter,
    ctx: &Context,
    s: &Slide,
    pass: &mut Pass<'_>,
) {
    let Pass {
        keep,
        fit,
        forced: forced_opt,
    } = pass;
    let forced = *forced_opt;
    let keep: &mut Option<egui::TextureHandle> = keep;
    let mut y = MARGIN + 6.0;
    if let Some(b) = &s.badge {
        let r = paint_badge(
            p,
            ctx,
            Pos2::new(PAGE.x - MARGIN, y + HUD_SIZE * 0.5),
            &b.text,
            tone_color(b.tone),
        );
        record("badge", &b.text, r);
    }
    if let Some(k) = &s.kicker {
        let g = hud_galley(ctx, k, ACCENT_400, 0.15);
        paint_text(p, Pos2::new(MARGIN, y), g, "kicker", k);
        y += HUD_SIZE + 18.0;
    }
    if let Some(t) = &s.title {
        let g = text_galley(ctx, t, display(32.0), INK_STRONG, CONTENT_W, 40.0);
        let h = g.size().y;
        paint_text(p, Pos2::new(MARGIN - 1.0, y), g, "title", t);
        y += h + 12.0;
        p.line_segment(
            [Pos2::new(MARGIN, y), Pos2::new(PAGE.x - MARGIN, y)],
            hairline(),
        );
        y += 22.0;
    }

    // Callout layout family: one bordered feature section filling the body, centred
    // between the title rule and the footer (ArtCraft pages/common.rs:212-224).
    if let Some(c) = &s.callout {
        // The callout owns the body band; stat cards keep their anchored row only
        // when the section + cards both fit, otherwise the callout takes the space.
        let floor_all = PAGE.y - 40.0 - 24.0;
        let cards_h = if s.stats.is_empty() {
            0.0
        } else {
            112.0 + 28.0
        };
        let avail_with_cards = floor_all - cards_h - y;
        let band_full = floor_all - y;
        let (head_sz, body_sz) = callout_sizes(
            ctx,
            CONTENT_W,
            &c.value,
            &c.label,
            avail_with_cards.max(band_full),
            forced,
        );
        fit.set(fit.get().min(body_sz));
        let need_sized = {
            let inner_w = CONTENT_W - 80.0;
            let hh = text_galley(
                ctx,
                &c.value,
                display(head_sz),
                INK_STRONG,
                inner_w,
                head_sz * 1.25,
            )
            .size()
            .y;
            let bh = if c.label.is_empty() {
                0.0
            } else {
                16.0 + text_galley(ctx, &c.label, inter(body_sz), MUTED, inner_w, body_sz * 1.5)
                    .size()
                    .y
            };
            hh + bh + 104.0
        };
        if need_sized <= avail_with_cards || s.stats.is_empty() {
            // Section and cards fit as stacked bands (type already fitted).
            let (h, cards_below) = if need_sized <= avail_with_cards {
                (need_sized, true)
            } else {
                (need_sized.min(avail_with_cards.max(band_full)), false)
            };
            let bottom = floor_all - if cards_below { cards_h } else { 0.0 };
            let rect = Rect::from_min_size(
                Pos2::new(MARGIN, y + ((bottom - y - h) / 2.0).max(0.0)),
                vec2(CONTENT_W, h),
            );
            paint_callout(p, ctx, rect, &c.value, &c.label, head_sz, body_sz);
            if cards_below {
                paint_stats(p, ctx, s, false, None);
            }
            return;
        }
        // Too tall to stack: the section takes the left column and the cards stand
        // in a right column, so no metric is dropped.
        let band = floor_all - y;
        let cards_w = CONTENT_W * 0.30;
        let gap = 28.0;
        let col_w = CONTENT_W - cards_w - gap;
        let (ch_sz, cb_sz) = callout_sizes(ctx, col_w, &c.value, &c.label, band, forced);
        fit.set(fit.get().min(cb_sz));
        let h = callout_height(ctx, col_w, &c.value, &c.label).min(band);
        let h = {
            let inner_w = col_w - 80.0;
            let hh = text_galley(
                ctx,
                &c.value,
                display(ch_sz),
                INK_STRONG,
                inner_w,
                ch_sz * 1.25,
            )
            .size()
            .y;
            let bh = if c.label.is_empty() {
                0.0
            } else {
                16.0 + text_galley(ctx, &c.label, inter(cb_sz), MUTED, inner_w, cb_sz * 1.5)
                    .size()
                    .y
            };
            (hh + bh + 104.0).min(h.max(hh + bh + 104.0)).min(band)
        };
        let rect = Rect::from_min_size(
            Pos2::new(MARGIN, y + ((band - h) / 2.0).max(0.0)),
            vec2(col_w, h),
        );
        paint_callout(p, ctx, rect, &c.value, &c.label, ch_sz, cb_sz);
        let n = s.stats.len().min(4) as f32;
        let card_gap = 14.0;
        let card_h = ((band - card_gap * (n - 1.0)) / n).min(112.0);
        let x = PAGE.x - MARGIN - cards_w;
        let top = y + ((band - (card_h * n + card_gap * (n - 1.0))) / 2.0).max(0.0);
        for (i, stat) in s.stats.iter().take(4).enumerate() {
            let cy = top + (card_h + card_gap) * i as f32;
            let panel = Rect::from_min_size(Pos2::new(x, cy), vec2(cards_w, card_h));
            p.rect_filled(panel, RADIUS, CONTROLS);
            p.rect_stroke(panel, RADIUS, hairline(), egui::StrokeKind::Inside);
            p.hline(
                (panel.left() + 1.0)..=(panel.right() - 1.0),
                panel.top() + 0.5,
                Stroke::new(1.0, fade(LINE_STRONG, 0.55)),
            );
            record("card", &stat.label, panel);
            let vg = text_galley(
                ctx,
                &stat.value,
                display(34.0),
                ACCENT_400,
                cards_w - 32.0,
                38.0,
            );
            let vh = vg.size().y;
            let lg = hud_galley(ctx, &stat.label, MUTED, 0.10);
            let lh = lg.size().y;
            let block = vh + 10.0 + lh;
            let ty = cy + (card_h - block) / 2.0;
            paint_text(p, Pos2::new(x + 16.0, ty), vg, "card-value", &stat.value);
            paint_text(
                p,
                Pos2::new(x + 16.0, ty + vh + 10.0),
                lg,
                "card-label",
                &stat.label,
            );
        }
        return;
    }

    let stats_top = PAGE.y - 40.0 - 24.0 - 112.0;
    let floor = if s.stats.is_empty() {
        PAGE.y - 40.0 - 24.0
    } else {
        stats_top - 28.0
    };

    // Optional image column (right 42 %): the frame fills its slot — the band between
    // the rule and the card row, grown up to 20 % past the pure aspect fit — so a
    // chart reads at full weight instead of floating in a taller well. The source is
    // centre-cropped (uv) to the frame's aspect at paint time.
    let img = s.image.as_ref().map(|path| {
        let im = image::open(path).unwrap_or_else(|e| {
            eprintln!("deckgen: IMG {}: {e}", path.display());
            std::process::exit(1);
        });
        let slot_w = CONTENT_W * 0.50 - 8.0;
        let band = (floor - y - 26.0).max(40.0);
        let aspect_h = slot_w * im.height() as f32 / im.width() as f32;
        let h = band.min(aspect_h * 1.2);
        let rect = Rect::from_min_size(
            Pos2::new(
                MARGIN + CONTENT_W - slot_w,
                y + (band - h).max(0.0) / 2.0,
            ),
            vec2(slot_w, h),
        );
        (im, rect)
    });
    let body_w = if img.is_some() {
        CONTENT_W * 0.50
    } else {
        CONTENT_W
    };

    let texts: Vec<&str> = s
        .paragraphs
        .iter()
        .chain(s.bullets.iter())
        .map(String::as_str)
        .collect();
    // Hero layout: one big number (per strategyu.co layout #1, "the big
    // number") with claims in a right column. Triggered by a HERO: directive.
    if let (Some(h), true) = (&s.hero, img.is_none()) {
        p.rect_filled(
            Rect::from_min_size(Pos2::new(MARGIN, y), vec2(32.0, 3.0)),
            0.0,
            ACCENT,
        );
        y += 34.0;
        let colw = CONTENT_W * 0.42;
        let x1 = PAGE.x - MARGIN - colw;
        // Hero number with wrapped label under it (left ~45%).
        let hy = y + 10.0;
        // The hero number takes whatever the claim column leaves: 110 pt when it fits,
        // smaller when the claims at deck body size need the height.
        let hg = text_galley(
            ctx,
            &h.value,
            display(96.0),
            ACCENT_400,
            CONTENT_W * 0.44,
            104.0,
        );
        let hh = hg.size().y;
        paint_text(
            p,
            Pos2::new(MARGIN - 3.0, hy),
            hg.clone(),
            "hero-value",
            &h.value,
        );
        let lg = text_galley(ctx, &h.label, inter(15.0), MUTED, CONTENT_W * 0.42, 22.0);
        paint_text(
            p,
            Pos2::new(MARGIN, hy + hh + 14.0),
            lg,
            "hero-label",
            &h.label,
        );
        // The claim column must clear the card row: it ends at the card band, and its
        // gaps compress to fit rather than running over the cards.
        let col_floor = if s.stats.is_empty() {
            PAGE.y - 40.0 - 24.0
        } else {
            PAGE.y - 40.0 - 24.0 - 112.0 - 20.0
        };
        let blocks: Vec<(Option<&str>, &str)> = texts
            .iter()
            .map(|t| match t.split_once(": ") {
                Some((hdr, claim)) => (Some(hdr), claim),
                None => (None, *t),
            })
            .collect();
        let heights: Vec<f32> = blocks
            .iter()
            .map(|(hdr, claim)| {
                let hh = if hdr.is_some() { 34.0 } else { 0.0 };
                hh + text_galley(
                    ctx,
                    claim,
                    inter(CALLOUT_BODY),
                    MUTED,
                    colw,
                    CALLOUT_BODY * 1.45,
                )
                .size()
                .y
            })
            .collect();
        let gaps = blocks.len().saturating_sub(1) as f32;
        // Fit the column inside [y, col_floor]: shrink the leading gaps first, then
        // (if the text alone cannot fit) fall back to the smallest body step that does.
        let avail = col_floor - y;
        let mut body_sz = forced.unwrap_or(CALLOUT_BODY).min(CALLOUT_BODY);
        let mut hs = heights.clone();
        while hs.iter().sum::<f32>() + 6.0 * gaps > avail && body_sz > 15.0 {
            body_sz -= 1.0;
            hs = blocks
                .iter()
                .map(|(hdr, claim)| {
                    let hh = if hdr.is_some() { 34.0 } else { 0.0 };
                    hh + text_galley(ctx, claim, inter(body_sz), MUTED, colw, body_sz * 1.45)
                        .size()
                        .y
                })
                .collect();
        }
        let total2: f32 = hs.iter().sum();
        let gap2 = if gaps > 0.0 {
            ((avail - total2) / gaps).clamp(6.0, 16.0)
        } else {
            0.0
        };
        let mut yy = y;
        for ((hdr, claim), h) in blocks.iter().zip(hs.iter()) {
            if let Some(hdr) = hdr {
                let g = hud_galley(ctx, hdr, ACCENT_400, 0.15);
                paint_text(p, Pos2::new(x1, yy), g, "claim-header", hdr);
                let g = text_galley(ctx, claim, inter(body_sz), MUTED, colw, body_sz * 1.45);
                paint_text(p, Pos2::new(x1, yy + 34.0), g, "claim", claim);
            } else {
                let g = text_galley(ctx, claim, inter(body_sz), MUTED, colw, body_sz * 1.45);
                paint_text(p, Pos2::new(x1, yy), g, "claim", claim);
            }
            yy += h + gap2;
        }
        paint_stats(p, ctx, s, false, None);
        return;
    }
    // Statement mode: unmarked claims; a "HEADER: claim" bullet becomes a
    // two-column evidence/interpretation pair with a tracked label (per
    // theanalystacademy.com/two-column-slide-layout: columns must relate).
    let statement = img.is_none() && !texts.is_empty() && texts.iter().any(|t| t.contains(": "));
    if statement {
        let mut cols: Vec<(Option<String>, String)> = vec![];
        for b in &texts {
            match b.split_once(": ") {
                Some((h, c)) => cols.push((Some(h.to_string()), c.to_string())),
                None => cols.push((None, b.to_string())),
            }
        }
        fit.set(fit.get().min(21.0f32.min(floor - y)));
        let sz = forced.unwrap_or(21.0).min(21.0);
        let mut y0 = y;
        // `chunks`, not `chunks_exact`: an odd final claim must render as its own
        // full-width row rather than vanish (`chunks_exact` would drop it).
        #[allow(unknown_lints)]
        let pairs: Vec<_> = cols.chunks(2).collect();
        p.rect_filled(
            Rect::from_min_size(Pos2::new(MARGIN, y0), vec2(32.0, 3.0)),
            0.0,
            ACCENT,
        );
        y0 += 22.0;
        let (total, colw, vg) = {
            let mut total = 0.0f32;
            let colw = (CONTENT_W - 44.0) / 2.0;
            let mut vg = Vec::new();
            for pair in &pairs {
                if pair.len() == 2 {
                    let h0 = text_galley(ctx, &pair[0].1, inter(sz), INK_STRONG, colw, sz * 1.5)
                        .size()
                        .y
                        + 34.0;
                    let h1 = text_galley(ctx, &pair[1].1, inter(sz), MUTED, colw, sz * 1.5)
                        .size()
                        .y
                        + 34.0;
                    vg.push(h0.max(h1));
                } else {
                    vg.push(
                        text_galley(ctx, &pair[0].1, inter(sz), INK_STRONG, CONTENT_W, sz * 1.5)
                            .size()
                            .y,
                    );
                }
                total += *vg.last().unwrap() + 26.0;
            }
            (total, colw, vg)
        };
        let start = y0 + ((floor - y0 - total).max(0.0) / 2.0).min(80.0);
        let mut yy = start;
        for (i, pair) in pairs.iter().enumerate() {
            if pair.len() == 2 {
                for (j, (hdr, claim)) in pair.iter().enumerate() {
                    let x = MARGIN + j as f32 * (colw + 44.0);
                    if let Some(h) = hdr {
                        let hg = hud_galley(ctx, h, ACCENT_400, 0.15);
                        paint_text(p, Pos2::new(x, yy), hg, "claim-header", h);
                    }
                    let g = text_galley(
                        ctx,
                        claim,
                        inter(sz),
                        if j == 1 { MUTED } else { INK_STRONG },
                        colw,
                        sz * 1.5,
                    );
                    paint_text(p, Pos2::new(x, yy + 34.0), g, "claim", claim);
                }
            } else {
                let g = text_galley(ctx, &pair[0].1, inter(sz), INK_STRONG, CONTENT_W, sz * 1.5);
                paint_text(p, Pos2::new(MARGIN, yy), g, "claim", &pair[0].1);
            }
            yy += vg[i] + 26.0;
        }
        // The statement family closes with a banded row, not a card row.
        paint_stats_inner(p, ctx, s, img.is_some(), Some(yy + 28.0), true);
        return;
    }
    // List path: paragraphs and bullets in one flow, deck-wide fitted size.
    let items: Vec<(&str, bool)> = s
        .paragraphs
        .iter()
        .map(|t| (t.as_str(), false))
        .chain(s.bullets.iter().map(|t| (t.as_str(), true)))
        .collect();
    let gap = 14.0;
    let fitted = [30.0f32, 27.0, 24.0, 22.0, 20.0, 18.0, 16.0, 15.0]
        .into_iter()
        .find(|&sz| {
            let mut h = 0.0;
            for (t, bullet) in &items {
                let w = if *bullet { body_w - 24.0 } else { body_w };
                h += text_galley(ctx, t, inter(sz), INK, w, sz * 1.5).size().y + gap;
            }
            y + h <= floor
        })
        .unwrap_or(15.0);
    fit.set(fit.get().min(fitted.min(30.0)));
    let size = forced.unwrap_or(fit.get().min(30.0));
    let used: f32 = items
        .iter()
        .map(|(t, bullet)| {
            let w = if *bullet { body_w - 24.0 } else { body_w };
            text_galley(ctx, t, inter(size), INK, w, size * 1.5)
                .size()
                .y
        })
        .sum();
    let gaps = items.len() + 1;
    let gap = gap.max(((floor - y - used) / gaps as f32).min(gap * 1.3));
    y += gap;
    let mut copy_bottom = y;
    for (t, bullet) in items.iter() {
        let w = if *bullet { body_w - 24.0 } else { body_w };
        let g = text_galley(ctx, t, inter(size), INK, w, size * 1.5);
        let h = g.size().y;
        if *bullet {
            let m = size * 0.28;
            p.rect_filled(
                Rect::from_min_size(Pos2::new(MARGIN, y + size * 0.55 - m / 2.0), vec2(m, m)),
                1.5,
                ACCENT,
            );
            paint_text(p, Pos2::new(MARGIN + 24.0, y), g, "bullet", t);
        } else {
            paint_text(p, Pos2::new(MARGIN, y), g, "para", t);
        }
        copy_bottom = y + h;
        y += h + gap;
    }
    if let Some(d) = &s.divider {
        let dy = if s.stats.is_empty() {
            PAGE.y - 40.0 - 32.0
        } else {
            PAGE.y - 40.0 - 24.0 - 112.0 - 26.0
        };
        // Span the text column only: an image slide's right panel keeps its own frame.
        let (dl, dw) = if img.is_some() {
            (MARGIN, CONTENT_W * 0.50)
        } else {
            (MARGIN, CONTENT_W)
        };
        paint_divider(p, ctx, dy, dl, dw, d);
    }
    // Under an image column the copy is the shorter column, so the card row follows the
    // last line of copy (not the trailing gap) and only falls back to the anchored band.
    paint_stats(p, ctx, s, img.is_some(), Some(copy_bottom + 26.0));

    // Image column: hairline frame.
    if let Some((im, rect)) = img {
        let cimg = egui::ColorImage::from_rgba_unmultiplied(
            [im.width() as usize, im.height() as usize],
            im.to_rgba8().as_raw(),
        );
        let tex = ctx.load_texture("deck-img", cimg, egui::TextureOptions::LINEAR);
        let id = tex.id();
        *keep = Some(tex);
        record("image", "IMG", rect);
        // Cover-fit: centre-crop the source to the frame's aspect so the chart fills
        // the frame instead of letterboxing inside it.
        let src_a = im.width() as f32 / im.height() as f32;
        let frame_a = rect.width() / rect.height();
        let uv = if src_a > frame_a {
            let f = frame_a / src_a;
            Rect::from_min_max(Pos2::new((1.0 - f) / 2.0, 0.0), Pos2::new((1.0 + f) / 2.0, 1.0))
        } else {
            let f = src_a / frame_a;
            Rect::from_min_max(Pos2::new(0.0, (1.0 - f) / 2.0), Pos2::new(1.0, (1.0 + f) / 2.0))
        };
        p.image(id, rect, uv, Color32::WHITE);
        p.rect_stroke(rect, RADIUS, hairline(), egui::StrokeKind::Inside);
    }
    ui.interact(
        Rect::from_min_size(Pos2::ZERO, PAGE),
        egui::Id::new("page"),
        Sense::hover(),
    );
}

/// Stat cards: big display numbers with mono labels, on wash panels,
/// anchored above the footer (right-aligned under the image column).
fn paint_stats(p: &egui::Painter, ctx: &Context, s: &Slide, has_img: bool, want_top: Option<f32>) {
    paint_stats_inner(p, ctx, s, has_img, want_top, false)
}

/// `banded` renders the row as one raised panel with hairline column dividers (the
/// statement family's closing element); the default renders separate cards.
fn paint_stats_inner(
    p: &egui::Painter,
    ctx: &Context,
    s: &Slide,
    has_img: bool,
    want_top: Option<f32>,
    banded: bool,
) {
    if !s.stats.is_empty() {
        // A slide whose text ended early hangs its card row right under the copy; the
        // band stays anchored when the copy already reaches it (never below the footer).
        let anchored = PAGE.y - 40.0 - 24.0 - 112.0;
        // The wide closing band always sits on the shared closing line (bottom 531 like
        // every card row); ordinary cards may hang under the copy instead.
        let y = want_top.map_or(anchored, |t| {
            if s.stats.len() == 1 && has_img {
                anchored // the wide band closes the page on the shared line
            } else {
                t.min(anchored)
            }
        });
        let cols = s.stats.len().min(4);
        let gap = 14.0;
        // The row always spans the full content width: two cards are half the width each,
        // not two small cards plus a void; one card is the full-width band.
        let w = (CONTENT_W - gap * (cols - 1) as f32) / cols as f32;
        if banded {
            let panel = Rect::from_min_size(Pos2::new(MARGIN, y), vec2(CONTENT_W, 112.0));
            p.rect_filled(panel, RADIUS, CONTROLS);
            p.rect_stroke(panel, RADIUS, hairline(), egui::StrokeKind::Inside);
            p.hline(
                (panel.left() + 1.0)..=(panel.right() - 1.0),
                panel.top() + 0.5,
                Stroke::new(1.0, fade(LINE_STRONG, 0.55)),
            );
            let colw = CONTENT_W / cols as f32;
            for (i, stat) in s.stats.iter().take(4).enumerate() {
                let cx = MARGIN + colw * i as f32;
                if i > 0 {
                    p.vline(
                        cx,
                        panel.top() + 14.0..=panel.bottom() - 14.0,
                        Stroke::new(1.0, fade(LINE, 1.0)),
                    );
                }
                let vg = text_galley(ctx, &stat.value, display(34.0), ACCENT_400, colw - 32.0, 38.0);
                paint_text(p, Pos2::new(cx + 16.0, y + 22.0), vg, "card-value", &stat.value);
                let lg = hud_galley(ctx, &stat.label, MUTED, 0.10);
                paint_text(p, Pos2::new(cx + 16.0, y + 76.0), lg, "card-label", &stat.label);
            }
            return;
        }
        for (i, stat) in s.stats.iter().take(4).enumerate() {
            let row_w = w * cols as f32 + gap * (cols - 1) as f32;
            // With an image column the cards sit under the text, not under the image:
            // a card floating at the page edge far below the copy reads as a gap.
            let _ = has_img;
            let x0 = MARGIN;
            // One card, one band: the row spans the columns the slide actually uses so the
            // card reads as the last line of the composition rather than a stray chip.
            // A lone card on an image slide spans the full content width so it reads as the
            // closing band under both columns instead of a chip with a void beside it.
            // A lone stat on a wide slide becomes one horizontal band: the number and its
            // label share the row, so the card has a value at both ends instead of a void.
            // Full card height, so it closes the page on the same rhythm as a card row.
            let wide = s.stats.len() == 1 && has_img;
            let card_w = if wide { CONTENT_W } else { w };
            let card_h = 112.0;
            let _ = row_w;
            let x = x0 + (w + gap) * i as f32;
            let panel = Rect::from_min_size(Pos2::new(x, y), vec2(card_w, card_h));
            // ArtCraft's raised-surface treatment: CONTROLS over the page, a hairline
            // border, and a brighter top edge (the hover state's LINE_STRONG).
            p.rect_filled(panel, RADIUS, CONTROLS);
            p.rect_stroke(panel, RADIUS, hairline(), egui::StrokeKind::Inside);
            p.hline(
                (panel.left() + 1.0)..=(panel.right() - 1.0),
                panel.top() + 0.5,
                Stroke::new(1.0, fade(LINE_STRONG, 0.55)),
            );
            record("card", &stat.label, panel);
            if wide {
                let vg = text_galley(ctx, &stat.value, display(34.0), ACCENT_400, 200.0, 38.0);
                paint_text(
                    p,
                    Pos2::new(x + 20.0, y + 19.0),
                    vg,
                    "card-value",
                    &stat.value,
                );
                let lg = hud_galley(ctx, &stat.label, MUTED, 0.10);
                let lw = lg.size().x;
                paint_text(
                    p,
                    Pos2::new(x + card_w - 20.0 - lw, y + 31.0),
                    lg,
                    "card-label",
                    &stat.label,
                );
            } else {
                let vg = text_galley(
                    ctx,
                    &stat.value,
                    display(34.0),
                    ACCENT_400,
                    card_w - 24.0,
                    38.0,
                );
                paint_text(
                    p,
                    Pos2::new(x + 16.0, y + 20.0),
                    vg,
                    "card-value",
                    &stat.value,
                );
                let lg = hud_galley(ctx, &stat.label, MUTED, 0.10);
                paint_text(
                    p,
                    Pos2::new(x + 16.0, y + 76.0),
                    lg,
                    "card-label",
                    &stat.label,
                );
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::spec;

    /// One crowded slide sets the size for the whole deck: the fit is deck-wide, so adding
    /// copy to a single slide must shrink every slide's body, and removing it must restore.
    #[test]
    fn one_crowded_slide_sets_the_deck_body_size() {
        let light = "# D\n---\n# A\n- One short line.\n---\n# B\n- Another short line.\n";
        let crowded = format!(
            "{light}---\n# C\n- {}\n- {}\n- {}\n",
            "long body copy that wraps across the column ".repeat(3),
            "more long body copy that wraps across the column ".repeat(3),
            "still more long body copy that wraps across the column ".repeat(3),
        );
        let p = std::path::Path::new(".");
        render_deck(&spec::parse(light, p));
        let roomy = deck_body_size();
        render_deck(&spec::parse(&crowded, p));
        let squeezed = deck_body_size();
        assert!(roomy > 0.0 && squeezed > 0.0, "both decks have body slides");
        assert!(
            squeezed < roomy,
            "crowding one slide must shrink the deck body ({squeezed} vs {roomy})"
        );
    }

    /// A crowded hero slide must not push its claim column into the card row: the
    /// column compresses (and steps down in size) to clear the cards.
    #[test]
    fn hero_claims_clear_the_card_row() {
        let deck = spec::parse(
            "# D\n---\n# Hero\nKICKER: K\nHERO: 1.00 | CONVERGED SCORE - AGAINST A 0.65 TARGET, IN 2 OF 6 ROUNDS\nTHE FORCED RUN: The same loop scored 0.1536 against an impossible 1.01 target and kept going for six more rounds of argument.\n- A benchmark that only shows wins is marketing, so this deck prints both scores side by side.\nSTAT: 0.15 | FORCED SCORE\nSTAT: 392 | TOKENS SPENT\n",
            std::path::Path::new("."),
        );
        render_deck(&deck);
        let lay = layout();
        let page = &lay[1];
        let cards: Vec<&LayoutItem> = page.iter().filter(|i| i.kind == "card").collect();
        assert_eq!(cards.len(), 2, "cards survive the hero");
        let card_top = cards[0].y;
        for it in page
            .iter()
            .filter(|i| i.kind == "claim" || i.kind == "claim-header")
        {
            assert!(
                it.y + it.h <= card_top - 4.0,
                "{} '{}' bottom {:.1} runs into the card row at {:.1}",
                it.kind,
                it.label,
                it.y + it.h,
                card_top
            );
        }
    }

    /// The title block is centred in the space above the meta anchor: the void above
    /// the accent bar equals the void between the subtitle and the meta line, so the
    /// empty areas read as distributed, not accidental.
    #[test]
    fn title_block_is_centred_above_the_meta() {
        let deck = spec::parse(
            "# Deck\nKICKER: K\nSUBTITLE: A subtitle that wraps onto a second line for good measure\nMETA: META\n---\n# Slide\n- one\n",
            std::path::Path::new("."),
        );
        render_deck(&deck);
        let lay = layout();
        let page = &lay[0];
        let kicker = page.iter().find(|i| i.kind == "kicker").unwrap();
        let subtitle = page.iter().find(|i| i.kind == "subtitle").unwrap();
        let meta = page.iter().find(|i| i.kind == "meta").unwrap();
        let above = kicker.y - 48.0; // the accent bar sits 48 pt above the kicker
        let below = meta.y - (subtitle.y + subtitle.h);
        assert!(
            (above - below).abs() < 1.0,
            "void above the block {above:.1} != void below it {below:.1}"
        );
    }

    /// The divider must record a rule that spans only the text column on an image slide,
    /// so it never runs under the image panel.
    #[test]
    fn divider_stays_out_of_the_image_column() {
        let deck = spec::parse(
            "# D\n---\n# Slide\nKICKER: K\n- one item here\n- two item here\nDIVIDER: RENDERED OFFLINE\nIMG: ../../ui/deck/shots/chart.jpg\nSTAT: 0 | BROWSERS\n",
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")),
        );
        render_deck(&deck);
        let page = &layout()[1];
        let rule = page
            .iter()
            .find(|i| i.kind == "divider")
            .expect("divider recorded");
        let label = page
            .iter()
            .find(|i| i.kind == "divider-label")
            .expect("divider label");
        assert!((rule.x - MARGIN).abs() < 0.5);
        // Text column is half the content width; the rule must not reach the image slot.
        assert!(
            rule.w <= CONTENT_W * 0.50 + 0.5,
            "rule spans {} of {}",
            rule.w,
            CONTENT_W
        );
        assert!(
            (label.y + label.h / 2.0 - rule.y).abs() < 2.0,
            "label centred on the rule"
        );
    }

    /// The image frame fills its band (up to the cover-fit cap) rather than sitting at
    /// the pure aspect height, and its bottom still clears the card row.
    #[test]
    fn image_frame_fills_its_band_and_clears_the_cards() {
        let img_path =
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../ui/deck/shots/chart.jpg");
        let im = image::open(&img_path).expect("chart fixture");
        let deck = spec::parse(
            "# D\n---\n# Slide\nKICKER: K\n- one item here\n- two item here\nIMG: ../../ui/deck/shots/chart.jpg\nSTAT: 0 | BROWSERS\n",
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")),
        );
        render_deck(&deck);
        let page = &layout()[1];
        let img = page.iter().find(|i| i.kind == "image").expect("image recorded");
        let card = page.iter().find(|i| i.kind == "card").expect("card recorded");
        let aspect_h = img.w * im.height() as f32 / im.width() as f32;
        assert!(
            img.h > aspect_h + 1.0,
            "frame h {:.1} should exceed the aspect fit {:.1} (cover-fit fills the band)",
            img.h,
            aspect_h
        );
        assert!(
            img.h <= aspect_h * 1.2 + 0.5,
            "frame h {:.1} exceeds the 20% cover cap {:.1}",
            img.h,
            aspect_h * 1.2
        );
        assert!(
            img.y + img.h <= card.y - 20.0,
            "image bottom {:.1} runs toward the card row at {:.1}",
            img.y + img.h,
            card.y
        );
    }

    /// Cards are raised surfaces: CONTROLS fill over the page background.
    #[test]
    fn callout_cards_use_the_raised_surface() {
        let deck = spec::parse(
            "# D\n---\n# S\nKICKER: K\n- a\n- b\nSTAT: 1 | ONE\nSTAT: 2 | TWO\n",
            std::path::Path::new("."),
        );
        render_deck(&deck);
        let lay = layout();
        let cards: Vec<&LayoutItem> = lay[1].iter().filter(|i| i.kind == "card").collect();
        assert_eq!(cards.len(), 2);
        assert!(
            (cards[0].y - cards[1].y).abs() < 0.5,
            "row shares a baseline"
        );
    }

    /// A tall callout plus stat cards must not lose the cards: they stack in a right
    /// column, and nothing overlaps.
    #[test]
    fn callout_and_cards_coexist_without_overlap() {
        let deck = spec::parse(
            "# D\n---\n# Deck\nKICKER: K\nCALLOUT: Any repo that emits JSON can emit a deck | Reports, benchmarks and architecture reviews render from the same file, regenerated by an agent with no browser and no network and no layout code at all.\nSTAT: 1 | DESIGN SYSTEM\nSTAT: 3 | OFL TYPEFACES\nSTAT: 6 | PAGES\n",
            std::path::Path::new("."),
        );
        render_deck(&deck);
        let page = &layout()[1];
        let kinds: Vec<&str> = page.iter().map(|i| i.kind).collect();
        assert!(
            kinds.contains(&"callout-heading"),
            "callout rendered: {kinds:?}"
        );
        assert!(kinds.contains(&"callout-body"));
        let cards: Vec<&LayoutItem> = page.iter().filter(|i| i.kind == "card").collect();
        assert_eq!(cards.len(), 3, "every card survives the callout: {kinds:?}");
        // No two content rects may intersect (the checker's rule, asserted here).
        let content: Vec<&LayoutItem> = page
            .iter()
            .filter(|i| {
                !i.kind.starts_with("card-")
                    && i.kind != "footer"
                    && i.kind != "callout"
                    && i.kind != "card"
            })
            .collect();
        for (i, a) in content.iter().enumerate() {
            for b in content.iter().skip(i + 1) {
                let ov_x = (a.x + a.w).min(b.x + b.w) - a.x.max(b.x);
                let ov_y = (a.y + a.h).min(b.y + b.h) - a.y.max(b.y);
                assert!(
                    !(ov_x > 2.0 && ov_y > 2.0),
                    "{} {:?} overlaps {} {:?}",
                    a.kind,
                    a.label,
                    b.kind,
                    b.label
                );
            }
        }
        // Cards stand in a column: one left edge, one width.
        assert!(cards.iter().all(|c| (c.x - cards[0].x).abs() < 0.5));
        assert!(cards.iter().all(|c| (c.w - cards[0].w).abs() < 0.5));
        // Each card's label sits below its value inside the panel.
        for c in &cards {
            let v = page.iter().find(|i| i.kind == "card-value").unwrap();
            let l = page.iter().find(|i| i.kind == "card-label").unwrap();
            assert!(v.y + v.h <= l.y + 0.5, "value above label");
            assert!(l.y + l.h <= c.y + c.h + 0.5, "label inside panel");
        }
    }

    /// The layout collector is what `check_deck.py` gates on: it must emit one
    /// record per painted rect, deduped, with geometry inside the page.
    #[test]
    fn layout_collector_reports_page_geometry() {
        let deck = spec::parse(
            "# Deck\nKICKER: K\nBADGE: OK | accent\nTAG: RUST\n---\n# Slide\nKICKER: S\n- alpha item one\n- beta item two\nSTAT: 4 | AGENTS\nSTAT: 2 | ROUNDS\n---\n# Claims\nKICKER: C\n- Left header: left claim\n- Right header: right claim\n---\n# Hero\nHERO: 1.00 | converged\n- the forced run: 0.15\n",
            std::path::Path::new("."),
        );
        let pages = render_deck(&deck);
        let layout = layout();
        assert_eq!(pages.len(), 4);
        assert_eq!(layout.len(), 4, "one rect list per page");
        for (i, page) in layout.iter().enumerate() {
            assert!(!page.is_empty(), "page {} recorded nothing", i + 1);
            for it in page {
                assert!(it.w > 0.0 && it.h > 0.0, "degenerate rect {:?}", it.label);
                assert!(it.x >= 0.0 && it.y >= 0.0, "off-page rect {:?}", it.label);
                assert!(
                    it.x + it.w <= PAGE.x + 0.5,
                    "{:?} overflows width",
                    it.label
                );
                assert!(
                    it.y + it.h <= PAGE.y + 0.5,
                    "{:?} overflows height",
                    it.label
                );
            }
            // No exact duplicates: kittest's second paint pass must not double-record.
            let mut seen = std::collections::HashSet::new();
            for it in page {
                let key = (
                    it.kind,
                    it.x.to_bits(),
                    it.y.to_bits(),
                    it.w.to_bits(),
                    it.h.to_bits(),
                );
                assert!(
                    seen.insert(key),
                    "duplicate rect recorded: {} {:?}",
                    it.kind,
                    it.label
                );
            }
        }
        // The directives reach the collector under their own kinds.
        let kinds: Vec<&str> = layout.iter().flatten().map(|i| i.kind).collect();
        for want in [
            "tag",
            "badge",
            "kicker",
            "title",
            "bullet",
            "claim-header",
            "claim",
            "card",
            "hero-value",
        ] {
            assert!(
                kinds.contains(&want),
                "collector never recorded a `{want}` rect: {kinds:?}"
            );
        }
        // Cards on one page share a baseline.
        let cards: Vec<&LayoutItem> = layout[1].iter().filter(|i| i.kind == "card").collect();
        assert_eq!(cards.len(), 2);
        assert_eq!(
            cards[0].y.to_bits(),
            cards[1].y.to_bits(),
            "cards must share a top edge"
        );
    }
}
