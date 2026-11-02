//! deckgen — render a styled PDF deck from a Markdown slide spec using
//! ArtCraft's design system: headless egui (kittest) → raster pages → PDF.

mod page;
mod pdf;
mod spec;
mod tokens;

use std::path::PathBuf;

fn main() {
    let mut args = std::env::args().skip(1);
    let input = match args.next() {
        Some(a) => PathBuf::from(a),
        None => die("usage: deckgen <deck.md> [-o out.pdf]"),
    };
    let mut out = input.with_extension("pdf");
    let mut layout_out: Option<PathBuf> = None;
    while let Some(a) = args.next() {
        if a == "-o" {
            out = args
                .next()
                .map(PathBuf::from)
                .unwrap_or_else(|| die("-o needs a path"));
        } else if a == "--layout" {
            layout_out = Some(PathBuf::from(
                args.next().unwrap_or_else(|| die("--layout needs a path")),
            ));
        } else {
            die(&format!("unknown argument {a}"));
        }
    }

    let source = std::fs::read_to_string(&input)
        .unwrap_or_else(|e| die(&format!("read {}: {e}", input.display())));
    let deck = spec::parse(
        &source,
        input.parent().unwrap_or_else(|| std::path::Path::new(".")),
    );

    let pages = page::render_deck(&deck);
    if std::env::var("DECKGEN_VERBOSE").is_ok() {
        eprintln!("deck body size: {} pt", page::deck_body_size());
    }
    if let Some(dir) = out.parent() {
        std::fs::create_dir_all(dir).ok();
    }
    if let Some(path) = &layout_out {
        let pages_json: Vec<serde_json::Value> = page::layout()
            .iter()
            .enumerate()
            .map(|(i, items)| {
                let rects: Vec<serde_json::Value> = items
                    .iter()
                    .map(|it| {
                        serde_json::json!({
                            "kind": it.kind, "label": it.label,
                            "x": it.x, "y": it.y, "w": it.w, "h": it.h,
                        })
                    })
                    .collect();
                serde_json::json!({ "page": i + 1, "size": { "w": page::PAGE.x, "h": page::PAGE.y }, "rects": rects })
            })
            .collect();
        let doc = serde_json::json!({ "pages": pages_json });
        std::fs::write(path, serde_json::to_string_pretty(&doc).unwrap())
            .unwrap_or_else(|e| die(&format!("write {}: {e}", path.display())));
        println!("layout: {} pages -> {}", pages.len(), path.display());
    }
    pdf::write_pdf(&pages, &out).unwrap_or_else(|e| die(&format!("write {}: {e}", out.display())));
    println!(
        "{} — {} pages, {}×{} px each",
        out.display(),
        pages.len(),
        pages[0].width(),
        pages[0].height()
    );
}

fn die(msg: &str) -> ! {
    eprintln!("deckgen: {msg}");
    std::process::exit(1);
}
