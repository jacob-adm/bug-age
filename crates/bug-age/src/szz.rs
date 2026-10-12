//! Method A (SZZ-style): for each fix commit, blame the lines it removed or changed in its
//! first parent and nominate the commit(s) that last touched them. Known limits are flagged
//! per bug rather than hidden: addition-only fixes have nothing to blame, the latest toucher is
//! not necessarily the introducer, and `-w` only discounts whitespace-only changes.

use crate::catalog::Entry;
use crate::git::{author_time, commit_date, commit_time, git};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::Path;

#[derive(Debug, Serialize)]
pub struct Nominee {
    pub sha: String,
    pub date: String,
    pub blamed_lines: usize,
}

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
    /// Releases that shipped the bug: `v[0-9]*` tags containing the introducer but not the fix,
    /// created no later than the fix landed. Counts release-branch tags that `--merged` would miss.
    pub releases_spanned: Vec<String>,
    pub churn_files: u64,
    pub churn_insertions: u64,
    pub churn_deletions: u64,
}

#[derive(Debug, Serialize)]
pub struct Bug {
    pub fix: String,
    pub fix_date: String,
    pub subject: String,
    pub blamed_files: Vec<String>,
    pub nominees: Vec<Nominee>,
    pub lifetime: Option<Lifetime>,
    pub in_window: Option<bool>,
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

fn days(secs: i64) -> f64 {
    (secs as f64 / 86_400.0 * 10.0).round() / 10.0
}

fn shortstat(s: &str) -> (u64, u64, u64) {
    let num = |key: &str| {
        s.split(',')
            .find(|p| p.contains(key))
            .and_then(|p| p.split_whitespace().next()?.parse().ok())
            .unwrap_or(0)
    };
    (num("file"), num("insertion"), num("deletion"))
}

pub fn lifetime(repo: &Path, intro: &str, fix: &str, path: &str) -> Result<Lifetime, String> {
    let range = format!("{intro}..{fix}");
    let count = |extra: &[&str]| -> Result<u64, String> {
        let mut args = vec!["rev-list", "--count"];
        args.extend_from_slice(extra);
        args.push(&range);
        git(repo, &args)?.trim().parse().map_err(|e| format!("bad count: {e}"))
    };
    let fix_time = commit_time(repo, fix)?;
    let tags = git(repo, &["tag", "--list", "v[0-9]*", "--contains", intro, "--no-contains", fix,
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

pub fn analyze(repo: &Path, fix: &Entry, path: &str, window_start: Option<&str>) -> Result<Bug, String> {
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
    let life = lifetime(repo, &primary.sha, &fix.sha, path)?;
    if life.calendar_days < 0.1 && life.commits_elapsed > 1 {
        bug.flags.push("committer-dates-compressed(use-author-days)".into());
    }
    bug.lifetime = Some(life);
    Ok(bug)
}
