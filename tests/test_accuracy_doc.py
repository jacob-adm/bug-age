# SPDX-License-Identifier: MIT OR Apache-2.0
"""docs/accuracy.md states exactly what the committed study results say.

Every scored row is recomputed from results/oracle/fixes.json with the study's own scoring and
must equal summary.json and the page's tables, so the page cannot drift from the data.
"""
import importlib.util
import json
import re
import unittest

from helpers import ROOT

spec = importlib.util.spec_from_file_location("oracle_study", ROOT / "scripts" / "oracle_study.py")
study = importlib.util.module_from_spec(spec)
spec.loader.exec_module(study)

LABELS = {"bug_age_primary": "bug-age, primary nominee", "bug_age_all": "bug-age, all nominees",
          "pydriller": "PyDriller B-SZZ"}


def row(label, s, total):
    return (f"| {label} | {s['named']} | {s['correct']} | {s['precision']:.2f} | {s['recall']:.2f} "
            f"| {s['f1']:.2f} | {s['fixes_with_true_introducer']} of {total} |")


class AccuracyDocTest(unittest.TestCase):

    def setUp(self):
        self.rows = json.loads((ROOT / "results" / "oracle" / "fixes.json").read_text(encoding="utf-8"))
        self.summary = json.loads((ROOT / "results" / "oracle" / "summary.json").read_text(encoding="utf-8"))
        self.page = (ROOT / "docs" / "accuracy.md").read_text(encoding="utf-8")

    def check(self, rows, key):
        for name, label in LABELS.items():
            scored = study.score(rows, name)
            self.assertEqual(scored, self.summary[key][name])
            self.assertIn(row(label, scored, len(rows)), self.page)

    def test_all_fixes(self):
        self.assertEqual(len(self.rows), 83)
        self.check(self.rows, "scores")

    def test_product_code_fixes(self):
        product = [r for r in self.rows if r["changes_product_code"]]
        self.assertEqual(len(product), self.summary["product_code_fixes"])
        self.check(product, "scores_product_code_fixes")

    def test_stated_counts(self):
        test_only = [r for r in self.rows if not r["changes_product_code"]]
        self.assertTrue(all(r["bug_age_all"] == [] for r in test_only))
        hit = lambda r, k: bool(set(r[k]) & set(r["oracle"]))
        only_pyd = [r for r in self.rows if hit(r, "pydriller") and not hit(r, "bug_age_all")]
        self.assertEqual(only_pyd, test_only)
        self.assertFalse([r for r in self.rows if hit(r, "bug_age_all") and not hit(r, "pydriller")])
        self.assertEqual(len(test_only), 6)
        self.assertIn("Six fixes change only test files", self.page)
        self.assertEqual(len(self.summary["fix_commits_missing"]), 1)
        self.assertIn("Run on bug-age %s, PyDriller %s" % (self.summary["bug_age"], self.summary["pydriller"]),
                      self.page)
        selected = (ROOT / "results" / "oracle" / "repos.tsv").read_text(encoding="utf-8").splitlines()[1:]
        self.assertEqual(len(selected), 80)
        self.assertIn(study.ORACLE_URL, self.page)


if __name__ == "__main__":
    unittest.main()
