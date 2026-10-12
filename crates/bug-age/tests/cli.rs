//! Runs the built binary as a subprocess; no mocks.

use std::process::Command;

fn bug_age(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_bug-age"))
        .args(args)
        .output()
        .expect("failed to spawn bug-age binary")
}

#[test]
fn version_reports_crate_version() {
    let out = bug_age(&["--version"]);
    assert!(out.status.success());
    assert_eq!(
        String::from_utf8_lossy(&out.stdout).trim(),
        format!("bug-age {}", env!("CARGO_PKG_VERSION"))
    );
}

#[test]
fn unknown_argument_fails_with_usage_exit_code() {
    let out = bug_age(&["--definitely-not-a-flag"]);
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("unknown argument"));
}
