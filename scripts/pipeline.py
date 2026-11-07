#!/usr/bin/env python3
"""Run the bug-age pipeline for one target from its config file.

Usage: python3 scripts/pipeline.py targets/NAME.toml [--fresh] [--skip-feasibility]

Stages: clone -> feasibility (baseline, time-travel) -> catalog -> szz -> repros -> bundle.
A stage whose output already exists is REUSED unless --fresh (the expensive Docker stages
are never redone silently). A failing stage is recorded with its reason and the pipeline
continues with whatever does not depend on it. Writes <results_dir>/PIPELINE.md and pipeline.json.
"""
import datetime as dt, hashlib, json, subprocess, sys, time, tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "target" / "debug" / "bug-age"


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None


def run(cmd, log):
    with open(log, "a") as f:
        f.write(f"\n$ {' '.join(map(str, cmd))}\n"); f.flush()
        return subprocess.run(list(map(str, cmd)), cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode


def tail(log, n=3):
    lines = [l for l in Path(log).read_text().splitlines() if l.strip()]
    text = " / ".join(lines[-n:]).replace(f"{ROOT}/", "").replace(str(ROOT), ".").replace(str(Path.home()), "~")
    return text[:300]


def main():
    cfg_path = Path(sys.argv[1])
    fresh, skip_feas = "--fresh" in sys.argv, "--skip-feasibility" in sys.argv
    c = tomllib.loads(cfg_path.read_text())
    repo, res, spike, dist = (ROOT / c[k] for k in ("work_dir", "results_dir", "spike_dir", "dist_dir"))
    res.mkdir(parents=True, exist_ok=True)
    log = ROOT / "work" / f"pipeline-{c['name']}.log"
    log.parent.mkdir(exist_ok=True); log.write_text("")
    stages = []

    def stage(name, out, fn):
        t0 = time.time()
        try:
            status, reason = fn()
        except Exception as e:  # recorded, never swallowed silently
            status, reason = "FAILED", f"{type(e).__name__}: {e}"
        stages.append({"stage": name, "status": status, "reason": reason, "seconds": round(time.time() - t0),
                       "output": str(Path(out).relative_to(ROOT)) if out else None,
                       "sha256": sha256(out) if out else None})
        print(f"{name:<24} {status:<11} {reason}", flush=True)
        return status in ("OK", "REUSED")

    def clone():
        if not repo.is_dir() and run(["git", "clone", "-q", c["repo_url"], repo], log):
            return "FAILED", "git clone failed: " + tail(log)
        g = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
        if g("cat-file", "-e", c["head"] + "^{commit}").returncode:
            g("fetch", "-q", "origin")
        if g("rev-parse", "HEAD").stdout.strip() != c["head"]:
            if g("status", "--porcelain").stdout.strip():
                return "FAILED", f"{repo.name} has local changes; not moving it to the pinned head"
            if g("checkout", "-q", "--detach", c["head"]).returncode:
                return "FAILED", f"cannot check out pinned head {c['head']}"
        return "OK", f"at pinned head {c['head'][:10]}"

    def feasibility(tt):
        out = spike / ("results-timetravel" if tt else "results") / "report.json"
        def fn():
            if skip_feas:
                return "NOT TESTED", "skipped (--skip-feasibility)"
            if out.is_file() and not fresh:
                return "REUSED", "existing report (pass --fresh to rerun)"
            cmd = [sys.executable, "spike/feasibility.py", "--config", cfg_path, "--samples", c.get("samples", 20)]
            if run(cmd + (["--time-travel"] if tt else []), log) or not out.is_file():
                return "FAILED", tail(log)
            r = json.loads(out.read_text())
            return "OK", f"{r['verdict']}, built+tested share {r['built_and_tested_share']}"
        return out, fn

    def cli(name, args, out):
        def fn():
            if run([BIN, name, *args, "--out", out], log):
                return "FAILED", tail(log)
            return "OK", tail(log, 1)
        return fn

    def repros():
        overlays = sorted((res / "repros").glob("*/overlay")) if (res / "repros").is_dir() else []
        if not overlays:
            return "NOT TESTED", "no regression tests written for this target (results_dir/repros/<fix>/overlay)"
        if all((o.parent / "sweep.json").is_file() for o in overlays) and not fresh:
            return "REUSED", f"{len(overlays)} existing sweeps (pass --fresh to rerun)"
        if run([sys.executable, "results/run_repros.py", res, repo, c["crate_path"]], log):
            return "FAILED", tail(log)
        return "OK", f"{len(overlays)} repros swept"

    if run(["cargo", "build", "-q"], log):
        print("cargo build failed; see", log); return 1
    if not stage("clone", None, clone):
        return finish(c, res, stages)
    for tt in (False, True):
        out, fn = feasibility(tt)
        stage("feasibility (time-travel)" if tt else "feasibility (baseline)", out, fn)
    cat = res / "catalog.json"
    if stage("catalog (rule-based fixes)", cat, cli("catalog", ["--repo", repo, "--path", c["crate_path"], "--head", c["head"]], cat)):
        szz_args = ["--repo", repo, "--catalog", cat] + (["--window-start", c["szz_window_start"]] if "szz_window_start" in c else []) \
            + (["--release-tags", c["release_tag_glob"]] if "release_tag_glob" in c else [])
        szz_ok = stage("Method A (szz)", res / "szz.json", cli("szz", szz_args, res / "szz.json"))
    else:
        szz_ok = False
    stage("Method B (repro sweeps)", None, repros)
    if szz_ok:
        args = ["--repo", repo, "--results", res, "--repo-url", c["repo_url"], "--spike", spike]
        args += ["--out-of-scope", c["out_of_scope"]] if "out_of_scope" in c else []
        stage("bundle", dist / "bundle.json", cli("bundle", args, dist))
    else:
        stages.append({"stage": "bundle", "status": "NOT TESTED", "reason": "needs catalog and szz", "seconds": 0, "output": None, "sha256": None})
    return finish(c, res, stages)


def finish(c, res, stages):
    failed = [s for s in stages if s["status"] == "FAILED"]
    doc = {"target": c["name"], "repo_url": c["repo_url"], "head": c["head"], "crate_path": c["crate_path"],
           "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "stages": stages}
    (res / "pipeline.json").write_text(json.dumps(doc, indent=2) + "\n")
    md = [f"# Pipeline: {c['name']}", "", f"- subject: {c['repo_url']} `{c['crate_path']}` at `{c['head']}`",
          f"- generated: {doc['generated_utc']}", "", "| Stage | Status | Reason | Output sha256 |", "|---|---|---|---|"]
    md += [f"| {s['stage']} | {s['status']} | {s['reason'].replace('|', '/')} | {(s['sha256'] or '')[:16]} |" for s in stages]
    (res / "PIPELINE.md").write_text("\n".join(md) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
