# SPDX-License-Identifier: MIT OR Apache-2.0
"""Git access layer.

Thin wrapper over the `git` CLI. All history access goes through this module, so every number
bug-age reports is traceable to a concrete git command that anyone can re-run.
"""
import os
import subprocess

from ._compat import trim

# Variables git exports to hooks and subprocesses. `git -C <repo>` does not override them, so a
# bug-age run from inside a hook (or its tests during pre-commit) would otherwise read or write the
# *calling* repository. Every git invocation starts from this environment.
GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
           "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_PREFIX", "GIT_NAMESPACE",
           "GIT_CEILING_DIRECTORIES")


class GitError(RuntimeError):
    """A git command could not start or exited non-zero."""


def env():
    """The caller's environment without the inherited repository variables."""
    return {k: v for k, v in os.environ.items() if k not in GIT_ENV}


def run(repo, args, check=True, stdin=None):
    """Run `git -C repo args`; return the completed process (stdout and stderr as bytes)."""
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], env=env(), input=stdin, capture_output=True)
    except OSError as exc:
        raise GitError(f"failed to spawn git: {exc}") from exc
    if check and out.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {trim(out.stderr.decode('utf-8', 'replace'))}")
    return out


def git(repo, args):
    """Run `git -C repo args` and return stdout as text (invalid UTF-8 replaced, as Rust's from_utf8_lossy)."""
    return run(repo, args).stdout.decode("utf-8", "replace")


def _unix_time(repo, sha, fmt):
    """One timestamp field (`%ct` or `%at`) of a commit as unix seconds."""
    s = trim(git(repo, ["show", "-s", f"--format={fmt}", sha]))
    try:
        return int(s)
    except ValueError as exc:
        raise GitError(f"bad time for {sha}: {exc}") from exc


def commit_time(repo, sha):
    """Committer time (unix seconds) of a commit."""
    return _unix_time(repo, sha, "%ct")


def author_time(repo, sha):
    """Author time (unix seconds): survives rebases that rewrite committer dates."""
    return _unix_time(repo, sha, "%at")


def commit_date(repo, sha):
    """Committer date (YYYY-MM-DD, committer timezone) of a commit."""
    return trim(git(repo, ["show", "-s", "--format=%cs", sha]))


def is_ancestor(repo, a, b):
    """Whether commit `a` is an ancestor of (or equal to) commit `b`."""
    return run(repo, ["merge-base", "--is-ancestor", a, b], check=False).returncode == 0
