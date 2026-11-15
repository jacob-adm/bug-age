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


if __name__ == "__main__":
    unittest.main()
