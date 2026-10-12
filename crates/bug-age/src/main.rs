//! bug-age CLI.
//!
//!   bug-age catalog --repo DIR --path CRATE [--head REV] [--out FILE]
//!   bug-age szz     --repo DIR --catalog FILE [--window-start YYYY-MM-DD] [--out FILE]

use bug_age::{catalog, szz};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::path::Path;
use std::process::ExitCode;

const USAGE: &str = "usage: bug-age [--version | --help]
       bug-age catalog --repo DIR --path CRATE [--head REV] [--out FILE]
       bug-age szz --repo DIR --catalog FILE [--window-start YYYY-MM-DD] [--out FILE]";

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
