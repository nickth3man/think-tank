//! ArtCraft design tokens, transcribed from `artcraft-native/src/theme.rs`
//! (github.com/storytold/artcraft, MIT OR Apache-2.0) and the webapp's
//! `base.css` custom properties. Values only — no egui widget code copied.
//! Fonts are the three OFL-1.1 variable faces shipped beside this file.
//!
//! The palette is mirrored whole, not pruned to current use: an unused token is still the
//! documented value of an ArtCraft surface a future slide may adopt, and dropping it would
//! silently break the path back to `theme.rs`.
#![allow(dead_code)]

use egui::epaint::text::VariationCoords;
use egui::{
    text::TextFormat, Color32, CornerRadius, FontData, FontDefinitions, FontFamily, FontId,
    FontTweak, Stroke,
};
use std::sync::Arc;

// --- Colour tokens (theme.rs:21-70) -------------------------------------

pub const BG: Color32 = Color32::from_rgb(0x12, 0x13, 0x16);
pub const PANEL: Color32 = Color32::from_rgb(0x10, 0x10, 0x14);
pub const INK: Color32 = Color32::from_rgb(0xf2, 0xf1, 0xee);
pub const INK_STRONG: Color32 = Color32::WHITE;
pub const MUTED: Color32 = Color32::from_rgba_unmultiplied_const(0xf2, 0xf1, 0xee, 153);
pub const FAINT: Color32 = Color32::from_rgba_unmultiplied_const(0xf2, 0xf1, 0xee, 102);
pub const LINE: Color32 = Color32::from_rgba_unmultiplied_const(0xff, 0xff, 0xff, 38);
pub const ACCENT: Color32 = Color32::from_rgb(0x2d, 0x81, 0xff);
pub const ACCENT_400: Color32 = Color32::from_rgb(0x59, 0xa7, 0xff);
/// `ui-accent-ink`: blue text and focus rings.
pub const ACCENT_INK: Color32 = Color32::from_rgb(0x74, 0xaa, 0xff);
/// `ui-controls`: the sidebar, the prompt box and toolbar buttons.
pub const CONTROLS: Color32 = Color32::from_rgb(0x1e, 0x1f, 0x22);
/// The window chrome behind the content panel.
pub const CHROME: Color32 = Color32::from_rgb(0x0a, 0x0a, 0x0c);
/// `ui-sunken`: wells and inputs.
pub const SUNKEN: Color32 = Color32::from_rgb(0x06, 0x06, 0x07);
/// `base-fg/50`: idle toolbar icons.
pub const DIM: Color32 = Color32::from_rgba_unmultiplied_const(0xf2, 0xf1, 0xee, 128);
/// `base-fg/40`: outlined buttons and corner marks.
pub const LINE_STRONG: Color32 = Color32::from_rgba_unmultiplied_const(0xf2, 0xf1, 0xee, 102);
/// `white/5`: quiet fills.
pub const WASH: Color32 = Color32::from_rgba_unmultiplied_const(0xff, 0xff, 0xff, 13);
/// `white/10`: hovered menu rows.
pub const WASH_HOVER: Color32 = Color32::from_rgba_unmultiplied_const(0xff, 0xff, 0xff, 26);
/// `red-400`: failure text.
pub const BAD: Color32 = Color32::from_rgb(0xf8, 0x71, 0x71);
/// `red`: destructive fills.
pub const DANGER: Color32 = Color32::from_rgb(0xd3, 0x32, 0x42);
/// The "BETA" / "NEW" sidebar badges.
pub const BADGE_BETA: Color32 = Color32::from_rgb(0xff, 0xc1, 0x4d);

/// `c` at `a` (0-1) of its opacity (theme.rs `fade`).
pub fn fade(c: Color32, a: f32) -> Color32 {
    let k = a.clamp(0.0, 1.0);
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), ((c.a() as f32) * k).round() as u8)
}

/// The landing page's bordered section: 4/255 ink fill (common.rs:217).
pub const SECTION_FILL: Color32 = Color32::from_rgba_unmultiplied_const(0xf2, 0xf1, 0xee, 4);
/// ...and its 51/255 ink stroke (common.rs:217).
pub const SECTION_STROKE: Color32 = Color32::from_rgba_unmultiplied_const(0xf2, 0xf1, 0xee, 51);

/// The shadow under menus, modals and toasts (theme.rs `shadow`).
pub fn shadow() -> egui::epaint::Shadow {
    egui::epaint::Shadow {
        offset: [0, 8],
        blur: 24,
        spread: 0,
        color: Color32::from_black_alpha(140),
    }
}

// --- Type + shape tokens -------------------------------------------------

/// 3 px on anything pressable, square on anything large (theme.rs:1-5,76).
pub const RADIUS: CornerRadius = CornerRadius::same(3);
/// Height of toolbar controls (`py-1.5` + 14 px text + hairline).
pub const CONTROL_H: f32 = 34.0;
pub const HUD_SIZE: f32 = 11.0;

/// Fonts bundled from `artcraft-native/assets/fonts` (OFL-1.1, licences beside them).
pub fn install_fonts(ctx: &egui::Context) {
    const INTER: &[u8] = include_bytes!("../assets/fonts/Inter-Variable.ttf");
    const ARCHIVO: &[u8] = include_bytes!("../assets/fonts/Archivo-Variable.ttf");
    const GEIST_MONO: &[u8] = include_bytes!("../assets/fonts/GeistMono-Variable.ttf");
    let mut fonts = FontDefinitions::default();
    let fallback = fonts
        .families
        .get(&FontFamily::Proportional)
        .cloned()
        .unwrap_or_default();
    type Face<'a> = (
        &'a str,
        &'static [u8],
        &'a [(&'static [u8; 4], f32)],
        FontFamily,
    );
    let faces: [Face<'_>; 7] = [
        (
            "Inter",
            INTER,
            &[(b"wght", 400.0), (b"opsz", 14.0)],
            FontFamily::Proportional,
        ),
        (
            "Inter-Medium",
            INTER,
            &[(b"wght", 500.0), (b"opsz", 14.0)],
            FontFamily::Name("medium".into()),
        ),
        (
            "Inter-SemiBold",
            INTER,
            &[(b"wght", 600.0), (b"opsz", 14.0)],
            FontFamily::Name("semibold".into()),
        ),
        (
            "Archivo-Display",
            ARCHIVO,
            &[(b"wght", 620.0), (b"wdth", 118.0)],
            FontFamily::Name("display".into()),
        ),
        (
            "GeistMono",
            GEIST_MONO,
            &[(b"wght", 400.0)],
            FontFamily::Monospace,
        ),
        (
            "GeistMono-Medium",
            GEIST_MONO,
            &[(b"wght", 500.0)],
            FontFamily::Name("mono-med".into()),
        ),
        (
            "GeistMono-SemiBold",
            GEIST_MONO,
            &[(b"wght", 650.0)],
            FontFamily::Name("mono-bold".into()),
        ),
    ];
    for (name, bytes, coords, family) in faces {
        let coords: Vec<(&str, f32)> = coords
            .iter()
            .map(|(t, v)| (std::str::from_utf8(*t).unwrap(), *v))
            .collect();
        let tweak = FontTweak {
            coords: VariationCoords::new(coords),
            ..Default::default()
        };
        fonts.font_data.insert(
            name.to_owned(),
            Arc::new(FontData::from_static(bytes).tweak(tweak)),
        );
        let mut stack = vec![name.to_owned()];
        stack.extend(fallback.iter().cloned());
        fonts.families.insert(family, stack);
    }
    ctx.set_fonts(fonts);
}

pub fn display(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name("display".into()))
}
pub fn inter(size: f32) -> FontId {
    FontId::new(size, FontFamily::Proportional)
}
pub fn mono_med(size: f32) -> FontId {
    FontId::new(size, FontFamily::Name("mono-med".into()))
}
pub fn mono_bold() -> FontId {
    FontId::new(HUD_SIZE, FontFamily::Name("mono-bold".into()))
}

/// ArtCraft `widgets::caps` (widgets.rs:12-15): `text` upper-cased in `family` with
/// `spacing` points between letters.
pub fn caps_galley(
    ctx: &egui::Context,
    text: &str,
    size: f32,
    font: FontId,
    spacing: f32,
    color: Color32,
) -> std::sync::Arc<egui::Galley> {
    let font = FontId::new(size, font.family.clone());
    let format = TextFormat {
        font_id: font,
        color,
        extra_letter_spacing: spacing,
        ..Default::default()
    };
    let job = egui::text::LayoutJob::single_section(text.to_uppercase(), format);
    ctx.fonts_mut(|f| f.layout_job(job))
}

/// Hairline stroke, 1 pt at page scale (theme.rs `hairline`, LINE).
pub fn hairline() -> Stroke {
    Stroke::new(1.0, LINE)
}

/// Tracked uppercase HUD label (`.hud-label`: Geist Mono 500, 0.15 em apart).
pub fn hud_galley(
    ctx: &egui::Context,
    text: &str,
    color: Color32,
    spacing_em: f32,
) -> std::sync::Arc<egui::Galley> {
    let format = TextFormat {
        font_id: mono_med(HUD_SIZE),
        color,
        extra_letter_spacing: HUD_SIZE * spacing_em,
        ..Default::default()
    };
    let mut job = egui::text::LayoutJob::default();
    job.append(&text.to_uppercase(), 0.0, format);
    ctx.fonts_mut(|f| f.layout_job(job))
}

/// Wrapped paragraph galley.
pub fn text_galley(
    ctx: &egui::Context,
    text: &str,
    font: FontId,
    color: Color32,
    wrap: f32,
    line_h: f32,
) -> std::sync::Arc<egui::Galley> {
    let mut job = egui::text::LayoutJob::simple(text.to_owned(), font, color, wrap);
    job.sections[0].format.line_height = Some(line_h);
    ctx.fonts_mut(|f| f.layout_job(job))
}
