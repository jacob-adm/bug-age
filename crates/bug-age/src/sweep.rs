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
    /// First commit where the regression test compiles.
    pub frontier: Option<String>,
    pub confirmation: String,
    pub range_commits: usize,
    pub commits_tested: usize,
    /// Tested commits in history order.
    pub results: Vec<CommitResult>,
}

pub fn evaluate(runner: &mut dyn Runner, spec: &Spec, sha: &str, repeats: u32) -> CommitResult {
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
    let mut toolchain = toolchain;
    if step(runner, "build", &spec.build, false, &mut steps) != 0 {
        // An error in the overlay test means the tested API is absent: genuinely untestable. Any other
        // build error under a bucketed toolchain gets one retry with the exact date-matched toolchain.
        let log = std::fs::read_to_string(logs.join("build.log")).unwrap_or_default();
        let overlay_error = log.lines().any(|l| l.contains("bugage_repro.rs"));
        let retried = !overlay_error && runner.fallback_toolchain(spec, &logs.join("toolchain-fallback.log")).map(|t| {
            toolchain = t;
            runner.name() != "docker" || step(runner, "fetch_exact", "cargo fetch", true, &mut steps) == 0
        }) == Some(true) && step(runner, "build_exact", &spec.build, false, &mut steps) == 0;
        if !retried {
            return result(Outcome::Untestable, "test build failed (overlay does not compile here)".into(), toolchain, steps);
        }
    }
    let exits: Vec<i32> = (1..=repeats)
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
            let r = evaluate(self.runner, self.spec, &self.commits[i], SEARCH_REPEATS);
            eprintln!("sweep: [{i}] {} {:?} ({})", &self.commits[i][..10], r.outcome, r.reason);
            self.seen.insert(i, r);
        }
        self.seen[&i].outcome
    }

    /// Re-run a commit with the full repeat count; returns a note if the outcome changed.
    fn confirm(&mut self, i: usize) -> Option<String> {
        let before = self.outcome(i);
        if self.spec.repeats <= SEARCH_REPEATS || matches!(before, Outcome::Untestable) {
            return None;
        }
        let r = evaluate(self.runner, self.spec, &self.commits[i], self.spec.repeats);
        eprintln!("sweep: confirm [{i}] {} {:?} ({})", &self.commits[i][..10], r.outcome, r.reason);
        let changed = (r.outcome != before).then(|| format!("{} {before:?} -> {:?}", &self.commits[i][..10], r.outcome));
        self.seen.insert(i, r);
        changed
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
/// Repeats while searching; decisive commits are confirmed with `Spec::repeats`.
const SEARCH_REPEATS: u32 = 1;

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
        untestable_between: 0, non_monotonic: false, frontier: None, confirmation: String::new(), range_commits: probe.commits.len(), commits_tested: 0,
        results: vec![],
    };
    let (of, op) = (probe.outcome(f), probe.outcome(p));
    if of != Outcome::Pass || op != Outcome::Fail {
        sweep.verdict = "repro-invalid".into();
        sweep.reason = format!("expected FAIL on fix^ and PASS on fix, got {op:?} / {of:?}");
        return Ok(finish(sweep, probe));
    }
    // 1. Compile frontier: first commit where the test builds (build-ability assumed monotonic:
    //    once the tested API exists it keeps existing). Binary search instead of probing outward.
    let frontier = if probe.outcome(0) != Outcome::Untestable {
        0
    } else {
        let (mut untestable, mut testable) = (0usize, p);
        while testable - untestable > 1 {
            let mid = (untestable + testable) / 2;
            if probe.outcome(mid) == Outcome::Untestable { untestable = mid } else { testable = mid }
        }
        testable
    };
    sweep.frontier = Some(probe.commits[frontier].clone());
    // 2. PASS->FAIL bisect inside [frontier, fix^]; rare untestable commits there (broken builds)
    //    are skipped within SKIP_RADIUS.
    let (mut lo, mut hi) = (frontier as i64 - 1, p as i64);
    if probe.outcome(frontier) == Outcome::Pass {
        lo = frontier as i64;
        while hi - lo > 1 {
            match probe.testable_near((lo + hi) / 2, lo, hi) {
                Some((i, Outcome::Pass)) => lo = i as i64,
                Some((i, _)) => hi = i as i64,
                None => break,
            }
        }
    } else {
        hi = frontier as i64;
    }
    // 3. Bounded sweep around the boundary for monotonicity.
    for i in (hi - 2).max(frontier as i64)..=(hi + 2).min(p as i64) {
        probe.outcome(i as usize);
    }
    // 4. Confirm the decisive commits with the full repeat count.
    let mut decisive = vec![f, p, hi as usize];
    if lo >= frontier as i64 {
        decisive.push(lo as usize);
    }
    let unstable: Vec<String> = decisive.into_iter().filter_map(|i| probe.confirm(i)).collect();
    sweep.confirmation = if unstable.is_empty() {
        format!("decisive commits confirmed x{}", spec.repeats)
    } else {
        format!("UNSTABLE on confirmation: {}", unstable.join("; "))
    };
    let testable_lo = lo >= frontier as i64;
    sweep.first_failing = Some(probe.commits[hi as usize].clone());
    sweep.last_passing = testable_lo.then(|| probe.commits[lo as usize].clone());
    sweep.untestable_between = if testable_lo { (hi - lo - 1) as usize } else { 0 };
    (sweep.verdict, sweep.reason) = if testable_lo && hi - lo == 1 {
        ("located".into(), "adjacent last PASS and first FAIL".into())
    } else if testable_lo {
        ("interval".into(), format!("bug introduced within {} untestable commit(s) between last PASS and first FAIL",
                                     sweep.untestable_between))
    } else if frontier == 0 {
        ("left-censored".into(), "test fails from the first commit of the range".into())
    } else {
        ("censored-by-testability".into(), format!(
            "test already fails at {}, the first commit where it compiles (build-ability assumed monotonic)",
            &probe.commits[frontier][..10]))
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
