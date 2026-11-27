# SPDX-License-Identifier: MIT OR Apache-2.0
"""Method A against a developer-informed oracle, side by side with PyDriller.

The oracle is Rosa et al., "Evaluating SZZ Implementations Through a Developer-informed Oracle"
(ICSE 2021): fix commits whose bug-introducing commits the developers named themselves. See
docs/accuracy.md for the selection, the metrics and the results.

    python3 scripts/oracle_study.py select --oracle FILE --out results/oracle/repos.tsv
    python3 scripts/oracle_study.py run --oracle FILE --repos results/oracle/repos.tsv \
        --work work/oracle-study --out results/oracle

`select` needs network access to the GitHub API (GITHUB_TOKEN raises the rate limit). `run`
clones the selected repositories and needs PyDriller installed (pip install pydriller).
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ORACLE_URL = ("https://raw.githubusercontent.com/grosa1/icse2021-szz-replication-package/"
              "45a712d1508745b0d60e779d1bbc5035d1647b34/json-input-raw/bugfix_commits_all.json")
REPOS = 80


def python_entries(oracle):
    """Oracle entries whose only language is Python."""
    return [e for e in json.loads(Path(oracle).read_text(encoding="utf-8")) if e["language"] == ["py"]]


def repo_size(name, token):
    """GitHub's size in KB for `name`, or None when the repository is gone."""
    req = urllib.request.Request(f"https://api.github.com/repos/{name}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "bug-age-oracle-study"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code in (404, 451):
            return None
        raise
    # A renamed repository redirects; keep the oracle's name, which still resolves.
    return data["size"]


def cmd_select(args):
    names = sorted({e["repo_name"] for e in python_entries(args.oracle)})
    token = os.environ.get("GITHUB_TOKEN", "")
    sized = []
    for name in names:
        size = repo_size(name, token)
        if size is not None:
            sized.append((size, name))
    sized.sort()
    rows = ["repo\tsize_kb"] + [f"{n}\t{s}" for s, n in sized[:REPOS]]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"select: {len(names)} Python repositories, {len(sized)} still exist, kept {len(sized[:REPOS])}",
          file=sys.stderr)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout


def clone(name, work):
    dest = Path(work) / name.replace("/", "__")
    if not dest.exists():
        subprocess.run(["git", "clone", "-q", "--no-checkout", f"https://github.com/{name}", str(dest)],
                       check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    return dest


def has_commit(repo, sha):
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def bug_age_nominees(repo, fixes, work):
    """Run `bug-age szz` (python profile) on these fixes; return {fix: [nominee, ...]} ranked."""
    entries = []
    for sha in fixes:
        parents, date, subject = git(repo, "log", "-1", "--format=%P%x1f%cs%x1f%s", sha).rstrip("\n").split("\x1f")
        entries.append({"sha": sha, "parents": parents.split(), "date": date, "subject": subject,
                        "rule": "include"})
    catalog = Path(work) / (repo.name + ".catalog.json")
    out = Path(work) / (repo.name + ".szz.json")
    catalog.write_text(json.dumps({"head": fixes[0], "path": ".", "profile": "python",
                                   "fixes": entries}), encoding="utf-8")
    subprocess.run([sys.executable, "-m", "bug_age", "szz", "--repo", str(repo), "--catalog", str(catalog),
                    "--out", str(out)], check=True, capture_output=True, cwd=ROOT,
                   env={**os.environ, "PYTHONPATH": str(ROOT)})
    bugs = json.loads(out.read_text(encoding="utf-8"))["bugs"]
    return {b["fix"]: [n["sha"] for n in b["nominees"]] for b in bugs}


def pydriller_nominees(repo, sha):
    """PyDriller's B-SZZ: every commit that last modified a line the fix deleted or changed."""
    from pydriller import Git
    found = Git(str(repo)).get_commits_last_modified_lines(Git(str(repo)).get_commit(sha))
    return sorted({c for commits in found.values() for c in commits})


def score(rows, key):
    """Pair-level precision, recall and F1 over (fix, commit) pairs, and fixes with a hit."""
    named = sum(len(r[key]) for r in rows)
    truth = sum(len(r["oracle"]) for r in rows)
    hits = sum(len(set(r[key]) & set(r["oracle"])) for r in rows)
    fixes_hit = sum(1 for r in rows if set(r[key]) & set(r["oracle"]))
    p = hits / named if named else 0.0
    rec = hits / truth if truth else 0.0
    f1 = 2 * p * rec / (p + rec) if p + rec else 0.0
    return {"named": named, "correct": hits, "oracle": truth, "precision": round(p, 2),
            "recall": round(rec, 2), "f1": round(f1, 2), "fixes_with_true_introducer": fixes_hit}


def cmd_run(args):
    import pydriller
    from bug_age import __version__, profiles
    selected = [line.split("\t")[0] for line in Path(args.repos).read_text(encoding="utf-8").splitlines()[1:]]
    entries = [e for e in python_entries(args.oracle) if e["repo_name"] in set(selected)]
    Path(args.work).mkdir(parents=True, exist_ok=True)
    rows, missing = [], []
    for name in selected:
        repo = clone(name, args.work)
        fixes = [e for e in entries if e["repo_name"] == name]
        present = [e for e in fixes if has_commit(repo, e["fix_commit_hash"])]
        missing += [e["fix_commit_hash"] for e in fixes if e not in present]
        if not present:
            continue
        ours = bug_age_nominees(repo, [e["fix_commit_hash"] for e in present], args.work)
        for e in present:
            fix = e["fix_commit_hash"]
            nominees = ours.get(fix, [])
            changed = git(repo, "diff-tree", "--no-commit-id", "-r", "--name-only", fix + "^", fix).split("\n")
            rows.append({"repo": name, "fix": fix, "oracle": sorted(e["bug_commit_hash"]),
                         "changes_product_code": any(profiles.in_scope("python", f, ".") for f in changed if f),
                         "bug_age_all": nominees, "bug_age_primary": nominees[:1],
                         "pydriller": pydriller_nominees(repo, fix)})
    keys = ("bug_age_all", "bug_age_primary", "pydriller")
    product = [r for r in rows if r["changes_product_code"]]
    summary = {"oracle": ORACLE_URL, "repositories": len(selected), "fixes": len(rows),
               "fix_commits_missing": missing, "bug_age": __version__, "pydriller": pydriller.__version__,
               "git": git(".", "--version").strip(),
               "scores": {k: score(rows, k) for k in keys},
               "product_code_fixes": len(product),
               "scores_product_code_fixes": {k: score(product, k) for k in keys},
               "only_pydriller": sum(1 for r in rows if set(r["pydriller"]) & set(r["oracle"])
                                     and not set(r["bug_age_all"]) & set(r["oracle"])),
               "only_bug_age": sum(1 for r in rows if set(r["bug_age_all"]) & set(r["oracle"])
                                   and not set(r["pydriller"]) & set(r["oracle"])),
               "bug_age_no_nominee": sum(1 for r in rows if not r["bug_age_all"])}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fixes.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary["scores"], indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--oracle", required=True)
    s.add_argument("--out", required=True)
    r = sub.add_parser("run")
    r.add_argument("--oracle", required=True)
    r.add_argument("--repos", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--out", required=True)
    args = ap.parse_args()
    {"select": cmd_select, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
