//! Fix-commit catalog.
//!
//! This is where bug-age decides which commits are bug fixes. It does not test anything: it reads
//! commit subjects. A commit is a fix when it is on the first-parent history, touches the crate path,
//! its subject matches `INCLUDE`, and it matches none of the `EXCLUDE` rules. Bugs that were never
//! fixed, or were fixed under a subject without these words, are not in the catalog.
//!
//! First-parent commits touching the crate path whose subject matches
//! a deterministic include rule and none of the exclude rules. Every entry records the rule
//! that admitted or rejected it, so the catalog can be audited and re-derived.

use crate::git::git;
use regex::Regex;
use serde::Serialize;
use std::path::Path;

/// Subject words that mark a commit as a bug fix: fix, fixes, fixed, fixing, bug, bugs, hotfix.
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

/// One commit that matched the include rule, with the rule that admitted or excluded it.
#[derive(Debug, Serialize)]
pub struct Entry {
    /// Full commit SHA.
    pub sha: String,
    /// Parent SHAs; more than one means the fix is a merge commit.
    pub parents: Vec<String>,
    /// Committer date, YYYY-MM-DD.
    pub date: String,
    /// Subject with usernames removed ("from user/branch", "@handle").
    pub subject: String,
    /// `include`, or `exclude:<rule name>`.
    pub rule: String,
}

/// The full catalog for one crate path at one head commit.
#[derive(Debug, Serialize)]
pub struct Catalog {
    /// Resolved head SHA the catalog was built from.
    pub head: String,
    /// Crate path the history was filtered to.
    pub path: String,
    /// Number of first-parent commits touching the path.
    pub scanned: usize,
    /// The include pattern, recorded so the catalog can be re-derived.
    pub include_rule: String,
    /// Commits admitted as bug fixes.
    pub fixes: Vec<Entry>,
    /// Commits that matched the include rule but were excluded, with the reason.
    pub excluded: Vec<Entry>,
}

/// Removes usernames from a commit subject and caps it at 100 characters.
///
/// Strips GitHub merge phrasing (`from user/branch`) and `@handles`, so the bundle stays blameless.
pub fn sanitize_subject(s: &str) -> String {
    let from = Regex::new(r"\s+from\s+\S+/\S+").expect("valid regex");
    let handle = Regex::new(r"@[A-Za-z0-9][A-Za-z0-9_-]*").expect("valid regex");
    handle.replace_all(&from.replace_all(s, ""), "").trim().chars().take(100).collect()
}

/// Returns `Some(rule)` naming why the subject is a fix ("include") or excluded (`exclude:<name>`),
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

/// Builds the catalog from the first-parent history of `head`, limited to commits touching `path`.
///
/// # Errors
/// Returns an error if a git command fails.
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
