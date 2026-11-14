# SPDX-License-Identifier: MIT OR Apache-2.0
"""Method B search on scripted histories, without cargo: every verdict, flaky and non-monotonic cases.

The build passes when lib.rs defines mul (else the commit is UNTESTABLE); the test passes when mul
multiplies; a FLAKY body alternates pass and fail through a counter file. The expected values are
what bug-age 1.0.2 (Rust) reported for the same histories; the Python port's reports were
byte-identical to it apart from step timings.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import clean_env, cli

OK, BUG, NONE = "fn mul(a,b){ a * b }", "fn mul(a,b){ a + b }", "fn add(a,b){ a + b }"
FLAKY = "fn mul(a,b){ a * b } // FLAKY"

# name: (bodies, start index or None, verdict, commits tested, non_monotonic, confirmation prefix)
SCENARIOS = {
    "located": ([NONE, OK, OK, BUG, BUG, BUG, OK], None, "boundary", 7, False, "decisive commits confirmed x3"),
    "left-censored": ([OK, BUG, BUG, BUG, OK], 1, "left-censored", 4, False, "decisive commits confirmed x3"),
    "censored-by-testability": ([NONE, NONE, NONE, BUG, BUG, OK], None, "censored-by-testability", 5, False, "decisive"),
    "bounded": ([NONE] * 40 + [OK, OK, BUG, BUG, OK], None, "boundary", 11, False, "decisive"),
    "frontier": ([NONE, OK, NONE, NONE, NONE, NONE, NONE, BUG, BUG, OK], None, "censored-by-testability", 6, False, "decisive"),
    "interval": ([OK, OK, OK, NONE, NONE, NONE, BUG, BUG, OK], None, "interval", 8, False, "decisive"),
    "interval-wide": ([OK] * 5 + [NONE] * 9 + [BUG] * 5 + [OK], None, "interval", 10, False, "decisive"),
    "non-monotonic": ([OK, OK, BUG, OK, BUG, BUG, BUG, OK], None, "boundary", 7, True, "decisive"),
    "flaky-boundary": ([OK, OK, OK, FLAKY, BUG, BUG, OK], None, "boundary", 6, False, "UNSTABLE on confirmation: "),
    "repro-invalid": ([OK, OK, OK], None, "repro-invalid", 2, False, ""),
    "long": ([OK] * 30 + [BUG] * 30 + [OK], None, "boundary", 10, False, "decisive"),
}


class Scenarios(unittest.TestCase):
    """Each scripted history gets the verdict, cost and flags 1.0.2 reported."""

    def run_scenario(self, bodies, start, exhaustive=False):
        """Build the history, sweep its last commit, return (report, shas)."""
        root = Path(tempfile.mkdtemp(prefix="bug-age-scenario-"))
        self.addCleanup(shutil.rmtree, root, True)
        repo = root / "repo"
        (repo / "toy" / "src").mkdir(parents=True)
        env = dict(clean_env(), GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@e",
                   GIT_AUTHOR_DATE="2025-01-01T00:00:00Z", GIT_COMMITTER_DATE="2025-01-01T00:00:00Z",
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *a], env=env, check=True,
                                        capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main")
        shas = []
        for i, body in enumerate(bodies):
            (repo / "toy" / "src" / "lib.rs").write_text(f"// rev {i}\n{body}\n")
            git("add", "-A")
            git("commit", "-q", "-m", f"rev {i}")
            shas.append(git("rev-parse", "HEAD"))
        ov = root / "overlay" / "tests"
        ov.mkdir(parents=True)
        (ov / "bugage_repro.rs").write_text("// expects mul to multiply\n")
        counter = root / "counter"
        test = (f"if grep -q FLAKY src/lib.rs; then n=$(cat {counter} 2>/dev/null || echo 0); echo $((n+1)) > {counter}; "
                f"[ $((n % 2)) = 0 ]; else grep -q 'a \\* b' src/lib.rs; fi")
        args = ["sweep", *(["--search", "exhaustive"] if exhaustive else []), "--repo", repo, "--path", "toy", "--fix", shas[-1], "--overlay", root / "overlay", "--runner", "local",
                "--repeats", "3", "--build", "grep -q 'fn mul' src/lib.rs", "--test", test, "--scratch", root / "scratch",
                "--logs", root / "scratch" / "logs"] + (["--start", shas[start]] if start is not None else [])
        return json.loads(cli(*args).stdout)["report"], shas

    def test_scenarios(self):
        """Verdict, commits tested, non-monotonic flag and confirmation for every scenario."""
        for name, (bodies, start, verdict, tested, nonmono, confirmation) in SCENARIOS.items():
            with self.subTest(name=name):
                r, _ = self.run_scenario(bodies, start)
                self.assertEqual((r["verdict"], r["commits_tested"], r["non_monotonic"]), (verdict, tested, nonmono))
                self.assertTrue(r["confirmation"].startswith(confirmation), r["confirmation"])


    def test_exhaustive_scenarios(self):
        """Every commit tested: the true first failure, located only when the range is monotone."""
        # The audit's history: fails at 2, passes again, fails from 14. Bisection reports 14 as a boundary.
        audit = [OK, OK, BUG] + [OK] * 11 + [BUG, BUG, OK]
        r, s = self.run_scenario(audit, None)
        self.assertEqual((r["verdict"], s.index(r["first_failing"]), r["non_monotonic"]), ("boundary", 14, False))
        r, s = self.run_scenario(audit, None, exhaustive=True)
        self.assertEqual((r["verdict"], s.index(r["first_failing"]), s.index(r["last_passing"])), ("located", 2, 1))
        self.assertIs(r["non_monotonic"], True)
        self.assertEqual((r["search"], r["commits_tested"]), ("exhaustive", 17))
        # A monotone, fully testable history: only the exhaustive search may say located.
        r, s = self.run_scenario([OK, OK, OK, BUG, BUG, BUG, OK], None, exhaustive=True)
        self.assertEqual((r["verdict"], s.index(r["first_failing"]), r["non_monotonic"]), ("located", 3, False))
        # The same with an untestable first commit: an earlier failure could hide there, so a boundary.
        r, s = self.run_scenario([NONE, OK, OK, BUG, BUG, BUG, OK], None, exhaustive=True)
        self.assertEqual((r["verdict"], s.index(r["first_failing"])), ("boundary", 3))
        # Untestable commits between the last PASS and the first FAIL: an interval, even when exhaustive.
        r, s = self.run_scenario([OK, OK, OK, NONE, NONE, NONE, BUG, BUG, OK], None, exhaustive=True)
        self.assertEqual((r["verdict"], r["untestable_between"]), ("interval", 3))
        # The follow-up audit's history: build-ability is not monotonic. Every commit is tested, the true
        # first failure (2) is found, and an untestable commit before it rules out an exact claim.
        audit2 = [NONE, OK, BUG] + [NONE] * 6 + [OK] * 5 + [BUG, BUG, OK]
        r, s = self.run_scenario(audit2, None, exhaustive=True)
        self.assertEqual(r["commits_tested"], 17)
        self.assertEqual((r["verdict"], s.index(r["first_failing"]), r["non_monotonic"]), ("boundary", 2, True))
        self.assertIn("1 earlier commit(s) could not be tested", r["reason"])
        # Bisection on the same history is unchanged: a boundary found by sampling.
        r, s = self.run_scenario(audit2, None)
        self.assertEqual(r["verdict"], "boundary")
        # Only untestable commits before the first failure: censored, not located.
        r, _ = self.run_scenario([NONE, NONE, BUG, BUG, OK], None, exhaustive=True)
        self.assertEqual(r["verdict"], "censored-by-testability")
        # Failing from the first commit: left-censored either way.
        r, _ = self.run_scenario([BUG, BUG, BUG, OK], None, exhaustive=True)
        self.assertEqual(r["verdict"], "left-censored")


if __name__ == "__main__":
    unittest.main()
