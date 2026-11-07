# Pipeline: rust-sdk

- subject: https://github.com/modelcontextprotocol/rust-sdk `crates/rmcp` at `5596a8a0bba2a1ec5519cc855cdadf23e4dcecdc`
- generated: 2026-11-07T03:25:48+00:00

| Stage | Status | Reason | Output sha256 |
|---|---|---|---|
| clone | OK | at pinned head 5596a8a0bb |  |
| feasibility (baseline) | REUSED | existing report (pass --fresh to rerun) | 4bdf0c7ade866a75 |
| feasibility (time-travel) | REUSED | existing report (pass --fresh to rerun) | d0d17d2a86aade97 |
| catalog (rule-based fixes) | OK | catalog: 237 fixes, 28 excluded, 546 commits scanned | 331992cd3403aa5b |
| Method A (szz) | OK | szz: 237 fixes, 205 with a nominated introducer, 0 in window | a0ce68568a355463 |
| Method B (repro sweeps) | NOT TESTED | no regression tests written for this target (results_dir/repros/<fix>/overlay) |  |
| bundle | OK | bundle: 247801 bytes, sha256 ab9a9f87125107823f63987c40d513d33582fa972c352fdb6549c9b280c6a7b5, blameless gate PASS | ab9a9f8712510782 |
