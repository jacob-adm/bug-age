# SPDX-License-Identifier: MIT OR Apache-2.0
"""MCP server.

Read-only MCP server over stdio (JSON-RPC 2.0, one message per line) answering bundle queries.
Every value a tool returns is copied from a bundle.json; nothing is computed or inferred. An
unknown target, or an unknown or ambiguous SHA prefix, is a tool error, never a guess.
"""
import hashlib
import json
import math
from pathlib import Path

from . import __version__
from ._compat import as_f64, dumps, get, split_whitespace, trim

PROTOCOL_VERSION = "2025-06-18"


class ToolError(Exception):
    """A tool call that cannot be answered from the bundles."""


class Target:
    """One loaded bundle: its name, parsed value and file SHA-256."""

    def __init__(self, name, path):
        try:
            data = Path(path).read_bytes()
            self.bundle = json.loads(data)
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"{path}: {exc}") from exc
        self.name = name
        self.sha256 = hashlib.sha256(data).hexdigest()


def _target_arg():
    """Schema of the `target` argument."""
    return {"type": "string", "description": "Target name, as listed by list_targets"}


def tools():
    """The tool list returned by tools/list."""
    ro = {"readOnlyHint": True}
    return [
        {"name": "list_targets", "description": "Repositories loaded, with subject (repo URL, crate path, pinned head) and bundle sha256.",
         "inputSchema": {"type": "object", "properties": {}}, "annotations": ro},
        {"name": "get_summary", "description": "Headline metrics exactly as computed by the bug-age CLI, plus subject and bundle sha256.",
         "inputSchema": {"type": "object", "properties": {"target": _target_arg()}, "required": ["target"]}, "annotations": ro},
        {"name": "get_coverage", "description": "What each pipeline stage proves and does not prove; status COVERED, PARTIAL or NOT TESTED.",
         "inputSchema": {"type": "object", "properties": {"target": _target_arg()}, "required": ["target"]}, "annotations": ro},
        {"name": "search_fixes", "description": "Catalogued fixes whose subject contains every query word (case-insensitive) or whose SHA starts with the query. Empty query lists all. Sorted by days, longest first.",
         "inputSchema": {"type": "object", "properties": {"target": _target_arg(), "query": {"type": "string"},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}}, "required": ["target"]},
         "annotations": ro},
        {"name": "get_fix", "description": "One fix by full SHA or unique prefix (7+ hex chars): its Method A row, its Method B sweep if any (else null), and the subject/date of every SHA referenced.",
         "inputSchema": {"type": "object", "properties": {"target": _target_arg(), "sha": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"}}, "required": ["target", "sha"]},
         "annotations": ro},
    ]


def _find(targets, args):
    """The target named by `args`, or a ToolError listing the known ones."""
    name = get(args, "target")
    if not isinstance(name, str):
        raise ToolError("missing argument: target")
    for t in targets:
        if t.name == name:
            return t
    raise ToolError(f"unknown target '{name}'; known: {', '.join(t.name for t in targets)}")


def _subject(t, sha):
    """The bundle's subject for a commit, or ""."""
    s = get(t.bundle, "commits", sha, "subject")
    return s if isinstance(s, str) else ""


def _u64(value):
    """serde_json's Value::as_u64: a non-negative integer, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _search(t, args):
    """Fixes matching every query word in the subject, or a SHA prefix; longest-lived first."""
    q = get(args, "query")
    query = trim(q if isinstance(q, str) else "").lower()
    limit = _u64(get(args, "limit"))
    limit = min(max(20 if limit is None else limit, 1), 200)
    words = split_whitespace(query)
    rows = get(t.bundle, "method_a")
    if not isinstance(rows, list):
        raise ToolError("bundle has no method_a array")

    def fix_of(r):
        f = get(r, "fix")
        return f if isinstance(f, str) else ""
    hits = [r for r in rows if not words or fix_of(r).startswith(query)
            or all(w in _subject(t, fix_of(r)).lower() for w in words)]

    def days(r):
        d = as_f64(get(r, "days"))
        return -math.inf if d is None else d
    # Longest first (total order), then by fix SHA ascending; a missing fix sorts first, as Rust's None.
    hits.sort(key=lambda r: (get(r, "fix") is not None and isinstance(get(r, "fix"), str), fix_of(r)))
    hits.sort(key=lambda r: (-days(r), -math.copysign(1.0, days(r))))
    out = []
    for r in hits[:limit]:
        fix = fix_of(r)
        nominees = get(r, "nominees")
        out.append({"fix": fix, "fix_date": get(r, "fix_date"), "subject": _subject(t, fix), "days": get(r, "days"),
                    "commits_elapsed": get(r, "lifetime", "commits_elapsed"),
                    "releases_spanned": get(r, "lifetime", "releases_spanned"),
                    "nominees": [get(x, "sha") for x in nominees] if isinstance(nominees, list) else [],
                    "flags": get(r, "flags")})
    return {"target": t.name, "query": query, "total": len(hits), "returned": len(out), "fixes": out}


def _get_fix(t, args):
    """One fix by unique SHA prefix, with its Method B sweep and the commits it references."""
    sha = get(args, "sha")
    if not isinstance(sha, str):
        raise ToolError("missing argument: sha")
    if not 7 <= len(sha.encode()) <= 40 or not all(c in "0123456789abcdef" for c in sha):
        raise ToolError("sha must be 7 to 40 lowercase hex characters")
    rows = get(t.bundle, "method_a")
    if not isinstance(rows, list):
        raise ToolError("bundle has no method_a array")
    matches = [r for r in rows if isinstance(get(r, "fix"), str) and get(r, "fix").startswith(sha)]
    if not matches:
        raise ToolError(f"no catalogued fix starts with {sha} in target '{t.name}'")
    if len(matches) > 1:
        raise ToolError(f"{sha} matches {len(matches)} fixes; give more characters")
    row = matches[0]
    fix = get(row, "fix")
    sweeps = get(t.bundle, "method_b")
    sweep = next((m for m in sweeps if get(m, "fix") == fix), None) if isinstance(sweeps, list) else None
    nominees = get(row, "nominees")
    shas = [fix] + [n["sha"] for n in (nominees if isinstance(nominees, list) else []) if isinstance(get(n, "sha"), str)]
    for k in ("first_failing", "last_passing", "method_a_nominee"):
        if isinstance(get(sweep, k), str):
            shas.append(get(sweep, k))
    commits = {}
    for s in shas:
        c = get(t.bundle, "commits", s)
        if isinstance(get(t.bundle, "commits"), dict) and s in t.bundle["commits"]:
            commits[s] = c
    return {"target": t.name, "method_a": row, "method_b": sweep, "commits": commits}


def call(targets, name, args):
    """Run one tool; raises ToolError for anything the bundles cannot answer."""
    if name == "list_targets":
        return {"targets": [{"name": t.name, "subject": get(t.bundle, "subject"),
                             "schema_version": get(t.bundle, "schema_version"), "bundle_sha256": t.sha256} for t in targets]}
    if name == "get_summary":
        t = _find(targets, args)
        return {"target": t.name, "subject": get(t.bundle, "subject"), "bundle_sha256": t.sha256,
                "summary": get(t.bundle, "summary")}
    if name == "get_coverage":
        t = _find(targets, args)
        return {"target": t.name, "coverage": get(t.bundle, "coverage")}
    if name == "search_fixes":
        return _search(_find(targets, args), args)
    if name == "get_fix":
        return _get_fix(_find(targets, args), args)
    raise ToolError(f"unknown tool '{name}'")


def handle(targets, msg):
    """The reply to one JSON-RPC message, or None for a notification (no id)."""
    if not isinstance(msg, dict) or "id" not in msg:
        return None
    mid = msg["id"]
    method = get(msg, "method")
    method = method if isinstance(method, str) else ""
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "bug-age", "version": __version__},
                  "instructions": "Read-only facts from bug-age bundles. Every value is copied from bundle.json; cite fix SHAs when you use them."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": tools()}
    elif method == "tools/call":
        name = get(msg, "params", "name")
        name = name if isinstance(name, str) else ""
        params = get(msg, "params")
        args = params["arguments"] if isinstance(params, dict) and "arguments" in params else {}
        try:
            v = call(targets, name, args)
            result = {"content": [{"type": "text", "text": dumps(v)}], "structuredContent": v, "isError": False}
        except ToolError as e:
            result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(targets, stdin, stdout):
    """Answer one JSON-RPC message per input line until end of input."""
    for raw in stdin:
        line = raw.rstrip("\n")
        if not trim(line):
            continue
        try:
            reply = handle(targets, json.loads(line))
        except ValueError as e:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e}"}}
        if reply is not None:
            stdout.write(dumps(reply) + "\n")
            stdout.flush()
