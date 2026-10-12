#!/usr/bin/env python3
"""Render spike/results/REPORT.md from report.json + receipt.json. Every figure comes from those files."""
import hashlib, json
from pathlib import Path

RES = Path(__file__).resolve().parent / "results"
ROOT = Path(__file__).resolve().parent.parent


def main(res: Path = RES) -> None:
    global RES
    RES = res
    body = (RES / "report.json").read_text()
    rep, rec = json.loads(body), json.loads((RES / "receipt.json").read_text())
    smoke_f = Path(__file__).resolve().parent / "results" / "smoke-native-macos.report.json"
    smoke = json.loads(smoke_f.read_text())
    assert rec["outputs"][str((RES / "report.json").relative_to(ROOT))] == hashlib.sha256(body.encode()).hexdigest(), \
        "receipt hash does not match report.json"
    s, m, rows = rep["subject"], rep["method"], rep["results"]
    lines = [
        f"# {rep['ticket']} feasibility spike — verdict: **{rep['verdict']}**", "",
        f"Subject: `{s['repo']}` crate path `{s['crate_path']}/` at HEAD `{s['head']}` "
        f"({s['first_parent_commits_touching_crate']} first-parent commits touch the crate; "
        f"sampled window {s['history_window'][0]} → {s['history_window'][1]}).", "",
        f"Decision rule (fixed before the run): {m['decision_rule']}. "
        f"Result: {rep['built_and_tested_share']:.1%} BUILT_AND_TESTED.", "",
        "| Status | Commits |", "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(rep["counts"].items())], "",
        "## Method", "",
        *[f"- **{k}**: {v}" for k, v in m.items()], "",
        "## Per-commit results", "",
        "| # | SHA | Date | Toolchain | Edition | Lockfile | Status | Reason |", "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(f"| {r['index']} | `{r['sha'][:10]}` | {r['date']} | {r['toolchain']} | {r['edition']} | "
                     f"{'yes' if r['lockfile_committed'] else 'no'} | {r['status']} | {r['reason']} |")
    streak = []
    for r in reversed(rows):
        if r["status"] != "BUILT_AND_TESTED":
            break
        streak.append(r)
    lines += ["", "## Testable window today", "",
              (f"Newest unbroken run of BUILT_AND_TESTED samples: {len(streak)} of {len(rows)}, "
               f"from {streak[-1]['date']} (`{streak[-1]['sha'][:10]}`) to {streak[0]['date']}. "
               "A behavioral sweep is feasible as-is inside this window; older commits need the mitigations below."
               if streak else "The newest sample is not BUILT_AND_TESTED; there is no testable window as-is.")]
    no_lock = sum(1 for r in rows if not r["lockfile_committed"])
    fixture_rows = [r for r in rows if r["fixture_dependent_test_files"]]
    all_urls = {u["url"]: u["http"] for r in rows for u in r["fixture_urls"]}
    urls = {u: c for u, c in all_urls.items() if "$" not in u}  # "$" = Makefile pattern, not a fetchable URL
    patterns = sorted(u for u in all_urls if "$" in u)
    lines += [
        "", "## Drift and environment findings", "",
        f"- **Dependency drift**: {no_lock} of {len(rows)} sampled commits have no committed `Cargo.lock`; "
        "their dependencies were resolved against today's registry, not the versions used at the time.",
        f"- **Toolchain pin**: `rust-toolchain` values seen: "
        f"{sorted({str(r['pinned_toolchain_file']) for r in rows})} (`stable` floats, so it pins nothing).",
        f"- **Fixture-dependent integration tests**: {len(fixture_rows)} of {len(rows)} sampled commits have "
        "test files reading `data/` (downloaded fixtures). These were NOT TESTED; unit tests only.",
        f"- **Fixture URLs in Makefiles** ({len(urls)} distinct), HTTP status today: "
        + (", ".join(f"`{u}` → {c}" for u, c in sorted(urls.items())) or "none found")
        + (f". Not probed (Makefile patterns): {', '.join(f'`{u}`' for u in patterns)}" if patterns else ""),
        f"- **Licenses seen** (`license` key in the crate Cargo.toml; None = key absent): "
        f"{sorted({str(r['license']) for r in rows})}",
        "- **Host linker drift (native macOS)**: smoke run on this Mac → "
        + "; ".join(f"`{r['sha'][:10]}` ({r['toolchain']}): {r['status']}"
                    + "".join(f" — linker said: `{l.strip()[:90]}…`" for l in
                              [x for x in r.get("steps", {}).get("build", {}).get("tail", []) if "mach-o" in x][:1])
                    for r in smoke["results"])
        + ". Hence all build/test steps run in a Linux container (`results/smoke-native-macos.*`).",
        "- **Harness hermeticity**: a worktree nested inside bug-age's own Cargo workspace absorbed old "
        "commits (no `[workspace]`) into the parent workspace; scratch dirs now live outside the repo.",
        "", "## Mitigations to evaluate before the sweep (not run in this spike)", "",
        "- Time-travel dependency resolution for lockfile-less commits: resolve each crate to the newest "
        "version published before the commit date (crates.io version timestamps). The nightly cargo used here "
        "has no built-in flag for this.",
        "- Treat genuinely broken commits (compile errors on the commit's own code) as untestable intervals, "
        "never as bug-present.",
        "- Fixture snapshotting: vendor the HF test fixtures at a pinned revision so integration tests can run "
        "offline.",
        "", "## Evidence receipt", "",
        f"- Command: `{rec['command']}`"
        + (f", then `{rec['post_processing']}`" if rec.get("post_processing") else ""),
        f"- Generated: {rec['generated_utc']}",
        f"- Versions: {json.dumps(rec['versions'])}",
        f"- `report.json` sha256: `{rec['outputs'][str((RES / 'report.json').relative_to(ROOT))]}`",
        "", "## What this does and does not prove", "",
        "- COVERED: build + workspace unit tests at the sampled commits, offline, repeated for flakiness.",
        "- PARTIAL: dependency versions for lockfile-less commits are today's, not historical.",
        "- NOT TESTED: integration tests needing downloaded fixtures, benches, Python/Node bindings, "
        "commits between samples.",
    ]
    (RES / "REPORT.md").write_text("\n".join(lines) + "\n")
    print((RES / "REPORT.md"))


if __name__ == "__main__":
    import sys
    main(Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else RES)
