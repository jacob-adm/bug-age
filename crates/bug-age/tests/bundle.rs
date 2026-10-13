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
