# Method A vs Method B — per-bug lifetimes

A = SZZ nominee (latest toucher of the lines the fix changed). B = first commit where the regression test fails, found by `bug-age sweep` (date-matched toolchain, time-travel dependencies, `--network none`, 3 repeats; range = 3 years before the fix).

B days marked ≥ are lower bounds (censored). A-check probes A's nominee and its parent with the same test; it is reported separately and never changes B's verdict.

| Fix | A: nominated introducer | B: first failing commit | B verdict | A vs B | A days | B days | A-check | Commits tested / in range |
|---|---|---|---|---|---|---|---|---|
| `05e9c6bd63` | `0ec7f713d6` (2023-08-19) | `7d399e80c3` (2023-08-16) — present at range start | left-censored | B earlier by 18 commits | 1088.1 | ≥ 1091.0 | A plausible: bug present at the nominee, where the tested code first compiles | 5/154 |
| `127df57a06` | `b146a13f63` (2020-08-01) | `5e378b4f28` (2019-05-06) — present at range start | left-censored | B earlier by 478 commits | 640.1 | ≥ 1093.0 | A too late: bug already present before the nominee | 5/380 |

## Inputs

- `repros/05e9c6bd63/sweep.json` sha256 `d99b8d9115fdc44b4043ce5c64523d737abacf74af0a2c8ead47a0eeb915d690`
- `repros/127df57a06/sweep.json` sha256 `ab5f3c398b7be71b0727faec5a476833c5d8cf4febc6bb9f59fb2d0f6e0e9fac`
