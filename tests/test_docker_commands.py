# SPDX-License-Identifier: MIT OR Apache-2.0
"""The Docker runner's exact commands for the rust profile, recorded with a stand-in `docker`.

The golden trace pins every docker command line and every step of a probe over two commits, with
and without a time-travel index, so restructuring the runner cannot change what a Rust sweep runs.
Regenerate it only for an intended change: BUG_AGE_WRITE_GOLDEN=1.
"""
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, SyntheticRepo, clean_env, cli

GOLDEN = ROOT / "tests" / "fixtures" / "docker" / "rust-probe.txt"

FAKE_DOCKER = """#!/bin/sh
# Records its arguments, one per line, then a separator; succeeds. Only `run -i` is sent data
# (a tar stream), so only it reads stdin: other calls may inherit a stdin that never closes.
for a in "$@"; do printf '%s\\n' "$a"; done >> "$BUG_AGE_DOCKER_TRACE"
printf -- '--\\n' >> "$BUG_AGE_DOCKER_TRACE"
if [ "$1 $2" = "run -i" ]; then cat > /dev/null; fi
exit 0
"""

FAKE_TIME_TRAVEL = """import sys, pathlib
out = pathlib.Path(sys.argv[5]); out.mkdir(parents=True)
(out / "config.json").write_text('{"dl": "fake"}')
"""


class RustDockerCommands(unittest.TestCase):
    """A probe on the docker runner issues exactly the recorded commands."""

    def test_commands_match_the_golden_trace(self):
        """Same docker argv sequence and same probe report as recorded."""
        repo = SyntheticRepo()
        self.addCleanup(repo.cleanup)
        d = Path(tempfile.mkdtemp(prefix="bug-age-dockertrace-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "bin").mkdir()
        (d / "bin" / "docker").write_text(FAKE_DOCKER)
        (d / "bin" / "docker").chmod(0o755)
        (d / "tt.py").write_text(FAKE_TIME_TRAVEL)
        overlay = d / "overlay" / "tests"
        overlay.mkdir(parents=True)
        (overlay / "bugage_repro.rs").write_text("#[test]\nfn repro() {}\n")
        trace = d / "trace.txt"
        env = dict(clean_env(), PATH=f"{d / 'bin'}{os.pathsep}{os.environ['PATH']}", BUG_AGE_DOCKER_TRACE=str(trace))
        parts = []
        for name, tt in (("no-time-travel", "none"), ("time-travel", str(d / "tt.py"))):
            out = cli("probe", "--repo", repo.dir, "--path", "core", "--commits", f"{repo.intro},{repo.fix}",
                      "--overlay", d / "overlay", "--test", "cargo test --test bugage_repro", "--runner", "docker",
                      "--repeats", "2", "--time-travel-script", tt, "--scratch", d / "scratch", "--logs", d / "logs",
                      env=env)
            report = json.loads(out.stdout)
            for r in report["results"]:
                for s in r["steps"]:
                    s["seconds"] = 0
            parts.append(f"== {name}: report\n{json.dumps(report, indent=1, sort_keys=True)}\n== {name}: docker\n"
                         + trace.read_text())
            trace.write_text("")
        text = "".join(parts)
        text = text.replace(str(repo.dir), "<repo>").replace(str(d), "<tmp>").replace(repo.intro, "<intro>") \
            .replace(repo.fix, "<fix>").replace(repo.intro[:12], "<intro12>").replace(repo.fix[:12], "<fix12>")
        text = re.sub(r"bugage-step-[0-9a-f]{12}", "bugage-step-<id>", text)
        if os.environ.get("BUG_AGE_WRITE_GOLDEN") == "1":
            GOLDEN.parent.mkdir(parents=True, exist_ok=True)
            GOLDEN.write_text(text)
        self.assertEqual(text, GOLDEN.read_text())


class PythonDockerCommands(unittest.TestCase):
    """The python profile's docker commands for a two-commit probe, recorded the same way."""

    def test_commands_match_the_golden_trace(self):
        """Image per CPython minor, fresh environment per commit, install as of the commit time, offline test."""
        from helpers import commit, run_git
        d = Path(tempfile.mkdtemp(prefix="bug-age-pytrace-"))
        self.addCleanup(shutil.rmtree, d, True)
        repo = d / "repo"
        repo.mkdir()
        run_git(repo, ["init", "-q"], "2020-05-01T00:00:00Z")
        first = commit(repo, "pkg/calc.py", "def mul(a, b):\n    return a + b\n", "init", "2020-05-01T00:00:00Z")
        second = commit(repo, "pyproject.toml", '[project]\nname = "calc"\nrequires-python = ">=3.11"\n', "require 3.11",
                        "2021-12-01T00:00:00Z")
        (d / "bin").mkdir()
        (d / "bin" / "docker").write_text(FAKE_DOCKER)
        (d / "bin" / "docker").chmod(0o755)
        overlay = d / "overlay" / "tests"
        overlay.mkdir(parents=True)
        (overlay / "bugage_repro_test.py").write_text("def test_x():\n    pass\n")
        trace = d / "trace.txt"
        env = dict(clean_env(), PATH=f"{d / 'bin'}{os.pathsep}{os.environ['PATH']}", BUG_AGE_DOCKER_TRACE=str(trace))
        out = cli("probe", "--profile", "python", "--repo", repo, "--path", ".", "--commits", f"{first},{second}",
                  "--overlay", d / "overlay", "--test", "python -m pytest -q tests/bugage_repro_test.py",
                  "--install", ".[test]", "--test-deps", "pytest,pytest-mock", "--repeats", "1",
                  "--scratch", d / "scratch", "--logs", d / "logs", env=env)
        report = json.loads(out.stdout)
        for r in report["results"]:
            for s in r["steps"]:
                s["seconds"] = 0
        text = f"== report\n{json.dumps(report, indent=1, sort_keys=True)}\n== docker\n{trace.read_text()}"
        text = text.replace(str(d), "<tmp>").replace(first, "<first>").replace(second, "<second>") \
            .replace(first[:12], "<first12>").replace(second[:12], "<second12>")
        text = re.sub(r"bugage-step-[0-9a-f]{12}", "bugage-step-<id>", text)
        text = re.sub(r"bug-age-python:(3\.\d+)-[0-9a-f]{12}", r"bug-age-python:\1-<recipe>", text)
        golden = GOLDEN.with_name("python-probe.txt")
        if os.environ.get("BUG_AGE_WRITE_GOLDEN") == "1":
            golden.write_text(text)
        self.assertEqual(text, golden.read_text())


class SourceReset(unittest.TestCase):
    """A source volume that cannot be removed is never staged over."""

    def probe(self, fail_removals):
        """Probe one commit with a docker that refuses the first `fail_removals` volume removals."""
        repo = SyntheticRepo()
        self.addCleanup(repo.cleanup)
        d = Path(tempfile.mkdtemp(prefix="bug-age-reset-"))
        self.addCleanup(shutil.rmtree, d, True)
        (d / "bin").mkdir()
        refusing = FAKE_DOCKER.replace("exit 0\n", f"""if [ "$1 $2" = "volume rm" ]; then
  n=$(cat "$BUG_AGE_DOCKER_TRACE.rm" 2>/dev/null || echo 0); echo $((n + 1)) > "$BUG_AGE_DOCKER_TRACE.rm"
  [ "$n" -lt {fail_removals} ] && {{ echo "volume is in use" >&2; exit 1; }}
fi
exit 0
""")
        (d / "bin" / "docker").write_text(refusing)
        (d / "bin" / "docker").chmod(0o755)
        (d / "overlay" / "tests").mkdir(parents=True)
        (d / "overlay" / "tests" / "bugage_repro.rs").write_text("#[test]\nfn repro() {}\n")
        env = dict(clean_env(), PATH=f"{d / 'bin'}{os.pathsep}{os.environ['PATH']}", BUG_AGE_DOCKER_TRACE=str(d / "t"))
        out = cli("probe", "--repo", repo.dir, "--path", "core", "--commits", repo.fix, "--overlay", d / "overlay",
                  "--test", "true", "--runner", "docker", "--repeats", "1", "--time-travel-script", "none",
                  "--scratch", d / "scratch", "--logs", d / "logs", env=env)
        return json.loads(out.stdout)["results"][0], int((d / "t.rm").read_text())

    def test_a_volume_released_late_is_retried(self):
        """Two refusals, then success: the commit is tested normally."""
        r, removals = self.probe(2)
        self.assertEqual(r["outcome"], "PASS")
        self.assertGreaterEqual(removals, 3)

    def test_a_volume_never_released_makes_the_commit_untestable(self):
        """Removal never succeeds: UNTESTABLE with the reason, and nothing staged over the old tree."""
        r, _ = self.probe(1000)
        self.assertEqual(r["outcome"], "UNTESTABLE")
        self.assertIn("still in use", r["reason"])
        self.assertEqual(r["steps"], [])


if __name__ == "__main__":
    unittest.main()
