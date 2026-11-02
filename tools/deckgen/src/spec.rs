//! Deck spec: a Markdown file. Blocks separated by lines of exactly `---`.
//! First block is the title slide; each later block is one page.
//!
//! Within a block:
//!   `# Heading`      slide title (display face)
//!   `KICKER: text`   tracked HUD label above the title
//!   `SUBTITLE: text` title-slide subtitle
//!   `META: text`     title-slide line anchored above the footer
//!   `- item`         bullet
//!   `STAT: 1.00 | alignment score`   big display number + mono label
//!   `HERO: 1.00 | context label`  one oversized number; claims stack at right
//!                                 (ignored when the slide also has `IMG:`)
//!   `IMG: path`      image, framed, in the right column (path relative to the deck file)
//!   anything else    body paragraph (claim/header splitting is renderer-side, page.rs)
//!
//! Blocks of only blank lines make no pages; a block with only `# Title` is a Section.
//!
//! Title-slide block: `# Title`, `SUBTITLE: text`, `KICKER: text`.

use std::path::{Path, PathBuf};

/// Badge tone, mapped to ArtCraft's BADGE_BETA / BAD / ACCENT / MUTED colors.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Tone {
    Accent,
    Beta,
    Bad,
    Neutral,
}

/// A status badge: `BADGE: text | tone` (tone defaults to accent).
#[derive(Clone, Debug)]
pub struct Badge {
    pub text: String,
    pub tone: Tone,
}

pub struct Stat {
    pub value: String,
    pub label: String,
}

pub struct Slide {
    pub kicker: Option<String>,
    pub title: Option<String>,
    pub subtitle: Option<String>,
    pub meta: Option<String>,
    pub badge: Option<Badge>,
    /// A control pill (`TAG: text`), drawn with ArtCraft's toolbar-pill frame.
    pub tag: Option<String>,
    /// A labelled horizontal rule (`DIVIDER: text`), ArtCraft's `divider_with_label`.
    pub divider: Option<String>,
    /// A bordered feature section (`CALLOUT: heading | body`), ArtCraft's
    /// landing-page section with corner registration marks.
    pub callout: Option<Stat>,
    pub hero: Option<Stat>,
    pub bullets: Vec<String>,
    pub paragraphs: Vec<String>,
    pub stats: Vec<Stat>,
    pub image: Option<PathBuf>,
    pub kind: SlideKind,
}

#[derive(PartialEq, Clone, Copy)]
pub enum SlideKind {
    Title,
    Content,
    Section,
}

pub struct Deck {
    pub slides: Vec<Slide>,
}

pub fn parse(source: &str, base: &Path) -> Deck {
    let mut blocks: Vec<Vec<&str>> = vec![vec![]];
    for line in source.lines() {
        if line.trim() == "---" {
            blocks.push(vec![]);
        } else {
            blocks.last_mut().unwrap().push(line);
        }
    }
    let mut slides: Vec<Slide> = Vec::new();
    blocks.retain(|b| b.iter().any(|l| !l.trim().is_empty()));
    for (i, block) in blocks.into_iter().enumerate() {
        let mut s = Slide {
            kicker: None,
            title: None,
            subtitle: None,
            meta: None,
            badge: None,
            tag: None,
            callout: None,
            divider: None,
            hero: None,
            bullets: vec![],
            paragraphs: vec![],
            stats: vec![],
            image: None,
            kind: SlideKind::Content,
        };
        for line in block {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            if let Some(v) = line.strip_prefix("KICKER: ") {
                s.kicker = Some(v.to_string());
            } else if let Some(v) = line.strip_prefix("SUBTITLE: ") {
                s.subtitle = Some(v.to_string());
            } else if let Some(v) = line.strip_prefix("META: ") {
                s.meta = Some(v.to_string());
            } else if let Some(v) = line.strip_prefix("DIVIDER: ") {
                s.divider = Some(v.trim().to_string());
            } else if let Some(v) = line.strip_prefix("CALLOUT: ") {
                let (heading, body) = v.split_once('|').unwrap_or((v, ""));
                s.callout = Some(Stat {
                    value: heading.trim().to_string(),
                    label: body.trim().to_string(),
                });
            } else if let Some(v) = line.strip_prefix("TAG: ") {
                s.tag = Some(v.trim().to_string());
            } else if let Some(v) = line.strip_prefix("BADGE: ") {
                let (text, tone) = match v.split_once('|') {
                    Some((t, tone)) => {
                        let tone = match tone.trim().to_ascii_lowercase().as_str() {
                            "beta" | "warning" => Tone::Beta,
                            "bad" | "error" => Tone::Bad,
                            "neutral" | "muted" => Tone::Neutral,
                            _ => Tone::Accent,
                        };
                        (t.trim(), tone)
                    }
                    None => (v.trim(), Tone::Accent),
                };
                s.badge = Some(Badge {
                    text: text.to_string(),
                    tone,
                });
            } else if let Some(v) = line.strip_prefix("HERO: ") {
                if let Some((value, label)) = v.split_once('|') {
                    s.hero = Some(Stat {
                        value: value.trim().to_string(),
                        label: label.trim().to_string(),
                    });
                }
            } else if let Some(v) = line.strip_prefix("STAT: ") {
                if let Some((value, label)) = v.split_once('|') {
                    s.stats.push(Stat {
                        value: value.trim().to_string(),
                        label: label.trim().to_string(),
                    });
                }
            } else if let Some(v) = line.strip_prefix("IMG: ") {
                s.image = Some(base.join(v.trim()));
            } else if let Some(v) = line.strip_prefix("# ") {
                s.title = Some(v.to_string());
            } else if let Some(v) = line.strip_prefix("- ") {
                s.bullets.push(v.to_string());
            } else {
                s.paragraphs.push(line.to_string());
            }
        }
        s.kind = if i == 0 {
            SlideKind::Title
        } else if s.bullets.is_empty()
            && s.paragraphs.is_empty()
            && s.stats.is_empty()
            && s.image.is_none()
        {
            SlideKind::Section
        } else {
            SlideKind::Content
        };
        slides.push(s);
    }
    Deck { slides }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blank_blocks_make_no_pages() {
        let d = parse("# A\n---\n\n---\n# B\n- x\n---\n\n", Path::new("."));
        assert_eq!(d.slides.len(), 2);
    }

    #[test]
    fn badge_and_tag_directives() {
        let d = parse(
            "# T\nTAG: RUST \u{b7} CARGO\nBADGE: CONVERGED | accent\n---\n# C\nBADGE: FAILED | bad\n- x\n---\n# D\nBADGE: BETA THING\n- y\n",
            Path::new("."),
        );
        assert_eq!(d.slides[0].tag.as_deref(), Some("RUST \u{b7} CARGO"));
        let b = d.slides[0].badge.as_ref().expect("title badge");
        assert_eq!(b.text, "CONVERGED");
        assert!(matches!(b.tone, Tone::Accent));
        assert!(matches!(
            d.slides[1].badge.as_ref().unwrap().tone,
            Tone::Bad
        ));
        // No tone suffix -> accent default, and the text keeps its words.
        let b = d.slides[2].badge.as_ref().unwrap();
        assert_eq!(b.text, "BETA THING");
        assert!(matches!(b.tone, Tone::Accent));
        assert!(d.slides[2].tag.is_none());
    }

    #[test]
    fn callout_splits_heading_and_body() {
        let d = parse(
            "# T\nCALLOUT: Any repo can emit a deck | Reports render from the same file.\n---\n# C\nCALLOUT: Heading only\n- x\n",
            Path::new("."),
        );
        let c = d.slides[0].callout.as_ref().expect("title callout");
        assert_eq!(c.value, "Any repo can emit a deck");
        assert_eq!(c.label, "Reports render from the same file.");
        // A pipe-less callout keeps the whole line as the heading and no body.
        let c = d.slides[1].callout.as_ref().unwrap();
        assert_eq!(c.value, "Heading only");
        assert_eq!(c.label, "");
    }

    #[test]
    fn divider_directive() {
        let d = parse(
            "# T\n---\n# C\nDIVIDER: RENDERED OFFLINE\n- x\n",
            Path::new("."),
        );
        assert_eq!(d.slides[1].divider.as_deref(), Some("RENDERED OFFLINE"));
        assert!(d.slides[0].divider.is_none());
    }

    #[test]
    fn kinds_stats_and_image_paths() {
        let d = parse(
            "# T\n---\n# Sec\n---\n# C\nSTAT: 1 | X\nIMG: a.png\n",
            Path::new("/d"),
        );
        assert!(matches!(d.slides[0].kind, SlideKind::Title));
        assert!(matches!(d.slides[1].kind, SlideKind::Section));
        assert!(matches!(d.slides[2].kind, SlideKind::Content));
        assert_eq!(d.slides[2].stats.len(), 1);
        assert_eq!(d.slides[2].image.as_deref(), Some(Path::new("/d/a.png")));
    }
}
