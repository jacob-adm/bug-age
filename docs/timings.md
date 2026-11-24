# Timings

How long a run takes, measured from the committed run records.

## How long it takes

<!-- timings:begin -->

Measured on Darwin arm64, Docker 28.3.3 arm64. Figures come from committed run records via `scripts/timings.py`; full tables in [`results/TIMINGS.md`](../results/TIMINGS.md). Step time excludes container staging and toolchain installs, so expect wall time to be longer.

| Stage | What was measured | Time |
|---|---|---|
| catalog | last pipeline run, 4 target(s) | 0-3 s |
| Method A | last pipeline run, 4 target(s) | 19-60 s |
| bundle | last pipeline run, 4 target(s) | 4-6 s |
| Feasibility (one run, 20 sampled commits) | 8 runs | 46 s to 71 min per run |
| Method B sweep (one bug, current search) | 6 sweeps, 84 commits | 101 s to 6 min of step time per bug; median per commit 7 s to 22 s |
| Method B, all 6 tokenizers sweeps end to end | one unattended run, wall clock | 20 min |

Method B dominates: each bug needs a regression test, and the current search built and tested 5 to 23 commits per bug in Docker. Catalog, Method A and bundle together took 23 to 65 s per repository.

<!-- timings:end -->
