//! Method A against a synthetic repository built here: a bug is planted, an unrelated
//! commit and a release tag follow, then the fix, then a typo-only commit. No network, no mocks:
//! real git and the real bug-age binary.

use bug_age::catalog::{classify, sanitize_subject};
use bug_age::szz::{in_scope, removed_ranges};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::Command;

/// Runs git in `dir` with fixed author and committer identity and date.
fn run_git(dir: &Path, args: &[&str], date: &str) {
    let ok = bug_age::git::command()
        .arg("-C").arg(dir)
        .args(["-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "init.defaultBranch=main"])
        .args(args)
        .env("GIT_AUTHOR_NAME", "Test").env("GIT_AUTHOR_EMAIL", "test@example.invalid")
        .env("GIT_COMMITTER_NAME", "Test").env("GIT_COMMITTER_EMAIL", "test@example.invalid")
        .env("GIT_AUTHOR_DATE", date).env("GIT_COMMITTER_DATE", date)
        .env("GIT_CONFIG_GLOBAL", "/dev/null").env("GIT_CONFIG_NOSYSTEM", "1")
        .status().expect("git runs").success();
    assert!(ok, "git {args:?} failed");
}

/// Writes `body` to `file`, commits it with message `msg` at `date`, and returns the SHA.
fn commit(dir: &Path, file: &str, body: &str, msg: &str, date: &str) -> String {
    let p = dir.join(file);
    std::fs::create_dir_all(p.parent().unwrap()).unwrap();
    std::fs::write(p, body).unwrap();
    run_git(dir, &["add", "-A"], date);
    run_git(dir, &["commit", "-q", "-m", msg], date);
    let out = bug_age::git::command().arg("-C").arg(dir).args(["rev-parse", "HEAD"]).output().unwrap();
    String::from_utf8(out.stdout).unwrap().trim().to_string()
}

/// The synthetic repository and the SHAs of its planted bug, fix and typo-only commit.
struct Repo { dir: PathBuf, intro: String, fix: String, typo: String }

/// Builds the synthetic history: init, planted bug, README, release tags on main and a release branch, the fix, then a typo-only commit.
fn synthetic_repo(name: &str) -> Repo {
    let dir = std::env::temp_dir().join(format!("bug-age-test-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    run_git(&dir, &["init", "-q"], "2025-01-01T00:00:00Z");
    let lib = "core/src/lib.rs";
    commit(&dir, lib, "pub fn add(a: i32, b: i32) -> i32 { a + b }\n", "init", "2025-01-01T00:00:00Z");
    let intro = commit(&dir, lib,
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\npub fn mul(a: i32, b: i32) -> i32 { a + b }\n",
        "add mul", "2025-01-02T00:00:00Z");
    commit(&dir, "core/README.md", "core\n", "describe core", "2025-01-05T00:00:00Z");
    run_git(&dir, &["tag", "v0.1.0"], "2025-01-05T00:00:00Z");
    run_git(&dir, &["tag", "core-v0.1.0"], "2025-01-05T00:00:00Z"); // prefixed scheme, matched only with --release-tags
    // Release branch cut from main before the fix: its tag shipped the bug but is never merged back.
    run_git(&dir, &["checkout", "-q", "-b", "release-0.1"], "2025-01-06T00:00:00Z");
    commit(&dir, "core/CHANGELOG.md", "0.1.1\n", "changelog 0.1.1", "2025-01-06T00:00:00Z");
    run_git(&dir, &["tag", "-a", "v0.1.1", "-m", "v0.1.1"], "2025-01-06T00:00:00Z");
    // A tag on the same branch after the fix landed must not count.
    commit(&dir, "core/CHANGELOG.md", "0.1.2\n", "changelog 0.1.2", "2025-01-20T00:00:00Z");
    run_git(&dir, &["tag", "-a", "v0.1.2", "-m", "v0.1.2"], "2025-01-20T00:00:00Z");
    run_git(&dir, &["checkout", "-q", "main"], "2025-01-06T00:00:00Z");
    let fix = commit(&dir, lib,
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\npub fn mul(a: i32, b: i32) -> i32 { a * b }\n",
        "fix: mul used addition (#1) from someuser/branch", "2025-01-12T00:00:00Z");
    let typo = commit(&dir, lib,
        "pub fn add(a: i32, b: i32) -> i32 { a + b }\npub fn mul(a: i32, b: i32) -> i32 { a * b } // product\n",
        "Fix typo in comment", "2025-01-13T00:00:00Z");
    Repo { dir, intro, fix, typo }
}

/// Runs the built binary with `args`, asserts success, and parses stdout as JSON.
fn bug_age(args: &[&str]) -> Value {
    let out = Command::new(env!("CARGO_BIN_EXE_bug-age")).args(args).output().expect("spawn bug-age");
    assert!(out.status.success(), "bug-age {args:?}: {}", String::from_utf8_lossy(&out.stderr));
    serde_json::from_slice(&out.stdout).expect("json output")
}

/// The catalog admits the fix and records the typo commit as `exclude:typo`.
#[test]
fn catalog_admits_fix_and_records_exclusion_rule() {
    let r = synthetic_repo("catalog");
    let cat = bug_age(&["catalog", "--repo", r.dir.to_str().unwrap(), "--path", "core"]);
    let fixes = cat["fixes"].as_array().unwrap();
    assert_eq!(fixes.len(), 1);
    assert_eq!(fixes[0]["sha"], r.fix.as_str());
    assert_eq!(fixes[0]["subject"], "fix: mul used addition (#1)");
    let excluded = cat["excluded"].as_array().unwrap();
    assert_eq!(excluded.len(), 1);
    assert_eq!(excluded[0]["sha"], r.typo.as_str());
    assert_eq!(excluded[0]["rule"], "exclude:typo");
    assert_eq!(cat["scanned"], 5);
}

/// Method A nominates the planting commit and reports the scripted days, commits, releases and churn.
#[test]
fn szz_nominates_planting_commit_with_scripted_lifetime() {
    let r = synthetic_repo("szz");
    let dir = r.dir.to_str().unwrap();
    let cat_path = r.dir.join("catalog.json");
    let out = Command::new(env!("CARGO_BIN_EXE_bug-age"))
        .args(["catalog", "--repo", dir, "--path", "core", "--out", cat_path.to_str().unwrap()])
        .output().unwrap();
    assert!(out.status.success());
    let res = bug_age(&["szz", "--repo", dir, "--catalog", cat_path.to_str().unwrap(), "--window-start", "2025-01-02"]);
    let bug = &res["bugs"][0];
    assert_eq!(bug["nominees"][0]["sha"], r.intro.as_str());
    assert_eq!(bug["nominees"][0]["blamed_lines"], 1);
    let life = &bug["lifetime"];
    assert_eq!(life["commits_elapsed"], 2, "README commit + fix");
    assert_eq!(life["calendar_days"], 10.0);
    assert_eq!(life["calendar_days_author"], 10.0);
    assert!(bug["flags"].as_array().unwrap().is_empty(), "single clean nominee, distinct dates");
    assert_eq!(life["releases_spanned"], serde_json::json!(["v0.1.0", "v0.1.1"]), "branch tag before fix counts; after does not");
    assert_eq!(life["churn_files"], 2, "README.md added and lib.rs fixed under core/");
    assert_eq!(bug["in_window"], true);
    assert_eq!(res["summary"]["in_window"], 1);
}

/// `--release-tags` counts prefixed release tags that the default glob ignores.
#[test]
fn release_tag_glob_selects_prefixed_release_tags() {
    let r = synthetic_repo("tags");
    let dir = r.dir.to_str().unwrap();
    let cat_path = r.dir.join("catalog.json");
    assert!(Command::new(env!("CARGO_BIN_EXE_bug-age"))
        .args(["catalog", "--repo", dir, "--path", "core", "--out", cat_path.to_str().unwrap()])
        .output().unwrap().status.success());
    let res = bug_age(&["szz", "--repo", dir, "--catalog", cat_path.to_str().unwrap(), "--release-tags", "core-v[0-9]*"]);
    assert_eq!(res["bugs"][0]["lifetime"]["releases_spanned"], serde_json::json!(["core-v0.1.0"]));
    assert_eq!(res["summary"]["release_tags"], "core-v[0-9]*");
}

/// Include and exclude rules classify representative subjects as expected.
#[test]
fn classify_rules() {
    assert_eq!(classify("fix(bpe): wrong merge order (#12)").as_deref(), Some("include"));
    assert_eq!(classify("Fix warnings in decoder").as_deref(), Some("exclude:lint-or-format"));
    assert_eq!(classify("Fixed Length Pre-Tokenizer").as_deref(), Some("exclude:feature-name"));
    assert_eq!(classify("Add a prefix option"), None, "'prefix' must not match the fix rule");
}

/// Sanitized subjects drop `from user/branch` and `@handles`.
#[test]
fn subjects_lose_usernames() {
    assert_eq!(sanitize_subject("Merge pull request #7 from alice/fix-bpe"), "Merge pull request #7");
    assert_eq!(sanitize_subject("fix decoder, thanks @bob-dev"), "fix decoder, thanks");
}

/// Removed-line ranges cover only in-scope Rust files and parse hunk counts correctly.
#[test]
fn removed_ranges_respects_scope_and_counts() {
    let diff = "--- a/core/src/lib.rs\n+++ b/core/src/lib.rs\n@@ -2 +2 @@\n-x\n+y\n@@ -10,0 +11,2 @@\n+z\n\
                --- a/core/tests/t.rs\n+++ b/core/tests/t.rs\n@@ -1,3 +1,0 @@\n";
    assert_eq!(removed_ranges(diff, "core"), vec![("core/src/lib.rs".to_string(), 2, 1)]);
    assert!(in_scope("core/src/a.rs", "core") && !in_scope("core/benches/b.rs", "core") && !in_scope("other/a.rs", "core"));
}

/// Inherited `GIT_DIR` and related variables do not redirect bug-age to the calling repository.
#[test]
fn ignores_git_env_inherited_from_hooks() {
    // A git hook exports GIT_DIR/GIT_INDEX_FILE; bug-age must still read --repo, not the caller.
    let r = synthetic_repo("hookenv");
    let decoy = synthetic_repo("decoy");
    let decoy_head = |d: &Path| {
        let o = bug_age::git::command().arg("-C").arg(d).args(["rev-parse", "HEAD"]).output().unwrap();
        String::from_utf8(o.stdout).unwrap()
    };
    let before = decoy_head(&decoy.dir);
    let out = Command::new(env!("CARGO_BIN_EXE_bug-age"))
        .args(["catalog", "--repo", r.dir.to_str().unwrap(), "--path", "core"])
        .env("GIT_DIR", decoy.dir.join(".git"))
        .env("GIT_INDEX_FILE", decoy.dir.join(".git/index"))
        .output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let cat: Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(cat["fixes"][0]["sha"], r.fix.as_str(), "catalog must come from --repo");
    assert_eq!(decoy_head(&decoy.dir), before, "decoy repository must be untouched");
}
