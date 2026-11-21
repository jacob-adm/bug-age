# Pipeline: requests

- subject: https://github.com/psf/requests `.` at `3c7baaa05ab4aa49cc819ce3a819d260de19c157`
- generated: 2026-11-21T07:45:25+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 3c7baaa05a |  |
| feasibility (baseline) | REUSED | existing report, every recorded input matches | a5d297ba34f4d80b |
| feasibility (time-travel) | REUSED | existing report, every recorded input matches | 06ee4378ec40a6dc |
| catalog (rule-based fixes) | OK | catalog: 169 fixes, 40 excluded, 2651 commits scanned | 860bb159ee367d8b |
| Method A (szz) | OK | szz: 169 fixes, 89 with a nominated introducer, 0 in window | 259cef3b2a84184d |
| Method B (repro sweeps) | REUSED | 3 existing sweeps, every recorded input matches |  |
| bundle | OK | bundle: 151493 bytes, sha256 4c9d9676db27a7a7e2a946d1efb3e728729b59590a57de1d37b76e10d1c3871e, blameless gate PASS | 4c9d9676db27a7a7 |
