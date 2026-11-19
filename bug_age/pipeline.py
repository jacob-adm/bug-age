#!/usr/bin/env python3
"""Run the bug-age pipeline for one target from its config file.

Usage: bug-age pipeline targets/NAME.toml [--fresh] [--skip-feasibility]

Stages: clone -> feasibility (baseline, time-travel) -> catalog -> szz -> repros -> bundle.
A stage whose output already exists is REUSED unless --fresh (the expensive Docker stages
are never redone silently). A failing stage is recorded with its reason and the pipeline
continues with whatever does not depend on it. Writes <results_dir>/PIPELINE.md and pipeline.json.
"""
import datetime as dt, hashlib, json, re, shutil, subprocess, sys, time, tomllib
from pathlib import Path

from . import profiles
from .repros import BUILD, PY_BUILD, PY_TEST, TEST, range_start
from .sweep import _overlay_listing as overlay_listing

# The Method B image's recipe; receipts made since 2.1.1 record its hash so reuse can check it.
RECIPE = hashlib.sha256((Path(__file__).parent / "data" / "Dockerfile").read_bytes()).hexdigest()
PY_RECIPE = hashlib.sha256((Path(__file__).parent / "data" / "python.Dockerfile").read_bytes()).hexdigest()

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
    try:
        c = profiles.target(tomllib.loads(cfg_path.read_text()))
    except ValueError as exc:
        print(f"bug-age pipeline: {cfg_path}: {exc}", file=sys.stderr)
        return 2
    rust = c["profile"] == "rust"
    recipe = RECIPE if rust else PY_RECIPE
    if not rust and not all(k in c for k in ("import", "test")):
        print(f"bug-age pipeline: {cfg_path}: a python target needs import and test", file=sys.stderr)
        return 2
    # What a python target installs at each commit: the project spec and its test dependencies.
    py_args = [] if rust else ["--profile", "python", "--install", c.get("install", "."),
                               "--test-deps", ",".join(c.get("test_deps", ["pytest"]))]
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
                notes = []
                stale = feasibility_mismatch(out, tt, notes)
                if stale:
                    return "FAILED", f"stale report: {stale} (pass --fresh to rerun)"
                current.add(out)
                return "REUSED", "existing report, every recorded input matches" + "".join(f"; {n}" for n in notes)
            module = "bug_age.feasibility" if rust else "bug_age.pyfeasibility"
            cmd = [sys.executable, "-m", module, "--config", cfg_path, "--samples", c.get("samples", 20)]
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
            notes = []
            stale = [f"{o.parent.name}: {why}" for o in overlays if (why := sweep_mismatch(o, notes))]
            if stale:
                return "FAILED", f"stale sweeps: {'; '.join(stale)} (pass --fresh to rerun)"
            current.update(o.parent for o in overlays)
            note = f"; image recipe not recorded for {len(notes)} (made before 2.1.1)" if notes else ""
            return "REUSED", f"{len(overlays)} existing sweeps, every recorded input matches{note}"
        if run([sys.executable, "-m", "bug_age.repros", res, repo, c["crate_path"], *py_args], log):
            return "FAILED", tail(log)
        current.update(o.parent for o in overlays if (o.parent / "sweep.json").is_file() and not sweep_mismatch(o, []))
        return "OK", f"{len(overlays)} repros swept"

    def image_mismatch(versions, what, notes):
        """Compare the recorded image recipe with this package's; note receipts that predate the record."""
        recorded = versions.get("image_recipe") if isinstance(versions, dict) else None
        if recorded is None:
            notes.append(f"{what}: image recipe not recorded (made before 2.1.1)")
            return None
        return None if recorded == recipe else "made with a different Method B image recipe"

    def feasibility_mismatch(report, tt, notes):
        """Why a feasibility report does not match this run's material inputs, or None.

        Material: repository, pinned head, sample count, time-travel or not, package scope, the
        report's own bytes (against the hash its receipt recorded), and the image recipe.
        """
        receipt = report.parent / "receipt.json"
        if not receipt.is_file():
            return "no receipt recording its inputs"
        rec = json.loads(receipt.read_text())
        inputs = rec.get("inputs", {})
        if inputs.get("head") != c["head"]:
            return f"made at head {str(inputs.get('head'))[:10]}, pinned head is {c['head'][:10]}"
        if str(inputs.get("repo", "")).removesuffix(".git") != c["repo_url"].removesuffix(".git"):
            return f"made for {inputs.get('repo')}"
        command = str(rec.get("command", ""))
        m = re.search(r"--samples (\d+)", command)
        want = int(c.get("samples", 20))
        if not m or int(m.group(1)) != want:
            return f"made with --samples {m.group(1) if m else '?'}, the config asks for {want}"
        if ("--time-travel" in command) != tt:
            return "made " + ("with" if not tt else "without") + " time-travel dependencies"
        hashes = [v for k, v in rec.get("outputs", {}).items() if k.endswith("report.json")]
        if hashes != [sha256(report)]:
            return "report.json does not match the hash recorded in its receipt"
        if not rust:
            want = {"install": " ".join([c.get("install", "."), *c.get("test_deps", ["pytest"])]),
                    "import": c["import"], "test": c["test"]}
            for key, value in want.items():
                if inputs.get(key) != value:
                    return f"made with {key} {inputs.get(key)!r}, the config asks for {value!r}"
            return image_mismatch(rec.get("versions"), "feasibility", notes)
        scope = f"--package {c['package']}" if "package" in c else "--all"
        build = str(json.loads(report.read_text()).get("method", {}).get("build", ""))
        if not build.startswith(f"cargo build {scope} "):
            return f"built with another package scope ({build.split(' --offline')[0]}), the config asks for {scope}"
        return image_mismatch(rec.get("versions"), "feasibility", notes)

    def sweep_mismatch(overlay, notes):
        """Why a recorded sweep does not match what this run would do, or None.

        Material: the fix (in the pinned history), the range start, the regression test, the
        build and test commands, repeats, runner and search, the report's own bytes (against the
        hash its receipt recorded), and the image recipe.
        """
        receipt = overlay.parent / "sweep.json.receipt.json"
        report = overlay.parent / "sweep.json"
        if not receipt.is_file():
            return "no receipt recording its inputs"
        rec = json.loads(receipt.read_text())
        inputs = rec.get("inputs", {})
        if inputs.get("overlay_files") != overlay_listing(overlay):
            return "the regression test changed since it was swept"
        fix = str(inputs.get("fix", ""))
        if subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", fix, c["head"]], capture_output=True).returncode:
            return f"fix {fix[:10]} is not in the history of the pinned head"
        if rec.get("report_sha256") != sha256(report):
            return "sweep.json does not match the hash recorded in its receipt"
        s = json.loads(report.read_text())
        want = {"build": BUILD if rust else PY_BUILD, "test": TEST if rust else PY_TEST, "repeats": 3, "runner": "docker", "search": "bisection",
                "start": range_start(repo, fix)}
        got = dict(s, search=s.get("search") or "bisection")
        for key, value in want.items():
            if got.get(key) != value:
                return f"made with {key} {got.get(key)!r}, this run would use {value!r}"
        command = str(rec.get("command", ""))
        for key, value in zip(py_args[::2], py_args[1::2]):
            if f"{key} {value}" not in command and f"{key} '{value}'" not in command:
                return f"made without {key} {value}"
        return image_mismatch(rec.get("versions"), overlay.parent.name, notes)

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
    if stage("catalog (rule-based fixes)", cat, cli("catalog", ["--repo", repo, "--path", c["crate_path"], "--head", c["head"]]
                                                       + ([] if rust else ["--profile", c["profile"]]), cat)):
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
           **({} if c["profile"] == "rust" else {"profile": c["profile"]}), "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "stages": stages}
    (res / "pipeline.json").write_text(json.dumps(doc, indent=2) + "\n")
    md = [f"# Pipeline: {c['name']}", "", f"- subject: {c['repo_url']} `{c['crate_path']}` at `{c['head']}`",
          f"- generated: {doc['generated_utc']}", "", "| Stage | Status | Reason | Output sha256 |", "|---|---|---|---|"]
    md += [f"| {s['stage']} | {s['status']} | {s['reason'].replace('|', '/')} | {(s['sha256'] or '')[:16]} |" for s in stages]
    (res / "PIPELINE.md").write_text("\n".join(md) + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
