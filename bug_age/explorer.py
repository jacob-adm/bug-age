# SPDX-License-Identifier: MIT OR Apache-2.0
"""Explorer page assembly.

The page is a static HTML file containing the marker `<!-- bug-age:data -->`; it is replaced by one
`<script src="data/<name>.js">` per target, in the order given. Each data file pushes
`{name, receipt, bundle}` onto `window.BUG_AGE`, so the page reads every target without fetch.
"""
import re

from ._compat import dumps

MARKER = "<!-- bug-age:data -->"
GATE_BYTES = 8 * 1024 * 1024
_NAME = re.compile(r"[a-z0-9-]+")


class ExplorerError(RuntimeError):
    """The page or a target is invalid, or the result is over the size gate."""


def assemble(page, targets):
    """Return (page, [(path, text)], total_bytes) for targets given as (name, bundle, receipt)."""
    if not targets:
        raise ExplorerError("no targets given")
    if page.count(MARKER) != 1:
        raise ExplorerError(f"page must contain the marker {MARKER} exactly once")
    files, tags = [], []
    for name, bundle, receipt in targets:
        if not _NAME.fullmatch(name):
            raise ExplorerError(f"target name '{name}' must be lowercase letters, digits or '-'")
        path = f"data/{name}.js"
        if any(p == path for p, _ in files):
            raise ExplorerError(f"target '{name}' given twice")
        # "</" is escaped so a string in the data can never close the page's <script> element.
        text = dumps({"name": name, "receipt": receipt, "bundle": bundle}).replace("</", "<\\/")
        files.append((path, f"(window.BUG_AGE = window.BUG_AGE || []).push({text});\n"))
        tags.append(f'<script src="data/{name}.js"></script>\n')
    page = page.replace(MARKER, "".join(tags).rstrip(), 1)
    total = len(page.encode()) + sum(len(c.encode()) for _, c in files)
    if total > GATE_BYTES:
        raise ExplorerError(f"size gate failed: page plus data is {total} bytes (> {GATE_BYTES})")
    return page, files, total
