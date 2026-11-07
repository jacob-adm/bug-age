#!/usr/bin/env python3
"""Timing benchmarks derived only from committed run records.

    python3 scripts/timings.py [--check]

Reads the step durations already recorded by real runs, and nothing else:
  - results/<target>/pipeline.json            per-stage wall time of the last pipeline run
  - <spike dir>/results*/report.json          per-step time of every feasibility sample (Docker)
  - results/<target>/repros/*/sweep.json       per-step time of every commit a Method B sweep tested

Writes results/TIMINGS.md (full tables) and rewrites the block between the timing markers in
README.md. With --check, exits 1 if either file is out of date (used in CI).

Step times cover fetch, build and test commands only. They exclude container staging, toolchain
installs and time-travel index builds, which the runs did not record, so real wall time is longer.
"""
import argparse, json, re, statistics, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BEGIN, END = "<!-- timings:begin -->", "<!-- timings:end -->"
# Results directory -> label. `bench` is a re-run of the tokenizers sweeps with the current search
# (compile-frontier binary search and adaptive repeats); `tokenizers` holds the first, slower run.
LABELS = {"bench": "tokenizers, current sweep search", "tokenizers": "tokenizers, first run (older search)"}

# (target name, feasibility directory holding results/ and results-timetravel/)
TARGETS = [("tokenizers", ROOT / "spike"), ("rust-sdk", ROOT / "results" / "rust-sdk" / "spike")]


def committed(pattern):
    """Committed files matching a git pathspec glob, so local scratch runs never change the output."""
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", pattern], capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in sorted(out.splitlines())]


def mins(seconds):
    """Human duration: seconds under two minutes, else minutes, else hours."""
    if seconds < 120:
        return f"{seconds:.0f} s"
    if seconds < 7200:
        return f"{seconds / 60:.0f} min"
    return f"{seconds / 3600:.1f} h"


def host():
    """Machine the Docker runs used, from the tokenizers feasibility receipt."""
    v = json.loads((ROOT / "spike" / "results" / "receipt.json").read_text()).get("versions", {})
    return f"{v.get('host', 'unknown host')}, Docker {v.get('docker', 'unknown')}"


def feasibility_rows():
    """One row per feasibility run: samples, total and per-sample step time, by step."""
    rows = []
    for name, d in TARGETS:
        for run, label in [("results", "today's registry"), ("results-timetravel", "dated dependencies")]:
            f = d / run / "report.json"
            if not f.is_file():
                continue
            samples = json.loads(f.read_text())["results"]
            per = [sum(s["seconds"] for s in r.get("steps", {}).values()) for r in samples]
            built = [t for t, r in zip(per, samples) if r["status"] == "BUILT_AND_TESTED"]
            rows.append({"target": name, "run": label, "n": len(samples), "total": sum(per),
                         "median": statistics.median(per) if per else 0, "max": max(per, default=0),
                         "built_median": statistics.median(built) if built else None,
                         "src": f.relative_to(ROOT).as_posix()})
    return rows


def sweep_rows():
    """One row per Method B sweep: commits tested, total and per-commit step time."""
    rows = []
    for f in committed("results/*/repros/*/sweep.json"):
        s = json.loads(f.read_text())
        per = [sum(st["seconds"] for st in r["steps"]) for r in s["results"]]
        rows.append({"target": LABELS.get(f.parts[-4], f.parts[-4]), "id": f.parent.name, "verdict": s["verdict"], "n": len(per),
                     "range": s["range_commits"], "total": sum(per), "median": statistics.median(per) if per else 0,
                     "src": f.relative_to(ROOT).as_posix()})
    return rows


def pipeline_rows():
    """Stages that actually ran (status OK) in each target's last recorded pipeline run."""
    rows = []
    for f in committed("results/*/pipeline.json"):
        p = json.loads(f.read_text())
        for s in p["stages"]:
            if s["status"] == "OK" and s["stage"] != "clone":
                rows.append({"target": p["target"], "stage": s["stage"], "seconds": s["seconds"],
                             "src": f.relative_to(ROOT).as_posix()})
    return rows


def wall_times():
    """End-to-end wall time of unattended sweep runs, from each committed SUMMARY.md."""
    rows = []
    for f in committed("results/*/SUMMARY.md"):
        m = re.search(r"wall time: (\d+) min", f.read_text())
        n = len(committed(f"results/{f.parent.name}/repros/*/sweep.json"))
        if m:
            rows.append({"target": LABELS.get(f.parent.name, f.parent.name), "minutes": int(m.group(1)), "sweeps": n,
                         "src": f.relative_to(ROOT).as_posix()})
    return rows


def render():
    """Return (TIMINGS.md text, README block text)."""
    feas, sweeps, pipe, walls = feasibility_rows(), sweep_rows(), pipeline_rows(), wall_times()
    current = [r for r in sweeps if r["target"] == LABELS["bench"]] or sweeps
    sweep_total = sum(r["total"] for r in sweeps)
    sweep_commits = sum(r["n"] for r in sweeps)

    md = ["# Timing benchmarks", "",
          "Generated by `scripts/timings.py` from the run records listed in each table. Do not edit by hand.", "",
          f"Machine: {host()}. Step time counts fetch, build and test commands only; container staging, "
          "toolchain installs and time-travel index builds were not recorded, so wall time is longer.", "",
          "## Fast stages (last pipeline run)", "", "| Target | Stage | Time | Source |", "|---|---|---|---|"]
    md += [f"| {r['target']} | {r['stage']} | {r['seconds']} s | `{r['src']}` |" for r in pipe]
    md += ["", "## Feasibility: build and unit-test sampled commits in Docker", "",
           "| Target | Dependencies | Samples | Total step time | Median per sample | Slowest sample | Median, samples that built | Source |",
           "|---|---|---|---|---|---|---|---|"]
    md += [f"| {r['target']} | {r['run']} | {r['n']} | {mins(r['total'])} | {mins(r['median'])} | {mins(r['max'])} | "
           f"{mins(r['built_median']) if r['built_median'] is not None else 'none built'} | `{r['src']}` |" for r in feas]
    md += ["", "## Method B: one regression test swept across history", "",
           "| Target | Bug | Verdict | Commits tested / in range | Total step time | Median per commit | Source |",
           "|---|---|---|---|---|---|---|"]
    md += [f"| {r['target']} | {r['id']} | {r['verdict']} | {r['n']} / {r['range']} | {mins(r['total'])} | {mins(r['median'])} | `{r['src']}` |"
           for r in sweeps]
    if sweeps:
        md += ["", f"All sweeps: {sweep_commits} commits tested, {mins(sweep_total)} of step time."]
    if walls:
        md += ["", "## End-to-end wall time of unattended sweep runs", "", "| Run | Sweeps | Wall time | Source |", "|---|---|---|---|"]
        md += [f"| {r['target']} | {r['sweeps']} | {r['minutes']} min | `{r['src']}` |" for r in walls]

    fast = {}
    for r in pipe:
        fast.setdefault(r["stage"].split(" (")[0], []).append(r["seconds"])
    readme = [BEGIN, "",
              "Measured on " + host() + ". Figures come from committed run records via `scripts/timings.py`; "
              "full tables in [`results/TIMINGS.md`](results/TIMINGS.md). Step time excludes container staging "
              "and toolchain installs, so expect wall time to be longer.", "",
              "| Stage | What was measured | Time |", "|---|---|---|"]
    for stage, secs in fast.items():
        readme.append(f"| {stage} | last pipeline run, {len(secs)} target(s) | {min(secs)}-{max(secs)} s |"
                      if len(secs) > 1 else f"| {stage} | last pipeline run | {secs[0]} s |")
    if feas:
        readme.append(f"| Feasibility (one run, {feas[0]['n']} sampled commits) | {len(feas)} runs | "
                      f"{mins(min(r['total'] for r in feas))} to {mins(max(r['total'] for r in feas))} per run |")
    if current:
        meds = [r["median"] for r in current]
        readme.append(f"| Method B sweep (one bug, current search) | {len(current)} sweeps, {sum(r['n'] for r in current)} commits | "
                      f"{mins(min(r['total'] for r in current))} to {mins(max(r['total'] for r in current))} of step time per bug; "
                      f"median per commit {mins(min(meds))} to {mins(max(meds))} |")
    for r in walls:
        if r["target"] == LABELS["bench"]:
            readme.append(f"| Method B, all {r['sweeps']} tokenizers sweeps end to end | one unattended run, wall clock | {r['minutes']} min |")
    per_repo = {}
    for r in pipe:
        per_repo[r["target"]] = per_repo.get(r["target"], 0) + r["seconds"]
    note = []
    if current:
        note.append(f"Method B dominates: each bug needs a regression test, and the current search built and tested "
                    f"{min(r['n'] for r in current)} to {max(r['n'] for r in current)} commits per bug in Docker.")
    if per_repo:
        note.append(f"Catalog, Method A and bundle together took {min(per_repo.values())} to {max(per_repo.values())} s per repository.")
    readme += ["", " ".join(note), "", END]
    return "\n".join(md) + "\n", "\n".join(readme)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="fail if TIMINGS.md or the README block is stale")
    a = ap.parse_args()
    timings, block = render()
    out, readme = ROOT / "results" / "TIMINGS.md", ROOT / "README.md"
    text = readme.read_text()
    if BEGIN not in text or END not in text:
        print("README.md has no timing markers", file=sys.stderr)
        return 1
    new_readme = text[:text.index(BEGIN)] + block + text[text.index(END) + len(END):]
    if a.check:
        stale = [p.name for p, want in [(out, timings), (readme, new_readme)] if not p.is_file() or p.read_text() != want]
        if stale:
            print("stale: " + ", ".join(stale) + " (run python3 scripts/timings.py)", file=sys.stderr)
            return 1
        return 0
    out.write_text(timings)
    readme.write_text(new_readme)
    print("timings: wrote results/TIMINGS.md and the README block", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
