//! Method B end-to-end with the local runner: real git, real cargo, real bug-age binary,
//! synthetic crates with a planted bug. Each test owns its scratch dir, so they can run in parallel.

use serde_json::Value;
use std::path::{Path, PathBuf};
use std::process::Command;

const OK: &str = "pub fn mul(a: i32, b: i32) -> i32 { a * b }\n";
const BUG: &str = "pub fn mul(a: i32, b: i32) -> i32 { a + b }\n";
const NONE: &str = "pub fn add(a: i32, b: i32) -> i32 { a + b }\n";

fn git(dir: &Path, args: &[&str]) {
    let ok = bug_age::git::command().arg("-C").arg(dir)
        .args(["-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]).args(args)
        .env("GIT_AUTHOR_NAME", "T").env("GIT_AUTHOR_EMAIL", "t@example.invalid")
        .env("GIT_COMMITTER_NAME", "T").env("GIT_COMMITTER_EMAIL", "t@example.invalid")
        .env("GIT_CONFIG_GLOBAL", "/dev/null").env("GIT_CONFIG_NOSYSTEM", "1")
        .status().unwrap().success();
    assert!(ok, "git {args:?}");
}

/// One commit per lib.rs body; returns (repo dir, scratch dir, shas oldest first).
fn repo(name: &str, bodies: &[&str]) -> (PathBuf, PathBuf, Vec<String>) {
    let root = std::env::temp_dir().join(format!("bug-age-sweep-{name}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&root);
    let dir = root.join("repo");
    std::fs::create_dir_all(dir.join("toy/src")).unwrap();
    git(&dir, &["init", "-q"]);
    std::fs::write(dir.join("toy/Cargo.toml"), "[package]\nname = \"toy\"\nversion = \"0.1.0\"\nedition = \"2021\"\n\n[workspace]\n").unwrap();
    let mut shas = vec![];
    for (i, body) in bodies.iter().enumerate() {
        std::fs::write(dir.join("toy/src/lib.rs"), format!("// rev {i}\n{body}")).unwrap();
        git(&dir, &["add", "-A"]);
        git(&dir, &["commit", "-q", "-m", &format!("rev {i}")]);
        let out = bug_age::git::command().arg("-C").arg(&dir).args(["rev-parse", "HEAD"]).output().unwrap();
        shas.push(String::from_utf8(out.stdout).unwrap().trim().to_string());
    }
    (dir, root.join("scratch"), shas)
}

fn overlay(root: &Path, expected: i32) -> PathBuf {
    let o = root.join("overlay");
    std::fs::create_dir_all(o.join("tests")).unwrap();
    std::fs::write(o.join("tests/bugage_repro.rs"),
        format!("#[test]\nfn mul_multiplies() {{ assert_eq!(toy::mul(2, 3), {expected}); }}\n")).unwrap();
    o
}

fn sweep(dir: &Path, scratch: &Path, fix: &str, start: Option<&str>, expected: i32) -> Value {
    let ov = overlay(scratch.parent().unwrap(), expected);
    let mut args = vec!["sweep", "--repo", dir.to_str().unwrap(), "--path", "toy", "--fix", fix,
        "--overlay", ov.to_str().unwrap(), "--runner", "local", "--repeats", "2",
        "--build", "cargo test --test bugage_repro --no-run", "--test", "cargo test --test bugage_repro",
        "--scratch", scratch.to_str().unwrap()];
    let logs = scratch.join("logs");
    args.extend(["--logs", logs.to_str().unwrap()]);
    if let Some(s) = start {
        args.extend(["--start", s]);
    }
    let out = Command::new(env!("CARGO_BIN_EXE_bug-age")).args(&args).output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    serde_json::from_slice::<Value>(&out.stdout).unwrap()["report"].clone()
}

#[test]
fn locates_exact_introducing_commit() {
    // rev0 lacks mul (overlay cannot compile), rev1-2 correct, rev3 plants the bug, rev6 fixes it.
    let (dir, scratch, s) = repo("located", &[NONE, OK, OK, BUG, BUG, BUG, OK]);
    let r = sweep(&dir, &scratch, &s[6], None, 6);
    assert_eq!(r["verdict"], "located", "{r}");
    assert_eq!(r["last_passing"], s[2].as_str());
    assert_eq!(r["first_failing"], s[3].as_str());
    assert_eq!(r["untestable_between"], 0);
    assert_eq!(r["non_monotonic"], false);
}

#[test]
fn left_censored_when_range_starts_inside_the_bug() {
    let (dir, scratch, s) = repo("censored", &[OK, BUG, BUG, BUG, OK]);
    let r = sweep(&dir, &scratch, &s[4], Some(&s[1]), 6);
    assert_eq!(r["verdict"], "left-censored", "{r}");
    assert_eq!(r["first_failing"], s[1].as_str());
    assert!(r["last_passing"].is_null());
}

#[test]
fn skips_untestable_commits_and_reports_unresolved() {
    // mul only exists from rev3 (already buggy): everything before the first FAIL is untestable.
    let (dir, scratch, s) = repo("unresolved", &[NONE, NONE, NONE, BUG, BUG, OK]);
    let r = sweep(&dir, &scratch, &s[5], None, 6);
    assert_eq!(r["verdict"], "unresolved", "{r}");
    assert_eq!(r["first_failing"], s[3].as_str());
    assert_eq!(r["untestable_between"], 3);
    let untestable = r["results"].as_array().unwrap().iter().filter(|c| c["outcome"] == "UNTESTABLE").count();
    assert!(untestable >= 2, "bisect must have probed and skipped untestable midpoints");
}

#[test]
fn rejects_a_repro_that_does_not_fail_before_the_fix() {
    let (dir, scratch, s) = repo("invalid", &[OK, BUG, OK]);
    // Wrong expectation: the test fails on the fix too.
    let r = sweep(&dir, &scratch, &s[2], None, 7);
    assert_eq!(r["verdict"], "repro-invalid", "{r}");
}

/// Docker runner end-to-end (needs Docker + image bug-age-spike:3): `cargo test -- --ignored`.
/// Exercises git-archive staging, the time-travel index (the toy crate has no lockfile),
/// the date-matched toolchain and --network none for build/test.
#[test]
#[ignore]
fn docker_runner_locates_exact_introducing_commit() {
    let (dir, scratch, s) = repo("docker", &[NONE, OK, OK, BUG, BUG, BUG, OK]);
    let ov = overlay(scratch.parent().unwrap(), 6);
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../spike/timetravel.py");
    let logs = scratch.join("logs");
    let out = Command::new(env!("CARGO_BIN_EXE_bug-age"))
        .args(["sweep", "--repo", dir.to_str().unwrap(), "--path", "toy", "--fix", &s[6],
               "--overlay", ov.to_str().unwrap(), "--runner", "docker", "--repeats", "2",
               "--build", "cargo test --test bugage_repro --no-run", "--test", "cargo test --test bugage_repro",
               "--time-travel-script", script.to_str().unwrap(),
               "--scratch", scratch.to_str().unwrap(), "--logs", logs.to_str().unwrap()])
        .output().unwrap();
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let v: Value = serde_json::from_slice(&out.stdout).unwrap();
    let r = &v["report"];
    assert_eq!(r["verdict"], "located", "{r}");
    assert_eq!(r["first_failing"], s[3].as_str());
    assert_eq!(r["last_passing"], s[2].as_str());
    assert!(r["results"].as_array().unwrap().iter().all(|c| c["steps"].as_array().unwrap().iter()
        .filter(|st| st["name"].as_str().unwrap().starts_with("test_") || st["name"] == "build")
        .all(|st| st["network"] == false)), "build/test must run without network");
    assert!(v["receipt"]["versions"]["image"].as_str().unwrap().starts_with("sha256:"));
}
