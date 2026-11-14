# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bundle schema, blameless gate, partial bundles and published command lines."""
import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from bug_age import bundle, schema
from helpers import ROOT, clean_env


def load(rel):
    """A JSON file of the repository."""
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


SCHEMA = load("schema/bundle.schema.json")


class Schema(unittest.TestCase):
    """The committed bundles satisfy the schema, and broken ones do not."""

    def test_committed_bundles_match_schema(self):
        """Both example bundles validate."""
        for name in ("tokenizers", "rust-sdk"):
            with self.subTest(name=name):
                self.assertEqual(schema.errors(load(f"dist/{name}/bundle.json"), SCHEMA), [])

    def test_schema_rejects_broken_bundles(self):
        """Missing summary, a subject on a Method A row, an unknown verdict and an author field are rejected."""
        good = load("dist/tokenizers/bundle.json")
        no_summary = copy.deepcopy(good)
        del no_summary["summary"]
        identity_leak = copy.deepcopy(good)
        identity_leak["method_a"][0]["subject"] = "Fix by someone"
        bad_verdict = copy.deepcopy(good)
        bad_verdict["method_b"][0]["verdict"] = "probably"
        author_field = copy.deepcopy(good)
        author_field["commits"][next(iter(author_field["commits"]))]["author"] = "Someone"
        for name, b in [("no summary", no_summary), ("subject on method_a", identity_leak),
                        ("unknown verdict", bad_verdict), ("author on commit", author_field)]:
            with self.subTest(name=name):
                self.assertNotEqual(schema.errors(b, SCHEMA), [], f"schema accepted a bundle with {name}")


class Gate(unittest.TestCase):
    """Identity scan, redaction and the people list."""

    def test_gate_catches_planted_identities_and_redaction_removes_them(self):
        """Names, emails and handles are found; redaction removes whole-word names only."""
        ids = bundle.Identities(["ada lovelace", "adal"])
        self.assertEqual(bundle.scan({"commits": {"x": {"subject": "Fix tokenizer padding (#12)"}}}, ids), [])
        for planted in ["thanks Ada Lovelace", "mail ada@example.org", "ping @adal", "by ADAL"]:
            with self.subTest(planted=planted):
                self.assertNotEqual(bundle.scan({"commits": {"x": {"subject": planted}}}, ids), [])
        redacted = ids.redact("Fix from Ada Lovelace and adal")
        self.assertEqual(bundle.scan(redacted, ids), [], redacted)
        self.assertEqual(ids.redact("adalovelace-ish words stay"), "adalovelace-ish words stay", "whole words only")

    def test_people_include_names_emails_and_noreply_usernames(self):
        """A noreply address yields the name, the address and the username behind the '+'."""
        d = tempfile.mkdtemp()
        try:
            env = dict(clean_env(), GIT_AUTHOR_NAME="Grace Hopper", GIT_AUTHOR_EMAIL="123+ghopper@users.noreply.github.com",
                       GIT_COMMITTER_NAME="Grace Hopper", GIT_COMMITTER_EMAIL="123+ghopper@users.noreply.github.com",
                       GIT_CONFIG_GLOBAL="/dev/null")
            for args in (["init", "-q"], ["-c", "commit.gpgsign=false", "commit", "-q", "--allow-empty", "-m", "init"]):
                subprocess.run(["git", "-C", d, *args], env=env, check=True, capture_output=True)
            p = bundle.people(d)
            for expected in ["grace hopper", "ghopper", "123+ghopper@users.noreply.github.com"]:
                self.assertIn(expected, p)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Partial(unittest.TestCase):
    """Stages that did not run are reported, not hidden."""

    def test_missing_stages_bundle_as_not_tested(self):
        """No feasibility and no sweeps: valid bundle, those stages NOT TESTED, out-of-scope row present."""
        d = Path(tempfile.mkdtemp())
        try:
            repo, results = d / "repo", d / "results"
            repo.mkdir()
            results.mkdir()
            env = dict(clean_env(), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
            git = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()
            git("init", "-q")
            (repo / "a.rs").write_text("fn main() {}\n")
            git("add", ".")
            git("commit", "-q", "-m", "initial")
            head = git("rev-parse", "HEAD")
            (results / "catalog.json").write_text(json.dumps({"include_rule": "fix", "scanned": 1, "excluded": [], "fixes": []}))
            (results / "szz.json").write_text(json.dumps({"head": head, "path": ".", "bugs": [],
                                                          "summary": {"fixes": 0, "with_introducer": 0}}))
            b = bundle.build(repo, results, d / "no-spike", "https://example.org/r", ("Bindings", "out of scope", "binding behaviour"))
            self.assertEqual(schema.errors(b, SCHEMA), [])
            self.assertIsNone(b["feasibility"]["baseline"])
            self.assertIsNone(b["feasibility"]["time_travel"])
            status = {r["stage"]: r["status"] for r in b["coverage"]}
            self.assertEqual(status["Historical buildability"], "NOT TESTED")
            self.assertEqual(status["Method B (behavioural sweep)"], "NOT TESTED")
            self.assertEqual(status["Bindings"], "NOT TESTED")
            self.assertEqual(b["summary"]["method_b"]["swept"], 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Commands(unittest.TestCase):
    """Recorded command lines carry no local paths and re-run as written."""

    def test_recorded_commands_carry_no_local_paths_and_rerun_as_written(self):
        """Paths under the working directory become relative, under home become ~; others are kept."""
        cmd = ["/home/u/src/bug-age/target/debug/bug-age", "bundle", "--repo", "/home/u/src/bug-age/work/t",
               "--here", "/home/u/src/bug-age", "--scratch", "/home/u/.cache/x", "--other", "/home/user2/x",
               "--note", "a|b c", "--q", "it's"]
        self.assertEqual(bundle.public_command(cmd, "/home/u/src/bug-age", "/home/u"),
                         "target/debug/bug-age bundle --repo work/t --here . --scratch ~/.cache/x --other /home/user2/x "
                         "--note 'a|b c' --q 'it'\\''s'")
        self.assertEqual(bundle.public_command(["/usr/bin/x", "/data/y"], "/", ""), "/usr/bin/x /data/y")
        self.assertEqual(bundle.public_command(["/a/c", "/b/a/c"], "/a", ""), "c /b/a/c")


if __name__ == "__main__":
    unittest.main()
