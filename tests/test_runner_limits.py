# SPDX-License-Identifier: MIT OR Apache-2.0
"""Runner steps are bounded in time and in logged output."""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
import warnings
from pathlib import Path

from bug_age import runner
from helpers import clean_env, cli


class Limits(unittest.TestCase):
    """A step that never ends is stopped; endless output is capped; neither leaves processes behind."""

    def setUp(self):
        """A scratch directory per test."""
        self.d = Path(tempfile.mkdtemp(prefix="bug-age-limits-"))
        self.addCleanup(shutil.rmtree, self.d, True)

    def test_step_over_its_limit_is_stopped_with_its_children(self):
        """A shell that starts a sleeping child is stopped at the limit; the child does not survive."""
        pidfile = self.d / "child.pid"
        t0 = time.monotonic()
        code, _ = runner.run_logged(["sh", "-c", f"sleep 300 & echo $! > {pidfile}; wait"], self.d / "a.log", timeout=1)
        self.assertEqual(code, runner.TIMED_OUT)
        self.assertLess(time.monotonic() - t0, 30)
        self.assertIn("step limit", (self.d / "a.log").read_text())
        child = int(pidfile.read_text())
        time.sleep(0.2)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)

    def test_endless_output_is_capped(self):
        """64 MiB of output leaves a log of about the cap, with its start, its end and a note."""
        cmd = "printf START; head -c 67108864 /dev/zero | tr '\\\\0' x; printf END"
        code, _ = runner.run_logged(["sh", "-c", cmd], self.d / "b.log")
        self.assertEqual(code, 0)
        text = (self.d / "b.log").read_bytes()
        self.assertLess(len(text), runner.LOG_CAP + 4096)
        self.assertIn(b"START", text[:200])
        self.assertTrue(text.rstrip().endswith(b"END"))
        self.assertIn(b"bytes of output not kept", text)

    def test_cap_is_exact_for_sizes_that_do_not_fit_read_chunks(self):
        """The kept output is exactly min(size, LOG_CAP) bytes; only the command line and one notice are added."""
        for size in (8 * 1024 * 1024 + 1, 9_000_001, 12_345_678, 20_000_003, 33_554_431, 1000):
            with self.subTest(size=size):
                log = self.d / f"{size}.log"
                runner.run_logged(["sh", "-c", f"head -c {size} /dev/zero | tr '\\0' x"], log)
                text = log.read_bytes()
                header, _, rest = text.partition(b"\n")
                kept = rest.replace(f"\n[bug-age: {max(0, size - runner.LOG_CAP)} bytes of output not kept]\n".encode(), b"")
                self.assertEqual(len(kept), min(size, runner.LOG_CAP))
                self.assertEqual(set(kept), {ord("x")})
                self.assertLessEqual(len(text), runner.LOG_CAP + len(header) + 1 + 64)

    def test_hanging_test_is_a_failure_with_the_reason(self):
        """In a sweep, a test that hangs fails at --step-timeout and the reason names the limit."""
        repo = self.d / "repo"
        (repo / "toy").mkdir(parents=True)
        env = dict(clean_env(), GIT_AUTHOR_NAME="T", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="T", GIT_COMMITTER_EMAIL="t@e",
                   GIT_CONFIG_GLOBAL=os.devnull)
        git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *a], env=env, check=True,
                                        capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main")
        (repo / "toy" / "a.txt").write_text("x\n")
        git("add", "-A")
        git("commit", "-q", "-m", "one")
        overlay = self.d / "overlay"
        overlay.mkdir()
        (overlay / "t.txt").write_text("t\n")
        out = cli("probe", "--repo", repo, "--path", "toy", "--commits", "HEAD", "--overlay", overlay, "--runner", "local",
                  "--repeats", "1", "--build", "true", "--test", "sleep 60", "--step-timeout", "1",
                  "--scratch", self.d / "scratch", "--logs", self.d / "logs")
        r = json.loads(out.stdout)["results"][0]
        self.assertEqual(r["outcome"], "FAIL")
        self.assertIn("stopped at the 1 s step limit", r["reason"])
        self.assertEqual(r["steps"][-1]["exit"], runner.TIMED_OUT)

    def test_output_pipe_is_closed_when_the_step_returns(self):
        """Neither a finished nor a stopped step leaves its output pipe for the garbage collector."""
        for name, cmd, timeout in (("done", "echo out", None), ("stopped", "echo out; sleep 5", 1)):
            with self.subTest(name), warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", ResourceWarning)
                runner.run_logged(["sh", "-c", cmd], self.d / f"{name}.log", timeout=timeout)
                leaks = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
                self.assertEqual(leaks, [])

    def test_step_timeout_must_be_positive(self):
        """--step-timeout 0 is a usage error."""
        out = cli("probe", "--repo", ".", "--path", "x", "--commits", "HEAD", "--overlay", ".", "--test", "true",
                  "--runner", "local", "--step-timeout", "0", check=False)
        self.assertEqual(out.returncode, 2)


if __name__ == "__main__":
    unittest.main()
