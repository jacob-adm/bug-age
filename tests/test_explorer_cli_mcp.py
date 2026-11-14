# SPDX-License-Identifier: MIT OR Apache-2.0
"""Explorer assembly, the command-line contract and the MCP server."""
import json
import unittest

from bug_age import __version__
from bug_age.explorer import GATE_BYTES, MARKER, ExplorerError, assemble
from helpers import ROOT, cli

BUNDLE = ROOT / "dist" / "tokenizers" / "bundle.json"
FIXTURES = ROOT / "tests" / "fixtures" / "mcp"


def target(name, filler):
    """A minimal explorer target whose bundle carries `filler` bytes."""
    return (name, {"commits": {}, "pad": "x" * filler}, {"blameless_gate": "PASS"})


class Explorer(unittest.TestCase):
    """The page links one data script per target and enforces its gates."""

    def test_links_one_data_script_per_target_in_order(self):
        """Scripts appear in the given order, before the page's own code; the marker is gone."""
        page, files, _ = assemble(f"<title>t</title>{MARKER}<script>boot()</script>",
                                  [target("tokenizers", 0), target("rust-sdk", 0)])
        a, b = page.find("data/tokenizers.js"), page.find("data/rust-sdk.js")
        self.assertTrue(0 <= a < b < page.find("boot()"))
        self.assertNotIn(MARKER, page)
        self.assertEqual(len(files), 2)
        self.assertTrue(files[1][1].startswith("(window.BUG_AGE = window.BUG_AGE || []).push({"))

    def test_escapes_closing_tags_inside_data(self):
        """A string containing </script> cannot close the page's script element."""
        _, files, _ = assemble(MARKER, [("a", {"subject": "</script><img src=x>"}, {"blameless_gate": "PASS"})])
        self.assertNotIn("</script>", files[0][1])

    def test_rejects_oversize_bad_names_duplicates_and_missing_marker(self):
        """Each invalid input is refused."""
        with self.assertRaisesRegex(ExplorerError, "size gate failed"):
            assemble(MARKER, [target("big", GATE_BYTES)])
        with self.assertRaises(ExplorerError):
            assemble(MARKER, [target("../x", 0)])
        with self.assertRaisesRegex(ExplorerError, "twice"):
            assemble(MARKER, [target("a", 0), target("a", 0)])
        with self.assertRaises(ExplorerError):
            assemble("<p>no marker</p>", [target("a", 0)])
        with self.assertRaises(ExplorerError):
            assemble(MARKER, [])


class Cli(unittest.TestCase):
    """Version, usage errors and exit codes."""

    def test_version_reports_package_version(self):
        """--version prints the package version."""
        out = cli("--version")
        self.assertEqual(out.stdout.strip(), f"bug-age {__version__}")

    def test_unknown_argument_fails_with_usage_exit_code(self):
        """An unknown subcommand exits 2 with the usage text."""
        out = cli("--definitely-not-a-flag", check=False)
        self.assertEqual(out.returncode, 2)
        self.assertIn("unknown argument", out.stderr)

    def test_runtime_error_exits_1(self):
        """A missing required flag is a runtime error: exit 1 and one message line."""
        out = cli("catalog", "--path", "x", check=False)
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stderr.strip(), "bug-age: missing --repo")


def serve(requests):
    """Replies of the MCP server over the tokenizers bundle to the given request lines."""
    out = cli("mcp", "--bundles", f"tokenizers={BUNDLE}", stdin=requests)
    return [json.loads(line) for line in out.stdout.splitlines()]


class Mcp(unittest.TestCase):
    """The MCP server answers only with values copied from the bundle."""

    @classmethod
    def setUpClass(cls):
        """The tokenizers bundle."""
        cls.b = json.loads(BUNDLE.read_text(encoding="utf-8"))

    def test_replays_recorded_session_exactly(self):
        """Replies equal the recorded session byte for byte, apart from the server version."""
        out = cli("mcp", "--bundles", f"tokenizers={BUNDLE}", stdin=(FIXTURES / "requests.jsonl").read_text()).stdout
        want = (FIXTURES / "responses.jsonl").read_text()
        recorded = json.loads(want.splitlines()[0])["result"]["serverInfo"]["version"]
        self.assertEqual(out.replace(f'"version":"{__version__}"', f'"version":"{recorded}"', 1), want)

    def test_get_fix_returns_the_bundle_row_unchanged(self):
        """get_fix copies the Method A row, the Method B row and the commit entries."""
        row = self.b["method_b"][0]
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "get_fix", "arguments": {"target": "tokenizers", "sha": row["fix"][:12]}}})
        reply = serve(req + "\n")[0]["result"]["structuredContent"]
        self.assertEqual(reply["method_a"], next(r for r in self.b["method_a"] if r["fix"] == row["fix"]))
        self.assertEqual(reply["method_b"], row)
        for sha, c in reply["commits"].items():
            self.assertEqual(c, self.b["commits"][sha], f"commit {sha} must be copied from the bundle")

    def test_search_rows_only_carry_bundle_values(self):
        """search_fixes rows carry exactly the documented keys, each copied from the bundle."""
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": "search_fixes", "arguments": {"target": "tokenizers", "limit": 200}}})
        reply = serve(req + "\n")[0]["result"]["structuredContent"]
        self.assertEqual(reply["total"], len(self.b["method_a"]))
        for f in reply["fixes"]:
            row = next(r for r in self.b["method_a"] if r["fix"] == f["fix"])
            self.assertEqual(f["days"], row["days"])
            self.assertEqual(f["fix_date"], row["fix_date"])
            self.assertEqual(f["subject"], self.b["commits"][f["fix"]]["subject"])
            self.assertEqual(f["commits_elapsed"], (row["lifetime"] or {}).get("commits_elapsed"))
            self.assertEqual(sorted(f), ["commits_elapsed", "days", "fix", "fix_date", "flags", "nominees",
                                         "releases_spanned", "subject"])

    def test_unknown_or_ambiguous_inputs_are_tool_errors_not_guesses(self):
        """An unknown SHA and an ambiguous prefix are tool errors without structured content."""
        fixes = sorted(r["fix"] for r in self.b["method_a"])
        shared = next((a[:7] for a, b in zip(fixes, fixes[1:]) if a[:7] == b[:7]), None)
        reqs = [{"target": "tokenizers", "sha": "fffffff0000000"}] + ([{"target": "tokenizers", "sha": shared}] if shared else [])
        lines = "".join(json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                                    "params": {"name": "get_fix", "arguments": a}}) + "\n" for i, a in enumerate(reqs, 1))
        for r in serve(lines):
            self.assertIs(r["result"]["isError"], True)
            self.assertNotIn("structuredContent", r["result"])


if __name__ == "__main__":
    unittest.main()
