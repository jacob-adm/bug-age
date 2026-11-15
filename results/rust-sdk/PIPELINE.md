# Pipeline: rust-sdk

- subject: https://github.com/modelcontextprotocol/rust-sdk `crates/rmcp` at `5596a8a0bba2a1ec5519cc855cdadf23e4dcecdc`
- generated: 2026-11-15T11:27:25+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 5596a8a0bb |  |
| feasibility (baseline) | REUSED | existing report, every recorded input matches; feasibility: image recipe not recorded (made before 2.1.1) | 4bdf0c7ade866a75 |
| feasibility (time-travel) | REUSED | existing report, every recorded input matches; feasibility: image recipe not recorded (made before 2.1.1) | d0d17d2a86aade97 |
| catalog (rule-based fixes) | OK | catalog: 237 fixes, 28 excluded, 546 commits scanned | 331992cd3403aa5b |
| Method A (szz) | OK | szz: 237 fixes, 205 with a nominated introducer, 0 in window | a0ce68568a355463 |
| Method B (repro sweeps) | NOT TESTED | no regression tests written for this target (results_dir/repros/<fix>/overlay) |  |
| bundle | OK | bundle: 247801 bytes, sha256 ebdbfc655494a185a5d448ebbd0e2911c3e952b4b2e699b0830ce461e359f888, blameless gate PASS | ebdbfc655494a185 |
