# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bundle schema, blameless gate, partial bundles and published command lines."""
import copy
import json
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path

from bug_age import bundle, schema
from helpers import ROOT, clean_env, cli


def load(rel):
    """A JSON file of the repository."""
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


SCHEMA = load("bug_age/data/bundle.schema.json")


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


def old_redact(names, text, limit=50):
    """The 1.x redaction (boundary-consuming pattern, repeated until no match); None if it does not settle."""
    import re as _re
    pat = _re.compile(r"(?i)(^|[^\w])(" + "|".join(_re.escape(n) for n in names) + r")(\Z|[^\w])")
    for _ in range(limit):
        if not pat.search(text):
            return text
        text = pat.sub(lambda m: m.group(1) + bundle.REDACTED + m.group(3), text)
    return None


class Redaction(unittest.TestCase):
    """Redaction terminates on any input and removes the same names as 1.x did."""

    def setUp(self):
        """Fail any test that runs longer than five seconds (a hang is the defect under test)."""
        signal.signal(signal.SIGALRM, lambda *a: (_ for _ in ()).throw(TimeoutError("redaction did not finish")))
        signal.alarm(5)
        self.addCleanup(signal.alarm, 0)

    def test_terminates_when_a_name_is_the_placeholder_word(self):
        """A contributor called "redacted" no longer makes redaction loop forever."""
        ids = bundle.Identities(["redacted"])
        self.assertEqual(ids.redact("redacted"), "[redacted]")
        self.assertEqual(ids.redact("fix by redacted and [redacted]"), "fix by [redacted] and [[redacted]]")
        self.assertEqual(bundle.scan("[redacted]", ids), [], "the placeholder is not a person")

    def test_same_result_as_the_old_loop_wherever_it_settled(self):
        """Adjacent, overlapping and repeated names give exactly the 1.x output."""
        names = ["ada lovelace", "lovelace", "ada", "bob-x", "c.d"]
        texts = ["Ada Lovelace", "ada ada ada", "ada,ada.ada", "lovelace ada lovelace", "bob-x/ada", "xada adax ada_",
                 "c.d c.dx (ada)", "ADA-bob-x", "", "nothing here", "ada\nada"]
        ids = bundle.Identities(names)
        for t in texts:
            with self.subTest(text=t):
                self.assertEqual(ids.redact(t), old_redact(names, t))

    def test_user_names_warn_and_full_names_fail(self):
        """An email user name in the bundle is a warning; a full name or an email still fails the gate."""
        ids = bundle.Identities(["grace hopper", "ghopper", "hello"], user_names={"ghopper", "hello"})
        found = []
        self.assertEqual(bundle.scan({"a": "assert_eq!(out, vec![\"hello\"])"}, ids, found), [])
        self.assertEqual(found, ["hello"])
        self.assertNotEqual(bundle.scan({"a": "thanks Grace Hopper"}, ids, []), [])
        self.assertNotEqual(bundle.scan({"a": "mail hello@example.org"}, ids, []), [])
        self.assertEqual(ids.redact("fix from ghopper"), "fix from [redacted]", "user names are still redacted")


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
            b, _ = bundle.build(repo, results, d / "no-spike", "https://example.org/r", ("Bindings", "out of scope", "binding behaviour"))
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


class SchemaGate(unittest.TestCase):
    """bug-age bundle writes nothing that its own schema rejects."""

    def test_malformed_feasibility_report_is_refused_and_nothing_written(self):
        """A share that is not a number fails the schema: exit 1, no bundle, no receipt."""
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, True)
        repo, results, spike, out = d / "repo", d / "results", d / "spike", d / "out"
        for x in (repo, results, spike / "results"):
            x.mkdir(parents=True)
        env = dict(clean_env(), GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, env=env, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q")
        (repo / "a.rs").write_text("fn main() {}\n")
        git("add", ".")
        git("commit", "-q", "-m", "initial")
        (results / "catalog.json").write_text(json.dumps({"include_rule": "fix", "scanned": 1, "excluded": [], "fixes": []}))
        (results / "szz.json").write_text(json.dumps({"head": git("rev-parse", "HEAD"), "path": ".", "bugs": [],
                                                      "summary": {"fixes": 0, "with_introducer": 0}}))
        (spike / "results" / "report.json").write_text(json.dumps({"verdict": "GO", "built_and_tested_share": "high",
                                                                   "counts": {}, "method": {}, "results": []}))
        run = cli("bundle", "--repo", repo, "--results", results, "--repo-url", "https://example.org/r",
                  "--out", out, "--spike", spike, check=False)
        self.assertEqual(run.returncode, 1, run.stderr)
        self.assertIn("bundle fails its schema", run.stderr)
        self.assertFalse(out.exists() and any(out.iterdir()), "nothing may be written")
        # The same inputs with a valid report build and record the schema check.
        (spike / "results" / "report.json").write_text(json.dumps({"verdict": "GO", "built_and_tested_share": 0.9,
                                                                   "counts": {}, "method": {}, "results": []}))
        cli("bundle", "--repo", repo, "--results", results, "--repo-url", "https://example.org/r", "--out", out, "--spike", spike)
        self.assertEqual(json.loads((out / "receipt.json").read_text())["schema_check"], "PASS")


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
