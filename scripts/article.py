#!/usr/bin/env python3
"""Render the article from bundle references and fail on any number that is not one.

    python3 scripts/article.py article/ARTICLE.tmpl.md --bundle tokenizers=dist/tokenizers/bundle.json \
        --bundle rust-sdk=dist/rust-sdk/bundle.json --out article/ARTICLE.md --trace article/TRACE.md

Every number in the prose is written as {{target:path}} or {{target:path|format}}:
  path     dotted fields; [3] indexes a list; [key=value] picks the first row whose key equals
           (or, for SHAs, starts with) value; [@max=key] picks the row with the largest key
  format   num (default: integer, else 1 decimal) | pct (share x 100, integer, with %) | len |
           short (first 10 characters) | text (string as is) | subject (commit subject of a SHA) | limits (bullet list of every coverage
           stage that is not COVERED)

The check fails (exit 1) on an unknown target or path, a null value, or any digit left in the prose
outside a reference, a code span, a fenced block, or a link/image target.
"""
import argparse, json, re, sys
from pathlib import Path

# {{target:path}} or {{target:path|format}}
REF = re.compile(r"\{\{([a-z0-9-]+):([^}|]+)(?:\|([a-z]+))?\}\}")
# One path segment: an optional field name followed by zero or more [selector]s
SEG = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)?((?:\[[^\]]+\])*)$")


class TraceError(Exception):
    pass


def resolve(value, path):
    """Follow a dotted bundle path (with [i], [key=value] and [@max=key] selectors) and return the value.

    Raises TraceError when a field, index or matching row does not exist.
    """
    for seg in path.split("."):
        m = SEG.match(seg)
        if not m:
            raise TraceError(f"bad path segment '{seg}'")
        name, selectors = m.groups()
        if name:
            if not isinstance(value, dict) or name not in value:
                raise TraceError(f"no field '{name}'")
            value = value[name]
        for sel in re.findall(r"\[([^\]]+)\]", selectors):
            if not isinstance(value, list):
                raise TraceError(f"[{sel}] applied to a non-list")
            if sel.isdigit():
                if int(sel) >= len(value):
                    raise TraceError(f"index {sel} out of range")
                value = value[int(sel)]
            elif sel.startswith("@max="):
                key = sel[5:]
                rows = [r for r in value if isinstance(r, dict) and isinstance(r.get(key), (int, float))]
                if not rows:
                    raise TraceError(f"no row has a numeric '{key}'")
                value = max(rows, key=lambda r: r[key])
            elif "=" in sel:
                key, want = sel.split("=", 1)
                hit = next((r for r in value if isinstance(r, dict) and (r.get(key) == want or (
                    isinstance(r.get(key), str) and len(want) >= 7 and r[key].startswith(want)))), None)
                if hit is None:
                    raise TraceError(f"no row with {key}={want}")
                value = hit
            else:
                raise TraceError(f"bad selector [{sel}]")
    return value


def fmt(value, how, bundle):
    """Format a resolved value for the article according to `how` (num, pct, len, short, text, subject, limits).

    Raises TraceError for null values and type mismatches, so a missing stage cannot print as a number.
    """
    if how == "limits":
        rows = [c for c in bundle["coverage"] if c["status"] != "COVERED"]
        return "\n".join(f"- **{c['stage']}** ({c['status']}): {c['evidence']}. Does not prove: {c['does_not_prove']}." for c in rows)
    if value is None:
        raise TraceError("value is null (stage not run); say NOT TESTED in prose instead")
    if how == "len":
        return str(len(value))
    if how == "subject":
        if not isinstance(value, str) or value not in bundle["commits"]:
            raise TraceError("|subject needs a SHA present in commits")
        return bundle["commits"][value]["subject"]
    if how in ("short", "text"):
        if not isinstance(value, str):
            raise TraceError(f"|{how} needs a string")
        return value[:10] if how == "short" else value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TraceError(f"|{how or 'num'} needs a number, got {type(value).__name__}")
    if how == "pct":
        return f"{round(value * 100)}%"
    if how in (None, "num"):
        return str(int(value)) if float(value).is_integer() else f"{value:.1f}"
    raise TraceError(f"unknown format '{how}'")


def strip_allowed(text):
    """Remove the places where digits are allowed so that what remains is prose."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    return REF.sub(" ", text)


def main():
    """Render the template, check that every number is traced, and write the article and trace table."""
    ap = argparse.ArgumentParser()
    ap.add_argument("template")
    ap.add_argument("--bundle", action="append", required=True, metavar="NAME=FILE")
    ap.add_argument("--out")
    ap.add_argument("--trace")
    a = ap.parse_args()
    bundles = {}
    for spec in a.bundle:
        name, path = spec.split("=", 1)
        bundles[name] = json.loads(Path(path).read_text())
    src = Path(a.template).read_text()
    errors, trace = [], []

    def sub(m):
        """Replace one reference with its formatted value and record the trace; collect errors instead of raising."""
        target, path, how = m.group(1), m.group(2).strip(), m.group(3)
        line = src.count("\n", 0, m.start()) + 1
        try:
            if target not in bundles:
                raise TraceError(f"unknown target '{target}'")
            b = bundles[target]
            out = fmt(None if how == "limits" else resolve(b, path), how, b)
            if how == "limits":
                trace.append((line, "(coverage list)", f"{target}:coverage[status!=COVERED]"))
            if how != "limits":
                trace.append((line, out, f"{target}:{path}" + (f"|{how}" if how else "")))
            return out
        except TraceError as e:
            errors.append(f"line {line}: {{{{{target}:{path}}}}}: {e}")
            return m.group(0)

    rendered = REF.sub(sub, src)
    for i, line in enumerate(strip_allowed(src).splitlines(), 1):
        for n in re.findall(r"\d+(?:[.,]\d+)?", line):
            errors.append(f"line {i}: literal number '{n}' in prose; write it as a bundle reference")
    if errors:
        print("article check FAILED:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    if a.out:
        Path(a.out).write_text(rendered)
    if a.trace:
        rows = "\n".join(f"| {ln} | {val} | `{p}` |" for ln, val, p in trace)
        Path(a.trace).write_text("# Number trace\n\nEvery number in ARTICLE.md, the template line it comes from, and its bundle path.\n\n"
                                 "| Line | Value | Bundle path |\n|---|---|---|\n" + rows + "\n")
    print(f"article check PASS: {len(trace)} numbers traced to the bundle, no literal numbers in prose", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
