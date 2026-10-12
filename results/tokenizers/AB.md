# Method A vs Method B — per-bug lifetimes

A = SZZ nominee (latest toucher of the lines the fix changed). B = first commit where the regression test fails, found by `bug-age sweep` (date-matched toolchain, time-travel dependencies, `--network none`, 3 repeats; range = 3 years before the fix).

B days marked ≥ are lower bounds (censored). A-check probes A's nominee and its parent with the same test; it is reported separately and never changes B's verdict.

| Fix | A: nominated introducer | B: first failing commit | B verdict | A vs B | A days | B days | A-check | Commits tested / in range |
|---|---|---|---|---|---|---|---|---|
| `8a6a8dc9d5` | `e4aea890d5` (2023-03-24) | `e4aea890d5` (2023-03-24) — first commit where the test compiles | censored-by-testability | agree | 0.0 | ≥ 0.0 | A plausible: bug present at the nominee, where the tested code first compiles | 38/731 |
| `9a93c50c25` | `c2664ae13f` (2023-07-28) | `c2664ae13f` (2023-07-28) — first commit where the test compiles | censored-by-testability | agree | 17.3 | ≥ 17.3 | A plausible: bug present at the nominee, where the tested code first compiles | 35/593 |
| `9b77c054ef` | `66fef2b907` (2020-08-19) | `c1100ec542` (2021-12-15) — present at range start | left-censored | consistent: A predates the window | 1516.6 | ≥ 1033.7 | A plausible: bug present at the nominee, where the tested code first compiles | 11/274 |
| `a350ec3e72` | `dad70e8e85` (2020-08-03) | `0a930ef1d8` (2020-09-23) — first commit where the test compiles | censored-by-testability | consistent: A predates B's earliest testable FAIL | 183.9 | ≥ 132.9 | A untested: test cannot compile at the nominee or its parent | 26/928 |
| `c046da7679` | `bb8321ac0d` (2020-02-17) | `66fef2b907` (2020-08-19) | located | B later by 527 commits | 462.4 | 278.2 | A refuted by B's sweep: test PASSes at `5d8728a26b`, after the nominee | 13/960 |
| `fb837b4adb` | `8200112e9b` (2020-02-05) | `991128f9e1` (2020-10-30) — first commit where the test compiles | censored-by-testability | consistent: A predates B's earliest testable FAIL | 700.9 | ≥ 432.9 | A untested: test cannot compile at the nominee or its parent | 27/1008 |

## Inputs

- `repros/8a6a8dc9d5/sweep.json` sha256 `20072a1a45ecfdd5bfbdef1838342738de3ee25cb61dc57cf879905e985892f8`
- `repros/9a93c50c25/sweep.json` sha256 `468179872657e0aa20ee2b088e8ff73156133a2df6efa4e05983b8de94191c45`
- `repros/9b77c054ef/sweep.json` sha256 `0a7b14a58fe154523736a4bf215bbc3336b1ee18ba98f441aa07e99e5dfb1a02`
- `repros/a350ec3e72/sweep.json` sha256 `dd0261d14a1f08c9e1fad3af01cb1886fca9318c236f4a7e64ac8e39a9f902ae`
- `repros/c046da7679/sweep.json` sha256 `6a982fb60ffc957163ffb59a1a968603ae5a071de591f73c501d6a60e4444b00`
- `repros/fb837b4adb/sweep.json` sha256 `c65c422b9cfde0d789b20b29dd85f01fff898f9db08af83743aa9a07169769f7`
