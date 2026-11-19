# SPDX-License-Identifier: MIT OR Apache-2.0
"""Feasibility for the python profile: can the target be installed and tested at historical commits?

Samples evenly spaced first-parent commits touching the measured path, and for each: chooses the
CPython for its date, installs the project and the target's test dependencies with uv (as of the
commit time with --time-travel, else today's PyPI), checks that the package imports offline, and
runs the target's test command offline twice. Writes report.json and receipt.json in the same
shape as the Rust feasibility spike, so the pipeline and the bundle read both alike.

Usage: python3 -m bug_age.pyfeasibility --config targets/NAME.toml [--samples N] [--time-travel]
"""
import argparse
import datetime as dt
import hashlib
import json
import platform
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

from . import profiles
from .runner import PY_RECIPE, PythonDocker, RunnerError, Spec

ROOT = Path.cwd()
TEST_REPEATS = 2
GO_MIN_SHARE = 0.5
STEP_TIMEOUT = 1800


def git(repo, *args):
    """Run git in `repo`; stripped stdout."""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def hint(log):
    """The last informative line of a step log, without host paths, at most 200 characters."""
    rows = [r.strip() for r in Path(log).read_text(errors="replace").splitlines()[1:] if r.strip()]
    text = rows[-1] if rows else "no output"
    return text.replace(f"{ROOT}/", "").replace(str(Path.home()), "~")[:200]


def totals(log):
    """(passed, failed) from pytest's summary line in a step log."""
    text = Path(log).read_text(errors="replace")
    count = lambda word: sum(int(n) for n in re.findall(rf"(\d+) {word}\b", text.splitlines()[-1] if text else ""))
    return count("passed"), count("failed") + count("errors?")


def probe(runner, spec, sha, cfg, freeze):
    """One sampled commit: install, import check, tests; a record in the Rust report's shape."""
    rec = {"sha": sha, "date": git(spec.repo, "show", "-s", "--format=%cs", sha), "steps": {},
           "lockfile_committed": any(subprocess.run(["git", "-C", str(spec.repo), "cat-file", "-e", f"{sha}:{p}"],
                                                    capture_output=True).returncode == 0
                                     for p in (f"{spec.crate_path}/uv.lock", "uv.lock"))}
    try:
        rec["toolchain"] = runner.stage(spec, sha)
    except RunnerError as e:
        return {**rec, "toolchain": "", "status": "NOT_TESTED", "reason": f"stage: {e}"}
    if not freeze:
        runner.fetch_cmd = re.sub(r" --exclude-newer \S+", "", runner.fetch_cmd)
    logs = spec.logs / sha[:12]

    def step(name, cmd, network):
        code, seconds = runner.exec(spec, cmd, network, logs / f"{name}.log")
        rec["steps"][name] = {"exit": code, "seconds": seconds, "hint": hint(logs / f"{name}.log") if code else ""}
        return code
    if step("install", runner.fetch_cmd, True) != 0:
        return {**rec, "status": "NOT_TESTED", "reason": "dependency install failed: " + rec["steps"]["install"]["hint"]}
    if step("import", f"python -c 'import {cfg['import']}'", False) != 0:
        return {**rec, "status": "BUILD_FAILED", "reason": rec["steps"]["import"]["hint"]}
    runs = []
    for r in range(TEST_REPEATS):
        code = step(f"test_{r + 1}", cfg["test"], False)
        runs.append((code, *totals(logs / f"test_{r + 1}.log")))
    rec["test_runs"] = [{"exit": c, "passed": p, "failed": f} for c, p, f in runs]
    if len({c for c, _, _ in runs}) > 1:
        return {**rec, "status": "FLAKY", "reason": "test outcome differed across repeats"}
    code, passed, _ = runs[0]
    if code != 0:
        return {**rec, "status": "TESTS_FAILED", "reason": rec["steps"]["test_1"]["hint"]}
    if passed == 0:
        return {**rec, "status": "NOT_TESTED", "reason": "installed but zero tests executed"}
    return {**rec, "status": "BUILT_AND_TESTED", "reason": f"{passed} tests passed x{TEST_REPEATS}"}


def main(argv=None):
    """Sample commits, probe each, write report.json and receipt.json."""
    ap = argparse.ArgumentParser(prog="python3 -m bug_age.pyfeasibility")
    ap.add_argument("--config", required=True)
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--time-travel", action="store_true")
    args = ap.parse_args(argv)
    cfg = profiles.target(tomllib.loads(Path(args.config).read_text()))
    if cfg["profile"] != "python" or "import" not in cfg or "test" not in cfg:
        raise SystemExit("pyfeasibility needs profile = \"python\", import and test in the target config")
    repo, path = ROOT / cfg["work_dir"], cfg["crate_path"]
    out = ROOT / cfg["spike_dir"] / ("results-timetravel" if args.time_travel else "results")
    out.mkdir(parents=True, exist_ok=True)
    head = git(repo, "rev-parse", "HEAD")
    history = git(repo, "rev-list", "--first-parent", "--reverse", head, "--", path).splitlines()
    n = args.samples
    picks = sorted({round(i * (len(history) - 1) / (n - 1)) for i in range(n)})
    deps = cfg.get("test_deps", ["pytest"])
    runner = PythonDocker(f"-feas{'-tt' if args.time_travel else ''}", cfg.get("install", "."), deps)
    empty = Path(tempfile.mkdtemp(prefix="bug-age-noverlay-"))
    spec = Spec(repo, path, empty, "", cfg["test"], TEST_REPEATS, ROOT / "work" / "scratch",
                ROOT / "work" / f"feasibility-logs-{cfg['name']}{'-tt' if args.time_travel else ''}", STEP_TIMEOUT)
    results = []
    for i in picks:
        r = probe(runner, spec, history[i], cfg, args.time_travel)
        print(f"[{len(results) + 1}/{len(picks)}] {r['sha'][:10]} {r['date']} {r['toolchain']:<11} {r['status']}: {r['reason']}",
              flush=True)
        results.append(r)
    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    share = counts.get("BUILT_AND_TESTED", 0) / len(results)
    verdict = "GO" if share >= GO_MIN_SHARE and not counts.get("FLAKY") else "NO-GO"
    install = " ".join([cfg.get("install", "."), *deps])
    report = {
        "ticket": None,
        "subject": {"repo": cfg["repo_url"], "crate_path": path, "head": head,
                    "first_parent_commits_touching_crate": len(history),
                    "history_window": [results[0]["date"], results[-1]["date"]]},
        "method": {"profile": "python",
                   "sampling": f"{len(picks)} evenly spaced first-parent commits touching {path}/",
                   "toolchain_rule": "CPython minor released >=14 days before the commit date, at least 3.8 (uv's floor), "
                                     "raised to requires-python; image python:<minor> with uv 0.9.2",
                   "dependency_resolution": ("uv pip install --exclude-newer <commit time>: every package as published by "
                                             "the commit time" if args.time_travel else "uv pip install: today's PyPI"),
                   "build": f"uv pip install {install} (network), then python -c 'import {cfg['import']}' in docker --network none",
                   "test": f"{cfg['test']} in docker --network none, environment read-only, repeated {TEST_REPEATS}x",
                   "not_covered": cfg.get("not_covered", "tests outside the configured test command"),
                   "decision_rule": f"GO iff BUILT_AND_TESTED share >= {GO_MIN_SHARE:.0%} and no FLAKY"},
        "counts": counts, "built_and_tested_share": round(share, 3), "verdict": verdict, "results": results,
    }
    body = json.dumps(report, indent=2, sort_keys=True)
    (out / "report.json").write_text(body)
    tool = lambda *c: subprocess.run(c, capture_output=True, text=True).stdout.strip().splitlines()[0]
    receipt = {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "command": "python3 -m bug_age.pyfeasibility --samples %d%s" % (n, " --time-travel" if args.time_travel else ""),
        "inputs": {"repo": cfg["repo_url"], "head": head, "sampled_shas": [r["sha"] for r in results],
                   "install": install, "import": cfg["import"], "test": cfg["test"]},
        "versions": {"python": platform.python_version(), "git": tool("git", "--version"),
                     "docker": tool("docker", "version", "--format", "{{.Server.Version}} {{.Server.Arch}}"),
                     "images": dict(sorted(runner.images.items())),
                     "image_recipe": hashlib.sha256(PY_RECIPE.read_bytes()).hexdigest(),
                     "host": f"{platform.system()} {platform.machine()}",
                     "toolchains": sorted({r["toolchain"] for r in results})},
        "totals": counts, "verdict": verdict,
        "outputs": {str((out / "report.json").relative_to(ROOT)): hashlib.sha256(body.encode()).hexdigest()},
    }
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True))
    print(json.dumps({"counts": counts, "share": round(share, 3), "verdict": verdict}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
