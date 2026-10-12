#!/usr/bin/env python3
"""BUGAGE-1 feasibility spike: can the target crate be built and tested at historical commits?

Throwaway evidence script (stdlib only). Every number in the report is produced here; nothing is
hand-entered. Usage:  python3 spike/feasibility.py [--samples 20]
Needs: git, docker (image built from spike/Dockerfile as bug-age-spike:4), network for clone/fetch.
Build and test steps run in a Linux container with --network none. A native macOS run was abandoned:
the current Xcode linker rejects rlibs from old toolchains (see results/smoke-native-macos.*).
"""
from __future__ import annotations

import argparse, datetime as dt, hashlib, json, os, platform, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
REPO = WORK / "tokenizers"
REPO_URL = "https://github.com/huggingface/tokenizers.git"
CRATE = "tokenizers"                       # path of the Rust core crate inside the repo
OUT = ROOT / "spike" / "results"
LOGS = WORK / "logs"
TICKET = "BUGAGE-1"
TIME_TRAVEL = False                         # BUGAGE-5: resolve lockfile-less commits as of their date
INDEX_VOLUME = "bugage-index"
# Worktree and target dir must live outside this repo: an old commit without [workspace] would
# otherwise be absorbed into bug-age's own Cargo workspace (found by the first smoke run).
SCRATCH = Path(os.environ.get("BUG_AGE_SCRATCH", Path.home() / ".cache" / "bug-age"))
# Decision rule, fixed before any run: GO if at least this share of sampled commits is BUILT+TESTED
# and no commit is FLAKY.
GO_MIN_SHARE = 0.70
TEST_REPEATS = 2
IMAGE = "bug-age-spike:4"
TARGET_VOLUME = "bugage-target"               # wiped before every commit
SRC_VOLUME = "bugage-src"                     # commit tree, copied in with git archive; wiped per commit
RUST_1_0 = dt.date(2015, 5, 15)            # stable cadence: one minor release every 42 days


def run(cmd, cwd=None, env=None, timeout=1800, log=None):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, timeout=timeout)
        code, out = p.returncode, p.stdout
    except subprocess.TimeoutExpired as e:
        code, out = 124, f"TIMEOUT after {timeout}s\n{e.stdout or ''}{e.stderr or ''}"
    if log:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"$ {' '.join(cmd)}\n{out}")
    return code, out, round(time.time() - t0, 1)


def git(*args):
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True).stdout.strip()


def toolchain_for(day: dt.date, rust_version: str | None) -> tuple[str, int]:
    """Latest stable released >=14 days before the commit, raised to the crate's rust-version."""
    minor = ((day - dt.timedelta(days=14)) - RUST_1_0).days // 42
    if rust_version:
        m = re.match(r"1\.(\d+)", rust_version)
        if m:
            minor = max(minor, int(m.group(1)))
    return f"1.{minor}", minor


def test_totals(out: str) -> tuple[int, int]:
    passed = sum(int(x) for x in re.findall(r"test result: \w+\. (\d+) passed", out))
    failed = sum(int(x) for x in re.findall(r"(\d+) failed;", out))
    return passed, failed


HINTS = [
    (r"edition2024|feature `edition|unknown edition|edition .* is unstable|supported edition values|older than the `20\d\d` edition", "edition newer than toolchain"),
    (r"requires rustc|rust-version|is not supported by the following package", "dependency needs newer rustc"),
    (r"failed to select a version|no matching package", "dependency resolution failed"),
    (r"data/\S*\W+(No such file|not found)|(No such file|not found)\W+\S*data/", "missing fixture data"),
    (r"Could not resolve host|Network is unreachable|failed to lookup address|Temporary failure in name resolution", "network access attempted"),
    (r"Unable to find libclang|is `cmake` not installed|linker `\S+` not found|pkg-config", "missing system build dependency"),
    (r"TIMEOUT", "timeout"),
    (r"error\[E\d+\]", "compile error"),
]


def hint(out: str) -> str:
    for pat, label in HINTS:
        if re.search(pat, out, re.I):
            return label
    return "unclassified"


def fixture_urls(wt: Path) -> list[dict]:
    mk = wt / CRATE / "Makefile"
    if not mk.is_file():
        return []
    urls = sorted(set(re.findall(r"https?://[^\s\"')]+", mk.read_text(errors="replace"))))
    res = []
    for u in urls:
        code, out, _ = run(["curl", "-sIL", "-o", "/dev/null", "-w", "%{http_code}", "-m", "20", u], timeout=40)
        res.append({"url": u, "http": out.strip() if code == 0 else f"curl-exit-{code}"})
    return res


class HarnessError(RuntimeError):
    """The harness itself failed; the run must stop rather than record this as a result."""


def stage_source(sha: str) -> None:
    """Copy the commit tree into a Docker volume. Host bind mounts of a per-commit worktree served a
    stale view inside the Colima VM in two earlier runs (missing Cargo.toml), so source never comes
    from a host mount."""
    archive = subprocess.Popen(["git", "-C", str(REPO), "archive", "--format=tar", sha], stdout=subprocess.PIPE)
    untar = subprocess.run(["docker", "run", "-i", "--rm", "-v", f"{SRC_VOLUME}:/src", IMAGE,
                            "tar", "-x", "-C", "/src"], stdin=archive.stdout, capture_output=True, text=True)
    archive.stdout.close()
    if archive.wait() != 0 or untar.returncode != 0:
        raise HarnessError(f"staging {sha} failed: {untar.stderr.strip()[-300:]}")
    check = subprocess.run(["docker", "run", "--rm", "-v", f"{SRC_VOLUME}:/src", IMAGE,
                            "test", "-f", f"/src/{CRATE}/Cargo.toml"])
    if check.returncode != 0:
        raise HarnessError(f"staged tree for {sha} has no {CRATE}/Cargo.toml")


def stage_time_travel_index(sha: str, wt: Path) -> dict:
    """Build the as-of-commit index on the host, copy it into the index volume and point the staged
    tree's cargo at it. Index paths are per commit so cargo's index cache never mixes cutoffs."""
    import timetravel
    cutoff = dt.datetime.fromtimestamp(int(git("show", "-s", "--format=%ct", sha)), dt.timezone.utc)
    cutoff_s = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = SCRATCH / "tt-index" / sha[:12]
    if out.exists():
        subprocess.run(["rm", "-rf", str(out)], check=True)
    stats = timetravel.build_index(wt, CRATE, cutoff_s, SCRATCH / "index-cache", out)
    tar = subprocess.Popen(["tar", "--no-xattrs", "-C", str(out), "-cf", "-", "."], stdout=subprocess.PIPE,
                           env={**os.environ, "COPYFILE_DISABLE": "1"})
    untar = subprocess.run(["docker", "run", "-i", "--rm", "-v", f"{INDEX_VOLUME}:/index", IMAGE, "sh", "-c",
                            f"rm -rf /index/{sha[:12]} && mkdir -p /index/{sha[:12]} && tar -x -C /index/{sha[:12]}"],
                           stdin=tar.stdout, capture_output=True, text=True)
    tar.stdout.close()
    cfg = f'[source.crates-io]\nreplace-with = "tt"\n[source.tt]\nregistry = "file:///index/{sha[:12]}"\n'
    wrote = subprocess.run(["docker", "run", "--rm", "-v", f"{SRC_VOLUME}:/src", IMAGE, "sh", "-c",
                            f"mkdir -p /src/.cargo && printf '{cfg}' > /src/.cargo/config"], capture_output=True, text=True)
    if tar.wait() != 0 or untar.returncode != 0 or wrote.returncode != 0:
        raise HarnessError(f"time-travel staging for {sha} failed: {untar.stderr[-300:]}{wrote.stderr[-300:]}")
    return stats


def probe(sha: str, idx: int) -> dict:
    wt, logs = SCRATCH / "wt", LOGS / sha[:12]
    run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(wt)])
    git("worktree", "add", "--force", "--detach", str(wt), sha)
    run(["docker", "volume", "rm", "-f", TARGET_VOLUME, SRC_VOLUME])
    stage_source(sha)
    crate = wt / CRATE
    day = dt.date.fromisoformat(git("show", "-s", "--format=%cs", sha))
    manifest = (crate / "Cargo.toml").read_text(errors="replace")
    rv = re.search(r'^rust-version\s*=\s*"([^"]+)"', manifest, re.M)
    ed = re.search(r'^edition\s*=\s*"([^"]+)"', manifest, re.M)
    lic = re.search(r'^license\s*=\s*"([^"]+)"', manifest, re.M)
    tc, minor = toolchain_for(day, rv.group(1) if rv else None)
    rec = {
        "index": idx, "sha": sha, "date": day.isoformat(),
        "edition": ed.group(1) if ed else "2015", "rust_version_field": rv.group(1) if rv else None,
        "license": lic.group(1) if lic else None,
        "lockfile_committed": (crate / "Cargo.lock").is_file() or (wt / "Cargo.lock").is_file(),
        "pinned_toolchain_file": (crate / "rust-toolchain").read_text().strip() if (crate / "rust-toolchain").is_file() else None,
        "toolchain": tc,
        "fixture_dependent_test_files": sum(
            1 for f in (crate / "tests").glob("*.rs") if "data/" in f.read_text(errors="replace")
        ) if (crate / "tests").is_dir() else 0,
        "fixture_urls": fixture_urls(wt), "steps": {},
    }
    if TIME_TRAVEL and not rec["lockfile_committed"]:
        rec["time_travel"] = stage_time_travel_index(sha, wt)
    def step(name, cmd, offline, timeout=1800):
        docker = ["docker", "run", "--rm", *(["--network", "none"] if offline else []),
                  "-v", f"{SRC_VOLUME}:/src", "-v", f"{INDEX_VOLUME}:/index", "-v", "bugage-rustup:/rustup", "-v", "bugage-cargo:/cargo",
                  "-v", f"{TARGET_VOLUME}:/target", "-e", "CARGO_TARGET_DIR=/target",
                  "-e", "CARGO_TERM_COLOR=never", "-w", f"/src/{CRATE}", IMAGE]
        code, out, secs = run(docker + cmd, timeout=timeout, log=logs / f"{name}.log")
        rec["steps"][name] = {"cmd": " ".join(cmd), "exit": code, "seconds": secs, "network_none": offline,
                              **({} if code == 0 else {"hint": hint(out), "tail": out.strip().splitlines()[-12:]})}
        return code, out

    install = ["rustup", "toolchain", "install", tc, "--profile", "minimal", "--no-self-update"]
    if step("toolchain", install, False, timeout=900)[0] != 0:
        return {**rec, "status": "NOT_TESTED", "reason": "toolchain install failed"}
    if step("fetch", ["cargo", f"+{tc}", "fetch"], False, timeout=900)[0] != 0:
        return {**rec, "status": "NOT_TESTED", "reason": "dependency fetch/resolution failed: "
                + rec["steps"]["fetch"]["hint"]}
    if step("build", ["cargo", f"+{tc}", "build", "--all", "--offline"], True)[0] != 0:
        return {**rec, "status": "BUILD_FAILED", "reason": rec["steps"]["build"]["hint"]}
    runs = []
    for r in range(TEST_REPEATS):
        code, out = step(f"test_{r + 1}", ["cargo", f"+{tc}", "test", "--all", "--lib", "--offline"], True)
        runs.append((code, *test_totals(out)))
    rec["test_runs"] = [{"exit": c, "passed": p, "failed": f} for c, p, f in runs]
    if len({c for c, _, _ in runs}) > 1:
        return {**rec, "status": "FLAKY", "reason": "test outcome differed across repeats"}
    code, passed, _ = runs[0]
    if code != 0:
        return {**rec, "status": "TESTS_FAILED", "reason": rec["steps"]["test_1"]["hint"]}
    if passed == 0:
        return {**rec, "status": "NOT_TESTED", "reason": "build ok but zero unit tests executed"}
    return {**rec, "status": "BUILT_AND_TESTED", "reason": f"{passed} unit tests passed x{TEST_REPEATS}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--time-travel", action="store_true",
                    help="BUGAGE-5: resolve lockfile-less commits against a crates.io index as of the commit date")
    ap.add_argument("--reclassify", action="store_true",
                    help="recompute failure hints from saved logs with the current HINTS table and rewrite outputs")
    args = ap.parse_args()
    global OUT, LOGS, TICKET, TIME_TRAVEL
    if args.time_travel:
        OUT, LOGS, TICKET, TIME_TRAVEL = ROOT / "spike" / "results-timetravel", WORK / "logs-tt", "BUGAGE-5", True
    if args.reclassify:
        return reclassify()
    if not REPO.is_dir():
        subprocess.run(["git", "clone", "-q", REPO_URL, str(REPO)], check=True)
    head = git("rev-parse", "HEAD")
    history = git("rev-list", "--first-parent", "--reverse", head, "--", CRATE).splitlines()
    n = args.samples
    picks = sorted({round(i * (len(history) - 1) / (n - 1)) for i in range(n)})
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for i in picks:
        r = probe(history[i], i)
        print(f"[{len(results) + 1}/{len(picks)}] {r['sha'][:10]} {r['date']} {r['toolchain']:<28} {r['status']}: {r['reason']}",
              flush=True)
        results.append(r)
        (OUT / "partial.json").write_text(json.dumps(results, indent=2))
    run(["git", "-C", str(REPO), "worktree", "remove", "--force", str(SCRATCH / "wt")])
    return write_outputs(results, head, len(history), n)


REASON_PREFIX = {"NOT_TESTED": ("fetch", "dependency fetch/resolution failed: "),
                 "BUILD_FAILED": ("build", ""), "TESTS_FAILED": ("test_1", "")}


def reclassify() -> int:
    """Re-derive hints from saved step logs; statuses, exits and test counts are untouched."""
    rep = json.loads((OUT / "report.json").read_text())
    for r in rep["results"]:
        for name, st in r["steps"].items():
            if st["exit"] != 0:
                log = (LOGS / r["sha"][:12] / f"{name}.log").read_text(errors="replace")
                st["hint"] = hint(log.split("\n", 1)[1])  # line 1 is the "$ docker run ..." header
        step, prefix = REASON_PREFIX.get(r["status"], (None, ""))
        if step and r["steps"].get(step, {}).get("exit", 0) != 0:
            r["reason"] = prefix + r["steps"][step]["hint"]
    n = int(json.loads((OUT / "receipt.json").read_text())["command"].split("--samples ")[1].split()[0])
    return write_outputs(rep["results"], rep["subject"]["head"],
                         rep["subject"]["first_parent_commits_touching_crate"], n, reclassified=True)


def sanitize(obj):
    """Blameless + leak-safe outputs: no commit subjects (may embed usernames), no host home paths."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items() if k != "subject" or not isinstance(v, str)}
    if isinstance(obj, list):
        return [sanitize(v) for v in obj]
    return obj.replace(str(Path.home()), "~") if isinstance(obj, str) else obj


def write_outputs(results, head, history_len, n, reclassified=False) -> int:
    results = sanitize(results)
    picks = results
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    ok = counts.get("BUILT_AND_TESTED", 0)
    share = ok / len(results)
    verdict = "GO" if share >= GO_MIN_SHARE and not counts.get("FLAKY") else "NO-GO"
    report = {
        "ticket": TICKET,
        "subject": {"repo": REPO_URL, "crate_path": CRATE, "head": head,
                    "first_parent_commits_touching_crate": history_len,
                    "history_window": [results[0]["date"], results[-1]["date"]]},
        "method": {"sampling": f"{len(picks)} evenly spaced first-parent commits touching {CRATE}/",
                   "toolchain_rule": "latest stable released >=14 days before commit date, raised to rust-version; "
                                     "aarch64-unknown-linux-gnu in " + IMAGE,
                   "dependency_resolution": ("lockfile-less commits: crates.io index filtered to versions published by "
                                             "the commit time (yank state reset); lockfile commits: committed lock")
                                            if TIME_TRAVEL else "committed Cargo.lock if present, else today's crates.io",
                   "build": "cargo build --all --offline in docker --network none",
                   "test": f"cargo test --all --lib --offline (all workspace members' unit tests) in docker --network none, repeated {TEST_REPEATS}x",
                   "not_covered": "integration tests under tests/ (need downloaded fixtures), benches, bindings",
                   "decision_rule": f"GO iff BUILT_AND_TESTED share >= {GO_MIN_SHARE:.0%} and no FLAKY"},
        "counts": counts, "built_and_tested_share": round(share, 3), "verdict": verdict,
        "results": results,
    }
    body = json.dumps(report, indent=2, sort_keys=True)
    (OUT / "report.json").write_text(body)
    (OUT / "partial.json").unlink(missing_ok=True)
    tool = lambda *c: subprocess.run(c, capture_output=True, text=True).stdout.strip().splitlines()[0]
    receipt = {
        "ticket": TICKET, "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "command": "python3 spike/feasibility.py --samples %d%s" % (n, " --time-travel" if TIME_TRAVEL else ""),
        **({"post_processing": "python3 spike/feasibility.py --reclassify%s" % (" --time-travel" if TIME_TRAVEL else "")}
           if reclassified else {}),
        "inputs": {"repo": REPO_URL, "head": head, "sampled_shas": [r["sha"] for r in results]},
        "versions": {"python": platform.python_version(), "git": tool("git", "--version"),
                     "docker": tool("docker", "version", "--format", "{{.Server.Version}} {{.Server.Arch}}"),
                     "image": tool("docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"),
                     "host": f"{platform.system()} {platform.machine()}",
                     "toolchains": sorted({r["toolchain"] for r in results})},
        "totals": counts, "verdict": verdict,
        "outputs": {str((OUT / "report.json").relative_to(ROOT)): hashlib.sha256(body.encode()).hexdigest()},
    }
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True))
    print(json.dumps({"counts": counts, "share": round(share, 3), "verdict": verdict}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
