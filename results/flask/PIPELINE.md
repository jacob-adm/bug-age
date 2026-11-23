# Pipeline: flask

- subject: https://github.com/pallets/flask `.` at `49943b5a94413a530761350f04e896f76e8d620e`
- generated: 2026-11-23T23:00:28+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 49943b5a94 |  |
| feasibility (baseline) | REUSED | existing report, every recorded input matches | 47d3eaadec8bbfa8 |
| feasibility (time-travel) | REUSED | existing report, every recorded input matches | a6d5b7b602f5017d |
| catalog (rule-based fixes) | OK | catalog: 185 fixes, 166 excluded, 2277 commits scanned | 0c032377ce1b9acd |
| Method A (szz) | OK | szz: 185 fixes, 92 with a nominated introducer, 0 in window | 8e6582a91e259df9 |
| Method B (repro sweeps) | REUSED | 2 existing sweeps, every recorded input matches |  |
| bundle | OK | bundle: 142305 bytes, sha256 5a64d5b522085a047a7102579f409bfad6083fd0297abb997a2abe1a154321bd, blameless gate PASS | 5a64d5b522085a04 |
