# SPDX-License-Identifier: MIT OR Apache-2.0
"""Fix-commit catalog.

This is where bug-age decides which commits are bug fixes. It does not test anything: it reads
commit subjects. A commit is a fix when it is on the first-parent history, touches the path, its
subject matches INCLUDE, and it matches none of the EXCLUDE rules. Bugs that were never fixed, or
were fixed under a subject without these words, are not in the catalog. Every entry records the
rule that admitted or rejected it, so the catalog can be audited and re-derived.
"""
import re

from ._compat import split_whitespace, trim
from .git import git

# A subject is a fix candidate when it says fix/fixes/fixed/fixing, bug(s) or hotfix as a word.
INCLUDE = r"(?i)\b(fix(e[sd]|ing)?|bugs?|hotfix)\b"

# (rule name, pattern). The first matching rule excludes the commit.
EXCLUDE = (
    ("typo", r"(?i)\btypos?\b"),
    ("lint-or-format", r"(?i)\b(warnings?|clippy|lint(s|ing)?|fmt|rustfmt|format(ting)?)\b"),
    ("docs", r"(?i)\b(docs?|readme|documentation|docstrings?|comments?)\b"),
    ("ci", r"(?i)\b(ci|workflows?)\b"),
    ("release", r"(?i)\b(release|bump|version)\b"),
    ("deprecation", r"(?i)\bdeprecat"),
    ("build-only", r"(?i)\b(compile errors?|builds?|compilation)\b"),
    ("feature-name", r"(?i)\bfixed[- ]length\b"),
)

_INCLUDE = re.compile(INCLUDE)
_EXCLUDE = tuple((name, re.compile(pat)) for name, pat in EXCLUDE)
_FROM = re.compile(r"\s+from\s+\S+/\S+")
_HANDLE = re.compile(r"@[A-Za-z0-9][A-Za-z0-9_-]*")


def sanitize_subject(subject):
    """Subject without merge-source `from owner/branch` and @handles, trimmed, at most 100 characters."""
    return trim(_HANDLE.sub("", _FROM.sub("", subject)))[:100]


def classify(subject):
    """None if the subject is not a fix candidate; else "include" or "exclude:<rule>"."""
    if not _INCLUDE.search(subject):
        return None
    for name, pat in _EXCLUDE:
        if pat.search(subject):
            return f"exclude:{name}"
    return "include"


def build(repo, head, path):
    """Scan first-parent history of `head` touching `path`; return the catalog as a dict."""
    log = git(repo, ["log", "--first-parent", "--format=%H%x1f%P%x1f%cs%x1f%s%x1e", head, "--", path])
    fixes, excluded, scanned = [], [], 0
    for rec in (trim(r) for r in log.split("\x1e")):
        if not rec:
            continue
        scanned += 1
        f = rec.split("\x1f")
        rule = classify(f[3])
        if rule is None:
            continue
        entry = {"sha": f[0], "parents": split_whitespace(f[1]), "date": f[2],
                 "subject": sanitize_subject(f[3]), "rule": rule}
        (fixes if rule == "include" else excluded).append(entry)
    head = trim(git(repo, ["rev-parse", head]))
    return {"head": head, "path": path, "scanned": scanned, "include_rule": INCLUDE,
            "fixes": fixes, "excluded": excluded}
