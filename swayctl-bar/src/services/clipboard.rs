//! Clipboard history for the launcher (":" prefix), straight from cliphist —
//! the history swayctl-center already keeps (`cliphist store` on every copy).
//! A line of `cliphist list` is `<id>\t<preview>`; images preview as
//! `[[ binary data 12 KiB png 640x480 ]]`. Copy / delete hand that line back
//! to cliphist on stdin, as its own pickers do.

use std::io::Write;
use std::process::{Command, Stdio};

#[derive(Clone, Debug, PartialEq)]
pub struct Entry {
    /// the whole `cliphist list` line (what decode/delete take)
    pub line: String,
    pub preview: String,
    /// "png 640x480" for an image, None for text
    pub image: Option<String>,
}

pub fn parse(out: &str) -> Vec<Entry> {
    out.lines()
        .filter_map(|line| {
            let (_, preview) = line.split_once('\t')?;
            let image = preview
                .strip_prefix("[[ binary data ")
                .and_then(|r| r.strip_suffix(" ]]"))
                .map(|r| r.split_whitespace().skip(2).collect::<Vec<_>>().join(" "));
            Some(Entry { line: line.to_owned(), preview: preview.trim().to_owned(), image })
        })
        .collect()
}

/// Newest first, as cliphist lists them.
pub fn list() -> Vec<Entry> {
    match Command::new("cliphist").arg("list").stderr(Stdio::null()).output() {
        Ok(o) if o.status.success() => parse(&String::from_utf8_lossy(&o.stdout)),
        _ => Vec::new(),
    }
}

fn with_line(args: &[&str], line: &str) -> std::io::Result<Vec<u8>> {
    let mut child = Command::new("cliphist").args(args).stdin(Stdio::piped()).stdout(Stdio::piped())
        .stderr(Stdio::null()).spawn()?;
    child.stdin.take().map(|mut s| s.write_all(format!("{line}\n").as_bytes())).transpose()?;
    Ok(child.wait_with_output()?.stdout)
}

/// The entry's content (text or image bytes).
pub fn decode(line: &str) -> Option<Vec<u8>> {
    with_line(&["decode"], line).ok().filter(|b| !b.is_empty())
}

/// Put the entry back on the clipboard (wl-copy guesses the type of an image).
pub fn copy(line: &str) {
    let line = line.to_owned();
    std::thread::spawn(move || {
        let Some(bytes) = decode(&line) else { return };
        if let Ok(mut c) = Command::new("wl-copy").stdin(Stdio::piped()).stderr(Stdio::null()).spawn() {
            if let Some(mut s) = c.stdin.take() {
                let _ = s.write_all(&bytes);
            }
            let _ = c.wait();
        }
    });
}

pub fn delete(line: &str) {
    let _ = with_line(&["delete"], line);
}

/// Case-insensitive match of `q` in `text`: the character positions to
/// highlight, or None. Words in any order ("foo bar" finds "bar ... foo").
pub fn matches(text: &str, q: &str) -> Option<Vec<i32>> {
    let lower: Vec<char> = text.chars().flat_map(|c| c.to_lowercase()).collect();
    let mut pos = Vec::new();
    for word in q.split_whitespace() {
        let w: Vec<char> = word.chars().flat_map(|c| c.to_lowercase()).collect();
        let at = lower.windows(w.len()).position(|win| win == w.as_slice())?;
        pos.extend((at..at + w.len()).map(|i| i as i32));
    }
    Some(pos)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_text_and_images() {
        let e = parse("12\thello world\n11\t[[ binary data 48 KiB png 640x480 ]]\nbad line\n");
        assert_eq!(e.len(), 2);
        assert_eq!((e[0].preview.as_str(), e[0].image.as_deref()), ("hello world", None));
        assert_eq!(e[1].image.as_deref(), Some("png 640x480"));
        assert_eq!(e[1].line, "11\t[[ binary data 48 KiB png 640x480 ]]");
    }

    #[test]
    fn matches_words_in_any_order() {
        assert_eq!(matches("Hello World", "wor"), Some(vec![6, 7, 8]));
        assert!(matches("Hello World", "world hello").is_some());
        assert!(matches("Hello World", "xyz").is_none());
        assert_eq!(matches("anything", ""), Some(vec![]));
    }
}
