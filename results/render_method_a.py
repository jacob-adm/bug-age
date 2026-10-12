#!/usr/bin/env python3
"""Render results/<repo>/METHOD_A.md from catalog.json + szz.json. Every figure is computed here.
Usage: python3 results/render_method_a.py results/tokenizers"""
import collections, hashlib, json, statistics, sys
from pathlib import Path


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))]


def main(d: Path) -> None:
    cat_raw, szz_raw = (d / "catalog.json").read_bytes(), (d / "szz.json").read_bytes()
    cat, szz = json.loads(cat_raw), json.loads(szz_raw)
    bugs = szz["bugs"]
    life = [b for b in bugs if b["lifetime"]]
    compressed = {b["fix"] for b in bugs if any(f.startswith("committer-dates-compressed") for f in b["flags"])}
    # Days per bug: committer days, except author days where committer dates were compressed by rebases.
    days = [b["lifetime"]["calendar_days_author" if b["fix"] in compressed else "calendar_days"] for b in life]
    commits = [b["lifetime"]["commits_elapsed"] for b in life]
    rels = [len(b["lifetime"]["releases_spanned"]) for b in life]
    s = szz["summary"]
    win = s["window_start"]
    fix_in_window = [b for b in bugs if win and b["fix_date"] >= win]
    flags = collections.Counter(f for b in bugs for f in b["flags"])
    lines = [
        f"# Method A (SZZ-style) — `{cat['path']}/` at `{szz['head'][:12]}`", "",
        f"Catalog: {cat['scanned']} first-parent commits scanned; {len(cat['fixes'])} fixes admitted by "
        f"`{cat['include_rule']}`; {len(cat['excluded'])} excluded by rule "
        f"({', '.join(f'{k.split(':')[1]}: {v}' for k, v in collections.Counter(e['rule'] for e in cat['excluded']).most_common())}).", "",
        f"Introducer nominated for {s['with_introducer']} of {s['fixes']} fixes.", "",
        "## Bug lifetimes (nominated introducer → fix)", "",
        "| Metric | Median | p90 | Max |", "|---|---|---|---|",
        f"| Calendar days | {statistics.median(days)} | {pct(days, .9)} | {max(days)} |",
        f"| Commits elapsed | {statistics.median(commits)} | {pct(commits, .9)} | {max(commits)} |",
        f"| Releases that shipped the bug (`v*` tags) | {statistics.median(rels)} | {pct(rels, .9)} | {max(rels)} |", "",
        f"Days use committer dates, except {len(compressed)} bugs whose committer dates were compressed by "
        "rebases (author dates used; flagged).", "",
        "## Testable window (from BUGAGE-1)", "",
        f"- Window start: {win}. Bugs whose nominated introducer is in the window: **{s['in_window']}**.",
        f"- Fixes dated in the window: {len(fix_in_window)}; of these, "
        f"{sum(1 for b in fix_in_window if b['in_window'] is False)} have an introducer before the window "
        "(a sweep could only give a lower bound).",
        f"- {round(100 * sum(1 for b in life if b['in_window'] is False) / len(life))}% of bugs with a nominee "
        "were introduced before the window; a window-only study would drop them, biasing lifetimes short.", "",
        "## Flags (known SZZ limits, per bug)", "",
        "| Flag | Bugs |", "|---|---|", *[f"| `{k}` | {v} |" for k, v in flags.most_common()], "",
        "## Longest-lived bugs", "",
        "| Fix | Fix date | Introducer | Days | Commits | Releases | Subject |", "|---|---|---|---|---|---|---|",
    ]
    for b, x in sorted(zip(life, days), key=lambda t: -t[1])[:10]:
        n = b["nominees"][0]
        lines.append(f"| `{b['fix'][:10]}` | {b['fix_date']} | `{n['sha'][:10]}` ({n['date']}) | {x} | "
                     f"{b['lifetime']['commits_elapsed']} | {len(b['lifetime']['releases_spanned'])} | "
                     f"{b['subject'][:60].replace('|', '/')} |")
    lines += ["", "## Limits", "",
              "- Nominee = latest toucher of removed/changed lines (`git blame -w`), not proven introducer; "
              "BUGAGE-4 checks this behaviourally.",
              "- Addition-only fixes have no blame lines; tests/ and benches/ are out of scope; "
              "in-file `#[cfg(test)]` modules are not excluded.",
              "- The catalog is rule-based on subjects: mixed commits (e.g. clippy + a real fix) can be excluded.",
              "", "## Inputs", "",
              f"- `catalog.json` sha256 `{hashlib.sha256(cat_raw).hexdigest()}`",
              f"- `szz.json` sha256 `{hashlib.sha256(szz_raw).hexdigest()}`"]
    (d / "METHOD_A.md").write_text("\n".join(lines) + "\n")
    print(d / "METHOD_A.md")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
