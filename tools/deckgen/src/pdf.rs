//! PDF assembly: full-page raster images on A4-landscape pages via pdf-writer.
//! Pages are stored as zlib-deflated DeviceRGB samples; the deck's flat
//! surfaces compress well. Follows pdf-writer's `image.rs` example.

use flate2::write::ZlibEncoder;
use flate2::Compression;
use pdf_writer::{Content, Filter, Finish, Name, Pdf, Rect, Ref};
use std::io::Write;

pub fn write_pdf(pages: &[image::RgbaImage], path: &std::path::Path) -> std::io::Result<()> {
    let mut pdf = Pdf::new();
    let catalog_id = Ref::new(1);
    let page_tree_id = Ref::new(2);
    pdf.catalog(catalog_id).pages(page_tree_id);
    pdf.pages(page_tree_id)
        .kids((0..pages.len() as u32).map(|i| Ref::new(10 + i as i32)))
        .count(pages.len() as i32);

    for (i, img) in pages.iter().enumerate() {
        let page_id = Ref::new(10 + i as i32);
        let image_id = Ref::new(10_000 + i as i32);
        let content_id = Ref::new(20_000 + i as i32);

        let mut page = pdf.page(page_id);
        page.media_box(Rect::new(
            0.0,
            0.0,
            crate::page::PAGE.x,
            crate::page::PAGE.y,
        ));
        page.parent(page_tree_id);
        page.contents(content_id);
        page.resources().x_objects().pair(Name(b"Im1"), image_id);
        page.finish();

        let rgba = img.as_raw();
        let mut rgb = Vec::with_capacity(rgba.len() / 4 * 3);
        for px in rgba.as_chunks::<4>().0 {
            rgb.extend_from_slice(&px[..3]);
        }
        let mut enc = ZlibEncoder::new(Vec::new(), Compression::default());
        enc.write_all(&rgb)?;
        let encoded = enc.finish()?;

        let mut xobj = pdf.image_xobject(image_id, &encoded);
        xobj.filter(Filter::FlateDecode);
        xobj.width(img.width() as i32);
        xobj.height(img.height() as i32);
        xobj.color_space().device_rgb();
        xobj.bits_per_component(8);
        xobj.finish();

        // PDF origin is bottom-left; the page image fills the media box.
        let mut content = Content::new();
        content.save_state();
        content.transform([crate::page::PAGE.x, 0.0, 0.0, crate::page::PAGE.y, 0.0, 0.0]);
        content.x_object(Name(b"Im1"));
        content.restore_state();
        pdf.stream(content_id, &content.finish());
    }

    std::fs::write(path, pdf.finish())
}
