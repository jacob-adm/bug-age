//! Fix-commit catalog: first-parent commits touching the crate path whose subject matches
//! a deterministic include rule and none of the exclude rules. Every entry records the rule
//! that admitted or rejected it, so the catalog can be audited and re-derived.

use crate::git::git;
use regex::Regex;
use serde::Serialize;
use std::path::Path;

pub const INCLUDE: &str = r"(?i)\b(fix(e[sd]|ing)?|bugs?|hotfix)\b";

/// (rule name, pattern). The first matching rule excludes the commit.
pub const EXCLUDE: &[(&str, &str)] = &[
    ("typo", r"(?i)\btypos?\b"),
    ("lint-or-format", r"(?i)\b(warnings?|clippy|lint(s|ing)?|fmt|rustfmt|format(ting)?)\b"),
    ("docs", r"(?i)\b(docs?|readme|documentation|docstrings?|comments?)\b"),
    ("ci", r"(?i)\b(ci|workflows?)\b"),
    ("release", r"(?i)\b(release|bump|version)\b"),
    ("deprecation", r"(?i)\bdeprecat"),
    ("build-only", r"(?i)\b(compile errors?|builds?|compilation)\b"),
    ("feature-name", r"(?i)\bfixed[- ]length\b"),
];

#[derive(Debug, Serialize)]
pub struct Entry {
    pub sha: String,
    pub parents: Vec<String>,
    pub date: String,
    /// Subject with usernames removed ("from user/branch", "@handle").
    pub subject: String,
    pub rule: String,
}

#[derive(Debug, Serialize)]
pub struct Catalog {
    pub head: String,
    pub path: String,
    pub scanned: usize,
    pub include_rule: String,
    pub fixes: Vec<Entry>,
    pub excluded: Vec<Entry>,
}

pub fn sanitize_subject(s: &str) -> String {
    let from = Regex::new(r"\s+from\s+\S+/\S+").expect("valid regex");
    let handle = Regex::new(r"@[A-Za-z0-9][A-Za-z0-9_-]*").expect("valid regex");
    handle.replace_all(&from.replace_all(s, ""), "").trim().chars().take(100).collect()
}

/// Returns `Some(rule)` naming why the subject is a fix ("include") or excluded ("exclude:<name>"),
/// or `None` if the include rule does not match at all.
pub fn classify(subject: &str) -> Option<String> {
    if !Regex::new(INCLUDE).expect("valid regex").is_match(subject) {
        return None;
    }
    for (name, pat) in EXCLUDE {
        if Regex::new(pat).expect("valid regex").is_match(subject) {
            return Some(format!("exclude:{name}"));
        }
    }
    Some("include".to_string())
}

pub fn build(repo: &Path, head: &str, path: &str) -> Result<Catalog, String> {
    let log = git(repo, &["log", "--first-parent", "--format=%H%x1f%P%x1f%cs%x1f%s%x1e", head, "--", path])?;
    let (mut fixes, mut excluded, mut scanned) = (Vec::new(), Vec::new(), 0);
    for rec in log.split('\x1e').map(str::trim).filter(|r| !r.is_empty()) {
        scanned += 1;
        let f: Vec<&str> = rec.split('\x1f').collect();
        let Some(rule) = classify(f[3]) else { continue };
        let entry = Entry {
            sha: f[0].to_string(),
            parents: f[1].split_whitespace().map(String::from).collect(),
            date: f[2].to_string(),
            subject: sanitize_subject(f[3]),
            rule: rule.clone(),
        };
        if rule == "include" { fixes.push(entry) } else { excluded.push(entry) }
    }
    let head = git(repo, &["rev-parse", head])?.trim().to_string();
    Ok(Catalog { head, path: path.to_string(), scanned, include_rule: INCLUDE.to_string(), fixes, excluded })
}
