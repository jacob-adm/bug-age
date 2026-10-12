#!/usr/bin/env python3
"""BUGAGE-5: per-commit comparison of the baseline spike (today's registry) with the time-travel run.
Writes spike/results-timetravel/COMPARISON.md. Every figure is read from the two report.json files."""
import hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE, TT = HERE / "results" / "report.json", HERE / "results-timetravel" / "report.json"
GO = 0.70  # the BUGAGE-1 GO rule, pre-registered for BUGAGE-5 in its Phase 1 comment


def main() -> None:
    base_raw, tt_raw = BASE.read_bytes(), TT.read_bytes()
    base = {r["sha"]: r for r in json.loads(base_raw)["results"]}
    tt_rep = json.loads(tt_raw)
    rows = tt_rep["results"]
    assert set(base) == {r["sha"] for r in rows}, "runs sampled different commits"
    ok = lambda r: r["status"] == "BUILT_AND_TESTED"
    b_ok, t_ok = sum(ok(base[r["sha"]]) for r in rows), sum(ok(r) for r in rows)
    tt_rows = [r for r in rows if "time_travel" in r]
    lines = [
        "# BUGAGE-5 — time-travel dependency resolution vs. BUGAGE-1 baseline", "",
        f"Same {len(rows)} sampled commits. BUILT_AND_TESTED: **{b_ok}/{len(rows)} ({b_ok / len(rows):.0%})** with "
        f"today's registry → **{t_ok}/{len(rows)} ({t_ok / len(rows):.0%})** with time-travel resolution. "
        f"Pre-registered criterion ≥ {GO:.0%}: **{'MET' if t_ok / len(rows) >= GO else 'NOT MET'}**.", "",
        "Environment: baseline image `" + json.loads((BASE.parent / "receipt.json").read_text())["versions"]["image"][7:19]
        + "`, time-travel image `" + json.loads((TT.parent / "receipt.json").read_text())["versions"]["image"][7:19]
        + "` (the later image only adds `libssl-dev`; every baseline failure it could affect had already failed at "
        "fetch or on edition drift).", "",
        f"Time-travel indexes were built for {len(tt_rows)} lockfile-less commits "
        f"(un-yanked versions across them: {sum(r['time_travel']['unyanked'] for r in tt_rows)}).", "",
        "| # | SHA | Date | Toolchain | Baseline | Time-travel | Index (crates / versions) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        b = base[r["sha"]]
        idx = r.get("time_travel")
        idx_cell = f"{idx['crates']} / {idx['versions']}" if idx else "committed lock"
        lines.append(f"| {r['index']} | `{r['sha'][:10]}` | {r['date']} | {r['toolchain']} | "
                     f"{b['status']}: {b['reason']} | {r['status']}: {r['reason']} | {idx_cell} |")
    changed = [r for r in rows if r["status"] != base[r["sha"]]["status"]]
    lines += ["", f"Status changed for {len(changed)} commits; "
              f"{sum(ok(r) and not ok(base[r['sha']]) for r in rows)} newly BUILT_AND_TESTED, "
              f"{sum(ok(base[r['sha']]) and not ok(r) for r in rows)} regressed.", "",
              "## Inputs", "",
              f"- baseline `spike/results/report.json` sha256 `{hashlib.sha256(base_raw).hexdigest()}`",
              f"- time-travel `spike/results-timetravel/report.json` sha256 `{hashlib.sha256(tt_raw).hexdigest()}`"]
    out = HERE / "results-timetravel" / "COMPARISON.md"
    out.write_text("\n".join(lines) + "\n")
    print(out)


if __name__ == "__main__":
    main()
