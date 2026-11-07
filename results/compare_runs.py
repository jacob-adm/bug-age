#!/usr/bin/env python3
"""Compare two sweep result dirs: verdict and first_failing must be identical per bug.
Usage: python3 results/compare_runs.py results/tokenizers results/bench"""
import json, sys
from pathlib import Path

a, b = Path(sys.argv[1]), Path(sys.argv[2])
same = True
for d in sorted((a / "repros").iterdir()):
    fa, fb = d / "sweep.json", b / "repros" / d.name / "sweep.json"
    if not fb.is_file():
        print(f"{d.name}: MISSING in {b}"); same = False; continue
    ra, rb = json.loads(fa.read_text()), json.loads(fb.read_text())
    ok = (ra["verdict"], ra["first_failing"]) == (rb["verdict"], rb["first_failing"])
    same &= ok
    print(f"{d.name}: {'SAME' if ok else 'DIFF'} {ra['verdict']}/{(ra['first_failing'] or '')[:10]} vs "
          f"{rb['verdict']}/{(rb['first_failing'] or '')[:10]}  tested {ra['commits_tested']} -> {rb['commits_tested']}"
          f"  {rb.get('confirmation', '')}")
print("IDENTICAL" if same else "DIFFERENT")
sys.exit(0 if same else 1)
