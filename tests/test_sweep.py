# SPDX-License-Identifier: MIT OR Apache-2.0
"""Method B end to end on a toy crate, with the local runner (needs cargo) and, opt-in, Docker."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, clean_env, cli

OK = "pub fn mul(a: i32, b: i32) -> i32 { a * b }\n"
BUG = "pub fn mul(a: i32, b: i32) -> i32 { a + b }\n"
NONE = "pub fn add(a: i32, b: i32) -> i32 { a + b }\n"
HAS_CARGO = shutil.which("cargo") is not None


def toy_repo(bodies):
    """A crate `toy` with one commit per body of src/lib.rs; returns (root, repo, scratch, shas)."""
    root = Path(tempfile.mkdtemp(prefix="bug-age-sweep-"))
    repo = root / "repo"
    (repo / "toy" / "src").mkdir(parents=True)
    env = dict(clean_env(), GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="T",
               GIT_COMMITTER_EMAIL="t@example.invalid", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main", *a],
                                    env=env, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q")
    (repo / "toy" / "Cargo.toml").write_text('[package]\nname = "toy"\nversion = "0.1.0"\nedition = "2021"\n\n[workspace]\n')
    shas = []
    for i, body in enumerate(bodies):
        (repo / "toy" / "src" / "lib.rs").write_text(f"// rev {i}\n{body}")
        git("add", "-A")
        git("commit", "-q", "-m", f"rev {i}")
        shas.append(git("rev-parse", "HEAD"))
    return root, repo, root / "scratch", shas


def overlay(root, expected):
    """The regression test: mul(2, 3) must equal `expected`."""
    o = root / "overlay"
    (o / "tests").mkdir(parents=True, exist_ok=True)
    (o / "tests" / "bugage_repro.rs").write_text(f"#[test]\nfn mul_multiplies() {{ assert_eq!(toy::mul(2, 3), {expected}); }}\n")
    return o


def sweep_args(repo, scratch, ov, runner="local", repeats="2"):
    """The flags every sweep and probe in these tests share."""
    return ["--repo", repo, "--path", "toy", "--overlay", ov, "--runner", runner, "--repeats", repeats,
            "--build", "cargo test --test bugage_repro --no-run", "--test", "cargo test --test bugage_repro",
            "--scratch", scratch, "--logs", scratch / "logs"]


@unittest.skipUnless(HAS_CARGO, "needs cargo to build the toy crate")
class Sweep(unittest.TestCase):
    """Verdicts on scripted histories."""

    def setUp(self):
        """Temporary directories to remove after each test."""
        self.roots = []

    def tearDown(self):
        """Remove them."""
        for r in self.roots:
            shutil.rmtree(r, ignore_errors=True)

    def sweep(self, bodies, fix, start=None, expected=6):
        """Sweep the toy history and return (report, shas)."""
        root, repo, scratch, s = toy_repo(bodies)
        self.roots.append(root)
        args = ["sweep", *sweep_args(repo, scratch, overlay(root, expected)), "--fix", s[fix]]
        if start is not None:
            args += ["--start", s[start]]
        return json.loads(cli(*args).stdout)["report"], s

    def test_locates_exact_introducing_commit(self):
        """Adjacent last PASS and first FAIL: located."""
        r, s = self.sweep([NONE, OK, OK, BUG, BUG, BUG, OK], 6)
        self.assertEqual(r["verdict"], "located", r)
        self.assertEqual((r["last_passing"], r["first_failing"]), (s[2], s[3]))
        self.assertEqual(r["untestable_between"], 0)
        self.assertIs(r["non_monotonic"], False)

    def test_left_censored_when_range_starts_inside_the_bug(self):
        """A range that fails from its first commit is left-censored."""
        r, s = self.sweep([OK, BUG, BUG, BUG, OK], 4, start=1)
        self.assertEqual(r["verdict"], "left-censored", r)
        self.assertEqual(r["first_failing"], s[1])
        self.assertIsNone(r["last_passing"])

    def test_censored_by_testability_when_bug_predates_compilable_test(self):
        """The test fails where it first compiles: censored by testability."""
        r, s = self.sweep([NONE, NONE, NONE, BUG, BUG, OK], 5)
        self.assertEqual(r["verdict"], "censored-by-testability", r)
        self.assertEqual(r["first_failing"], s[3])
        self.assertGreaterEqual(sum(1 for c in r["results"] if c["outcome"] == "UNTESTABLE"), 1)

    def test_long_untestable_history_costs_a_bounded_number_of_builds(self):
        """40 untestable commits do not cost 40 builds."""
        r, s = self.sweep([NONE] * 40 + [OK, OK, BUG, BUG, OK], 44)
        self.assertEqual(r["verdict"], "located", r)
        self.assertEqual(r["first_failing"], s[42])
        self.assertLessEqual(r["commits_tested"], 25)

    def test_frontier_assumes_monotonic_buildability(self):
        """An isolated compilable commit before the frontier is not searched."""
        r, s = self.sweep([NONE, OK, NONE, NONE, NONE, NONE, NONE, BUG, BUG, OK], 9)
        self.assertEqual(r["verdict"], "censored-by-testability", r)
        self.assertEqual((r["frontier"], r["first_failing"]), (s[7], s[7]))

    def test_decisive_commits_are_confirmed_with_full_repeats(self):
        """The fix, its parent and the boundary are re-run with --repeats."""
        r, s = self.sweep([OK, OK, BUG, BUG, OK], 4)
        self.assertEqual(r["verdict"], "located", r)
        self.assertEqual(r["confirmation"], "decisive commits confirmed x2")
        fix = next(c for c in r["results"] if c["sha"] == s[4])
        self.assertEqual(sum(1 for st in fix["steps"] if st["name"].startswith("test_")), 2)

    def test_rejects_a_repro_that_does_not_fail_before_the_fix(self):
        """A test that passes before the fix is not a regression test."""
        r, _ = self.sweep([OK, BUG, OK], 2, expected=7)
        self.assertEqual(r["verdict"], "repro-invalid", r)

    def test_probe_evaluates_listed_commits_without_searching(self):
        """probe tests exactly the listed commits."""
        root, repo, scratch, s = toy_repo([OK, BUG, OK])
        self.roots.append(root)
        out = json.loads(cli("probe", *sweep_args(repo, scratch, overlay(root, 6), repeats="1"),
                             "--commits", f"{s[0]},{s[1]}").stdout)
        self.assertEqual([r["outcome"] for r in out["results"]], ["PASS", "FAIL"])


@unittest.skipUnless(os.environ.get("BUG_AGE_DOCKER_TESTS") == "1", "set BUG_AGE_DOCKER_TESTS=1 (needs Docker and the image)")
class DockerSweep(unittest.TestCase):
    """The hermetic runner, opt-in because it needs Docker and network for toolchains."""

    def test_docker_runner_locates_exact_introducing_commit(self):
        """Located in Docker, with build and test steps offline, and the image id in the receipt."""
        root, repo, scratch, s = toy_repo([NONE, OK, OK, BUG, BUG, BUG, OK])
        try:
            v = json.loads(cli("sweep", *sweep_args(repo, scratch, overlay(root, 6), runner="docker"), "--fix", s[6],
                               "--time-travel-script", ROOT / "spike" / "timetravel.py").stdout)
            r = v["report"]
            self.assertEqual(r["verdict"], "located", r)
            self.assertEqual((r["first_failing"], r["last_passing"]), (s[3], s[2]))
            for c in r["results"]:
                for st in c["steps"]:
                    if st["name"].startswith("test_") or st["name"] == "build":
                        self.assertIs(st["network"], False)
            self.assertTrue(v["receipt"]["versions"]["image"].startswith("sha256:"))
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
