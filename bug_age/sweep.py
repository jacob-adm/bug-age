# SPDX-License-Identifier: MIT OR Apache-2.0
"""Method B: behavioural sweep.

This is the only place bug-age runs tests to date a bug. It does not find bugs: it takes a
regression test written for one already-fixed bug and asks where in history that test starts
failing.

A regression test (overlay) must FAIL on the fix's first parent and PASS on the fix. The
first-parent range [start, fix^] is then bisected for the PASS->FAIL boundary, skipping
UNTESTABLE/FLAKY commits the way `git bisect skip` does, and a bounded sweep around the boundary
checks monotonicity. Nothing is smoothed over: a PASS after a FAIL is reported as non-monotonic,
and a range that fails from its first commit is left-censored.
"""
import hashlib
import os
import sys
from pathlib import Path

from . import __version__
from ._compat import dumps, lines, trim
from .git import GitError, git
from .runner import DEBUG, FAIL, FLAKY, PASS, UNTESTABLE, Docker, Local, RunnerError, Spec

SKIP_RADIUS = 2      # how far either side of a midpoint to look for a testable commit
SEARCH_REPEATS = 1   # test runs per commit while searching; decisive commits get --repeats


def evaluate(runner, spec, sha, repeats):
    """Stage `sha`, build the overlay test, run it `repeats` times: PASS, FAIL, FLAKY or UNTESTABLE."""
    logs = spec.logs / sha[:12]
    steps = []

    def result(outcome, reason, toolchain):
        return {"sha": sha, "outcome": outcome, "reason": reason, "toolchain": toolchain, "steps": steps}
    try:
        toolchain = runner.stage(spec, sha)
    except (RunnerError, GitError, OSError) as e:
        return result(UNTESTABLE, f"stage: {e}", "")

    def step(name, cmd, network):
        try:
            code, seconds = runner.exec(spec, cmd, network, logs / f"{name}.log")
        except (RunnerError, OSError):
            code, seconds = -1, 0.0
        steps.append({"name": name, "cmd": cmd, "exit": code, "seconds": seconds, "network": network})
        return code

    if runner.name == "docker" and step("fetch", "cargo fetch", True) != 0:
        return result(UNTESTABLE, "dependency fetch failed", toolchain)
    if step("build", spec.build, False) != 0:
        try:
            log = (logs / "build.log").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            log = ""
        overlay_error = any("bugage_repro.rs" in line for line in lines(log))
        retried = False
        if not overlay_error:
            # A bucketed toolchain may be too new for this commit: retry once with the exact one.
            fallback = runner.fallback_toolchain(spec, logs / "toolchain-fallback.log")
            if fallback is not None:
                toolchain = fallback
                fetched = runner.name != "docker" or step("fetch_exact", "cargo fetch", True) == 0
                retried = fetched and step("build_exact", spec.build, False) == 0
        if not retried:
            return result(UNTESTABLE, "test build failed (overlay does not compile here)", toolchain)
    exits = [step(f"test_{i}", spec.test, False) for i in range(1, repeats + 1)]
    passed, failed = sum(1 for e in exits if e == 0), sum(1 for e in exits if e != 0)
    if failed == 0:
        return result(PASS, f"passed {passed}x", toolchain)
    if passed == 0:
        return result(FAIL, f"failed {failed}x", toolchain)
    return result(FLAKY, f"{passed} pass / {failed} fail", toolchain)


class Probe:
    """Evaluates commits of the range by index, each at most once (re-run only to confirm)."""

    def __init__(self, runner, spec, commits):
        self.runner, self.spec, self.commits, self.seen = runner, spec, commits, {}

    def outcome(self, i):
        """Outcome of commit `i`, testing it once if it has not been tested."""
        if i not in self.seen:
            r = evaluate(self.runner, self.spec, self.commits[i], SEARCH_REPEATS)
            print(f"sweep: [{i}] {self.commits[i][:10]} {DEBUG[r['outcome']]} ({r['reason']})", file=sys.stderr)
            self.seen[i] = r
        return self.seen[i]["outcome"]

    def confirm(self, i):
        """Re-test a decisive commit with the full repeats; a description if its outcome changed."""
        before = self.outcome(i)
        if self.spec.repeats <= SEARCH_REPEATS or before == UNTESTABLE:
            return None
        r = evaluate(self.runner, self.spec, self.commits[i], self.spec.repeats)
        print(f"sweep: confirm [{i}] {self.commits[i][:10]} {DEBUG[r['outcome']]} ({r['reason']})", file=sys.stderr)
        self.seen[i] = r
        return None if r["outcome"] == before else f"{self.commits[i][:10]} {DEBUG[before]} -> {DEBUG[r['outcome']]}"

    def testable_near(self, mid, lo, hi):
        """The nearest testable commit to `mid` strictly between lo and hi, within SKIP_RADIUS."""
        for d in range(SKIP_RADIUS + 1):
            for i in (mid - d, mid + d):
                if lo < i < hi:
                    o = self.outcome(i)
                    if o in (PASS, FAIL):
                        return i, o
        return None


def commit_range(spec, fix, start):
    """First-parent commits from `start` (default: the root) to `fix`, oldest first."""
    every = lines(git(spec.repo, ["rev-list", "--first-parent", "--reverse", fix]))
    if start is None:
        return every
    s = trim(git(spec.repo, ["rev-parse", start]))
    if s not in every:
        raise RuntimeError(f"start {s} is not on the first-parent chain of {fix}")
    return every[every.index(s):]


def run(runner, spec, fix, start=None):
    """Sweep one fix: validate the repro, find the PASS->FAIL boundary, confirm, and classify."""
    commits = commit_range(spec, fix, start)
    if len(commits) < 2:
        raise RuntimeError("range must contain the fix and at least its first parent")
    f, p = len(commits) - 1, len(commits) - 2
    probe = Probe(runner, spec, commits)
    sweep = {"fix": commits[f], "start": commits[0], "runner": runner.name, "build": spec.build, "test": spec.test,
             "repeats": spec.repeats, "verdict": "", "reason": "", "last_passing": None, "first_failing": None,
             "untestable_between": 0, "non_monotonic": False, "frontier": None, "confirmation": "",
             "range_commits": len(commits), "commits_tested": 0, "results": []}
    of, op = probe.outcome(f), probe.outcome(p)
    if of != PASS or op != FAIL:
        sweep["verdict"] = "repro-invalid"
        sweep["reason"] = f"expected FAIL on fix^ and PASS on fix, got {DEBUG[op]} / {DEBUG[of]}"
        return _finish(sweep, probe)
    # Frontier: the first commit where the test builds, assuming build-ability is monotonic.
    if probe.outcome(0) != UNTESTABLE:
        frontier = 0
    else:
        untestable, testable = 0, p
        while testable - untestable > 1:
            mid = (untestable + testable) // 2
            if probe.outcome(mid) == UNTESTABLE:
                untestable = mid
            else:
                testable = mid
        frontier = testable
    sweep["frontier"] = commits[frontier]
    lo, hi = frontier - 1, p
    if probe.outcome(frontier) == PASS:
        lo = frontier
        while hi - lo > 1:
            found = probe.testable_near((lo + hi) // 2, lo, hi)
            if found is None:
                break
            i, o = found
            if o == PASS:
                lo = i
            else:
                hi = i
    else:
        hi = frontier
    # Bounded sweep around the boundary, to see non-monotonic outcomes near it.
    for i in range(max(hi - 2, frontier), min(hi + 2, p) + 1):
        probe.outcome(i)
    decisive = [f, p, hi] + ([lo] if lo >= frontier else [])
    unstable = [c for c in (probe.confirm(i) for i in decisive) if c is not None]
    sweep["confirmation"] = (f"decisive commits confirmed x{spec.repeats}" if not unstable
                             else f"UNSTABLE on confirmation: {'; '.join(unstable)}")
    testable_lo = lo >= frontier
    sweep["first_failing"] = commits[hi]
    sweep["last_passing"] = commits[lo] if testable_lo else None
    sweep["untestable_between"] = hi - lo - 1 if testable_lo else 0
    if testable_lo and hi - lo == 1:
        sweep["verdict"], sweep["reason"] = "located", "adjacent last PASS and first FAIL"
    elif testable_lo:
        sweep["verdict"] = "interval"
        sweep["reason"] = (f"bug introduced within {sweep['untestable_between']} untestable commit(s) "
                           "between last PASS and first FAIL")
    elif frontier == 0:
        sweep["verdict"], sweep["reason"] = "left-censored", "test fails from the first commit of the range"
    else:
        sweep["verdict"] = "censored-by-testability"
        sweep["reason"] = (f"test already fails at {commits[frontier][:10]}, the first commit where it compiles "
                           "(build-ability assumed monotonic)")
    return _finish(sweep, probe)


def _finish(sweep, probe):
    """Results in commit order, the number tested, and whether a PASS follows a FAIL before the fix."""
    ordered = [probe.seen[i] for i in sorted(probe.seen)]
    seq = [r["outcome"] for r in ordered if r["outcome"] in (PASS, FAIL)]
    body = seq[:-1]
    sweep["non_monotonic"] = any(a == FAIL and b == PASS for a, b in zip(body, body[1:]))
    sweep["commits_tested"] = len(probe.seen)
    sweep["results"] = ordered
    return sweep


# ---------------------------------------------------------------- commands


def _spec_and_runner(f, tag):
    """The test spec and runner from the sweep/probe flags."""
    from .cli import Failure, need
    home = os.environ.get("HOME", "")

    def number(key, default, signed=False):
        # --repeats is unsigned (u32 in 1.x), --bucket may be negative (i64).
        text = f.get(key, default)
        digits = text[1:] if text[:1] in ("+", "-" if signed else "+") else text
        if not (digits.isascii() and digits.isdigit()):
            raise Failure(f"--{key}: invalid digit found in string")
        return int(text)
    spec = Spec(need(f, "repo"), need(f, "path"), need(f, "overlay"), f.get("build", "cargo test --no-run"),
                need(f, "test"), number("repeats", "3"), f.get("scratch", f"{home}/.cache/bug-age"),
                f.get("logs", f"work/sweep-logs/{tag}"))
    kind = f.get("runner", "docker")
    if kind == "local":
        return spec, Local(spec)
    if kind == "docker":
        tt = f.get("time-travel-script", "spike/timetravel.py")
        return spec, Docker(f.get("image", "bug-age-spike:4"), None if tt == "none" else Path(tt),
                            f"-{f['namespace']}" if "namespace" in f else "", number("bucket", "4", signed=True))
    raise Failure(f"unknown runner '{kind}'")


def _overlay_listing(d):
    """Every overlay file as `relative/path sha256:<hex>`, sorted."""
    out = []
    for dirpath, _, files in os.walk(d):
        for name in files:
            p = Path(dirpath) / name
            out.append(f"{os.path.relpath(p, d)} sha256:{hashlib.sha256(p.read_bytes()).hexdigest()}")
    return sorted(out)


def cmd_sweep(f):
    """`sweep`: Method B for one fix, with a receipt recording inputs and tool versions."""
    from .cli import command_line, emit, need, sha256, tool_version, write
    fix = need(f, "fix")
    spec, runner = _spec_and_runner(f, fix[:12])
    result = run(runner, spec, fix, f.get("start"))
    print(f"sweep: {result['verdict']} — {result['reason']} ({result['commits_tested']} of {result['range_commits']} "
          f"commits tested)", file=sys.stderr)
    report = dumps(result, pretty=True) + "\n"
    versions = {"bug-age": __version__, "git": tool_version("git", ["--version"])}
    if result["runner"] == "docker":
        versions["docker"] = tool_version("docker", ["version", "--format", "{{.Server.Version}} {{.Server.Arch}}"])
        versions["image"] = tool_version("docker", ["image", "inspect", f.get("image", "bug-age-spike:4"),
                                                    "--format", "{{.Id}}"])
    receipt = {
        "command": command_line(),
        "inputs": {"repo_head": trim(git(spec.repo, ["rev-parse", "HEAD"])), "fix": result["fix"],
                   "start": result["start"], "overlay_files": _overlay_listing(spec.overlay)},
        "versions": versions,
        "verdict": result["verdict"],
        "report_sha256": sha256(report),
    }
    out = f.get("out")
    if out is not None:
        write(out, report)
        emit(receipt, f"{out}.receipt.json")
    else:
        emit({"report": result, "receipt": receipt}, None)


def cmd_probe(f):
    """`probe`: test each listed commit with the full repeats, without searching."""
    from .cli import emit, need
    commits = [trim(c) for c in need(f, "commits").split(",")]
    spec, runner = _spec_and_runner(f, f"probe-{commits[0][:12]}")
    results = []
    for c in commits:
        sha = trim(git(spec.repo, ["rev-parse", c]))
        r = evaluate(runner, spec, sha, spec.repeats)
        print(f"probe: {sha[:10]} {DEBUG[r['outcome']]} ({r['reason']})", file=sys.stderr)
        results.append(r)
    emit({"runner": runner.name, "test": spec.test, "repeats": spec.repeats, "results": results}, f.get("out"))
