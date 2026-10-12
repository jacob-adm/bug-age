//! Method B: behavioural sweep. A regression test (overlay) must FAIL on the fix's first parent
//! and PASS on the fix. The first-parent range [start, fix^] is then bisected for the PASS->FAIL
//! boundary, skipping UNTESTABLE/FLAKY commits the way `git bisect skip` does, and a bounded
//! sweep around the boundary checks monotonicity. Nothing is smoothed over: a PASS after a FAIL
//! is reported as non-monotonic, and a range that fails from its first commit is left-censored.

use crate::git::git;
use crate::runner::{CommitResult, Outcome, Runner, Spec, Step};
use serde::Serialize;
use std::collections::BTreeMap;

#[derive(Debug, Serialize)]
pub struct Sweep {
    pub fix: String,
    pub start: String,
    pub runner: String,
    pub build: String,
    pub test: String,
    pub repeats: u32,
    /// located | interval | censored-by-testability | left-censored | repro-invalid
    pub verdict: String,
    pub reason: String,
    pub last_passing: Option<String>,
    pub first_failing: Option<String>,
    /// First-parent commits strictly between last_passing and first_failing (all untestable).
    pub untestable_between: usize,
    pub non_monotonic: bool,
    pub range_commits: usize,
    pub commits_tested: usize,
    /// Tested commits in history order.
    pub results: Vec<CommitResult>,
}

pub fn evaluate(runner: &mut dyn Runner, spec: &Spec, sha: &str) -> CommitResult {
    let logs = spec.logs.join(&sha[..12]);
    let mut steps = Vec::new();
    let result = |outcome, reason: String, toolchain: String, steps: Vec<Step>| CommitResult {
        sha: sha.to_string(), outcome, reason, toolchain, steps,
    };
    let toolchain = match runner.stage(spec, sha) {
        Ok(t) => t,
        Err(e) => return result(Outcome::Untestable, format!("stage: {e}"), String::new(), steps),
    };
    let step = |runner: &mut dyn Runner, name: &str, cmd: &str, network: bool, steps: &mut Vec<Step>| {
        let (exit, seconds) = runner.exec(spec, cmd, network, &logs.join(format!("{name}.log"))).unwrap_or((-1, 0.0));
        steps.push(Step { name: name.into(), cmd: cmd.into(), exit, seconds, network });
        exit
    };
    if runner.name() == "docker" && step(runner, "fetch", "cargo fetch", true, &mut steps) != 0 {
        return result(Outcome::Untestable, "dependency fetch failed".into(), toolchain, steps);
    }
    if step(runner, "build", &spec.build, false, &mut steps) != 0 {
        return result(Outcome::Untestable, "test build failed (overlay does not compile here)".into(), toolchain, steps);
    }
    let exits: Vec<i32> = (1..=spec.repeats)
        .map(|i| step(runner, &format!("test_{i}"), &spec.test, false, &mut steps))
        .collect();
    let (pass, fail) = (exits.iter().filter(|&&e| e == 0).count(), exits.iter().filter(|&&e| e != 0).count());
    match (pass, fail) {
        (_, 0) => result(Outcome::Pass, format!("passed {pass}x"), toolchain, steps),
        (0, _) => result(Outcome::Fail, format!("failed {fail}x"), toolchain, steps),
        _ => result(Outcome::Flaky, format!("{pass} pass / {fail} fail"), toolchain, steps),
    }
}

struct Probe<'a> {
    runner: &'a mut dyn Runner,
    spec: &'a Spec,
    commits: Vec<String>,
    seen: BTreeMap<usize, CommitResult>,
}

impl Probe<'_> {
    fn outcome(&mut self, i: usize) -> Outcome {
        if !self.seen.contains_key(&i) {
            let r = evaluate(self.runner, self.spec, &self.commits[i]);
            eprintln!("sweep: [{i}] {} {:?} ({})", &self.commits[i][..10], r.outcome, r.reason);
            self.seen.insert(i, r);
        }
        self.seen[&i].outcome
    }

    /// Nearest testable index to `mid` strictly inside (lo, hi), probing at most SKIP_RADIUS commits
    /// each way. Unbounded probing degenerated into a linear scan when the test cannot compile on a
    /// long stretch of older history (130 builds for one bug on tokenizers).
    fn testable_near(&mut self, mid: i64, lo: i64, hi: i64) -> Option<(usize, Outcome)> {
        for d in 0..=SKIP_RADIUS {
            for i in [mid - d, mid + d] {
                if i > lo && i < hi {
                    let o = self.outcome(i as usize);
                    if matches!(o, Outcome::Pass | Outcome::Fail) {
                        return Some((i as usize, o));
                    }
                }
            }
        }
        None
    }
}

/// First-parent commits from `start` (default: root) to `fix`, oldest first.
pub fn range(spec: &Spec, fix: &str, start: Option<&str>) -> Result<Vec<String>, String> {
    let all: Vec<String> = git(&spec.repo, &["rev-list", "--first-parent", "--reverse", fix])?
        .lines().map(String::from).collect();
    let from = match start {
        Some(s) => {
            let s = git(&spec.repo, &["rev-parse", s])?.trim().to_string();
            all.iter().position(|c| *c == s).ok_or(format!("start {s} is not on the first-parent chain of {fix}"))?
        }
        None => 0,
    };
    Ok(all[from..].to_vec())
}

const SKIP_RADIUS: i64 = 2;

pub fn run(runner: &mut dyn Runner, spec: &Spec, fix: &str, start: Option<&str>) -> Result<Sweep, String> {
    let commits = range(spec, fix, start)?;
    if commits.len() < 2 {
        return Err("range must contain the fix and at least its first parent".into());
    }
    let (f, p) = (commits.len() - 1, commits.len() - 2);
    let name = runner.name().to_string();
    let mut probe = Probe { runner, spec, commits, seen: BTreeMap::new() };
    let mut sweep = Sweep {
        fix: probe.commits[f].clone(), start: probe.commits[0].clone(), runner: name,
        build: spec.build.clone(), test: spec.test.clone(), repeats: spec.repeats,
        verdict: String::new(), reason: String::new(), last_passing: None, first_failing: None,
        untestable_between: 0, non_monotonic: false, range_commits: probe.commits.len(), commits_tested: 0,
        results: vec![],
    };
    let (of, op) = (probe.outcome(f), probe.outcome(p));
    if of != Outcome::Pass || op != Outcome::Fail {
        sweep.verdict = "repro-invalid".into();
        sweep.reason = format!("expected FAIL on fix^ and PASS on fix, got {op:?} / {of:?}");
        return Ok(finish(sweep, probe));
    }
    // lo: last known PASS; hi: first known FAIL; floor: everything at or below is assumed untestable
    // (an untestable neighbourhood is taken to mean the test cannot compile yet on older history).
    let (mut lo, mut hi, mut floor) = (-1i64, p as i64, -1i64);
    while hi - lo.max(floor) > 1 {
        let base = lo.max(floor);
        let mid = (base + hi) / 2;
        match probe.testable_near(mid, base, hi) {
            Some((i, Outcome::Pass)) => lo = i as i64,
            Some((i, _)) => hi = i as i64,
            None => floor = (mid + SKIP_RADIUS).min(hi - 1),
        }
    }
    let k = 2;
    for i in (hi - k).max(0)..=(hi + k).min(p as i64) {
        probe.outcome(i as usize);
    }
    sweep.first_failing = Some(probe.commits[hi as usize].clone());
    sweep.last_passing = (lo >= 0).then(|| probe.commits[lo as usize].clone());
    sweep.untestable_between = (hi - lo - 1).max(0) as usize;
    let assumed = (floor >= 0).then(|| format!(
        "; commits up to {} assumed untestable after {SKIP_RADIUS}-commit neighbourhoods failed to build",
        &probe.commits[floor as usize][..10]));
    (sweep.verdict, sweep.reason) = if lo >= 0 && hi - lo == 1 {
        ("located".into(), "adjacent last PASS and first FAIL".into())
    } else if lo >= 0 {
        ("interval".into(), format!("bug introduced within {} untestable commit(s) between last PASS and first FAIL{}",
                                     sweep.untestable_between, assumed.unwrap_or_default()))
    } else if floor >= 0 {
        sweep.untestable_between = 0;
        ("censored-by-testability".into(), format!("test already fails where it first compiles{}", assumed.unwrap_or_default()))
    } else {
        ("left-censored".into(), "test fails from the first commit of the range".into())
    };
    Ok(finish(sweep, probe))
}

fn finish(mut sweep: Sweep, probe: Probe) -> Sweep {
    let seq: Vec<Outcome> = probe.seen.values().map(|r| r.outcome)
        .filter(|o| matches!(o, Outcome::Pass | Outcome::Fail)).collect();
    // Within [start, fix^] the testable outcomes must read PASS* FAIL*; the fix itself is the last PASS.
    let body = &seq[..seq.len().saturating_sub(1)];
    sweep.non_monotonic = body.windows(2).any(|w| w[0] == Outcome::Fail && w[1] == Outcome::Pass);
    sweep.commits_tested = probe.seen.len();
    sweep.results = probe.seen.into_values().collect();
    sweep
}
