# Pipeline: requests

- subject: https://github.com/psf/requests `.` at `3c7baaa05ab4aa49cc819ce3a819d260de19c157`
- generated: 2026-11-15T11:27:56+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 3c7baaa05a |  |
| feasibility (baseline) | REUSED | existing report, every recorded input matches | a5d297ba34f4d80b |
| feasibility (time-travel) | REUSED | existing report, every recorded input matches | 06ee4378ec40a6dc |
| catalog (rule-based fixes) | OK | catalog: 169 fixes, 40 excluded, 2651 commits scanned | 860bb159ee367d8b |
| Method A (szz) | OK | szz: 169 fixes, 88 with a nominated introducer, 0 in window | 013f4b0b8662fc50 |
| Method B (repro sweeps) | REUSED | 3 existing sweeps, every recorded input matches |  |
| bundle | OK | bundle: 150453 bytes, sha256 a2f546d176df888c8c05344f90e10d0d6c3551ce014b69169ebad9e0804ca058, blameless gate PASS | a2f546d176df888c |
