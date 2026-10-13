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
    /// Switch to the exact date-matched toolchain after a non-overlay build failure under a bucketed
    /// one; returns the new toolchain label, or None if there is nothing to fall back to.
    fn fallback_toolchain(&mut self, _spec: &Spec, _log: &Path) -> Option<String> {
        None
    }
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

/// Round "1.N" up to the next multiple of `bucket` (0 or 1 = unchanged).
pub fn bucketed(toolchain: &str, bucket: i64) -> String {
    match (bucket, toolchain.strip_prefix("1.").and_then(|m| m.parse::<i64>().ok())) {
        (b, Some(m)) if b > 1 => format!("1.{}", (m + b - 1) / b * b),
        _ => toolchain.to_string(),
    }
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
    /// Most recently used toolchains whose build caches are kept (oldest first).
    recent: Vec<String>,
    /// Volume-name suffix for parallel workers ("" or e.g. "-w1"); rustup is shared (installs locked).
    pub namespace: String,
    /// Round date-matched toolchains up to multiples of this minor (0 = exact). Fewer toolchains
    /// means more build-cache reuse; a non-overlay build failure retries with the exact toolchain.
    pub bucket: i64,
    exact_toolchain: String,
    /// Bucket toolchains that failed to install (e.g. not released yet); not retried.
    unavailable: Vec<String>,
}

/// Build caches kept at once. Each holds 1.5-3 GB of compiled dependencies for tokenizers, and a
/// date-matched sweep touches many toolchains (an uncapped run consumed 17 GB in 10 minutes).
const KEEP_TARGETS: usize = 2;

const SRC: &str = "bugage-src";
/// Build cache: one volume per toolchain, reused across commits so registry dependencies are not
/// recompiled. Workspace crates always rebuild because staged files get fresh mtimes (see untar_into).
const INDEX: &str = "bugage-index";

impl Docker {
    pub fn new(image: String, time_travel_script: Option<PathBuf>) -> Self {
        Docker { image, time_travel_script, toolchain: String::new(), recent: Vec::new(), namespace: String::new(),
                 bucket: 0, exact_toolchain: String::new(), unavailable: Vec::new() }
    }

    fn v(&self, base: &str) -> String {
        format!("{base}{}", self.namespace)
    }

    fn target_volume(&self, toolchain: &str) -> String {
        format!("bugage-target{}-{toolchain}", self.namespace)
    }

    fn install(&mut self, spec: &Spec, log: &Path) -> Result<(), String> {
        // flock: parallel workers share the rustup volume; concurrent installs can corrupt it.
        let install = format!("flock /rustup/.bug-age-install.lock rustup toolchain install {} --profile minimal --no-self-update",
                              self.toolchain);
        let (code, _) = self.exec(spec, &install, true, log)?;
        if code != 0 {
            return Err(format!("toolchain {} could not be installed", self.toolchain));
        }
        Ok(())
    }

    fn docker(&self, args: &[&str], stdin: Option<&[u8]>, log: &Path) -> Result<(i32, f64), String> {
        run_logged(Command::new("docker").args(args), log, stdin)
    }

    fn untar_into(&self, volume: &str, dir: &str, tar: &[u8], log: &Path) -> Result<(), String> {
        let mount = format!("{}:/{volume}", self.v(volume));
        // -m: stamp files with extraction time. git archive stamps them with the commit time, and
        // bisecting moves to *older* commits, so cargo's mtime fingerprint would reuse a stale
        // build from the per-toolchain target cache (caught by the Docker end-to-end test).
        // --no-same-owner: files from the host keep uid 501 otherwise, and older cargo's libgit2
        // rejects a root-run clone of a repo owned by another user ("safe.directory" error).
        let script = format!("mkdir -p {dir} && tar -x -m --no-same-owner -C {dir}");
        let (code, _) = self.docker(&["run", "-i", "--rm", "-v", &mount, &self.image, "sh", "-c", &script], Some(tar), log)?;
        if code != 0 {
            return Err(format!("harness: untar into {volume}:{dir} failed (see {})", log.display()));
        }
        Ok(())
    }

    fn evict_build_caches(&mut self, logs: &Path) -> Result<(), String> {
        self.recent.retain(|t| *t != self.toolchain);
        self.recent.push(self.toolchain.clone());
        if self.recent.len() > KEEP_TARGETS {
            self.recent.remove(0);
        }
        let prefix = format!("bugage-target{}-", self.namespace);
        let keep: Vec<String> = self.recent.iter().map(|t| self.target_volume(t)).collect();
        let listed = Command::new("docker").args(["volume", "ls", "-q", "--filter", &format!("name={prefix}")])
            .output().map_err(|e| e.to_string())?;
        let stale: Vec<String> = String::from_utf8_lossy(&listed.stdout).lines()
            .filter(|v| v.starts_with(&prefix) && v[prefix.len()..].starts_with("1.") && !keep.iter().any(|k| k == v))
            .map(String::from).collect();
        if !stale.is_empty() {
            let mut args = vec!["volume", "rm", "-f"];
            args.extend(stale.iter().map(String::as_str));
            self.docker(&args, None, &logs.join("stage-evict.log"))?;
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
        let _ = std::fs::remove_dir_all(&tree);
        let _ = std::fs::remove_dir_all(&out);
        // One fixed index location, replaced per commit, and cargo's clone of it dropped first: per-commit
        // URLs made cargo keep a separate index clone and .crate cache per commit (20 GB on tokenizers).
        // Crate files stay shared across cutoffs; they are immutable once published.
        let reset = format!("rm -rf /{INDEX}/current && mkdir -p /cargo/registry/index && find /cargo/registry/index -mindepth 1 -maxdepth 1 \
                             ! -name 'github.com-*' ! -name 'index.crates.io-*' -exec rm -rf {{}} +");
        let mounts = [format!("{}:/{INDEX}", self.v(INDEX)), format!("{}:/cargo", self.v("bugage-cargo"))];
        self.docker(&["run", "--rm", "-v", &mounts[0], "-v", &mounts[1], &self.image, "sh", "-c", &reset], None,
                    &spec.logs.join(short).join("stage-index-reset.log"))?;
        self.untar_into(INDEX, &format!("/{INDEX}/current"), &packed.stdout, &spec.logs.join(short).join("stage-index.log"))?;
        let cfg = format!("[source.crates-io]\\nreplace-with = \\\"tt\\\"\\n[source.tt]\\nregistry = \\\"file:///{INDEX}/current\\\"\\n");
        let write = format!("mkdir -p /{SRC}/.cargo && printf \"{cfg}\" > /{SRC}/.cargo/config");
        let mount = format!("{}:/{SRC}", self.v(SRC));
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

    fn fallback_toolchain(&mut self, spec: &Spec, log: &Path) -> Option<String> {
        if self.toolchain == self.exact_toolchain {
            return None;
        }
        self.toolchain = self.exact_toolchain.clone();
        self.evict_build_caches(log.parent()?).ok()?;
        self.install(spec, log).ok()?;
        Some(self.toolchain.clone())
    }

    fn stage(&mut self, spec: &Spec, sha: &str) -> Result<String, String> {
        let logs = spec.logs.join(&sha[..12]);
        self.docker(&["volume", "rm", "-f", &self.v(SRC)], None, &logs.join("stage-reset.log"))?;
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
        self.exact_toolchain = toolchain_for(ct, rust_version(&spec.repo, sha, &spec.crate_path).as_deref());
        self.toolchain = bucketed(&self.exact_toolchain, self.bucket);
        if self.unavailable.contains(&self.toolchain) {
            self.toolchain = self.exact_toolchain.clone();
        }
        self.evict_build_caches(&logs)?;
        if self.install(spec, &logs.join("toolchain.log")).is_ok() {
            return Ok(self.toolchain.clone());
        }
        if self.toolchain == self.exact_toolchain {
            return Err(format!("toolchain {} could not be installed", self.toolchain));
        }
        self.unavailable.push(self.toolchain.clone());
        self.toolchain = self.exact_toolchain.clone(); // bucket toolchain not released yet
        self.evict_build_caches(&logs)?;
        self.install(spec, &logs.join("toolchain-exact.log"))?;
        Ok(self.toolchain.clone())
    }

    fn exec(&mut self, spec: &Spec, cmd: &str, network: bool, log: &Path) -> Result<(i32, f64), String> {
        let workdir = format!("/{SRC}/{}", spec.crate_path);
        let (src, idx) = (format!("{}:/{SRC}", self.v(SRC)), format!("{}:/{INDEX}", self.v(INDEX)));
        let tgt = format!("{}:/target", self.target_volume(&self.toolchain));
        let cargo = format!("{}:/cargo", self.v("bugage-cargo"));
        let tc = format!("RUSTUP_TOOLCHAIN={}", self.toolchain);
        let mut args = vec!["run", "--rm"];
        if !network {
            args.extend(["--network", "none", "-e", "CARGO_NET_OFFLINE=true"]);
        }
        args.extend(["-v", &src, "-v", &idx, "-v", &tgt, "-v", "bugage-rustup:/rustup", "-v", &cargo,
                     "-e", "CARGO_TARGET_DIR=/target", "-e", "CARGO_TERM_COLOR=never", "-e", &tc, "-w", &workdir,
                     &self.image, "sh", "-c", cmd]);
        self.docker(&args, None, log)
    }
}
