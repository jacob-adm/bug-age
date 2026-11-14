# SPDX-License-Identifier: MIT OR Apache-2.0
"""Exact text and number behaviour that bug-age's published results depend on.

bug-age 1.x was written in Rust; its outputs are the reference for every number this package
writes. Python differs from Rust in a few places that change bytes, so this module pins them:

- JSON text: object keys sorted, compact or two-space pretty, and floats written the way
  serde_json writes them (shortest round-trip digits, `1e+16`, `1e-7`, `12.0`).
- Rounding: halfway cases away from zero (Rust's `f64::round`), not to even (Python's `round`).
- Whitespace: Rust's `trim` and `split_whitespace` use Unicode White_Space, which excludes the
  separators 0x1C-0x1F that Python's `str.strip` and `str.split` also remove.
- Lines: Rust's `lines` splits on `\\n` only and drops one trailing `\\r`; `str.splitlines` also
  splits on 0x1C-0x1E, 0x85 and U+2028/U+2029.
"""
import json
import math

# Unicode White_Space, as Rust's char::is_whitespace defines it.
WHITESPACE = ("\t\n\x0b\x0c\r \x85\xa0        "
              "        　")


def trim(text):
    """Rust's str::trim: strip Unicode White_Space from both ends."""
    return text.strip(WHITESPACE)


def split_whitespace(text):
    """Rust's str::split_whitespace: split on runs of Unicode White_Space, no empty parts."""
    out, word = [], []
    for ch in text:
        if ch in WHITESPACE:
            if word:
                out.append("".join(word))
                word = []
        else:
            word.append(ch)
    if word:
        out.append("".join(word))
    return out


def lines(text):
    """Rust's str::lines: split on LF, drop one trailing CR per line, no final empty line."""
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return [p[:-1] if p.endswith("\r") else p for p in parts]


def round_half_away(x):
    """Rust's f64::round: the nearest integer, halfway cases away from zero."""
    if not math.isfinite(x):
        return x
    t = math.trunc(x)
    if abs(x - t) >= 0.5:
        t += math.copysign(1.0, x)
    return math.copysign(float(t), x)


def total_order(x):
    """Sort key matching Rust's f64::total_cmp for numbers: -0.0 sorts before 0.0."""
    return (x, math.copysign(1.0, x))


def round1(x):
    """`(x * 10.0).round() / 10.0`: one decimal place, as bug-age reports days."""
    return round_half_away(x * 10.0) / 10.0


def fmt_float(x):
    """serde_json's text for an f64; NaN and the infinities are written as null."""
    if not math.isfinite(x):
        return "null"
    if x == 0:
        return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    # repr gives the shortest digits that round-trip; only the layout differs from serde_json.
    mant, _, exp = repr(abs(x)).partition("e")
    ip, _, fp = mant.partition(".")
    digits = ip + fp
    point = len(ip) + (int(exp) if exp else 0)
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0") or "0"
    n, kk = len(digits), point
    if 0 <= kk - n and kk <= 16:
        out = digits + "0" * (kk - n) + ".0"
    elif 0 < kk <= 16:
        out = digits[:kk] + "." + digits[kk:]
    elif -5 < kk <= 0:
        out = "0." + "0" * (-kk) + digits
    else:
        ex = kk - 1
        out = (digits if n == 1 else digits[0] + "." + digits[1:]) + "e" + ("+" if ex > 0 else "") + str(ex)
    return ("-" if x < 0 else "") + out


def _string(s):
    """A JSON string as serde_json writes it: only quote, backslash and C0 controls escaped."""
    return json.dumps(s, ensure_ascii=False)


def dumps(value, pretty=False, _indent=0):
    """serde_json text of `value`: keys sorted; `pretty` is to_string_pretty (two spaces)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return fmt_float(value)
    if isinstance(value, str):
        return _string(value)
    if isinstance(value, dict):
        items = sorted(value.items())
        if not items:
            return "{}"
        if not pretty:
            return "{" + ",".join(_string(k) + ":" + dumps(v) for k, v in items) + "}"
        pad = "  " * (_indent + 1)
        body = ",\n".join(pad + _string(k) + ": " + dumps(v, True, _indent + 1) for k, v in items)
        return "{\n" + body + "\n" + "  " * _indent + "}"
    if isinstance(value, (list, tuple)):
        if not value:
            return "[]"
        if not pretty:
            return "[" + ",".join(dumps(v) for v in value) + "]"
        pad = "  " * (_indent + 1)
        return "[\n" + ",\n".join(pad + dumps(v, True, _indent + 1) for v in value) + "\n" + "  " * _indent + "]"
    raise TypeError(f"cannot write {type(value).__name__} as JSON")


def loads(text):
    """Parse JSON; integers stay int and numbers with a fraction or exponent become float, as in serde_json."""
    return json.loads(text)


def as_f64(value):
    """serde_json's Value::as_f64: any JSON number as a float, anything else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def get(value, *keys):
    """Index like serde_json's Value[...]: a missing key or index, or a non-container, gives None."""
    for k in keys:
        if isinstance(k, int):
            value = value[k] if isinstance(value, list) and 0 <= k < len(value) else None
        else:
            value = value.get(k) if isinstance(value, dict) else None
    return value
