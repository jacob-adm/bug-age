//! bug-age CLI.
//!
//!   bug-age catalog --repo DIR --path CRATE [--head REV] [--out FILE]
//!   bug-age szz     --repo DIR --catalog FILE [--window-start YYYY-MM-DD] [--out FILE]
//!   bug-age sweep   --repo DIR --path CRATE --fix SHA --overlay DIR --test CMD [options]
//!   bug-age probe   --repo DIR --path CRATE --commits SHA,SHA,... --overlay DIR --test CMD [options]
//!   bug-age bundle  --repo DIR --results DIR --repo-url URL --out DIR [--spike DIR]

use bug_age::runner::{Docker, Local, Runner, Spec};
use bug_age::{bundle, catalog, sweep, szz};
use sha2::{Digest, Sha256};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

const USAGE: &str = "usage: bug-age [--version | --help]
       bug-age catalog --repo DIR --path CRATE [--head REV] [--out FILE]
       bug-age szz --repo DIR --catalog FILE [--window-start YYYY-MM-DD] [--out FILE]
       bug-age sweep --repo DIR --path CRATE --fix SHA --overlay DIR --test CMD
             [--build CMD] [--start SHA] [--runner docker|local] [--repeats N] [--image IMG]
             [--time-travel-script FILE|none] [--scratch DIR] [--logs DIR] [--out FILE]
       bug-age probe --repo DIR --path CRATE --commits SHA,SHA,... --overlay DIR --test CMD [same options]
       bug-age bundle --repo DIR --results DIR --repo-url URL --out DIR [--spike DIR]";

fn flags(args: &[String]) -> Result<HashMap<String, String>, String> {
    let mut map = HashMap::new();
    let mut it = args.iter();
    while let Some(k) = it.next() {
        let key = k.strip_prefix("--").ok_or(format!("unexpected argument '{k}'"))?;
        let val = it.next().ok_or(format!("missing value for '{k}'"))?;
        map.insert(key.to_string(), val.clone());
    }
    Ok(map)
}

fn need<'a>(f: &'a HashMap<String, String>, key: &str) -> Result<&'a str, String> {
    f.get(key).map(String::as_str).ok_or(format!("missing --{key}"))
}

fn emit(value: &Value, out: Option<&String>) -> Result<(), String> {
    let text = serde_json::to_string_pretty(value).map_err(|e| e.to_string())? + "\n";
    match out {
        Some(p) => std::fs::write(p, text).map_err(|e| format!("cannot write {p}: {e}")),
        None => {
            print!("{text}");
            Ok(())
        }
    }
}

fn cmd_catalog(f: &HashMap<String, String>) -> Result<(), String> {
    let head = f.get("head").map_or("HEAD", String::as_str);
    let cat = catalog::build(Path::new(need(f, "repo")?), head, need(f, "path")?)?;
    eprintln!("catalog: {} fixes, {} excluded, {} commits scanned", cat.fixes.len(), cat.excluded.len(), cat.scanned);
    emit(&json!(cat), f.get("out"))
}

fn cmd_szz(f: &HashMap<String, String>) -> Result<(), String> {
    let repo = Path::new(need(f, "repo")?);
    let text = std::fs::read_to_string(need(f, "catalog")?).map_err(|e| e.to_string())?;
    let cat: Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
    let path = cat["path"].as_str().ok_or("catalog has no path")?;
    let window = f.get("window-start").map(String::as_str);
    let mut bugs = Vec::new();
    for e in cat["fixes"].as_array().ok_or("catalog has no fixes")? {
        let entry = catalog::Entry {
            sha: e["sha"].as_str().unwrap_or_default().into(),
            parents: e["parents"].as_array().into_iter().flatten().filter_map(|p| p.as_str().map(String::from)).collect(),
            date: e["date"].as_str().unwrap_or_default().into(),
            subject: e["subject"].as_str().unwrap_or_default().into(),
            rule: e["rule"].as_str().unwrap_or_default().into(),
        };
        bugs.push(szz::analyze(repo, &entry, path, window)?);
    }
    let with_intro = bugs.iter().filter(|b| b.lifetime.is_some()).count();
    let in_window = bugs.iter().filter(|b| b.in_window == Some(true)).count();
    eprintln!("szz: {} fixes, {with_intro} with a nominated introducer, {in_window} in window", bugs.len());
    let summary = json!({"fixes": bugs.len(), "with_introducer": with_intro,
                         "in_window": window.map(|_| in_window), "window_start": window});
    emit(&json!({"head": cat["head"], "path": path, "method": "A (SZZ-style, git blame -w on first parent)",
                 "summary": summary, "bugs": bugs}), f.get("out"))
}

fn tool_version(cmd: &str, args: &[&str]) -> String {
    std::process::Command::new(cmd).args(args).output()
        .map(|o| String::from_utf8_lossy(&o.stdout).lines().next().unwrap_or_default().to_string())
        .unwrap_or_else(|_| "unavailable".into())
}

fn spec_and_runner(f: &HashMap<String, String>, tag: &str) -> Result<(Spec, Box<dyn Runner>), String> {
    let opt = |k: &str, d: &str| f.get(k).cloned().unwrap_or_else(|| d.to_string());
    let home = std::env::var("HOME").unwrap_or_default();
    let spec = Spec {
        repo: PathBuf::from(need(f, "repo")?),
        crate_path: need(f, "path")?.to_string(),
        overlay: PathBuf::from(need(f, "overlay")?),
        build: opt("build", "cargo test --no-run"),
        test: need(f, "test")?.to_string(),
        repeats: opt("repeats", "3").parse().map_err(|e| format!("--repeats: {e}"))?,
        scratch: PathBuf::from(opt("scratch", &format!("{home}/.cache/bug-age"))),
        logs: PathBuf::from(opt("logs", &format!("work/sweep-logs/{tag}"))),
    };
    let runner: Box<dyn Runner> = match opt("runner", "docker").as_str() {
        "local" => Box::new(Local::new(&spec)),
        "docker" => {
            let tt = opt("time-travel-script", "spike/timetravel.py");
            Box::new(Docker::new(opt("image", "bug-age-spike:4"), (tt != "none").then(|| PathBuf::from(tt))))
        }
        other => return Err(format!("unknown runner '{other}'")),
    };
    Ok((spec, runner))
}

/// Evaluate an explicit list of commits (e.g. Method A's nominee and its parent) with the same
/// staging/build/test/repeat rules as `sweep`, without searching.
fn cmd_probe(f: &HashMap<String, String>) -> Result<(), String> {
    let commits: Vec<String> = need(f, "commits")?.split(',').map(|c| c.trim().to_string()).collect();
    let (spec, mut runner) = spec_and_runner(f, &format!("probe-{}", &commits[0][..commits[0].len().min(12)]))?;
    let mut results = Vec::new();
    for c in &commits {
        let sha = bug_age::git::git(&spec.repo, &["rev-parse", c])?.trim().to_string();
        let r = sweep::evaluate(runner.as_mut(), &spec, &sha);
        eprintln!("probe: {} {:?} ({})", &sha[..10], r.outcome, r.reason);
        results.push(r);
    }
    emit(&json!({"runner": runner.name(), "test": spec.test, "repeats": spec.repeats, "results": results}), f.get("out"))
}

fn cmd_sweep(f: &HashMap<String, String>) -> Result<(), String> {
    let opt = |k: &str, d: &str| f.get(k).cloned().unwrap_or_else(|| d.to_string());
    let fix = need(f, "fix")?.to_string();
    let (spec, mut runner) = spec_and_runner(f, &fix[..fix.len().min(12)])?;
    let start = f.get("start").map(String::as_str);
    let result = sweep::run(runner.as_mut(), &spec, &fix, start)?;
    eprintln!("sweep: {} — {} ({} of {} commits tested)", result.verdict, result.reason, result.commits_tested, result.range_commits);
    let report = serde_json::to_string_pretty(&json!(result)).map_err(|e| e.to_string())? + "\n";
    let mut versions = json!({"bug-age": env!("CARGO_PKG_VERSION"), "git": tool_version("git", &["--version"])});
    if result.runner == "docker" {
        versions["docker"] = json!(tool_version("docker", &["version", "--format", "{{.Server.Version}} {{.Server.Arch}}"]));
        versions["image"] = json!(tool_version("docker", &["image", "inspect", &opt("image", "bug-age-spike:4"), "--format", "{{.Id}}"]));
    }
    let receipt = json!({
        "command": std::env::args().collect::<Vec<_>>().join(" "),
        "inputs": {"repo_head": bug_age::git::git(&spec.repo, &["rev-parse", "HEAD"])?.trim(), "fix": result.fix,
                   "start": result.start, "overlay_files": overlay_listing(&spec.overlay)},
        "versions": versions,
        "verdict": result.verdict,
        "report_sha256": format!("{:x}", Sha256::digest(report.as_bytes())),
    });
    match f.get("out") {
        Some(out) => {
            std::fs::write(out, &report).map_err(|e| format!("{out}: {e}"))?;
            emit(&receipt, Some(&format!("{out}.receipt.json")))
        }
        None => emit(&json!({"report": result, "receipt": receipt}), None),
    }
}

/// Size gate for the published page's data (the artifact limit is 16 MB; target 8 MB).
const WARN_BYTES: usize = 8 * 1024 * 1024;
const MAX_BYTES: usize = 16 * 1024 * 1024;

fn cmd_bundle(f: &HashMap<String, String>) -> Result<(), String> {
    let repo = Path::new(need(f, "repo")?);
    let out = Path::new(need(f, "out")?);
    let spike = Path::new(f.get("spike").map_or("spike", String::as_str));
    let built = bundle::build(repo, Path::new(need(f, "results")?), spike, need(f, "repo-url")?)?;
    let json = serde_json::to_string(&built.bundle).map_err(|e| e.to_string())?;
    let js = format!("window.BUG_AGE_BUNDLE = {json};\n");
    if js.len() > MAX_BYTES {
        return Err(format!("size gate failed: bundle.js is {} bytes (> {MAX_BYTES})", js.len()));
    }
    std::fs::create_dir_all(out).map_err(|e| e.to_string())?;
    std::fs::write(out.join("bundle.json"), &json).map_err(|e| e.to_string())?;
    std::fs::write(out.join("bundle.js"), &js).map_err(|e| e.to_string())?;
    let sha = |b: &[u8]| format!("{:x}", Sha256::digest(b));
    let receipt = json!({
        "command": std::env::args().collect::<Vec<_>>().join(" ").replace(&std::env::var("HOME").unwrap_or_default(), "~"),
        "schema_version": bundle::SCHEMA_VERSION,
        "blameless_gate": "PASS",
        "size": {"bundle_json_bytes": json.len(), "bundle_js_bytes": js.len(), "warn_over_8mb": js.len() > WARN_BYTES},
        "outputs": {"bundle.json": sha(json.as_bytes()), "bundle.js": sha(js.as_bytes())},
        "versions": {"bug-age": env!("CARGO_PKG_VERSION"), "git": tool_version("git", &["--version"])},
        "warnings": built.warnings,
    });
    eprintln!("bundle: {} bytes, sha256 {}, blameless gate PASS", json.len(), sha(json.as_bytes()));
    emit(&receipt, Some(&out.join("receipt.json").to_string_lossy().to_string()))
}

fn overlay_listing(dir: &Path) -> Vec<String> {
    let mut out = Vec::new();
    let mut stack = vec![dir.to_path_buf()];
    while let Some(d) = stack.pop() {
        for e in std::fs::read_dir(&d).into_iter().flatten().flatten() {
            if e.path().is_dir() {
                stack.push(e.path());
            } else if let Ok(bytes) = std::fs::read(e.path()) {
                let rel = e.path().strip_prefix(dir).map(|p| p.display().to_string()).unwrap_or_default();
                out.push(format!("{rel} sha256:{:x}", Sha256::digest(&bytes)));
            }
        }
    }
    out.sort();
    out
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let result = match args.first().map(String::as_str) {
        Some("--version") | Some("-V") => {
            println!("bug-age {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        None | Some("--help") | Some("-h") => {
            println!("{USAGE}");
            Ok(())
        }
        Some("catalog") => flags(&args[1..]).and_then(|f| cmd_catalog(&f)),
        Some("szz") => flags(&args[1..]).and_then(|f| cmd_szz(&f)),
        Some("sweep") => flags(&args[1..]).and_then(|f| cmd_sweep(&f)),
        Some("probe") => flags(&args[1..]).and_then(|f| cmd_probe(&f)),
        Some("bundle") => flags(&args[1..]).and_then(|f| cmd_bundle(&f)),
        Some(other) => {
            eprintln!("bug-age: unknown argument '{other}'\n{USAGE}");
            return ExitCode::from(2);
        }
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("bug-age: {e}");
            ExitCode::FAILURE
        }
    }
}
