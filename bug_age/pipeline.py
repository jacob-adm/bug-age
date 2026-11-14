#!/usr/bin/env python3
"""Run the bug-age pipeline for one target from its config file.

Usage: bug-age pipeline targets/NAME.toml [--fresh] [--skip-feasibility]

Stages: clone -> feasibility (baseline, time-travel) -> catalog -> szz -> repros -> bundle.
A stage whose output already exists is REUSED unless --fresh (the expensive Docker stages
are never redone silently). A failing stage is recorded with its reason and the pipeline
continues with whatever does not depend on it. Writes <results_dir>/PIPELINE.md and pipeline.json.
"""
import datetime as dt, hashlib, json, shutil, subprocess, sys, time, tomllib
from pathlib import Path

from .sweep import _overlay_listing as overlay_listing

ROOT = Path.cwd()                                   # config paths are relative to the working directory
BIN = [sys.executable, "-m", "bug_age"]             # this package's CLI, same interpreter


def sha256(p):
    """Return the hex sha256 of a file, recorded per stage output."""
    return hashlib.sha256(Path(p).read_bytes()).hexdigest() if Path(p).is_file() else None


def run(cmd, log):
    """Run a command from the repo root, append its output to `log`, and return the exit status."""
    with open(log, "a") as f:
        f.write(f"\n$ {' '.join(map(str, cmd))}\n"); f.flush()
        return subprocess.run(list(map(str, cmd)), cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode


def tail(log, n=3):
    """Return the last `n` non-empty log lines as one stage reason, with local paths removed."""
    lines = [l for l in Path(log).read_text().splitlines() if l.strip()]
    text = " / ".join(lines[-n:]).replace(f"{ROOT}/", "").replace(str(ROOT), ".").replace(str(Path.home()), "~")
    return text[:300]


def main(argv=None):
    """Load the target config, run each stage in order, and write the stage report."""
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0].startswith("--"):
        print("usage: bug-age pipeline TARGET.toml [--fresh] [--skip-feasibility]", file=sys.stderr)
        return 2
    cfg_path = Path(argv[0])
    fresh, skip_feas = "--fresh" in argv, "--skip-feasibility" in argv
    c = tomllib.loads(cfg_path.read_text())
    repo, res, spike, dist = (ROOT / c[k] for k in ("work_dir", "results_dir", "spike_dir", "dist_dir"))
    res.mkdir(parents=True, exist_ok=True)
    log = ROOT / "work" / f"pipeline-{c['name']}.log"
    log.parent.mkdir(exist_ok=True); log.write_text("")
    stages = []
    current = set()  # stage outputs this run produced or verified; only these reach the bundle

    def stage(name, out, fn):
        """Run one stage unless its output exists (reused unless --fresh); record status, reason, time and hash."""
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
        """Clone the target repository if needed and check out the pinned head."""
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
        """Run the feasibility spike (baseline, or time-travel when `tt`) for this target."""
        out = spike / ("results-timetravel" if tt else "results") / "report.json"
        def fn():
            """Stage body; returns (status, reason)."""
            if skip_feas:
                return "NOT TESTED", "skipped (--skip-feasibility)"
            if out.is_file() and not fresh:
                # Reuse only a report made for this repository at this pinned head.
                stale = feasibility_mismatch(out.parent / "receipt.json")
                if stale:
                    return "FAILED", f"stale report: {stale} (pass --fresh to rerun)"
                current.add(out)
                return "REUSED", "existing report for this head (pass --fresh to rerun)"
            cmd = [sys.executable, "-m", "bug_age.feasibility", "--config", cfg_path, "--samples", c.get("samples", 20)]
            if run(cmd + (["--time-travel"] if tt else []), log) or not out.is_file():
                return "FAILED", tail(log)
            r = json.loads(out.read_text())
            current.add(out)
            return "OK", f"{r['verdict']}, built+tested share {r['built_and_tested_share']}"
        return out, fn

    def cli(name, args, out):
        """Return a stage function that runs one bug-age subcommand writing to `out`."""
        def fn():
            """Stage body; returns (status, reason)."""
            if run([*BIN, name, *args, "--out", out], log):
                return "FAILED", tail(log)
            return "OK", tail(log, 1)
        return fn

    def repros():
        """Sweep the target's regression tests if it has any; otherwise report Method B as NOT TESTED."""
        overlays = sorted((res / "repros").glob("*/overlay")) if (res / "repros").is_dir() else []
        if not overlays:
            return "NOT TESTED", "no regression tests written for this target (results_dir/repros/<fix>/overlay)"
        if all((o.parent / "sweep.json").is_file() for o in overlays) and not fresh:
            # Reuse only sweeps of this overlay whose fix is in the pinned history.
            stale = [f"{o.parent.name}: {why}" for o in overlays if (why := sweep_mismatch(o))]
            if stale:
                return "FAILED", f"stale sweeps: {'; '.join(stale)} (pass --fresh to rerun)"
            current.update(o.parent for o in overlays)
            return "REUSED", f"{len(overlays)} existing sweeps for this head and overlay (pass --fresh to rerun)"
        if run([sys.executable, "-m", "bug_age.repros", res, repo, c["crate_path"]], log):
            return "FAILED", tail(log)
        current.update(o.parent for o in overlays if (o.parent / "sweep.json").is_file() and not sweep_mismatch(o))
        return "OK", f"{len(overlays)} repros swept"

    def feasibility_mismatch(receipt):
        """Why a feasibility report does not belong to this run, or None."""
        if not receipt.is_file():
            return "no receipt recording its inputs"
        inputs = json.loads(receipt.read_text()).get("inputs", {})
        if inputs.get("head") != c["head"]:
            return f"made at head {str(inputs.get('head'))[:10]}, pinned head is {c['head'][:10]}"
        if str(inputs.get("repo", "")).removesuffix(".git") != c["repo_url"].removesuffix(".git"):
            return f"made for {inputs.get('repo')}"
        return None

    def sweep_mismatch(overlay):
        """Why a recorded sweep does not belong to this run, or None."""
        receipt = overlay.parent / "sweep.json.receipt.json"
        if not receipt.is_file():
            return "no receipt recording its inputs"
        inputs = json.loads(receipt.read_text()).get("inputs", {})
        if inputs.get("overlay_files") != overlay_listing(overlay):
            return "the regression test changed since it was swept"
        fix = str(inputs.get("fix", ""))
        if subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", fix, c["head"]], capture_output=True).returncode:
            return f"fix {fix[:10]} is not in the history of the pinned head"
        return None

    def bundle_inputs():
        """A results folder for the bundle holding only what this run produced or verified.

        Catalog and szz were just regenerated; feasibility reports and sweeps are included only
        when their stage ran or verified them now, so a skipped or stale stage adds no data.
        """
        d = ROOT / "work" / f"pipeline-inputs-{c['name']}"
        shutil.rmtree(d, ignore_errors=True)
        (d / "results" / "repros").mkdir(parents=True)
        for f in ("catalog.json", "szz.json"):
            shutil.copy2(res / f, d / "results" / f)
        for sweep_dir in sorted(x for x in current if x.is_dir()):
            shutil.copytree(sweep_dir, d / "results" / "repros" / sweep_dir.name)
        for report in (x for x in current if x.is_file()):
            target = d / "spike" / report.parent.name
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(report, target / "report.json")
        return d / "results", d / "spike"

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
        inputs_res, inputs_spike = bundle_inputs()
        args = ["--repo", repo, "--results", inputs_res, "--repo-url", c["repo_url"], "--spike", inputs_spike]
        args += ["--out-of-scope", c["out_of_scope"]] if "out_of_scope" in c else []
        stage("bundle", dist / "bundle.json", cli("bundle", args, dist))
    else:
        stages.append({"stage": "bundle", "status": "NOT TESTED", "reason": "needs catalog and szz", "seconds": 0, "output": None, "sha256": None})
    return finish(c, res, stages)


def finish(c, res, stages):
    """Write pipeline.json and PIPELINE.md, and return a non-zero exit code if any stage failed."""
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
