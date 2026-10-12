//! Execution environments for testing one commit with a regression-test overlay.
//!
//! `Docker` is the real runner: each commit's tree is copied into a volume with `git archive`
//! (host bind mounts served stale trees in BUGAGE-1), the toolchain is date-matched, lockfile-less
//! commits resolve against a time-travel index (BUGAGE-5), and build/test run with
//! `--network none`. `Local` uses the host toolchain in a git worktree; it exists so the sweep
//! logic can be tested end-to-end without Docker, and is not hermetic.

use crate::git::git;
use serde::Serialize;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Instant;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Outcome {
    Pass,
    Fail,
    Untestable,
    Flaky,
}

#[derive(Debug, Clone, Serialize)]
pub struct Step {
    pub name: String,
    pub cmd: String,
    pub exit: i32,
    pub seconds: f64,
    pub network: bool,
}

#[derive(Debug, Clone, Serialize)]
pub struct CommitResult {
    pub sha: String,
    pub outcome: Outcome,
    pub reason: String,
    pub toolchain: String,
    pub steps: Vec<Step>,
}

pub struct Spec {
    pub repo: PathBuf,
    pub crate_path: String,
    pub overlay: PathBuf,
    pub build: String,
    pub test: String,
    pub repeats: u32,
    pub scratch: PathBuf,
    pub logs: PathBuf,
}

pub trait Runner {
    fn name(&self) -> &'static str;
    /// Prepare the tree for `sha`; returns the toolchain label used.
    fn stage(&mut self, spec: &Spec, sha: &str) -> Result<String, String>;
    /// Run a shell command in the crate directory of the staged tree.
    fn exec(&mut self, spec: &Spec, cmd: &str, network: bool, log: &Path) -> Result<(i32, f64), String>;
}

/// Date-matched stable toolchain: latest release >= 14 days before the commit (one minor every 42
/// days since 1.0 on 2015-05-15), raised to the crate's `rust-version` if declared.
pub fn toolchain_for(commit_unix: i64, rust_version: Option<&str>) -> String {
    const RUST_1_0: i64 = 1_431_648_000;
    let mut minor = (commit_unix - 14 * 86_400 - RUST_1_0) / (42 * 86_400);
    if let Some(m) = rust_version.and_then(|v| v.strip_prefix("1.")?.split('.').next()?.parse::<i64>().ok()) {
        minor = minor.max(m);
    }
    format!("1.{minor}")
}

fn rust_version(repo: &Path, sha: &str, crate_path: &str) -> Option<String> {
    let manifest = git(repo, &["show", &format!("{sha}:{crate_path}/Cargo.toml")]).ok()?;
    manifest.lines().find_map(|l| {
        let v = l.trim().strip_prefix("rust-version")?.trim().strip_prefix('=')?.trim().trim_matches('"');
        Some(v.to_string())
    })
}

pub fn has_lockfile(repo: &Path, sha: &str, crate_path: &str) -> bool {
    [format!("{sha}:{crate_path}/Cargo.lock"), format!("{sha}:Cargo.lock")]
        .iter()
        .any(|obj| git(repo, &["cat-file", "-e", obj]).is_ok())
}

fn run_logged(cmd: &mut Command, log: &Path, stdin: Option<&[u8]>) -> Result<(i32, f64), String> {
    let t0 = Instant::now();
    let mut child = cmd
        .stdin(if stdin.is_some() { Stdio::piped() } else { Stdio::null() })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("spawn failed: {e}"))?;
    if let (Some(data), Some(mut pipe)) = (stdin, child.stdin.take()) {
        pipe.write_all(data).map_err(|e| e.to_string())?;
    }
    let out = child.wait_with_output().map_err(|e| e.to_string())?;
    if let Some(dir) = log.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let mut text = format!("$ {cmd:?}\n").into_bytes();
    text.extend_from_slice(&out.stdout);
    text.extend_from_slice(&out.stderr);
    std::fs::write(log, text).map_err(|e| e.to_string())?;
    Ok((out.status.code().unwrap_or(-1), (t0.elapsed().as_secs_f64() * 10.0).round() / 10.0))
}

/// Copy a directory tree (the regression-test overlay) into `dst`.
pub fn copy_tree(src: &Path, dst: &Path) -> Result<(), String> {
    for entry in std::fs::read_dir(src).map_err(|e| format!("{}: {e}", src.display()))? {
        let entry = entry.map_err(|e| e.to_string())?;
        let target = dst.join(entry.file_name());
        if entry.path().is_dir() {
            std::fs::create_dir_all(&target).map_err(|e| e.to_string())?;
            copy_tree(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), &target).map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

pub struct Local {
    wt: PathBuf,
}

impl Local {
    pub fn new(spec: &Spec) -> Self {
        Local { wt: spec.scratch.join("local-wt") }
    }
}

impl Runner for Local {
    fn name(&self) -> &'static str {
        "local"
    }

    fn stage(&mut self, spec: &Spec, sha: &str) -> Result<String, String> {
        let wt = self.wt.to_string_lossy().to_string();
        let _ = git(&spec.repo, &["worktree", "remove", "--force", &wt]);
        let _ = std::fs::remove_dir_all(&self.wt);
        git(&spec.repo, &["worktree", "add", "--force", "--detach", &wt, sha])?;
        copy_tree(&spec.overlay, &self.wt.join(&spec.crate_path))?;
        Ok("host".into())
    }

    fn exec(&mut self, spec: &Spec, cmd: &str, _network: bool, log: &Path) -> Result<(i32, f64), String> {
        run_logged(
            Command::new("sh")
                .args(["-c", cmd])
                .current_dir(self.wt.join(&spec.crate_path))
                .env("CARGO_TARGET_DIR", spec.scratch.join("local-target"))
                .env("CARGO_TERM_COLOR", "never"),
            log,
            None,
        )
    }
}

pub struct Docker {
    pub image: String,
    pub time_travel_script: Option<PathBuf>,
    toolchain: String,
}

const SRC: &str = "bugage-src";
const TARGET: &str = "bugage-target";
const INDEX: &str = "bugage-index";

impl Docker {
    pub fn new(image: String, time_travel_script: Option<PathBuf>) -> Self {
        Docker { image, time_travel_script, toolchain: String::new() }
    }

    fn docker(&self, args: &[&str], stdin: Option<&[u8]>, log: &Path) -> Result<(i32, f64), String> {
        run_logged(Command::new("docker").args(args), log, stdin)
    }

    fn untar_into(&self, volume: &str, dir: &str, tar: &[u8], log: &Path) -> Result<(), String> {
        let mount = format!("{volume}:/{volume}");
        let script = format!("mkdir -p {dir} && tar -x -C {dir}");
        let (code, _) = self.docker(&["run", "-i", "--rm", "-v", &mount, &self.image, "sh", "-c", &script], Some(tar), log)?;
        if code != 0 {
            return Err(format!("harness: untar into {volume}:{dir} failed (see {})", log.display()));
        }
        Ok(())
    }

    fn time_travel(&self, spec: &Spec, sha: &str, script: &Path) -> Result<(), String> {
        let short = &sha[..12];
        let tree = spec.scratch.join("tt-tree").join(short);
        let out = spec.scratch.join("tt-index").join(short);
        let _ = std::fs::remove_dir_all(&tree);
        let _ = std::fs::remove_dir_all(&out);
        std::fs::create_dir_all(&tree).map_err(|e| e.to_string())?;
        let archive = crate::git::command().arg("-C").arg(&spec.repo).args(["archive", "--format=tar", sha])
            .output().map_err(|e| e.to_string())?;
        let mut tar = Command::new("tar").arg("-x").arg("-C").arg(&tree).stdin(Stdio::piped()).spawn().map_err(|e| e.to_string())?;
        tar.stdin.take().expect("piped").write_all(&archive.stdout).map_err(|e| e.to_string())?;
        tar.wait().map_err(|e| e.to_string())?;
        let cutoff = git(&spec.repo, &["show", "-s", "--format=%ct", sha])?;
        let log = spec.logs.join(short).join("time-travel.log");
        let (code, _) = run_logged(
            Command::new("python3").arg("-I").arg(script)
                .args([tree.to_str().unwrap_or_default(), &spec.crate_path, cutoff.trim()])
                .arg(spec.scratch.join("index-cache")).arg(&out),
            &log, None)?;
        if code != 0 {
            return Err(format!("harness: time-travel index failed (see {})", log.display()));
        }
        let packed = Command::new("tar").args(["--no-xattrs", "-C"]).arg(&out).args(["-cf", "-", "."])
            .env("COPYFILE_DISABLE", "1").output().map_err(|e| e.to_string())?;
        self.untar_into(INDEX, &format!("/{INDEX}/{short}"), &packed.stdout, &spec.logs.join(short).join("stage-index.log"))?;
        let cfg = format!("[source.crates-io]\\nreplace-with = \\\"tt\\\"\\n[source.tt]\\nregistry = \\\"file:///{INDEX}/{short}\\\"\\n");
        let write = format!("mkdir -p /{SRC}/.cargo && printf \"{cfg}\" > /{SRC}/.cargo/config");
        let mount = format!("{SRC}:/{SRC}");
        let (code, _) = self.docker(&["run", "--rm", "-v", &mount, &self.image, "sh", "-c", &write], None,
                                    &spec.logs.join(short).join("stage-config.log"))?;
        if code != 0 {
            return Err("harness: writing .cargo/config failed".into());
        }
        Ok(())
    }
}

impl Runner for Docker {
    fn name(&self) -> &'static str {
        "docker"
    }

    fn stage(&mut self, spec: &Spec, sha: &str) -> Result<String, String> {
        let logs = spec.logs.join(&sha[..12]);
        self.docker(&["volume", "rm", "-f", SRC, TARGET], None, &logs.join("stage-reset.log"))?;
        let archive = crate::git::command().arg("-C").arg(&spec.repo).args(["archive", "--format=tar", sha])
            .output().map_err(|e| e.to_string())?;
        if !archive.status.success() {
            return Err(format!("harness: git archive {sha} failed"));
        }
        self.untar_into(SRC, &format!("/{SRC}"), &archive.stdout, &logs.join("stage-src.log"))?;
        let overlay = Command::new("tar").args(["--no-xattrs", "-C"]).arg(&spec.overlay).args(["-cf", "-", "."])
            .env("COPYFILE_DISABLE", "1").output().map_err(|e| e.to_string())?;
        self.untar_into(SRC, &format!("/{SRC}/{}", spec.crate_path), &overlay.stdout, &logs.join("stage-overlay.log"))?;
        if !has_lockfile(&spec.repo, sha, &spec.crate_path) {
            if let Some(script) = &self.time_travel_script {
                self.time_travel(spec, sha, script)?;
            }
        }
        let ct: i64 = git(&spec.repo, &["show", "-s", "--format=%ct", sha])?.trim().parse().map_err(|e| format!("{e}"))?;
        self.toolchain = toolchain_for(ct, rust_version(&spec.repo, sha, &spec.crate_path).as_deref());
        let install = format!("rustup toolchain install {} --profile minimal --no-self-update", self.toolchain);
        let (code, _) = self.exec(spec, &install, true, &logs.join("toolchain.log"))?;
        if code != 0 {
            return Err(format!("toolchain {} could not be installed", self.toolchain));
        }
        Ok(self.toolchain.clone())
    }

    fn exec(&mut self, spec: &Spec, cmd: &str, network: bool, log: &Path) -> Result<(i32, f64), String> {
        let workdir = format!("/{SRC}/{}", spec.crate_path);
        let (src, idx, tgt) = (format!("{SRC}:/{SRC}"), format!("{INDEX}:/{INDEX}"), format!("{TARGET}:/target"));
        let tc = format!("RUSTUP_TOOLCHAIN={}", self.toolchain);
        let mut args = vec!["run", "--rm"];
        if !network {
            args.extend(["--network", "none", "-e", "CARGO_NET_OFFLINE=true"]);
        }
        args.extend(["-v", &src, "-v", &idx, "-v", &tgt, "-v", "bugage-rustup:/rustup", "-v", "bugage-cargo:/cargo",
                     "-e", "CARGO_TARGET_DIR=/target", "-e", "CARGO_TERM_COLOR=never", "-e", &tc, "-w", &workdir,
                     &self.image, "sh", "-c", cmd]);
        self.docker(&args, None, log)
    }
}
