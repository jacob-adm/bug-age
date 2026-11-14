# SPDX-License-Identifier: MIT OR Apache-2.0
"""bug-age: measure how long bugs lived in a git repository, using only repository data.

bug-age does not discover new bugs. It starts from bugs the project already fixed:

1. `catalog` lists the commits whose subject says they fix something (rule-based, auditable).
2. `szz` (Method A) blames the lines each fix changed to nominate the commit that introduced the
   bug, then measures the time, commits, releases and churn in between.
3. `sweep` (Method B) replays a regression test for one bug across history to find the first
   commit where the bug's behaviour appears.
4. `bundle` assembles everything into one blameless, schema-checked JSON file.
"""
__version__ = "2.0.0"
