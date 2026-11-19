# Pipeline: flask

- subject: https://github.com/pallets/flask `.` at `49943b5a94413a530761350f04e896f76e8d620e`
- generated: 2026-11-15T09:52:06+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 49943b5a94 |  |
| feasibility (baseline) | OK | NO-GO, built+tested share 0.05 | 47d3eaadec8bbfa8 |
| feasibility (time-travel) | OK | NO-GO, built+tested share 0.1 | a6d5b7b602f5017d |
| catalog (rule-based fixes) | OK | catalog: 185 fixes, 166 excluded, 2277 commits scanned | 0c032377ce1b9acd |
| Method A (szz) | OK | szz: 185 fixes, 90 with a nominated introducer, 0 in window | 1c7af3ead8bd6512 |
| Method B (repro sweeps) | OK | 2 repros swept |  |
| bundle | OK | bundle: 137290 bytes, sha256 efaae1b3fd7b289ea9357fc92b05a0d05a015ef48c5e8885de7e0a3a1edf863f, blameless gate PASS | efaae1b3fd7b289e |
