# SPDX-License-Identifier: MIT OR Apache-2.0
"""Profiles: the rust profile is exactly the old behaviour; the python profile measures Python code."""
import json
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from bug_age import catalog, profiles, szz
from helpers import ROOT, cli, commit, run_git


class FixRule(unittest.TestCase):
    """The python profile adds lint-tool names to the exclusions and nothing else."""

    # Real first-parent subjects from psf/requests, pallets/flask and expressjs/express.
    LINT = ("pep8 fix", "fix mypy findings", "fix flake8 bugbear findings", "fix mypy finding")
    KEPT = ("Fixed missing closing </style> tag", "Style fixes", "Fixed ternary style", "fix black screen on resize")

    def test_lint_tool_fixes_are_excluded_only_by_the_python_profile(self):
        """Lint-tool subjects are fixes under rust (unchanged) and exclude:lint-tool under python."""
        for s in self.LINT:
            with self.subTest(subject=s):
                self.assertEqual(catalog.classify(s), "include")
                self.assertEqual(catalog.classify(s, "python"), "exclude:lint-tool")

    def test_other_subjects_classify_the_same_in_both_profiles(self):
        """A rule keyed on tool names leaves real fixes that mention style alone."""
        for s in self.KEPT:
            with self.subTest(subject=s):
                self.assertEqual(catalog.classify(s, "python"), catalog.classify(s))

    def test_unknown_profile_is_refused(self):
        """A misspelt profile is an error, never a silent fallback to rust."""
        with self.assertRaises(ValueError):
            catalog.classify("fix crash", "pyhton")
        out = cli("catalog", "--repo", ".", "--path", ".", "--profile", "pyhton", check=False)
        self.assertEqual(out.returncode, 2)


class Scope(unittest.TestCase):
    """Which files Method A blames."""

    def test_rust_scope_is_unchanged(self):
        """rust: .rs under the path, outside tests/ and benches/ (a top-level tests/ dir included, as in 1.x)."""
        cases = {"core/src/lib.rs": True, "core/tests/a.rs": False, "core/benches/b.rs": False,
                 "core/src/a.py": False, "other/src/lib.rs": False}
        for f, want in cases.items():
            self.assertEqual(szz.in_scope(f, "core"), want, f)
        self.assertTrue(szz.in_scope("tests/a.rs", "."))

    def test_python_scope_skips_tests(self):
        """python: .py under the path, outside test directories and test modules."""
        cases = {"pkg/core.py": True, "pkg/sub/util.py": True, "pkg/tests/test_core.py": False,
                 "pkg/test/helpers.py": False, "pkg/test_core.py": False, "pkg/core_test.py": False,
                 "pkg/conftest.py": False, "pkg/core.rs": False, "other/core.py": False}
        for f, want in cases.items():
            self.assertEqual(szz.in_scope(f, "pkg", "python"), want, f)
        self.assertFalse(szz.in_scope("tests/test_x.py", ".", "python"))


class PythonMethodA(unittest.TestCase):
    """Method A end to end on a scripted Python repository."""

    def setUp(self):
        """A history whose fix changes a module and its test in one commit."""
        self.d = Path(tempfile.mkdtemp(prefix="bug-age-py-"))
        self.addCleanup(shutil.rmtree, self.d, True)
        d = self.d
        run_git(d, ["init", "-q"], "2025-01-01T00:00:00Z")
        commit(d, "pkg/calc.py", "def add(a, b):\n    return a + b\n", "init", "2025-01-01T00:00:00Z")
        self.intro = commit(d, "pkg/calc.py", "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a + b\n",
                            "add mul", "2025-02-01T00:00:00Z")
        commit(d, "pkg/tests/test_calc.py", "from pkg.calc import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 5\n",
               "add tests", "2025-02-15T00:00:00Z")
        (d / "pkg/tests/test_calc.py").write_text("from pkg.calc import mul\n\n\ndef test_mul():\n    assert mul(2, 3) == 6\n")
        self.fix = commit(d, "pkg/calc.py", "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n",
                          "Fix mul returning the sum", "2025-03-01T00:00:00Z")
        commit(d, "pkg/calc.py", "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n# checked\n",
               "fix mypy findings", "2025-03-05T00:00:00Z")

    def method_a(self, *profile):
        """Catalog and szz output for the scripted repository."""
        cat, out = self.d / "catalog.json", self.d / "szz.json"
        cli("catalog", "--repo", self.d, "--path", "pkg", *profile, "--out", cat)
        cli("szz", "--repo", self.d, "--catalog", cat, "--out", out)
        return json.loads(cat.read_text()), json.loads(out.read_text())

    def test_python_profile_blames_the_module_not_its_test(self):
        """The fix's introducer is the commit that wrote the bug; the edited test is not blamed."""
        cat, a = self.method_a("--profile", "python")
        self.assertEqual(cat["profile"], "python")
        self.assertEqual([f["sha"] for f in cat["fixes"]], [self.fix])
        self.assertEqual([e["rule"] for e in cat["excluded"]], ["exclude:lint-tool"])
        bug = a["bugs"][0]
        self.assertEqual(a["profile"], "python")
        self.assertEqual(bug["blamed_files"], ["pkg/calc.py"])
        self.assertEqual(bug["nominees"][0]["sha"], self.intro)
        self.assertEqual(bug["lifetime"]["calendar_days"], 28.0)

    def test_rust_profile_finds_nothing_to_blame_and_records_no_profile(self):
        """The default profile sees no Rust sources here; its outputs carry no profile key, as before."""
        cat, a = self.method_a()
        self.assertNotIn("profile", cat)
        self.assertNotIn("profile", a)
        self.assertEqual(len(cat["fixes"]), 2)
        self.assertIn("no-blame-lines(addition-only-or-out-of-scope)", a["bugs"][0]["flags"])

    def test_bundle_records_the_profile_and_passes_its_schema(self):
        """A python bundle names its profile in subject and validates against the packaged schema."""
        self.method_a("--profile", "python")
        res, out = self.d / "res", self.d / "dist"
        res.mkdir()
        for f in ("catalog.json", "szz.json"):
            shutil.copy2(self.d / f, res / f)
        cli("bundle", "--repo", self.d, "--results", res, "--repo-url", "https://example.invalid/calc", "--out", out,
            "--spike", self.d / "no-spike")
        b = json.loads((out / "bundle.json").read_text())
        self.assertEqual(b["subject"]["profile"], "python")
        self.assertEqual(b["subject"]["crate_path"], "pkg")
        self.assertEqual(json.loads((out / "receipt.json").read_text())["schema_check"], "PASS")


class TargetConfig(unittest.TestCase):
    """`path` replaces `crate_path`; both are accepted, and only when they agree."""

    def test_path_and_alias(self):
        """path alone, crate_path alone, or both equal; profile defaults to rust."""
        self.assertEqual(profiles.target({"path": "a"}), {"path": "a", "crate_path": "a", "profile": "rust"})
        self.assertEqual(profiles.target({"crate_path": "a"})["crate_path"], "a")
        self.assertEqual(profiles.target({"path": "a", "crate_path": "a", "profile": "python"})["profile"], "python")
        for bad in ({}, {"path": "a", "crate_path": "b"}, {"path": "a", "profile": "go"}):
            with self.subTest(config=bad), self.assertRaises(ValueError):
                profiles.target(dict(bad))

    def test_pipeline_refuses_a_bad_target_before_any_work(self):
        """Disagreeing path keys exit 2 and write nothing."""
        d = Path(tempfile.mkdtemp(prefix="bug-age-cfg-"))
        self.addCleanup(shutil.rmtree, d, True)
        cfg = d / "t.toml"
        cfg.write_text('name = "t"\nrepo_url = "x"\nhead = "0"\npath = "a"\ncrate_path = "b"\n'
                       'work_dir = "w"\nresults_dir = "r"\nspike_dir = "s"\ndist_dir = "d"\n')
        out = subprocess.run([sys.executable, "-m", "bug_age", "pipeline", cfg], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 2)
        self.assertIn("path and crate_path disagree", out.stderr)


class PythonVersion(unittest.TestCase):
    """CPython chosen for a commit: date-matched, floor 3.8, raised to requires-python."""

    def test_choice(self):
        """Newest minor released at least 14 days before the commit."""
        import calendar
        from bug_age.runner import python_for
        at = lambda day: calendar.timegm(time.strptime(day, "%Y-%m-%d"))
        self.assertEqual(python_for(at("2018-05-27")), "3.8")        # before uv's floor: raised to it
        self.assertEqual(python_for(at("2020-10-18")), "3.8")        # 3.9 is 13 days old
        self.assertEqual(python_for(at("2020-10-19")), "3.9")        # 3.9 is 14 days old
        self.assertEqual(python_for(at("2021-10-20"), ">=3.11"), "3.11")
        self.assertEqual(python_for(at("2026-01-01"), ">=3.7"), "3.14")
        self.assertEqual(python_for(at("2026-01-01"), ">=3.99"), "3.14")  # unknown minimum: keep the date match


class SweepOptions(unittest.TestCase):
    """Options of one profile are refused for the other, so none is silently ignored."""

    def test_refusals(self):
        """--image with python, --install with rust, and an unknown profile exit 2."""
        base = ["probe", "--repo", ".", "--path", ".", "--commits", "HEAD", "--overlay", ".", "--test", "true"]
        for extra in (["--profile", "python", "--image", "x"], ["--install", ".[test]"], ["--test-deps", "pytest"],
                      ["--profile", "python", "--bucket", "0"], ["--profile", "go"]):
            with self.subTest(extra=extra):
                self.assertEqual(cli(*base, *extra, check=False).returncode, 2)


if __name__ == "__main__":
    unittest.main()
