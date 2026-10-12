# BUGAGE-5 — time-travel dependency resolution vs. BUGAGE-1 baseline

Same 20 sampled commits. BUILT_AND_TESTED: **4/20 (20%)** with today's registry → **18/20 (90%)** with time-travel resolution. Pre-registered criterion ≥ 70%: **MET**.

Environment: baseline image `76a5e56ed4bb`, time-travel image `65ce618efe20` (the later image only adds `libssl-dev`; every baseline failure it could affect had already failed at fetch or on edition drift).

Time-travel indexes were built for 16 lockfile-less commits (un-yanked versions across them: 46157).

| # | SHA | Date | Toolchain | Baseline | Time-travel | Index (crates / versions) |
|---|---|---|---|---|---|---|
| 0 | `2b72a5737f` | 2019-11-01 | 1.38 | NOT_TESTED: build ok but zero unit tests executed | NOT_TESTED: build ok but zero unit tests executed | committed lock |
| 38 | `4807894da6` | 2019-12-11 | 1.39 | BUILD_FAILED: compile error | BUILD_FAILED: compile error | committed lock |
| 75 | `c0ed873c4d` | 2019-12-23 | 1.39 | BUILT_AND_TESTED: 13 unit tests passed x2 | BUILT_AND_TESTED: 13 unit tests passed x2 | committed lock |
| 113 | `805dc58949` | 2020-01-03 | 1.40 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 26 unit tests passed x2 | 1206 / 21764 |
| 151 | `6524f09e99` | 2020-02-03 | 1.40 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 31 unit tests passed x2 | 1267 / 23116 |
| 188 | `6c232886b8` | 2020-03-26 | 1.41 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 42 unit tests passed x2 | 1321 / 24319 |
| 226 | `bb68ec3414` | 2020-06-11 | 1.43 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 43 unit tests passed x2 | 1518 / 27466 |
| 264 | `fcc68f27f6` | 2020-08-03 | 1.45 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 59 unit tests passed x2 | 1568 / 28515 |
| 301 | `857948e5b8` | 2020-08-31 | 1.45 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 63 unit tests passed x2 | 1603 / 29038 |
| 339 | `481f3bd976` | 2020-09-02 | 1.45 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 78 unit tests passed x2 | 1605 / 29075 |
| 377 | `98a30eead1` | 2020-09-24 | 1.46 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 99 unit tests passed x2 | 1617 / 29412 |
| 415 | `d3d9f2c76b` | 2020-11-09 | 1.47 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 115 unit tests passed x2 | 1708 / 30981 |
| 452 | `2e2e7558f7` | 2021-05-20 | 1.51 | BUILD_FAILED: edition newer than toolchain | BUILT_AND_TESTED: 131 unit tests passed x2 | 2169 / 39224 |
| 490 | `a4a68de98a` | 2022-02-28 | 1.58 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 146 unit tests passed x2 | 2734 / 57819 |
| 528 | `33a57e6418` | 2023-01-18 | 1.66 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 157 unit tests passed x2 | 3053 / 67153 |
| 565 | `aed491df8c` | 2023-10-05 | 1.72 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 173 unit tests passed x2 | 3932 / 88059 |
| 603 | `adc82cb49a` | 2024-08-06 | 1.79 | NOT_TESTED: dependency fetch/resolution failed: edition newer than toolchain | BUILT_AND_TESTED: 184 unit tests passed x2 | 4681 / 110629 |
| 641 | `4383a25787` | 2025-03-13 | 1.85 | BUILT_AND_TESTED: 189 unit tests passed x2 | BUILT_AND_TESTED: 189 unit tests passed x2 | 5215 / 125731 |
| 678 | `c58a47475c` | 2026-02-24 | 1.93 | BUILT_AND_TESTED: 192 unit tests passed x2 | BUILT_AND_TESTED: 192 unit tests passed x2 | 6488 / 184735 |
| 716 | `ff8ae1baab` | 2026-10-07 | 1.98 | BUILT_AND_TESTED: 281 unit tests passed x2 | BUILT_AND_TESTED: 281 unit tests passed x2 | committed lock |

Status changed for 14 commits; 14 newly BUILT_AND_TESTED, 0 regressed.

## Inputs

- baseline `spike/results/report.json` sha256 `47dc10dc1a51f1820211b001a88dac5aa7d9f1dee753d7c9ab265098820f7b2a`
- time-travel `spike/results-timetravel/report.json` sha256 `6e6fa99e9264e8b9b9ce3fb7a7c4bde9dc48037adfa663cc2011420bde2d8d05`
