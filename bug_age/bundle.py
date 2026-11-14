# SPDX-License-Identifier: MIT OR Apache-2.0
"""Bundle builder.

Canonical data bundle: every number the explorer page and the article use, assembled from script
outputs only (catalog, Method A, Method B sweeps, A-checks, feasibility runs).

Blameless by construction: commits carry SHA, date and a short subject; every author and committer
name/email in the repository history is redacted from subjects, and a gate scans every string in
the bundle for emails, @handles and those names. A hit fails the build.
"""
import os
import re
from pathlib import Path

from . import __version__
from ._compat import as_f64, dumps, get, lines, loads, round1, total_order, trim
from .catalog import sanitize_subject
from .git import commit_time, git, is_ancestor

SCHEMA_VERSION = "1.1.0"
REDACTED = "[redacted]"
_PLAIN = re.compile(r"[A-Za-z0-9_./:=,@+\-~]+")


class BundleError(RuntimeError):
    """The bundle cannot be built, or failed its blameless gate."""


def public_command(args, cwd, home):
    """The command line as it may be published: paths under cwd relative, under home as ~, shell-quoted."""
    def under(a, root):
        root = root.rstrip("/")
        if not root:
            return None
        if a == root:
            return ""
        if a.startswith(root + "/"):
            return a[len(root) + 1:]
        return None
    out = []
    for a in args:
        rel, hrel = under(a, cwd), under(a, home)
        if rel is not None:
            a = rel or "."
        elif hrel is not None:
            a = f"~/{hrel}" if hrel else "~"
        out.append(a if _PLAIN.fullmatch(a) else "'" + a.replace("'", "'\\''") + "'")
    return " ".join(out)


def people(repo):
    """Every author/committer name and email in the history, lowercased, longest first."""
    log = git(repo, ["log", "--all", "--format=%an%n%ae%n%cn%n%ce"])
    found = set()
    for line in (trim(l) for l in lines(log)):
        # Lengths are UTF-8 bytes, as Rust measures them.
        if len(line.encode()) < 3:
            continue
        found.add(line.lower())
        local, at, _ = line.partition("@")
        if at:
            user = local.rsplit("+", 1)[-1]
            if len(user.encode()) >= 3:
                found.add(user.lower())
    for generic in ("github", "noreply", "web-flow", "users.noreply.github.com"):
        found.discard(generic)
    # Byte order first (as a BTreeSet), then longest first, so full names win over their parts.
    ordered = sorted(found, key=lambda s: s.encode())
    return sorted(ordered, key=lambda s: -len(s.encode()))


class Identities:
    """Name, email and @handle patterns for redaction and for the blameless gate."""

    def __init__(self, names):
        # Rust's `$` matches only at the very end; Python's also before a final newline, hence \Z.
        alternation = [re.escape(p) for p in names]
        self.names = re.compile(r"(?i)(^|[^\w])(" + "|".join(alternation) + r")(\Z|[^\w])") if alternation else None
        self.email = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        self.handle = re.compile(r"(^|\s)@[A-Za-z0-9][A-Za-z0-9_-]+")

    def redact(self, text):
        """Replace every known name in `text`, repeating until none is left (matches can overlap)."""
        if self.names is None:
            return text
        while self.names.search(text):
            text = self.names.sub(lambda m: m.group(1) + REDACTED + m.group(3), text)
        return text

    def hit(self, s):
        """A description of the first identity found in `s`, or None."""
        if self.email.search(s) or self.handle.search(s):
            return f"email/handle in {s!r}"
        m = self.names.search(s) if self.names else None
        return f"person {m.group(2)!r} in {s!r}" if m else None


def scan(value, ids):
    """Every identity hit in every string of `value`."""
    hits, stack = [], [value]
    while stack:
        x = stack.pop()
        if isinstance(x, str):
            h = ids.hit(x)
            if h:
                hits.append(h)
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, dict):
            stack.extend(x.values())
    return hits


def _read(path):
    """A JSON file as a value."""
    try:
        return loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleError(f"{path}: {exc}") from exc


def _pct(v, q):
    """Value at rank floor(q * n) of sorted `v`, capped at the last."""
    return v[min(int(q * float(len(v))), len(v) - 1)]


def _median(v):
    """Median of sorted `v`; the mean of the middle two for an even count."""
    n = len(v)
    return v[n // 2] if n % 2 == 1 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def method_a_days(bug):
    """Committer days of a bug, or author days when a rebase compressed committer dates."""
    life = bug.get("lifetime")
    flags = bug.get("flags")
    if not isinstance(life, dict) or not isinstance(flags, list):
        return None
    compressed = any(isinstance(f, str) and f.startswith("committer-dates-compressed") for f in flags)
    return as_f64(life.get("calendar_days_author" if compressed else "calendar_days"))


def _stat(v):
    """Median, p90, max and count of sorted floats, or None when empty."""
    if not v:
        return None
    return {"median": _median(v), "p90": _pct(v, 0.9), "max": v[-1], "n": len(v)}


def method_a_summary(szz):
    """Headline Method A statistics over every bug with a lifetime."""
    bugs = get(szz, "bugs") if isinstance(get(szz, "bugs"), list) else []
    days = sorted((d for d in map(method_a_days, bugs) if d is not None), key=total_order)
    commits = sorted((c for c in (as_f64(get(b, "lifetime", "commits_elapsed")) for b in bugs) if c is not None),
                     key=total_order)
    releases = sorted((float(len(r)) for r in (get(b, "lifetime", "releases_spanned") for b in bugs)
                       if isinstance(r, list)), key=total_order)
    return {
        "fixes": len(bugs),
        "with_introducer": len(days),
        "in_window": get(szz, "summary", "in_window"),
        "window_start": get(szz, "summary", "window_start"),
        "calendar_days": _stat(days),
        "commits_elapsed": _stat(commits),
        "releases_shipped_bug": _stat(releases),
    }


def acheck_label(outcomes):
    """What the A-check (test at the nominee's parent and at the nominee) says about the nominee."""
    return {("PASS", "FAIL"): "confirmed", ("FAIL", "FAIL"): "too-late", ("PASS", "PASS"): "refuted",
            ("UNTESTABLE", "FAIL"): "plausible", ("UNTESTABLE", "UNTESTABLE"): "untested"}.get(tuple(outcomes), "inconclusive")


def _days_between(repo, a, b):
    """Committer-time difference from `a` to `b`, in days rounded to one decimal."""
    return round1((commit_time(repo, b) - commit_time(repo, a)) / 86400.0)


def _items(value):
    """The elements of a JSON array, or none."""
    return value if isinstance(value, list) else []


def _read_text_or_empty(path):
    """A UTF-8 file's text, or "" when it is missing or not UTF-8 (as Rust's read_to_string().unwrap_or_default())."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def method_b(repo, d, szz):
    """One entry per recorded sweep in `d` (sorted by directory name), with its A-check."""
    out = []
    d = Path(d)
    if not d.is_dir():
        return out  # no repros for this target: Method B is reported NOT TESTED
    for name in sorted(os.listdir(d), key=lambda n: os.fsencode(n)):
        entry = d / name
        if not (entry / "sweep.json").is_file():
            continue
        s = _read(entry / "sweep.json")
        fix = get(s, "fix") if isinstance(get(s, "fix"), str) else ""
        a_bug = next((b for b in _items(get(szz, "bugs")) if get(b, "fix") == fix), None)
        nominee = get(a_bug, "nominees", 0, "sha") if a_bug is not None else None
        nominee = nominee if isinstance(nominee, str) else None
        verdict = get(s, "verdict") if isinstance(get(s, "verdict"), str) else ""
        first = get(s, "first_failing") if isinstance(get(s, "first_failing"), str) else None
        b_days = _days_between(repo, first, fix) if first is not None else None
        if (entry / "acheck.json").is_file():
            a = _read(entry / "acheck.json")
            outs = [o for o in (get(r, "outcome") for r in _items(get(a, "results"))) if isinstance(o, str)]
            acheck = {"outcomes": outs, "label": acheck_label(outs)}
        else:
            acheck = {"outcomes": [], "label": "not-run"}
        if nominee is not None:
            # A pass after the nominee, on its own line of history, means the nominee did not break the test.
            passes_after = [r["sha"] for r in _items(get(s, "results"))
                            if get(r, "outcome") == "PASS" and get(r, "sha") != fix and get(r, "sha") != nominee
                            and isinstance(get(r, "sha"), str)]
            passes_after = [sha for sha in passes_after if is_ancestor(repo, nominee, sha)]
            if passes_after:
                acheck["label"] = "refuted"
                acheck["evidence"] = f"test passes at {passes_after[-1][:12]} after the nominee"
        results = [{"sha": get(r, "sha"), "outcome": get(r, "outcome"), "reason": get(r, "reason"),
                    "toolchain": get(r, "toolchain"),
                    "steps": [{"name": get(st, "name"), "exit": get(st, "exit"), "seconds": get(st, "seconds"),
                               "network": get(st, "network")} for st in _items(get(r, "steps"))]}
                   for r in _items(get(s, "results"))]
        out.append({
            "id": name,
            "fix": fix,
            "verdict": verdict,
            "reason": get(s, "reason"),
            "first_failing": first,
            "last_passing": get(s, "last_passing"),
            "days": b_days,
            "days_is_lower_bound": verdict != "located",
            "untestable_between": get(s, "untestable_between"),
            "non_monotonic": get(s, "non_monotonic"),
            "range_start": get(s, "start"),
            "range_commits": get(s, "range_commits"),
            "commits_tested": get(s, "commits_tested"),
            "repeats": get(s, "repeats"),
            "test_command": get(s, "test"),
            "method_a_nominee": nominee,
            "method_a_days": method_a_days(a_bug) if a_bug is not None else None,
            "a_check": acheck,
            "results": results,
            "repro_test": _read_text_or_empty(entry / "overlay" / "tests" / "bugage_repro.rs"),
        })
    return out


def feasibility(path):
    """The fields of a feasibility report the bundle publishes, or None when it was not run."""
    if not Path(path).is_file():
        return None
    r = _read(path)
    return {
        "verdict": get(r, "verdict"),
        "built_and_tested_share": get(r, "built_and_tested_share"),
        "counts": get(r, "counts"),
        "method": get(r, "method"),
        "samples": [{"sha": get(s, "sha"), "date": get(s, "date"), "toolchain": get(s, "toolchain"),
                     "status": get(s, "status"), "reason": get(s, "reason"),
                     "lockfile_committed": get(s, "lockfile_committed")} for s in _items(get(r, "results"))],
    }


def coverage(a, b, feas, tt, out_of_scope):
    """What each stage proves and does not prove: COVERED, PARTIAL or NOT TESTED."""
    swept = len(b)
    fixes = a["fixes"] if isinstance(a["fixes"], int) else 0

    def share(f):
        # Rust formats the JSON value itself, so a number prints as JSON and a missing one as null.
        return "not run" if f is None else dumps(get(f, "built_and_tested_share"))

    if feas is None and tt is None:
        buildability = {"stage": "Historical buildability", "status": "NOT TESTED",
                        "evidence": "no feasibility report", "proves": "nothing",
                        "does_not_prove": "that any historical commit builds"}
    else:
        first = next(f for f in (feas, tt) if f is not None)
        samples = len(first["samples"]) if isinstance(get(first, "samples"), list) else 0
        buildability = {"stage": "Historical buildability", "status": "COVERED",
                        "evidence": f"{samples} sampled commits; {share(feas)} with today's registry, "
                                    f"{share(tt)} with time-travel dependencies",
                        "proves": "sampled commits build and pass their unit tests offline in a date-matched toolchain",
                        "does_not_prove": "that every commit builds; integration tests needing downloaded fixtures were not run"}
    if swept == 0:
        mb = {"stage": "Method B (behavioural sweep)", "status": "NOT TESTED",
              "evidence": f"0 of {fixes} fixes have a regression test", "proves": "nothing",
              "does_not_prove": "any bug's behavioural lifetime"}
    else:
        mb = {"stage": "Method B (behavioural sweep)", "status": "PARTIAL",
              "evidence": f"{swept} of {fixes} fixes have a regression test and a sweep",
              "proves": "where each tested bug's regression test starts failing, or a lower bound when censored",
              "does_not_prove": "anything about the fixes without a regression test (NOT TESTED)"}
    refuted = any(get(s, "a_check", "label") == "refuted" for s in b)
    rows = [buildability,
            {"stage": "Method A (SZZ)", "status": "PARTIAL",
             "evidence": f"{fixes} fixes from a rule-based catalog, {dumps(a['with_introducer'])} with a nominated introducer",
             "proves": "which earlier commit last touched the lines each fix changed",
             "does_not_prove": ("that the nominee introduced the bug (see the refuted case in Method B); fixes missed by the subject rules"
                                if refuted else "that the nominee introduced the bug; fixes missed by the subject rules")},
            mb]
    if out_of_scope is not None:
        stage, evidence, not_proved = out_of_scope
        rows.append({"stage": stage, "status": "NOT TESTED", "evidence": evidence, "proves": "nothing",
                     "does_not_prove": not_proved})
    return rows


def build(repo, results, spike, repo_url, out_of_scope):
    """Assemble the bundle for one target; raises BundleError if the blameless gate finds anyone."""
    results, spike = Path(results), Path(spike)
    catalog = _read(results / "catalog.json")
    szz = _read(results / "szz.json")
    feas = feasibility(spike / "results" / "report.json")
    tt = feasibility(spike / "results-timetravel" / "report.json")
    a_summary = method_a_summary(szz)
    b = method_b(repo, results / "repros", szz)
    ids = Identities(people(repo))
    shas = set()

    def add(v):
        if isinstance(v, str) and len(v.encode()) == 40:
            shas.add(v)
    for bug in _items(get(szz, "bugs")):
        add(get(bug, "fix"))
        for n in _items(get(bug, "nominees")):
            add(get(n, "sha"))
    for s in b:
        for k in ("fix", "first_failing", "last_passing", "range_start", "method_a_nominee"):
            add(s[k])
        for r in s["results"]:
            add(r["sha"])
    for f in (feas, tt):
        for s in _items(get(f, "samples")):
            add(get(s, "sha"))
    commits = {}
    for sha in sorted(shas, key=lambda s: s.encode()):
        line = git(repo, ["show", "-s", "--format=%cs%x1f%s", sha])
        date, sep, subject = trim(line).partition("\x1f")
        if not sep:
            date, subject = "", ""
        commits[sha] = {"date": date, "subject": ids.redact(sanitize_subject(subject))}
    method_a = []
    for bug in _items(get(szz, "bugs")):
        row = dict(bug)
        row.pop("subject", None)
        row["days"] = method_a_days(bug)
        method_a.append(row)
    verdicts = {}
    for s in b:
        verdicts[s["verdict"]] = verdicts.get(s["verdict"], 0) + 1
    bundle = {
        "schema_version": SCHEMA_VERSION,
        "generator": f"bug-age {__version__}",
        "subject": {"repo_url": repo_url, "crate_path": get(szz, "path"), "head": get(szz, "head")},
        "summary": {"method_a": a_summary,
                    "method_b": {"swept": len(b), "located": sum(1 for s in b if s["verdict"] == "located"),
                                 "a_refuted": sum(1 for s in b if s["a_check"]["label"] == "refuted"),
                                 "verdicts": verdicts},
                    "feasibility": {"baseline_share": get(feas, "built_and_tested_share"),
                                    "time_travel_share": get(tt, "built_and_tested_share")}},
        "catalog": {"include_rule": get(catalog, "include_rule"), "scanned": get(catalog, "scanned"),
                    "excluded": [{"sha": get(e, "sha"), "rule": get(e, "rule")} for e in _items(get(catalog, "excluded"))]},
        "method_a": method_a,
        "method_b": b,
        "feasibility": {"baseline": feas, "time_travel": tt},
        "coverage": coverage(a_summary, b, feas, tt, out_of_scope),
        "commits": commits,
    }
    hits = scan(bundle, ids)
    if hits:
        raise BundleError(f"blameless gate failed ({len(hits)} hits), first: {hits[0]}")
    return bundle
