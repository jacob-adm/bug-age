//! Git access layer.
//!
//! Thin wrapper over the `git` CLI. All history access goes through this module, so every
//! number bug-age reports is traceable to a concrete git command that anyone can re-run.

use std::path::Path;
use std::process::Command;

/// Variables git exports to hooks and subprocesses. `git -C <repo>` does not override them, so a
/// bug-age run from inside a hook (or its tests during pre-commit) would otherwise read or write the
/// *calling* repository. Every git invocation must start from this command.
const GIT_ENV: &[&str] = &[
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
];

/// Returns a `git` command with inherited repository variables removed.
///
/// Use this instead of `Command::new("git")` everywhere, including tests.
pub fn command() -> Command {
    let mut cmd = Command::new("git");
    for var in GIT_ENV {
        cmd.env_remove(var);
    }
    cmd
}

/// Runs `git -C <repo> <args>` and returns stdout as text.
///
/// # Errors
/// Returns the command line and git's stderr when git cannot start or exits non-zero.
pub fn git(repo: &Path, args: &[&str]) -> Result<String, String> {
    let out = command()
        .arg("-C")
        .arg(repo)
        .args(args)
        .output()
        .map_err(|e| format!("failed to spawn git: {e}"))?;
    if !out.status.success() {
        return Err(format!(
            "git {} failed: {}",
            args.join(" "),
            String::from_utf8_lossy(&out.stderr).trim()
        ));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

/// Committer time (unix seconds) of a commit.
pub fn commit_time(repo: &Path, sha: &str) -> Result<i64, String> {
    unix_time(repo, sha, "%ct")
}

/// Author time (unix seconds): survives rebases that rewrite committer dates.
pub fn author_time(repo: &Path, sha: &str) -> Result<i64, String> {
    unix_time(repo, sha, "%at")
}

/// Reads one timestamp field (`%ct` or `%at`) of a commit as unix seconds.
fn unix_time(repo: &Path, sha: &str, fmt: &str) -> Result<i64, String> {
    let s = git(repo, &["show", "-s", &format!("--format={fmt}"), sha])?;
    s.trim().parse().map_err(|e| format!("bad time for {sha}: {e}"))
}

/// Committer date (YYYY-MM-DD, committer timezone) of a commit.
pub fn commit_date(repo: &Path, sha: &str) -> Result<String, String> {
    Ok(git(repo, &["show", "-s", "--format=%cs", sha])?.trim().to_string())
}
