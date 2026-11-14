# SPDX-License-Identifier: MIT OR Apache-2.0
"""Shared fixtures for the bug-age tests: a scripted git repository and the CLI as a subprocess."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A fixed identity and no user or system config, so every fixture commit is reproducible.
_ENV = {"GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def clean_env():
    """The test process's environment without inherited repository variables (as during a git hook)."""
    from bug_age.git import env
    return env()


def run_git(d, args, date, extra_env=None):
    """Run git in `d` with the fixture identity and both dates set to `date`."""
    e = dict(clean_env(), **_ENV, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date, **(extra_env or {}))
    subprocess.run(["git", "-C", str(d), "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
                    "-c", "init.defaultBranch=main", *args], env=e, check=True, capture_output=True)


def head(d):
    """HEAD of the repository at `d`."""
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], env=clean_env(), check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(d, file, body, msg, date):
    """Write `file`, commit everything with `msg` at `date`, return the commit SHA."""
    p = Path(d) / file
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    run_git(d, ["add", "-A"], date)
    run_git(d, ["commit", "-q", "-m", msg], date)
    return head(d)


class SyntheticRepo:
    """A small history: a bug planted in core/src/lib.rs, released, fixed, then a typo commit.

    Tags: v0.1.0 and core-v0.1.0 on main; v0.1.1 (before the fix) and v0.1.2 (after) on a release branch.
    """

    def __init__(self):
        self._tmp = tempfile.mkdtemp(prefix="bug-age-test-")
        d = self.dir = Path(self._tmp)
        run_git(d, ["init", "-q"], "2025-01-01T00:00:00Z")
        lib = "core/src/lib.rs"
        commit(d, lib, "pub fn add(a: i32, b: i32) -> i32 { a + b }\n", "init", "2025-01-01T00:00:00Z")
        self.intro = commit(d, lib, "pub fn add(a: i32, b: i32) -> i32 { a + b }\npub fn mul(a: i32, b: i32) -> i32 { a + b }\n",
                            "add mul", "2025-01-02T00:00:00Z")
        commit(d, "core/README.md", "core\n", "describe core", "2025-01-05T00:00:00Z")
        run_git(d, ["tag", "v0.1.0"], "2025-01-05T00:00:00Z")
        run_git(d, ["tag", "core-v0.1.0"], "2025-01-05T00:00:00Z")
        run_git(d, ["checkout", "-q", "-b", "release-0.1"], "2025-01-06T00:00:00Z")
        commit(d, "core/CHANGELOG.md", "0.1.1\n", "changelog 0.1.1", "2025-01-06T00:00:00Z")
        run_git(d, ["tag", "-a", "v0.1.1", "-m", "v0.1.1"], "2025-01-06T00:00:00Z")
        commit(d, "core/CHANGELOG.md", "0.1.2\n", "changelog 0.1.2", "2025-01-20T00:00:00Z")
        run_git(d, ["tag", "-a", "v0.1.2", "-m", "v0.1.2"], "2025-01-20T00:00:00Z")
        run_git(d, ["checkout", "-q", "main"], "2025-01-06T00:00:00Z")
        self.fix = commit(d, lib, "pub fn add(a: i32, b: i32) -> i32 { a + b }\npub fn mul(a: i32, b: i32) -> i32 { a * b }\n",
                          "fix: mul used addition (#1) from someuser/branch", "2025-01-12T00:00:00Z")
        self.typo = commit(d, lib, "pub fn add(a: i32, b: i32) -> i32 { a + b }\npub fn mul(a: i32, b: i32) -> i32 { a * b } // product\n",
                           "Fix typo in comment", "2025-01-13T00:00:00Z")

    def cleanup(self):
        """Remove the repository."""
        shutil.rmtree(self._tmp, ignore_errors=True)


def cli(*args, env=None, stdin=None, check=True):
    """Run `python -m bug_age args` from the repository root; return the completed process."""
    out = subprocess.run([sys.executable, "-m", "bug_age", *map(str, args)], cwd=ROOT, env=env or clean_env(),
                         input=stdin, capture_output=True, text=True)
    if check and out.returncode != 0:
        raise AssertionError(f"bug-age {args}: {out.stderr}")
    return out


def cli_json(*args, **kw):
    """Run the CLI and parse its stdout as JSON."""
    return json.loads(cli(*args, **kw).stdout)
