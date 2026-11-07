# Number trace

Every number in ARTICLE.md, the template line it comes from, and its bundle path.

| Line | Value | Bundle path |
|---|---|---|
| 3 | 37.3 | `tokenizers:summary.method_a.calendar_days.median` |
| 3 | 1668.6 | `tokenizers:summary.method_a.calendar_days.max` |
| 3 | 44 | `tokenizers:method_a[@max=days].lifetime.releases_spanned|len` |
| 19 | 20% | `tokenizers:summary.feasibility.baseline_share|pct` |
| 19 | 90% | `tokenizers:summary.feasibility.time_travel_share|pct` |
| 23 | 717 | `tokenizers:catalog.scanned` |
| 23 | 109 | `tokenizers:summary.method_a.fixes` |
| 23 | 93 | `tokenizers:summary.method_a.with_introducer` |
| 25 | 37.3 | `tokenizers:summary.method_a.calendar_days.median` |
| 25 | 82 | `tokenizers:summary.method_a.commits_elapsed.median` |
| 26 | 462.4 | `tokenizers:summary.method_a.calendar_days.p90` |
| 27 | 🚨 breaking: Fix training with special tokens (#1617) | `tokenizers:method_a[@max=days].fix|subject` |
| 27 | 1668.6 | `tokenizers:method_a[@max=days].days` |
| 27 | 479 | `tokenizers:method_a[@max=days].lifetime.commits_elapsed` |
| 31 | 6 | `tokenizers:summary.method_b.swept` |
| 31 | Fix stripping strings containing Unicode characters (#707) | `tokenizers:method_b[verdict=located].fix|subject` |
| 31 | 462.4 | `tokenizers:method_b[verdict=located].method_a_days` |
| 31 | 278.2 | `tokenizers:method_b[verdict=located].days` |
| 33 | 4 | `tokenizers:summary.method_b.verdicts.censored-by-testability` |
| 33 | Fix off-by-one error in tokenizer::normalizer::Range::len (#1638) | `tokenizers:method_b[verdict=left-censored].fix|subject` |
| 33 | 1033.7 | `tokenizers:method_b[verdict=left-censored].days` |
| 37 | 237 | `rust-sdk:summary.method_a.fixes` |
| 37 | 546 | `rust-sdk:catalog.scanned` |
| 37 | 205 | `rust-sdk:summary.method_a.with_introducer` |
| 37 | 93.6 | `rust-sdk:summary.method_a.calendar_days.median` |
| 37 | 350.9 | `rust-sdk:summary.method_a.calendar_days.p90` |
| 37 | 95% | `rust-sdk:summary.feasibility.baseline_share|pct` |
| 54 | (coverage list) | `tokenizers:coverage[status!=COVERED]` |
| 58 | (coverage list) | `rust-sdk:coverage[status!=COVERED]` |
| 60 | 0 | `rust-sdk:summary.method_a.releases_shipped_bug.max` |
