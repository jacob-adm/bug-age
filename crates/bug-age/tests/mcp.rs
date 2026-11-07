//! Offline replay of a recorded MCP session against the committed tokenizers bundle.
//! Re-record after a bundle or tool change:
//!   target/debug/bug-age mcp --bundles tokenizers=dist/tokenizers/bundle.json \
//!     < crates/bug-age/tests/fixtures/mcp/requests.jsonl > crates/bug-age/tests/fixtures/mcp/responses.jsonl

use serde_json::Value;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

fn root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

fn bundle() -> Value {
    serde_json::from_slice(&std::fs::read(root().join("dist/tokenizers/bundle.json")).unwrap()).unwrap()
}

fn serve(requests: &str) -> Vec<Value> {
    let mut child = Command::new(env!("CARGO_BIN_EXE_bug-age"))
        .args(["mcp", "--bundles", &format!("tokenizers={}", root().join("dist/tokenizers/bundle.json").display())])
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::null()).spawn().unwrap();
    child.stdin.take().unwrap().write_all(requests.as_bytes()).unwrap();
    let out = child.wait_with_output().unwrap();
    assert!(out.status.success());
    String::from_utf8(out.stdout).unwrap().lines().map(|l| serde_json::from_str(l).unwrap()).collect()
}

fn fixture(name: &str) -> String {
    std::fs::read_to_string(root().join("crates/bug-age/tests/fixtures/mcp").join(name)).unwrap()
}

#[test]
fn replays_recorded_session_exactly() {
    let got = serve(&fixture("requests.jsonl"));
    let want: Vec<Value> = fixture("responses.jsonl").lines().map(|l| serde_json::from_str(l).unwrap()).collect();
    assert_eq!(got.len(), want.len(), "one reply per request; none for the notification");
    for (g, w) in got.iter().zip(&want) {
        assert_eq!(g, w, "reply to id {} differs from the recording", w["id"]);
    }
}

#[test]
fn get_fix_returns_the_bundle_row_unchanged() {
    let b = bundle();
    let row = &b["method_b"][0];
    let fix = row["fix"].as_str().unwrap();
    let req = format!(r#"{{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{{"name":"get_fix","arguments":{{"target":"tokenizers","sha":"{}"}}}}}}"#, &fix[..12]);
    let reply = &serve(&format!("{req}\n"))[0]["result"]["structuredContent"];
    let a_row = b["method_a"].as_array().unwrap().iter().find(|r| r["fix"] == fix).unwrap();
    assert_eq!(&reply["method_a"], a_row);
    assert_eq!(&reply["method_b"], row);
    for (sha, c) in reply["commits"].as_object().unwrap() {
        assert_eq!(c, &b["commits"][sha], "commit {sha} must be copied from the bundle");
    }
}

#[test]
fn search_rows_only_carry_bundle_values() {
    let b = bundle();
    let req = r#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"search_fixes","arguments":{"target":"tokenizers","limit":200}}}"#;
    let reply = &serve(&format!("{req}\n"))[0]["result"]["structuredContent"];
    let fixes = reply["fixes"].as_array().unwrap();
    assert_eq!(reply["total"], b["method_a"].as_array().unwrap().len());
    for f in fixes {
        let row = b["method_a"].as_array().unwrap().iter().find(|r| r["fix"] == f["fix"]).expect("fix must exist in the bundle");
        assert_eq!(f["days"], row["days"]);
        assert_eq!(f["fix_date"], row["fix_date"]);
        assert_eq!(f["subject"], b["commits"][f["fix"].as_str().unwrap()]["subject"]);
        assert_eq!(f["commits_elapsed"], row["lifetime"]["commits_elapsed"]);
        let keys: Vec<&str> = f.as_object().unwrap().keys().map(String::as_str).collect();
        assert_eq!(keys, ["commits_elapsed", "days", "fix", "fix_date", "flags", "nominees", "releases_spanned", "subject"]);
    }
}

#[test]
fn unknown_or_ambiguous_inputs_are_tool_errors_not_guesses() {
    let b = bundle();
    // a 7-char prefix shared by two fixes, if the bundle has one; otherwise the unknown case alone
    let mut fixes: Vec<&str> = b["method_a"].as_array().unwrap().iter().map(|r| r["fix"].as_str().unwrap()).collect();
    fixes.sort();
    let shared = fixes.windows(2).find(|w| w[0][..7] == w[1][..7]).map(|w| &w[0][..7]);
    let mut reqs = String::from(r#"{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"get_fix","arguments":{"target":"tokenizers","sha":"fffffff0000000"}}}"#);
    reqs.push('\n');
    if let Some(p) = shared {
        reqs.push_str(&format!(r#"{{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{{"name":"get_fix","arguments":{{"target":"tokenizers","sha":"{p}"}}}}}}"#));
        reqs.push('\n');
    }
    for r in serve(&reqs) {
        assert_eq!(r["result"]["isError"], true);
        assert!(r["result"].get("structuredContent").is_none());
    }
}
