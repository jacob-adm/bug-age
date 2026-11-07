//! Assemble the explorer page: one data script per target beside the page, and a size gate.
//!
//! The page is a static HTML file containing the marker `<!-- bug-age:data -->`; it is replaced by
//! one `<script src="data/<name>.js">` per target, in the order given. Each data file pushes
//! `{name, receipt, bundle}` onto `window.BUG_AGE`, so the page reads every target without fetch.

use serde_json::{json, Value};

pub const MARKER: &str = "<!-- bug-age:data -->";
/// Target size for page plus data; the artifact hard limit is 16 MB.
pub const GATE_BYTES: usize = 8 * 1024 * 1024;

pub struct Target {
    pub name: String,
    pub bundle: Value,
    pub receipt: Value,
}

#[derive(Debug)]
pub struct Assembled {
    /// The page with the data scripts linked in.
    pub page: String,
    /// (published path, content) for each data file.
    pub files: Vec<(String, String)>,
    pub total_bytes: usize,
}

fn valid_name(name: &str) -> bool {
    !name.is_empty() && name.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
}

pub fn assemble(page: &str, targets: &[Target]) -> Result<Assembled, String> {
    if targets.is_empty() {
        return Err("no targets given".into());
    }
    if page.matches(MARKER).count() != 1 {
        return Err(format!("page must contain the marker {MARKER} exactly once"));
    }
    let mut files = Vec::new();
    let mut tags = String::new();
    for t in targets {
        if !valid_name(&t.name) {
            return Err(format!("target name '{}' must be lowercase letters, digits or '-'", t.name));
        }
        if files.iter().any(|(p, _): &(String, String)| p == &format!("data/{}.js", t.name)) {
            return Err(format!("target '{}' given twice", t.name));
        }
        let entry = json!({"name": t.name, "receipt": t.receipt, "bundle": t.bundle});
        // `</` can't appear raw inside a script file served as JS, but escape it anyway so the
        // same text is also safe if ever inlined.
        let text = serde_json::to_string(&entry).map_err(|e| e.to_string())?.replace("</", "<\\/");
        files.push((format!("data/{}.js", t.name), format!("(window.BUG_AGE = window.BUG_AGE || []).push({text});\n")));
        tags.push_str(&format!("<script src=\"data/{}.js\"></script>\n", t.name));
    }
    let page = page.replacen(MARKER, tags.trim_end(), 1);
    let total_bytes = page.len() + files.iter().map(|(_, c)| c.len()).sum::<usize>();
    if total_bytes > GATE_BYTES {
        return Err(format!("size gate failed: page plus data is {total_bytes} bytes (> {GATE_BYTES})"));
    }
    Ok(Assembled { page, files, total_bytes })
}
