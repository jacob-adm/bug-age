//! Canonical data bundle: every number the explorer page and the article use, assembled from
//! script outputs only (catalog, Method A, Method B sweeps, A-checks, feasibility runs).
//!
//! Blameless by construction: commits carry SHA, date and a short subject; every author and
//! committer name/email in the repository history is redacted from subjects, and a gate scans
//! every string in the bundle for emails, @handles and those names. A hit fails the build.

use crate::git::git;
use regex::Regex;
use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

pub const SCHEMA_VERSION: &str = "1.1.0";

/// Make a recorded command shareable: paths under `cwd` become relative, then `home` becomes `~`.
pub fn public_command(command: &str, cwd: &str, home: &str) -> String {
    let mut out = command.to_string();
    if !cwd.is_empty() {
        out = out.replace(&format!("{}/", cwd.trim_end_matches('/')), "");
    }
    if !home.is_empty() {
        out = out.replace(home, "~");
    }
    out
}
const REDACTED: &str = "[redacted]";

/// Names, emails and handles of everyone in the repository history (lower-cased, deduplicated).
pub fn people(repo: &Path) -> Result<Vec<String>, String> {
    let log = git(repo, &["log", "--all", "--format=%an%n%ae%n%cn%n%ce"])?;
    let mut set = BTreeSet::new();
    for line in log.lines().map(str::trim).filter(|l| l.len() >= 3) {
        set.insert(line.to_lowercase());
        if let Some((local, _)) = line.split_once('@') {
            // GitHub noreply addresses embed the username: 12345+name@users.noreply.github.com
            let user = local.rsplit('+').next().unwrap_or(local);
            if user.len() >= 3 {
                set.insert(user.to_lowercase());
            }
        }
    }
    for generic in ["github", "noreply", "web-flow", "users.noreply.github.com"] {
        set.remove(generic);
    }
    let mut v: Vec<String> = set.into_iter().collect();
    v.sort_by_key(|s| std::cmp::Reverse(s.len())); // longest first so full names win over parts
    Ok(v)
}

/// All identities as one case-insensitive whole-word regex, compiled once (one regex per person
/// per string made a bundle build take over ten minutes on tokenizers).
pub struct Identities {
    names: Option<Regex>,
    email: Regex,
    handle: Regex,
}

impl Identities {
    pub fn new(people: &[String]) -> Self {
        let alternation: Vec<String> = people.iter().map(|p| regex::escape(p)).collect();
        let names = (!alternation.is_empty()).then(|| {
            Regex::new(&format!(r"(?i)(^|[^\w])({})($|[^\w])", alternation.join("|"))).expect("escaped names")
        });
        Identities {
            names,
            email: Regex::new(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}").expect("valid"),
            handle: Regex::new(r"(^|\s)@[A-Za-z0-9][A-Za-z0-9_-]+").expect("valid"),
        }
    }

    pub fn redact(&self, text: &str) -> String {
        let mut out = text.to_string();
        if let Some(re) = &self.names {
            // Repeat: adjacent names share a boundary character, so one pass can skip the second.
            while re.is_match(&out) {
                out = re.replace_all(&out, format!("${{1}}{REDACTED}${{3}}")).into_owned();
            }
        }
        out
    }

    fn hits(&self, s: &str) -> Option<String> {
        if self.email.is_match(s) || self.handle.is_match(s) {
            return Some(format!("email/handle in {s:?}"));
        }
        let m = self.names.as_ref()?.captures(s)?;
        Some(format!("person {:?} in {s:?}", m.get(2).map_or("", |g| g.as_str())))
    }
}

pub fn redact(text: &str, people: &[String]) -> String {
    Identities::new(people).redact(text)
}

/// Every string in `v` that contains an email, an @handle or a known person; empty means clean.
pub fn scan(v: &Value, people: &[String]) -> Vec<String> {
    scan_with(v, &Identities::new(people))
}

fn scan_with(v: &Value, ids: &Identities) -> Vec<String> {
    let mut hits = Vec::new();
    let mut stack = vec![v];
    while let Some(x) = stack.pop() {
        match x {
            Value::String(s) => hits.extend(ids.hits(s)),
            Value::Array(a) => stack.extend(a),
            Value::Object(o) => stack.extend(o.values()),
            _ => {}
        }
    }
    hits
}

fn read(path: &Path) -> Result<Value, String> {
    let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))
}

fn pct(sorted: &[f64], q: f64) -> f64 {
    sorted[((q * sorted.len() as f64) as usize).min(sorted.len() - 1)]
}

fn median(sorted: &[f64]) -> f64 {
    let n = sorted.len();
    if n % 2 == 1 { sorted[n / 2] } else { (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0 }
}

/// Days per Method A bug: committer days, or author days where rebases compressed committer dates.
fn method_a_days(bug: &Value) -> Option<f64> {
    let life = bug.get("lifetime")?.as_object()?;
    let compressed = bug["flags"].as_array()?.iter().any(|f| f.as_str().is_some_and(|f| f.starts_with("committer-dates-compressed")));
    life.get(if compressed { "calendar_days_author" } else { "calendar_days" })?.as_f64()
}

fn method_a_summary(szz: &Value) -> Value {
    let bugs = szz["bugs"].as_array().cloned().unwrap_or_default();
    let mut days: Vec<f64> = bugs.iter().filter_map(method_a_days).collect();
    days.sort_by(|a, b| a.total_cmp(b));
    let mut commits: Vec<f64> = bugs.iter().filter_map(|b| b["lifetime"]["commits_elapsed"].as_f64()).collect();
    commits.sort_by(|a, b| a.total_cmp(b));
    let mut releases: Vec<f64> = bugs.iter().filter_map(|b| b["lifetime"]["releases_spanned"].as_array().map(|r| r.len() as f64)).collect();
    releases.sort_by(|a, b| a.total_cmp(b));
    let stat = |v: &[f64]| if v.is_empty() { json!(null) } else {
        json!({"median": median(v), "p90": pct(v, 0.9), "max": v[v.len() - 1], "n": v.len()})
    };
    json!({
        "fixes": bugs.len(),
        "with_introducer": days.len(),
        "in_window": szz["summary"]["in_window"],
        "window_start": szz["summary"]["window_start"],
        "calendar_days": stat(&days),
        "commits_elapsed": stat(&commits),
        "releases_shipped_bug": stat(&releases),
    })
}

fn acheck_label(outcomes: &[&str]) -> &'static str {
    match outcomes {
        ["PASS", "FAIL"] => "confirmed",
        ["FAIL", "FAIL"] => "too-late",
        ["PASS", "PASS"] => "refuted",
        ["UNTESTABLE", "FAIL"] => "plausible",
        ["UNTESTABLE", "UNTESTABLE"] => "untested",
        _ => "inconclusive",
    }
}

fn is_ancestor(repo: &Path, a: &str, b: &str) -> bool {
    crate::git::command().arg("-C").arg(repo).args(["merge-base", "--is-ancestor", a, b])
        .status().is_ok_and(|s| s.success())
}

fn commit_time(repo: &Path, sha: &str) -> Result<i64, String> {
    crate::git::commit_time(repo, sha)
}

fn days_between(repo: &Path, from: &str, to: &str) -> Result<f64, String> {
    Ok(((commit_time(repo, to)? - commit_time(repo, from)?) as f64 / 86_400.0 * 10.0).round() / 10.0)
}

/// One Method B record per repro, with the A-check and the A-vs-B relation derived from the data.
fn method_b(repo: &Path, dir: &Path, szz: &Value) -> Result<Vec<Value>, String> {
    let mut out = Vec::new();
    if !dir.is_dir() {
        return Ok(out); // no repros for this target: Method B is reported NOT TESTED
    }
    let mut entries: Vec<_> = std::fs::read_dir(dir).map_err(|e| e.to_string())?.flatten().collect();
    entries.sort_by_key(|e| e.file_name());
    for e in entries {
        let sweep_f = e.path().join("sweep.json");
        if !sweep_f.is_file() {
            continue;
        }
        let s = read(&sweep_f)?;
        let fix = s["fix"].as_str().unwrap_or_default().to_string();
        let a_bug = szz["bugs"].as_array().into_iter().flatten().find(|b| b["fix"] == fix.as_str());
        let nominee = a_bug.and_then(|b| b["nominees"][0]["sha"].as_str()).map(String::from);
        let verdict = s["verdict"].as_str().unwrap_or_default();
        let first = s["first_failing"].as_str().map(String::from);
        let b_days = match &first { Some(f) => Some(days_between(repo, f, &fix)?), None => None };
        let mut acheck = if e.path().join("acheck.json").is_file() {
            let a = read(&e.path().join("acheck.json"))?;
            let outs: Vec<&str> = a["results"].as_array().into_iter().flatten().filter_map(|r| r["outcome"].as_str()).collect();
            json!({"outcomes": outs, "label": acheck_label(&outs)})
        } else {
            json!({"outcomes": [], "label": "not-run"})
        };
        if let Some(a) = &nominee {
            let passes_after: Vec<&str> = s["results"].as_array().into_iter().flatten()
                .filter(|r| r["outcome"] == "PASS" && r["sha"] != fix.as_str() && r["sha"] != a.as_str())
                .filter_map(|r| r["sha"].as_str()).filter(|sha| is_ancestor(repo, a, sha)).collect();
            if let Some(evidence) = passes_after.last() {
                acheck["label"] = json!("refuted");
                acheck["evidence"] = json!(format!("test passes at {} after the nominee", &evidence[..12]));
            }
        }
        let results: Vec<Value> = s["results"].as_array().into_iter().flatten().map(|r| json!({
            "sha": r["sha"], "outcome": r["outcome"], "reason": r["reason"], "toolchain": r["toolchain"],
            "steps": r["steps"].as_array().into_iter().flatten().map(|st| json!({
                "name": st["name"], "exit": st["exit"], "seconds": st["seconds"], "network": st["network"]})).collect::<Vec<_>>(),
        })).collect();
        out.push(json!({
            "id": e.file_name().to_string_lossy(),
            "fix": fix,
            "verdict": verdict,
            "reason": s["reason"],
            "first_failing": first,
            "last_passing": s["last_passing"],
            "days": b_days,
            "days_is_lower_bound": verdict != "located",
            "untestable_between": s["untestable_between"],
            "non_monotonic": s["non_monotonic"],
            "range_start": s["start"],
            "range_commits": s["range_commits"],
            "commits_tested": s["commits_tested"],
            "repeats": s["repeats"],
            "test_command": s["test"],
            "method_a_nominee": nominee,
            "method_a_days": a_bug.and_then(method_a_days),
            "a_check": acheck,
            "results": results,
            "repro_test": std::fs::read_to_string(e.path().join("overlay/tests/bugage_repro.rs")).unwrap_or_default(),
        }));
    }
    Ok(out)
}

/// A missing report is `null` (the stage did not run) rather than an error.
fn feasibility(path: &Path) -> Result<Value, String> {
    if !path.is_file() {
        return Ok(Value::Null);
    }
    let r = read(path)?;
    Ok(json!({
        "verdict": r["verdict"],
        "built_and_tested_share": r["built_and_tested_share"],
        "counts": r["counts"],
        "method": r["method"],
        "samples": r["results"].as_array().into_iter().flatten().map(|s| json!({
            "sha": s["sha"], "date": s["date"], "toolchain": s["toolchain"], "status": s["status"],
            "reason": s["reason"], "lockfile_committed": s["lockfile_committed"],
        })).collect::<Vec<_>>(),
    }))
}

/// A stage that is out of scope for the target, as `(stage, evidence, does_not_prove)`; listed NOT TESTED.
pub type OutOfScope = Option<(String, String, String)>;

fn coverage(a: &Value, b: &[Value], feas: &Value, tt: &Value, out_of_scope: &OutOfScope) -> Value {
    let swept = b.len();
    let fixes = a["fixes"].as_u64().unwrap_or(0);
    let share = |f: &Value| if f.is_null() { "not run".to_string() } else { f["built_and_tested_share"].to_string() };
    let buildability = if feas.is_null() && tt.is_null() {
        json!({"stage": "Historical buildability", "status": "NOT TESTED",
               "evidence": "no feasibility report", "proves": "nothing",
               "does_not_prove": "that any historical commit builds"})
    } else {
        let samples = [feas, tt].iter().find(|f| !f.is_null()).and_then(|f| f["samples"].as_array()).map_or(0, Vec::len);
        json!({"stage": "Historical buildability", "status": "COVERED",
               "evidence": format!("{samples} sampled commits; {} with today's registry, {} with time-travel dependencies",
                                   share(feas), share(tt)),
               "proves": "sampled commits build and pass their unit tests offline in a date-matched toolchain",
               "does_not_prove": "that every commit builds; integration tests needing downloaded fixtures were not run"})
    };
    let method_b = if swept == 0 {
        json!({"stage": "Method B (behavioural sweep)", "status": "NOT TESTED",
               "evidence": format!("0 of {fixes} fixes have a regression test"), "proves": "nothing",
               "does_not_prove": "any bug's behavioural lifetime"})
    } else {
        json!({"stage": "Method B (behavioural sweep)", "status": "PARTIAL",
               "evidence": format!("{swept} of {fixes} fixes have a regression test and a sweep"),
               "proves": "where each tested bug's regression test starts failing, or a lower bound when censored",
               "does_not_prove": "anything about the fixes without a regression test (NOT TESTED)"})
    };
    let mut rows = vec![buildability, json!(
        {"stage": "Method A (SZZ)", "status": "PARTIAL",
         "evidence": format!("{} fixes from a rule-based catalog, {} with a nominated introducer", fixes, a["with_introducer"]),
         "proves": "which earlier commit last touched the lines each fix changed",
         "does_not_prove": if b.iter().any(|s| s["a_check"]["label"] == "refuted") {
             "that the nominee introduced the bug (see the refuted case in Method B); fixes missed by the subject rules"
         } else {
             "that the nominee introduced the bug; fixes missed by the subject rules"
         }}),
        method_b];
    if let Some((stage, evidence, not_proved)) = out_of_scope {
        rows.push(json!({"stage": stage, "status": "NOT TESTED", "evidence": evidence, "proves": "nothing",
                         "does_not_prove": not_proved}));
    }
    Value::Array(rows)
}

pub struct Built {
    pub bundle: Value,
    pub warnings: Vec<String>,
}

pub fn build(repo: &Path, results: &Path, spike: &Path, repo_url: &str, out_of_scope: &OutOfScope) -> Result<Built, String> {
    let catalog = read(&results.join("catalog.json"))?;
    let szz = read(&results.join("szz.json"))?;
    let feas = feasibility(&spike.join("results/report.json"))?;
    let tt = feasibility(&spike.join("results-timetravel/report.json"))?;
    let a_summary = method_a_summary(&szz);
    let b = method_b(repo, &results.join("repros"), &szz)?;
    let ids = Identities::new(&people(repo)?);

    let mut shas: BTreeSet<String> = BTreeSet::new();
    let mut add = |v: &Value| if let Some(s) = v.as_str().filter(|s| s.len() == 40) { shas.insert(s.to_string()); };
    for bug in szz["bugs"].as_array().into_iter().flatten() {
        add(&bug["fix"]);
        for n in bug["nominees"].as_array().into_iter().flatten() { add(&n["sha"]); }
    }
    for s in &b {
        for k in ["fix", "first_failing", "last_passing", "range_start", "method_a_nominee"] { add(&s[k]); }
        for r in s["results"].as_array().into_iter().flatten() { add(&r["sha"]); }
    }
    for f in [&feas, &tt] {
        for s in f["samples"].as_array().into_iter().flatten() { add(&s["sha"]); }
    }
    let mut commits = Map::new();
    for sha in &shas {
        let line = git(repo, &["show", "-s", "--format=%cs%x1f%s", sha])?;
        let (date, subject) = line.trim().split_once('\u{1f}').unwrap_or(("", ""));
        let subject = ids.redact(&crate::catalog::sanitize_subject(subject));
        commits.insert(sha.clone(), json!({"date": date, "subject": subject}));
    }
    let method_a: Vec<Value> = szz["bugs"].as_array().into_iter().flatten().map(|bug| {
        let mut b = bug.clone();
        b.as_object_mut().map(|o| o.remove("subject"));
        b["days"] = method_a_days(bug).map_or(json!(null), |d| json!(d));
        b
    }).collect();
    let refuted = b.iter().filter(|s| s["a_check"]["label"] == "refuted").count();
    let located = b.iter().filter(|s| s["verdict"] == "located").count();
    let bundle = json!({
        "schema_version": SCHEMA_VERSION,
        "generator": format!("bug-age {}", env!("CARGO_PKG_VERSION")),
        "subject": {"repo_url": repo_url, "crate_path": szz["path"], "head": szz["head"]},
        "summary": {"method_a": a_summary, "method_b": {
            "swept": b.len(), "located": located, "a_refuted": refuted,
            "verdicts": b.iter().fold(BTreeMap::<String, u64>::new(), |mut m, s| {
                *m.entry(s["verdict"].as_str().unwrap_or("").to_string()).or_default() += 1; m })},
            "feasibility": {"baseline_share": feas["built_and_tested_share"], "time_travel_share": tt["built_and_tested_share"]}},
        "catalog": {"include_rule": catalog["include_rule"], "scanned": catalog["scanned"],
                    "excluded": catalog["excluded"].as_array().into_iter().flatten()
                        .map(|e| json!({"sha": e["sha"], "rule": e["rule"]})).collect::<Vec<_>>()},
        "method_a": method_a,
        "method_b": b,
        "feasibility": {"baseline": feas, "time_travel": tt},
        "coverage": coverage(&a_summary, &b, &feas, &tt, out_of_scope),
        "commits": commits,
    });
    let hits = scan_with(&bundle, &ids);
    if !hits.is_empty() {
        return Err(format!("blameless gate failed ({} hits), first: {}", hits.len(), hits[0]));
    }
    Ok(Built { bundle, warnings: vec![] })
}
