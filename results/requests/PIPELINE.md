# Pipeline: requests

- subject: https://github.com/psf/requests `.` at `3c7baaa05ab4aa49cc819ce3a819d260de19c157`
- generated: 2026-11-15T09:48:02+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 3c7baaa05a |  |
| feasibility (baseline) | OK | NO-GO, built+tested share 0.05 | a5d297ba34f4d80b |
| feasibility (time-travel) | OK | NO-GO, built+tested share 0.15 | 06ee4378ec40a6dc |
| catalog (rule-based fixes) | OK | catalog: 169 fixes, 40 excluded, 2651 commits scanned | 860bb159ee367d8b |
| Method A (szz) | OK | szz: 169 fixes, 88 with a nominated introducer, 0 in window | 013f4b0b8662fc50 |
| Method B (repro sweeps) | OK | 3 repros swept |  |
| bundle | OK | bundle: 150453 bytes, sha256 da1766a376f05e5b3255db58eafd923ba39e895ccfba939c60694f8eac5f02f5, blameless gate PASS | da1766a376f05e5b |
