# SPDX-License-Identifier: MIT OR Apache-2.0
"""Method A: blame-based introducer nomination (SZZ-style).

For each fix commit, blame the lines it removed or changed in its first parent and nominate the
commit(s) that last touched them. Known limits are flagged per bug rather than hidden:
addition-only fixes have nothing to blame, the latest toucher is not necessarily the introducer,
and `-w` only discounts whitespace-only changes.
"""
import re

from ._compat import lines, round1, split_whitespace, trim
from .git import GitError, author_time, commit_date, commit_time, git

_HEX40 = re.compile(r"[0-9a-fA-F]{40}")


def in_scope(file, path):
    """Files of interest: Rust sources under `path`, outside tests/ and benches/."""
    prefix = path.rstrip("/") + "/"
    return ((path == "." or file.startswith(prefix)) and file.endswith(".rs")
            and "/tests/" not in file and "/benches/" not in file)


def _u64(text):
    """Rust's `str::parse::<u64>`: ASCII digits with an optional leading '+', else None."""
    t = text[1:] if text.startswith("+") else text
    return int(t) if t and t.isascii() and t.isdigit() else None


def removed_ranges(diff, path):
    """Old-side line ranges per file from `git diff -U0` output: (file, start, count)."""
    out, file = [], None
    for line in lines(diff):
        if line.startswith("--- "):
            rest = line[4:]
            file = rest[2:] if rest.startswith("a/") and in_scope(rest[2:], path) else None
        elif file is not None and line.startswith("@@ -"):
            words = split_whitespace(line[4:])
            old = words[0] if words else ""
            parts = old.split(",")
            start = _u64(parts[0]) or 0
            count = 1 if len(parts) == 1 else (_u64(parts[1]) or 0)
            if count > 0:
                out.append((file, start, count))
    return out


def blame_counts(porcelain, counts):
    """Count blamed lines per commit from `git blame --porcelain` output into `counts`."""
    for line in lines(porcelain):
        parts = line.split(" ")
        if len(parts) >= 3 and _HEX40.fullmatch(parts[0]):
            counts[parts[0]] = counts.get(parts[0], 0) + 1


def _shortstat(s):
    """`git diff --shortstat` as (files, insertions, deletions); missing parts count as zero."""
    def num(key):
        part = next((p for p in s.split(",") if key in p), None)
        words = split_whitespace(part) if part is not None else []
        return (_u64(words[0]) or 0) if words else 0
    return num("file"), num("insertion"), num("deletion")


def _count(repo, extra, rng):
    """`git rev-list --count [extra] range` as an int."""
    text = trim(git(repo, ["rev-list", "--count", *extra, rng]))
    value = _u64(text)
    if value is None:
        raise GitError(f"bad count: {text!r}")
    return value


def lifetime(repo, intro, fix, path, release_tags):
    """Span from introducer `intro` to `fix`: commits, days, releases shipped and churn."""
    rng = f"{intro}..{fix}"
    fix_time = commit_time(repo, fix)
    tags = git(repo, ["tag", "--list", release_tags, "--contains", intro, "--no-contains", fix,
                      "--format=%(refname:short)\t%(creatordate:unix)"])
    releases = []
    for line in lines(tags):
        name, tab, when = line.partition("\t")
        # Tags created after the fix landed did not ship the bug.
        if tab and re.fullmatch(r"[+-]?[0-9]+", when) and int(when) <= fix_time:
            releases.append(name)
    files, ins, dels = _shortstat(git(repo, ["diff", "--shortstat", intro, fix, "--", path]))
    secs = fix_time - commit_time(repo, intro)
    author_secs = author_time(repo, fix) - author_time(repo, intro)
    return {
        "commits_elapsed": _count(repo, [], rng),
        "commits_elapsed_first_parent": _count(repo, ["--first-parent"], rng),
        "calendar_days": round1(secs / 86400.0),
        "calendar_days_author": round1(author_secs / 86400.0),
        "releases_spanned": releases,
        "churn_files": files,
        "churn_insertions": ins,
        "churn_deletions": dels,
    }


def analyze(repo, fix, path, window_start, release_tags):
    """Method A for one catalogued fix: blame the changed lines, rank candidates, measure the lifetime."""
    bug = {"fix": fix["sha"], "fix_date": fix["date"], "subject": fix["subject"], "blamed_files": [],
           "nominees": [], "lifetime": None, "in_window": None, "flags": []}
    parents = fix["parents"]
    if not parents:
        bug["flags"].append("root-commit")
        return bug
    if len(parents) > 1:
        bug["flags"].append("fix-is-merge(diffed-against-first-parent)")
    parent = parents[0]
    diff = git(repo, ["diff", "-U0", "-w", "--no-color", "-M", parent, fix["sha"], "--", path])
    counts = {}
    for file, start, n in removed_ranges(diff, path):
        out = git(repo, ["blame", "-w", "--porcelain", "-L", f"{start},+{n}", parent, "--", file])
        blame_counts(out, counts)
        if file not in bug["blamed_files"]:
            bug["blamed_files"].append(file)
    if not counts:
        bug["flags"].append("no-blame-lines(addition-only-or-out-of-scope)")
        return bug
    # Rank by blamed lines (desc), then SHA, so the primary nominee is deterministic.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) > 1:
        bug["flags"].append("multiple-candidates")
    for sha, n in ranked:
        bug["nominees"].append({"sha": sha, "date": commit_date(repo, sha), "blamed_lines": n})
    primary = bug["nominees"][0]
    bug["in_window"] = None if window_start is None else primary["date"] >= window_start
    life = lifetime(repo, primary["sha"], fix["sha"], path, release_tags)
    # Near-zero committer days across several commits means a rebase rewrote committer dates.
    if life["calendar_days"] < 0.1 and life["commits_elapsed"] > 1:
        bug["flags"].append("committer-dates-compressed(use-author-days)")
    bug["lifetime"] = life
    return bug
