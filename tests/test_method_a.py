# SPDX-License-Identifier: MIT OR Apache-2.0
"""Catalog and Method A on a scripted repository, plus the pure helpers."""
import unittest

from bug_age.catalog import classify, sanitize_subject
from bug_age.szz import in_scope, removed_ranges
from helpers import SyntheticRepo, cli, cli_json, clean_env, head


class MethodA(unittest.TestCase):
    """End-to-end catalog and szz runs through the CLI."""

    def setUp(self):
        """A fresh synthetic repository per test."""
        self.r = SyntheticRepo()

    def tearDown(self):
        """Remove it."""
        self.r.cleanup()

    def catalog_file(self):
        """Write the catalog next to the repository and return its path."""
        path = self.r.dir / "catalog.json"
        cli("catalog", "--repo", self.r.dir, "--path", "core", "--out", path)
        return path

    def test_catalog_admits_fix_and_records_exclusion_rule(self):
        """The fix is admitted with its sanitised subject; the typo commit is excluded by rule."""
        cat = cli_json("catalog", "--repo", self.r.dir, "--path", "core")
        self.assertEqual([f["sha"] for f in cat["fixes"]], [self.r.fix])
        self.assertEqual(cat["fixes"][0]["subject"], "fix: mul used addition (#1)")
        self.assertEqual([(e["sha"], e["rule"]) for e in cat["excluded"]], [(self.r.typo, "exclude:typo")])
        self.assertEqual(cat["scanned"], 5)

    def test_szz_nominates_planting_commit_with_scripted_lifetime(self):
        """The planting commit is the nominee; commits, days, releases and churn are as scripted."""
        res = cli_json("szz", "--repo", self.r.dir, "--catalog", self.catalog_file(), "--window-start", "2025-01-02")
        bug = res["bugs"][0]
        self.assertEqual(bug["nominees"][0]["sha"], self.r.intro)
        self.assertEqual(bug["nominees"][0]["blamed_lines"], 1)
        life = bug["lifetime"]
        self.assertEqual(life["commits_elapsed"], 2, "README commit + fix")
        self.assertEqual(life["calendar_days"], 10.0)
        self.assertEqual(life["calendar_days_author"], 10.0)
        self.assertEqual(bug["flags"], [], "single clean nominee, distinct dates")
        self.assertEqual(life["releases_spanned"], ["v0.1.0", "v0.1.1"], "branch tag before fix counts; after does not")
        self.assertEqual(life["churn_files"], 2, "README.md added and lib.rs fixed under core/")
        self.assertIs(bug["in_window"], True)
        self.assertEqual(res["summary"]["in_window"], 1)

    def test_release_tag_glob_selects_prefixed_release_tags(self):
        """--release-tags picks a prefixed tag scheme and is recorded in the summary."""
        res = cli_json("szz", "--repo", self.r.dir, "--catalog", self.catalog_file(), "--release-tags", "core-v[0-9]*")
        self.assertEqual(res["bugs"][0]["lifetime"]["releases_spanned"], ["core-v0.1.0"])
        self.assertEqual(res["summary"]["release_tags"], "core-v[0-9]*")

    def test_ignores_git_env_inherited_from_hooks(self):
        """GIT_DIR and GIT_INDEX_FILE from a calling hook neither redirect nor touch another repository."""
        decoy = SyntheticRepo()
        try:
            before = head(decoy.dir)
            env = dict(clean_env(), GIT_DIR=str(decoy.dir / ".git"), GIT_INDEX_FILE=str(decoy.dir / ".git" / "index"))
            cat = cli_json("catalog", "--repo", self.r.dir, "--path", "core", env=env)
            self.assertEqual(cat["fixes"][0]["sha"], self.r.fix, "catalog must come from --repo")
            self.assertEqual(head(decoy.dir), before, "decoy repository must be untouched")
        finally:
            decoy.cleanup()


class Helpers(unittest.TestCase):
    """Rules and parsers that need no repository."""

    def test_classify_rules(self):
        """Include and exclude rules, and a word that must not count as 'fix'."""
        self.assertEqual(classify("fix(bpe): wrong merge order (#12)"), "include")
        self.assertEqual(classify("Fix warnings in decoder"), "exclude:lint-or-format")
        self.assertEqual(classify("Fixed Length Pre-Tokenizer"), "exclude:feature-name")
        self.assertIsNone(classify("Add a prefix option"), "'prefix' must not match the fix rule")

    def test_subjects_lose_usernames(self):
        """Merge sources and @handles are removed from subjects."""
        self.assertEqual(sanitize_subject("Merge pull request #7 from alice/fix-bpe"), "Merge pull request #7")
        self.assertEqual(sanitize_subject("fix decoder, thanks @bob-dev"), "fix decoder, thanks")

    def test_removed_ranges_respects_scope_and_counts(self):
        """Only in-scope sources are blamed, and pure additions have nothing to blame."""
        diff = ("--- a/core/src/lib.rs\n+++ b/core/src/lib.rs\n@@ -2 +2 @@\n-x\n+y\n@@ -10,0 +11,2 @@\n+z\n"
                "--- a/core/tests/t.rs\n+++ b/core/tests/t.rs\n@@ -1,3 +1,0 @@\n")
        self.assertEqual(removed_ranges(diff, "core"), [("core/src/lib.rs", 2, 1)])
        self.assertTrue(in_scope("core/src/a.rs", "core"))
        self.assertFalse(in_scope("core/benches/b.rs", "core"))
        self.assertFalse(in_scope("other/a.rs", "core"))


if __name__ == "__main__":
    unittest.main()
