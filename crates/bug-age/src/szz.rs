//! Method A: blame-based introducer nomination (SZZ-style).
//!
//! For each fix commit, blame the lines it removed or changed in its
//! first parent and nominate the commit(s) that last touched them. Known limits are flagged
//! per bug rather than hidden: addition-only fixes have nothing to blame, the latest toucher is
//! not necessarily the introducer, and `-w` only discounts whitespace-only changes.

use crate::catalog::Entry;
use crate::git::{author_time, commit_date, commit_time, git};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;

/// A commit that last touched lines the fix changed: a candidate introducer, not a proven one.
#[derive(Debug, Serialize)]
pub struct Nominee {
    /// Candidate introducing commit.
    pub sha: String,
    /// Its committer date, YYYY-MM-DD.
    pub date: String,
    /// How many of the fixed lines blame attributes to it; the primary nominee has the most.
    pub blamed_lines: usize,
}

/// How long the bug lived, measured from the primary nominee to the fix.
#[derive(Debug, Serialize)]
pub struct Lifetime {
    /// `git rev-list --count intro..fix` (full DAG).
    pub commits_elapsed: u64,
    /// Same range following first parents only.
    pub commits_elapsed_first_parent: u64,
    /// Committer-date difference: when each change landed on the branch.
    pub calendar_days: f64,
    /// Author-date difference: robust to rebases that compress committer dates.
    pub calendar_days_author: f64,
    /// Releases that shipped the bug: tags matching the release glob (default `v[0-9]*`) containing the introducer but not the fix,
    /// created no later than the fix landed. Counts release-branch tags that `--merged` would miss.
    pub releases_spanned: Vec<String>,
    /// Files changed under the crate path between introducer and fix.
    pub churn_files: u64,
    /// Lines added under the crate path between introducer and fix.
    pub churn_insertions: u64,
    /// Lines deleted under the crate path between introducer and fix.
    pub churn_deletions: u64,
}

/// Method A result for one catalogued fix.
#[derive(Debug, Serialize)]
pub struct Bug {
    /// Fix commit SHA.
    pub fix: String,
    /// Fix committer date, YYYY-MM-DD.
    pub fix_date: String,
    /// Sanitized fix subject (no usernames).
    pub subject: String,
    /// In-scope files whose changed lines were blamed.
    pub blamed_files: Vec<String>,
    /// Candidate introducers, most blamed lines first.
    pub nominees: Vec<Nominee>,
    /// Measured lifetime; `None` when blame found nothing to trace.
    pub lifetime: Option<Lifetime>,
    /// Whether the primary nominee falls on or after `--window-start`; `None` when no window is set.
    pub in_window: Option<bool>,
    /// Known-limit markers, e.g. `multiple-candidates`, `fix-is-merge(...)`.
    pub flags: Vec<String>,
}

/// Files of interest: Rust sources under `path`, outside tests/ and benches/.
pub fn in_scope(file: &str, path: &str) -> bool {
    let prefix = format!("{}/", path.trim_end_matches('/'));
    (path == "." || file.starts_with(&prefix))
        && file.ends_with(".rs")
        && !file.contains("/tests/")
        && !file.contains("/benches/")
}

/// Old-side line ranges per file from `git diff -U0` output: (file, start, count).
pub fn removed_ranges(diff: &str, path: &str) -> Vec<(String, u64, u64)> {
    let mut out = Vec::new();
    let mut file: Option<String> = None;
    for line in diff.lines() {
        if let Some(rest) = line.strip_prefix("--- ") {
            file = rest.strip_prefix("a/").map(String::from).filter(|f| in_scope(f, path));
        } else if let (Some(f), Some(hunk)) = (&file, line.strip_prefix("@@ -")) {
            let old = hunk.split_whitespace().next().unwrap_or("");
            let mut it = old.split(',');
            let start: u64 = it.next().and_then(|s| s.parse().ok()).unwrap_or(0);
            let count: u64 = it.next().map_or(Some(1), |c| c.parse().ok()).unwrap_or(0);
            if count > 0 {
                out.push((f.clone(), start, count));
            }
        }
    }
    out
}

/// Count blamed lines per commit from `git blame --porcelain` output.
pub fn blame_counts(porcelain: &str, counts: &mut BTreeMap<String, usize>) {
    for line in porcelain.lines() {
        let mut parts = line.split(' ');
        let first = parts.next().unwrap_or("");
        if first.len() == 40 && first.bytes().all(|b| b.is_ascii_hexdigit()) && parts.count() >= 2 {
            *counts.entry(first.to_string()).or_default() += 1;
        }
    }
}

/// Converts seconds to days, rounded to one decimal place.
fn days(secs: i64) -> f64 {
    (secs as f64 / 86_400.0 * 10.0).round() / 10.0
}

/// Parses `git diff --shortstat` into (files, insertions, deletions); missing parts count as zero.
fn shortstat(s: &str) -> (u64, u64, u64) {
    let num = |key: &str| {
        s.split(',')
            .find(|p| p.contains(key))
            .and_then(|p| p.split_whitespace().next()?.parse().ok())
            .unwrap_or(0)
    };
    (num("file"), num("insertion"), num("deletion"))
}

/// Measures the span from introducer `intro` to `fix`: commits, days, releases shipped and churn.
///
/// `release_tags` is a `git tag --list` glob for the target's release tags.
///
/// # Errors
/// Returns an error if a git command fails or its output cannot be parsed.
pub fn lifetime(repo: &Path, intro: &str, fix: &str, path: &str, release_tags: &str) -> Result<Lifetime, String> {
    let range = format!("{intro}..{fix}");
    let count = |extra: &[&str]| -> Result<u64, String> {
        let mut args = vec!["rev-list", "--count"];
        args.extend_from_slice(extra);
        args.push(&range);
        git(repo, &args)?.trim().parse().map_err(|e| format!("bad count: {e}"))
    };
    let fix_time = commit_time(repo, fix)?;
    let tags = git(repo, &["tag", "--list", release_tags, "--contains", intro, "--no-contains", fix,
                           "--format=%(refname:short)\t%(creatordate:unix)"])?;
    let releases_spanned = tags
        .lines()
        .filter_map(|l| l.split_once('\t'))
        .filter(|(_, t)| t.parse::<i64>().is_ok_and(|t| t <= fix_time))
        .map(|(name, _)| name.to_string())
        .collect();
    let (files, ins, del) = shortstat(&git(repo, &["diff", "--shortstat", intro, fix, "--", path])?);
    let secs = fix_time - commit_time(repo, intro)?;
    let author_secs = author_time(repo, fix)? - author_time(repo, intro)?;
    Ok(Lifetime {
        commits_elapsed: count(&[])?,
        commits_elapsed_first_parent: count(&["--first-parent"])?,
        calendar_days: days(secs),
        calendar_days_author: days(author_secs),
        releases_spanned,
        churn_files: files,
        churn_insertions: ins,
        churn_deletions: del,
    })
}

/// Runs Method A for one fix: diff against the first parent, blame the changed lines, rank the
/// candidate introducers by blamed lines, and measure the lifetime from the top candidate.
///
/// Root commits and fixes with nothing to blame return a `Bug` with a flag and no lifetime.
///
/// # Errors
/// Returns an error if a git command fails.
pub fn analyze(repo: &Path, fix: &Entry, path: &str, window_start: Option<&str>, release_tags: &str) -> Result<Bug, String> {
    let mut bug = Bug {
        fix: fix.sha.clone(),
        fix_date: fix.date.clone(),
        subject: fix.subject.clone(),
        blamed_files: vec![],
        nominees: vec![],
        lifetime: None,
        in_window: None,
        flags: vec![],
    };
    let Some(parent) = fix.parents.first() else {
        bug.flags.push("root-commit".into());
        return Ok(bug);
    };
    if fix.parents.len() > 1 {
        bug.flags.push("fix-is-merge(diffed-against-first-parent)".into());
    }
    let diff = git(repo, &["diff", "-U0", "-w", "--no-color", "-M", parent, &fix.sha, "--", path])?;
    let mut counts = BTreeMap::new();
    for (file, start, n) in removed_ranges(&diff, path) {
        let range = format!("{start},+{n}");
        let out = git(repo, &["blame", "-w", "--porcelain", "-L", &range, parent, "--", &file])?;
        blame_counts(&out, &mut counts);
        if !bug.blamed_files.contains(&file) {
            bug.blamed_files.push(file);
        }
    }
    if counts.is_empty() {
        bug.flags.push("no-blame-lines(addition-only-or-out-of-scope)".into());
        return Ok(bug);
    }
    // Rank by blamed lines (desc), then SHA, so the primary nominee is deterministic.
    let mut ranked: Vec<(String, usize)> = counts.into_iter().collect();
    ranked.sort_by(|a, b| b.1.cmp(&a.1).then(a.0.cmp(&b.0)));
    if ranked.len() > 1 {
        bug.flags.push("multiple-candidates".into());
    }
    for (sha, n) in &ranked {
        bug.nominees.push(Nominee { date: commit_date(repo, sha)?, sha: sha.clone(), blamed_lines: *n });
    }
    let primary = &bug.nominees[0];
    bug.in_window = window_start.map(|w| primary.date.as_str() >= w);
    let life = lifetime(repo, &primary.sha, &fix.sha, path, release_tags)?;
    // Near-zero committer days across several commits means a rebase rewrote committer dates.
    if life.calendar_days < 0.1 && life.commits_elapsed > 1 {
        bug.flags.push("committer-dates-compressed(use-author-days)".into());
    }
    bug.lifetime = Some(life);
    Ok(bug)
}
