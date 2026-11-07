#!/usr/bin/env python3
"""BUGAGE-4 driver: sweep every repro under results/<repo>/repros/<fix>/overlay with `bug-age sweep`
(docker runner), then compare Method B with Method A (szz.json) in results/<repo>/AB.md.

Range rule (fixed before any sweep, independent of Method A): the sweep starts at the first
first-parent commit dated at most 3 years before the fix (or the root). Bugs older than that are
reported left-censored rather than borrowing Method A's answer.

A-check (separate, labelled column): Method A's nominee and its parent are probed with the same
test. It verifies A behaviourally where the test compiles; it never changes Method B's verdict.

Usage: python3 results/run_repros.py results/tokenizers work/tokenizers tokenizers
       [--only ID ...] [--render-only] [--acheck-only]
"""
import datetime as dt, hashlib, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # repo root; stripped from recorded paths

WINDOW_DAYS = 3 * 365                                # sweep range: at most three years before the fix
BUILD = "cargo test --test bugage_repro --no-run"   # compile the regression test only
TEST = "cargo test --test bugage_repro"             # run the regression test


def git(repo, *args):
    """Run git in `repo` and return stripped stdout; raises on failure."""
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


def range_start(repo, fix):
    """Return the first first-parent commit dated at most WINDOW_DAYS before the fix, or the root."""
    cutoff = int(git(repo, "show", "-s", "--format=%ct", fix)) - WINDOW_DAYS * 86400
    for line in git(repo, "rev-list", "--first-parent", "--reverse", "--format=%H %ct", fix).splitlines():
        if not line.startswith("commit "):
            sha, ct = line.split()
            if int(ct) >= cutoff:
                return sha
    raise SystemExit(f"no commits for {fix}")


def sweep(res, repo, crate, rid, worker="w0"):
    """Run `bug-age sweep` (Docker) for one regression test and write its report, receipt and log."""
    fix = git(repo, "rev-parse", rid)
    out = res / "repros" / rid / "sweep.json"
    cmd = ["target/debug/bug-age", "sweep", "--repo", str(repo), "--path", crate, "--fix", fix,
           "--start", range_start(repo, fix), "--overlay", str(res / "repros" / rid / "overlay"),
           "--runner", "docker", "--repeats", "3", "--build", BUILD, "--test", TEST,
           "--logs", f"work/sweep-logs/{rid}", "--out", str(out), "--namespace", worker]
    print(f"== {rid}: {' '.join(cmd[2:])}", flush=True)
    p = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    (res / "repros" / rid / "sweep.stderr.log").write_text(p.stderr.replace(f"{ROOT}/", "").replace(str(Path.home()), "~"))
    if p.returncode != 0:
        print(f"!! {rid} failed: {p.stderr.strip().splitlines()[-1:]}", flush=True)
        return
    rec = out.with_name("sweep.json.receipt.json")
    rec.write_text(rec.read_text().replace(f"{ROOT}/", "").replace(str(Path.home()), "~"))
    print(f"   {json.loads(out.read_text())['verdict']}", flush=True)


def acheck(res, repo, crate, rid):
    """Probe Method A's nominee and its parent with the same test and write acheck.json."""
    fix = git(repo, "rev-parse", rid)
    szz = {b["fix"]: b for b in json.loads((res / "szz.json").read_text())["bugs"]}
    a = szz[fix]["nominees"][0]["sha"]
    out = res / "repros" / rid / "acheck.json"
    cmd = ["target/debug/bug-age", "probe", "--repo", str(repo), "--path", crate, "--commits", f"{a}^,{a}",
           "--overlay", str(res / "repros" / rid / "overlay"), "--runner", "docker", "--repeats", "3",
           "--build", BUILD, "--test", TEST, "--logs", f"work/sweep-logs/acheck-{rid}", "--out", str(out)]
    print(f"== A-check {rid}: nominee {a[:10]} and parent", flush=True)
    p = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        print(f"!! A-check {rid} failed: {p.stderr.strip().splitlines()[-1:]}", flush=True)
        return
    out.write_text(out.read_text().replace(f"{ROOT}/", "").replace(str(Path.home()), "~"))
    print("   " + " / ".join(r["outcome"] for r in json.loads(out.read_text())["results"]), flush=True)


ACHECK = {("PASS", "FAIL"): "A confirmed (parent PASS, nominee FAIL)",
          ("FAIL", "FAIL"): "A too late: bug already present before the nominee",
          ("PASS", "PASS"): "A refuted: test still passes at the nominee",
          ("UNTESTABLE", "FAIL"): "A plausible: bug present at the nominee, where the tested code first compiles",
          ("UNTESTABLE", "UNTESTABLE"): "A untested: test cannot compile at the nominee or its parent"}


def acheck_cell(d):
    """Describe one A-check result for the AB.md table."""
    f = d / "acheck.json"
    if not f.is_file():
        return "not run"
    outs = tuple(r["outcome"] for r in json.loads(f.read_text())["results"])
    return ACHECK.get(outs, f"inconclusive ({' / '.join(outs)}): test does not run at the nominee or its parent")


def when(repo, sha):
    """Return (committer unix time, committer date) of a commit."""
    return int(git(repo, "show", "-s", "--format=%ct", sha)), git(repo, "show", "-s", "--format=%cs", sha)


def is_ancestor(repo, a, b):
    """True if commit `a` is an ancestor of commit `b`."""
    return subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b]).returncode == 0


def relation(repo, a, b):
    """How Method B's first failing commit relates to Method A's nominee."""
    if a == b:
        return "agree"
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", a, b]).returncode == 0:
        n = git(repo, "rev-list", "--count", f"{a}..{b}")
        return f"B later by {n} commits"
    if subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", b, a]).returncode == 0:
        n = git(repo, "rev-list", "--count", f"{b}..{a}")
        return f"B earlier by {n} commits"
    return "unrelated branches"


def render(res, repo):
    """Write AB.md: one row per regression test comparing Method B with Method A."""
    szz = {b["fix"]: b for b in json.loads((res / "szz.json").read_text())["bugs"]}
    rows, inputs = [], []
    for d in sorted((res / "repros").iterdir()):
        f = d / "sweep.json"
        if not f.is_file():
            rows.append(f"| `{d.name}` | — | — | not swept | — | — | — |")
            continue
        raw = f.read_bytes()
        inputs.append(f"- `repros/{d.name}/sweep.json` sha256 `{hashlib.sha256(raw).hexdigest()}`")
        s = json.loads(raw)
        a = szz[s["fix"]]["nominees"][0]["sha"]
        fix_t, _ = when(repo, s["fix"])
        a_t, a_d = when(repo, a)
        b = s["first_failing"]
        if b and s["verdict"] in ("located", "left-censored", "censored-by-testability", "interval"):
            b_t, b_d = when(repo, b)
            exact = s["verdict"] == "located"
            b_days = ("" if exact else "≥ ") + str(round((fix_t - b_t) / 86400, 1))
            note = {"left-censored": " — present at range start",
                    "censored-by-testability": " — first commit where the test compiles",
                    "interval": f" — after {s['untestable_between']} untestable commits"}.get(s["verdict"], "")
            b_cell = f"`{b[:10]}` ({b_d}){note}"
            rel = relation(repo, a, b)
            if not exact and rel.startswith("B later"):
                rel = "consistent: A predates B's earliest testable FAIL" if s["verdict"] != "left-censored" else "consistent: A predates the window"
        else:
            b_cell, b_days, rel = "—", "—", "n/a"
        check = acheck_cell(d)
        passes_after_a = [r["sha"] for r in s["results"] if r["outcome"] == "PASS" and r["sha"] != s["fix"]
                          and r["sha"] != a and is_ancestor(repo, a, r["sha"])]
        if passes_after_a:
            check = f"A refuted by B's sweep: test PASSes at `{passes_after_a[-1][:10]}`, after the nominee"
        rows.append(f"| `{d.name}` | `{a[:10]}` ({a_d}) | {b_cell} | {s['verdict']} | {rel} | "
                    f"{round((fix_t - a_t) / 86400, 1)} | {b_days} | {check} | {s['commits_tested']}/{s['range_commits']} |")
    lines = ["# Method A vs Method B — per-bug lifetimes", "",
             "A = SZZ nominee (latest toucher of the lines the fix changed). "
             "B = first commit where the regression test fails, found by `bug-age sweep` "
             f"(date-matched toolchain, time-travel dependencies, `--network none`, 3 repeats; range = "
             f"{WINDOW_DAYS // 365} years before the fix).", "",
             "B days marked ≥ are lower bounds (censored). A-check probes A's nominee and its parent with the "
             "same test; it is reported separately and never changes B's verdict.", "",
             "| Fix | A: nominated introducer | B: first failing commit | B verdict | A vs B | A days | B days | A-check | Commits tested / in range |",
             "|---|---|---|---|---|---|---|---|---|", *rows, "", "## Inputs", "", *inputs]
    (res / "AB.md").write_text("\n".join(lines) + "\n")
    print(res / "AB.md")


if __name__ == "__main__":
    res, repo, crate = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    only = [a for a in sys.argv[sys.argv.index("--only") + 1:] if not a.startswith("--")] if "--only" in sys.argv else None
    ids = [d.name for d in sorted((res / "repros").iterdir()) if only is None or d.name in only]
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 2
    if "--render-only" not in sys.argv and "--acheck-only" not in sys.argv:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(workers) as pool:  # each worker gets its own docker volume namespace
            list(pool.map(lambda iw: sweep(res, repo, crate, iw[1], f"w{iw[0] % workers}"), enumerate(ids)))
    if "--render-only" not in sys.argv and "--no-acheck" not in sys.argv:
        for rid in ids:
            acheck(res, repo, crate, rid)
    render(res, repo)
