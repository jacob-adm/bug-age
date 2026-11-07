//! Bundle contract: the committed bundle validates against the documented schema, broken
//! bundles do not, and the blameless gate catches planted identities.

use bug_age::bundle::{people, redact, scan};
use serde_json::{json, Value};
use std::path::{Path, PathBuf};


fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn load(rel: &str) -> Value {
    serde_json::from_str(&std::fs::read_to_string(root().join(rel)).unwrap()).unwrap()
}

fn validator() -> jsonschema::Validator {
    jsonschema::validator_for(&load("schema/bundle.schema.json")).expect("schema compiles")
}

#[test]
fn committed_bundle_matches_schema() {
    let v = validator();
    let bundle = load("dist/tokenizers/bundle.json");
    let errors: Vec<String> = v.iter_errors(&bundle).map(|e| format!("{} at {}", e, e.instance_path())).collect();
    assert!(errors.is_empty(), "{errors:#?}");
}

#[test]
fn schema_rejects_broken_bundles() {
    let v = validator();
    let good = load("dist/tokenizers/bundle.json");
    let mut no_summary = good.clone();
    no_summary.as_object_mut().unwrap().remove("summary");
    let mut identity_leak = good.clone();
    identity_leak["method_a"][0]["subject"] = json!("Fix by someone");
    let mut bad_verdict = good.clone();
    bad_verdict["method_b"][0]["verdict"] = json!("probably");
    let mut author_field = good.clone();
    let first = author_field["commits"].as_object().unwrap().keys().next().unwrap().clone();
    author_field["commits"][&first]["author"] = json!("Someone");
    for (name, b) in [("no summary", no_summary), ("subject on method_a", identity_leak),
                      ("unknown verdict", bad_verdict), ("author on commit", author_field)] {
        assert!(!v.is_valid(&b), "schema accepted a bundle with {name}");
    }
}

#[test]
fn gate_catches_planted_identities_and_redaction_removes_them() {
    let people = vec!["ada lovelace".to_string(), "adal".to_string()];
    let clean = json!({"commits": {"x": {"subject": "Fix tokenizer padding (#12)"}}});
    assert!(scan(&clean, &people).is_empty());
    for planted in ["thanks Ada Lovelace", "mail ada@example.org", "ping @adal", "by ADAL"] {
        let dirty = json!({"commits": {"x": {"subject": planted}}});
        assert!(!scan(&dirty, &people).is_empty(), "gate missed {planted:?}");
    }
    let redacted = redact("Fix from Ada Lovelace and adal", &people);
    assert!(scan(&json!(redacted), &people).is_empty(), "{redacted}");
    assert_eq!(redact("adalovelace-ish words stay", &people), "adalovelace-ish words stay", "whole words only");
}

#[test]
fn people_include_names_emails_and_noreply_usernames() {
    let dir = std::env::temp_dir().join(format!("bug-age-people-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    let git = |args: &[&str]| assert!(bug_age::git::command().arg("-C").arg(&dir).args(args)
        .env("GIT_AUTHOR_NAME", "Grace Hopper").env("GIT_AUTHOR_EMAIL", "123+ghopper@users.noreply.github.com")
        .env("GIT_COMMITTER_NAME", "Grace Hopper").env("GIT_COMMITTER_EMAIL", "123+ghopper@users.noreply.github.com")
        .env("GIT_CONFIG_GLOBAL", "/dev/null").status().unwrap().success());
    git(&["init", "-q"]);
    git(&["-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "init"]);
    let p = people(&dir).unwrap();
    for expected in ["grace hopper", "ghopper", "123+ghopper@users.noreply.github.com"] {
        assert!(p.iter().any(|x| x == expected), "missing {expected}: {p:?}");
    }
}

/// A target with only Method A outputs (no feasibility reports, no repros) still bundles:
/// the missing stages are NOT TESTED, never an error and never a fabricated number.
#[test]
fn missing_stages_bundle_as_not_tested() {
    let dir = std::env::temp_dir().join(format!("bug-age-partial-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let (repo, results) = (dir.join("repo"), dir.join("results"));
    std::fs::create_dir_all(&repo).unwrap();
    std::fs::create_dir_all(&results).unwrap();
    let git = |args: &[&str]| {
        let out = std::process::Command::new("git").args(args).current_dir(&repo)
            .env_remove("GIT_DIR").env_remove("GIT_INDEX_FILE").env_remove("GIT_WORK_TREE")
            .env("GIT_AUTHOR_NAME", "t").env("GIT_AUTHOR_EMAIL", "t@t").env("GIT_COMMITTER_NAME", "t")
            .env("GIT_COMMITTER_EMAIL", "t@t").output().unwrap();
        assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
        String::from_utf8(out.stdout).unwrap().trim().to_string()
    };
    git(&["init", "-q"]);
    std::fs::write(repo.join("a.rs"), "fn main() {}\n").unwrap();
    git(&["add", "."]);
    git(&["commit", "-q", "-m", "initial"]);
    let head = git(&["rev-parse", "HEAD"]);
    std::fs::write(results.join("catalog.json"), json!({"include_rule": "fix", "scanned": 1, "excluded": [], "fixes": []}).to_string()).unwrap();
    std::fs::write(results.join("szz.json"), json!({"head": head, "path": ".", "bugs": [],
        "summary": {"fixes": 0, "with_introducer": 0}}).to_string()).unwrap();

    let scope = Some(("Bindings".to_string(), "out of scope".to_string(), "binding behaviour".to_string()));
    let built = bug_age::bundle::build(&repo, &results, &dir.join("no-spike"), "https://example.org/r", &scope).unwrap();
    let b = built.bundle;
    let errors: Vec<String> = validator().iter_errors(&b).map(|e| format!("{} at {}", e, e.instance_path())).collect();
    assert!(errors.is_empty(), "{errors:#?}");
    assert!(b["feasibility"]["baseline"].is_null() && b["feasibility"]["time_travel"].is_null());
    let status = |stage: &str| b["coverage"].as_array().unwrap().iter()
        .find(|r| r["stage"] == stage).map(|r| r["status"].as_str().unwrap().to_string());
    assert_eq!(status("Historical buildability").as_deref(), Some("NOT TESTED"));
    assert_eq!(status("Method B (behavioural sweep)").as_deref(), Some("NOT TESTED"));
    assert_eq!(status("Bindings").as_deref(), Some("NOT TESTED"));
    assert_eq!(b["summary"]["method_b"]["swept"], 0);
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn recorded_commands_carry_no_local_paths_and_rerun_as_written() {
    use bug_age::bundle::public_command;
    let v = |xs: &[&str]| xs.iter().map(|x| x.to_string()).collect::<Vec<_>>();
    let cmd = v(&["/home/u/src/bug-age/target/debug/bug-age", "bundle", "--repo", "/home/u/src/bug-age/work/t",
                  "--here", "/home/u/src/bug-age", "--scratch", "/home/u/.cache/x", "--other", "/home/user2/x",
                  "--note", "a|b c", "--q", "it's"]);
    assert_eq!(public_command(&cmd, "/home/u/src/bug-age", "/home/u"),
               "target/debug/bug-age bundle --repo work/t --here . --scratch ~/.cache/x --other /home/user2/x --note 'a|b c' --q 'it'\\''s'");
    // cwd "/" must not eat slashes; empty roots change nothing
    assert_eq!(public_command(&v(&["/usr/bin/x", "/data/y"]), "/", ""), "/usr/bin/x /data/y");
    assert_eq!(public_command(&v(&["/a/c", "/b/a/c"]), "/a", ""), "c /b/a/c");
}
