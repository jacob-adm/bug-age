# Pipeline: flask

- subject: https://github.com/pallets/flask `.` at `49943b5a94413a530761350f04e896f76e8d620e`
- generated: 2026-11-21T07:43:40+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 49943b5a94 |  |
| feasibility (baseline) | REUSED | existing report, every recorded input matches | 47d3eaadec8bbfa8 |
| feasibility (time-travel) | REUSED | existing report, every recorded input matches | a6d5b7b602f5017d |
| catalog (rule-based fixes) | OK | catalog: 185 fixes, 166 excluded, 2277 commits scanned | 0c032377ce1b9acd |
| Method A (szz) | OK | szz: 185 fixes, 92 with a nominated introducer, 0 in window | d58c021d88b34f2b |
| Method B (repro sweeps) | REUSED | 2 existing sweeps, every recorded input matches |  |
| bundle | OK | bundle: 140401 bytes, sha256 24d679a744118c2f28132feb89368f0640ddc2dda4816e302e6cdeffe0cb14fd, blameless gate PASS | 24d679a744118c2f |
