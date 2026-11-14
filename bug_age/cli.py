# SPDX-License-Identifier: MIT OR Apache-2.0
"""bug-age command-line interface.

One command, one subcommand per pipeline stage. Each subcommand reads files, writes one JSON output
(stdout or `--out`), and logs a one-line summary to stderr. Exit status is 0 on success, 1 on a
runtime error and 2 on a usage error.
"""
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from . import __version__, bundle, catalog, explorer, mcp, szz
from ._compat import dumps, get, lines, loads

USAGE = """usage: bug-age [--version | --help]
       bug-age catalog --repo DIR --path CRATE [--head REV] [--out FILE]
       bug-age szz --repo DIR --catalog FILE [--window-start YYYY-MM-DD] [--release-tags GLOB] [--out FILE]
       bug-age sweep --repo DIR --path CRATE --fix SHA --overlay DIR --test CMD
             [--build CMD] [--start SHA] [--runner docker|local] [--repeats N] [--image IMG]
             [--time-travel-script FILE|none] [--scratch DIR] [--logs DIR] [--out FILE]
             [--namespace NAME] [--bucket N (toolchain minor rounding, default 4; 0 = exact)]
       bug-age probe --repo DIR --path CRATE --commits SHA,SHA,... --overlay DIR --test CMD [same options]
       bug-age bundle --repo DIR --results DIR --repo-url URL --out DIR [--spike DIR] [--out-of-scope 'STAGE|EVIDENCE|DOES_NOT_PROVE']
       bug-age explorer --page FILE --targets NAME=DIR,NAME=DIR --out DIR   (DIR = a bundle output dir)
       bug-age mcp --bundles NAME=FILE,NAME=FILE   (read-only MCP server on stdio over bundle.json files)
       bug-age pipeline TARGET.toml [--fresh] [--skip-feasibility]   (every stage for one target)
       bug-age dockerfile   (print the Method B image's Dockerfile: bug-age dockerfile | docker build -t bug-age-spike:4 -)"""

WARN_BYTES = 8 * 1024 * 1024
MAX_BYTES = 16 * 1024 * 1024


class Failure(Exception):
    """A runtime error: printed as `bug-age: <message>`, exit status 1."""


def flags(args):
    """`--key value` pairs as a dict; anything else is an error."""
    out, it = {}, iter(args)
    for k in it:
        if not k.startswith("--"):
            raise Failure(f"unexpected argument '{k}'")
        try:
            out[k[2:]] = next(it)
        except StopIteration:
            raise Failure(f"missing value for '{k}'") from None
    return out


def need(f, key):
    """A required flag's value."""
    if key not in f:
        raise Failure(f"missing --{key}")
    return f[key]


def write(path, text):
    """Write UTF-8 text with LF line ends."""
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except OSError as exc:
        raise Failure(f"cannot write {path}: {exc}") from exc


def emit(value, out):
    """Pretty JSON to `out`, or to stdout when no file is given."""
    text = dumps(value, pretty=True) + "\n"
    if out is None:
        sys.stdout.write(text)
    else:
        write(out, text)


def sha256(text):
    """Hex SHA-256 of a text's UTF-8 bytes."""
    return hashlib.sha256(text.encode()).hexdigest()


def tool_version(cmd, args):
    """First line a tool prints for its version, or "unavailable"."""
    try:
        out = subprocess.run([cmd, *args], capture_output=True).stdout.decode("utf-8", "replace")
    except OSError:
        return "unavailable"
    first = lines(out)
    return first[0] if first else ""


def command_line():
    """This run's command line as it may be published (see bundle.public_command)."""
    return bundle.public_command(sys.argv, os.getcwd(), os.environ.get("HOME", ""))


def read_json(path):
    """A JSON file as a value, with the path in any error."""
    try:
        return loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Failure(f"{path}: {exc}") from exc


def cmd_catalog(f):
    """`catalog`: rule-based list of fix commits."""
    cat = catalog.build(Path(need(f, "repo")), f.get("head", "HEAD"), need(f, "path"))
    print(f"catalog: {len(cat['fixes'])} fixes, {len(cat['excluded'])} excluded, {cat['scanned']} commits scanned",
          file=sys.stderr)
    emit(cat, f.get("out"))


def cmd_szz(f):
    """`szz`: Method A for every catalogued fix."""
    repo = Path(need(f, "repo"))
    cat = read_json(need(f, "catalog"))
    path = get(cat, "path")
    if not isinstance(path, str):
        raise Failure("catalog has no path")
    window = f.get("window-start")
    release_tags = f.get("release-tags", "v[0-9]*")
    fixes = get(cat, "fixes")
    if not isinstance(fixes, list):
        raise Failure("catalog has no fixes")
    bugs = []
    for e in fixes:
        def text(k):
            v = get(e, k)
            return v if isinstance(v, str) else ""
        parents = get(e, "parents")
        entry = {"sha": text("sha"), "date": text("date"), "subject": text("subject"), "rule": text("rule"),
                 "parents": [p for p in parents if isinstance(p, str)] if isinstance(parents, list) else []}
        bugs.append(szz.analyze(repo, entry, path, window, release_tags))
    with_intro = sum(1 for b in bugs if b["lifetime"] is not None)
    in_window = sum(1 for b in bugs if b["in_window"] is True)
    print(f"szz: {len(bugs)} fixes, {with_intro} with a nominated introducer, {in_window} in window", file=sys.stderr)
    summary = {"fixes": len(bugs), "with_introducer": with_intro, "in_window": in_window if window is not None else None,
               "window_start": window, "release_tags": release_tags}
    emit({"head": get(cat, "head"), "path": path, "method": "A (SZZ-style, git blame -w on first parent)",
          "summary": summary, "bugs": bugs}, f.get("out"))


def cmd_bundle(f):
    """`bundle`: the canonical data bundle, its JS wrapper and a receipt."""
    repo, out = Path(need(f, "repo")), Path(need(f, "out"))
    spike = Path(f.get("spike", "spike"))
    oos = None
    if "out-of-scope" in f:
        parts = f["out-of-scope"].split("|", 2)
        if len(parts) != 3:
            raise Failure("--out-of-scope must be 'STAGE|EVIDENCE|DOES_NOT_PROVE'")
        oos = tuple(parts)
    try:
        built = bundle.build(repo, Path(need(f, "results")), spike, need(f, "repo-url"), oos)
    except bundle.BundleError as exc:
        raise Failure(str(exc)) from exc
    text = dumps(built)
    js = f"window.BUG_AGE_BUNDLE = {text};\n"
    if len(js.encode()) > MAX_BYTES:
        raise Failure(f"size gate failed: bundle.js is {len(js.encode())} bytes (> {MAX_BYTES})")
    out.mkdir(parents=True, exist_ok=True)
    write(out / "bundle.json", text)
    write(out / "bundle.js", js)
    receipt = {
        "command": command_line(),
        "schema_version": bundle.SCHEMA_VERSION,
        "blameless_gate": "PASS",
        "size": {"bundle_json_bytes": len(text.encode()), "bundle_js_bytes": len(js.encode()),
                 "warn_over_8mb": len(js.encode()) > WARN_BYTES},
        "outputs": {"bundle.json": sha256(text), "bundle.js": sha256(js)},
        "versions": {"bug-age": __version__, "git": tool_version("git", ["--version"])},
        "warnings": [],
    }
    print(f"bundle: {len(text.encode())} bytes, sha256 {sha256(text)}, blameless gate PASS", file=sys.stderr)
    emit(receipt, out / "receipt.json")


def cmd_explorer(f):
    """`explorer`: the static explorer page with one data file per target."""
    page_path = need(f, "page")
    try:
        page = Path(page_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Failure(f"{page_path}: {exc}") from exc
    out = Path(need(f, "out"))
    targets = []
    for spec in need(f, "targets").split(","):
        name, eq, d = spec.partition("=")
        if not eq:
            raise Failure(f"--targets entry '{spec}' must be NAME=DIR")
        targets.append((name, read_json(Path(d) / "bundle.json"), read_json(Path(d) / "receipt.json")))
    try:
        page, files, total = explorer.assemble(page, targets)
    except explorer.ExplorerError as exc:
        raise Failure(str(exc)) from exc
    (out / "data").mkdir(parents=True, exist_ok=True)
    write(out / "index.html", page)
    outputs = {"index.html": sha256(page)}
    for path, content in files:
        write(out / path, content)
        outputs[path] = sha256(content)
    print(f"explorer: {len(targets)} targets, {total} bytes (gate {explorer.GATE_BYTES}), size gate PASS", file=sys.stderr)
    emit({"total_bytes": total, "gate_bytes": explorer.GATE_BYTES, "size_gate": "PASS", "outputs": outputs,
          "bug-age": __version__}, out / "receipt.json")


def cmd_mcp(f):
    """`mcp`: read-only MCP server on stdio."""
    targets = []
    for spec in need(f, "bundles").split(","):
        name, eq, file = spec.partition("=")
        if not eq:
            raise Failure(f"--bundles entry '{spec}' must be NAME=FILE")
        try:
            targets.append(mcp.Target(name, file))
        except RuntimeError as exc:
            raise Failure(str(exc)) from exc
    print(f"bug-age mcp: serving {len(targets)} target(s) on stdio", file=sys.stderr)
    stdin = open(sys.stdin.fileno(), encoding="utf-8", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)
    mcp.serve(targets, stdin, stdout)


def cmd_sweep(f):
    """`sweep`: Method B for one fix (see bug_age.sweep)."""
    from .sweep import cmd_sweep as run
    run(f)


def cmd_probe(f):
    """`probe`: test given commits with a regression overlay (see bug_age.sweep)."""
    from .sweep import cmd_probe as run
    run(f)


COMMANDS = {"catalog": cmd_catalog, "szz": cmd_szz, "sweep": cmd_sweep, "probe": cmd_probe,
            "bundle": cmd_bundle, "explorer": cmd_explorer, "mcp": cmd_mcp}


def main(argv=None):
    """Run one subcommand; return the exit status."""
    args = sys.argv[1:] if argv is None else argv
    first = args[0] if args else None
    if first in ("--version", "-V"):
        print(f"bug-age {__version__}")
        return 0
    if first in (None, "--help", "-h"):
        print(USAGE)
        return 0
    if first == "pipeline":
        from .pipeline import main as pipeline
        return pipeline(args[1:])
    if first == "dockerfile":
        sys.stdout.write((Path(__file__).parent / "data" / "Dockerfile").read_text(encoding="utf-8"))
        return 0
    if first not in COMMANDS:
        print(f"bug-age: unknown argument '{first}'\n{USAGE}", file=sys.stderr)
        return 2
    try:
        COMMANDS[first](flags(args[1:]))
    except (Failure, RuntimeError) as exc:
        print(f"bug-age: {exc}", file=sys.stderr)
        return 1
    return 0
