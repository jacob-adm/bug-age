# SPDX-License-Identifier: MIT OR Apache-2.0
"""JSON Schema (draft 2020-12) validation for the keywords bug-age's bundle schema uses.

Supported: type, enum, const, properties, required, additionalProperties, propertyNames, items,
anyOf, not, pattern, maxLength, minimum, maximum, $ref to `#/$defs/...`. Any other keyword in a
schema is an error rather than silently ignored, so the schema can only use what is checked here.
"""
import math
import re

_ANNOTATIONS = {"$schema", "$id", "title", "description", "$defs", "default", "examples"}
_SUPPORTED = _ANNOTATIONS | {"type", "enum", "const", "properties", "required", "additionalProperties",
                             "propertyNames", "items", "anyOf", "not", "pattern", "maxLength", "minimum",
                             "maximum", "$ref"}


def _is_type(value, name):
    """Whether `value` has JSON type `name`; an integer-valued float is an integer, as the draft says."""
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    if name == "number":
        return True
    if name == "integer":
        return isinstance(value, int) or (math.isfinite(value) and value == int(value))
    raise ValueError(f"unknown type {name!r}")


def _equal(a, b):
    """JSON equality: numbers by value, booleans never equal to numbers."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_equal(x, y) for x, y in zip(a, b))
    return a == b


def errors(value, schema, root=None, path="$"):
    """Every validation error for `value`, as "path: message" strings."""
    root = schema if root is None else root
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: no value is allowed here"]
    unknown = set(schema) - _SUPPORTED
    if unknown:
        raise ValueError(f"unsupported schema keyword(s) at {path}: {sorted(unknown)}")
    out = []
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"unsupported $ref {ref!r}")
        out += errors(value, root["$defs"][ref[len("#/$defs/"):]], root, path)
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, t) for t in types):
            return out + [f"{path}: expected {' or '.join(types)}"]
    if "enum" in schema and not any(_equal(value, e) for e in schema["enum"]):
        out.append(f"{path}: {value!r} is not one of {schema['enum']!r}")
    if "const" in schema and not _equal(value, schema["const"]):
        out.append(f"{path}: must be {schema['const']!r}")
    if "anyOf" in schema and not any(not errors(value, s, root, path) for s in schema["anyOf"]):
        out.append(f"{path}: matches none of anyOf")
    if "not" in schema and not errors(value, schema["not"], root, path):
        out.append(f"{path}: matches a schema it must not")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            out.append(f"{path}: does not match {schema['pattern']!r}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            out.append(f"{path}: longer than {schema['maxLength']}")
    if _is_type(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for k in schema.get("required", []):
            if k not in value:
                out.append(f"{path}: missing {k!r}")
        for k, v in value.items():
            if k in props:
                out += errors(v, props[k], root, f"{path}.{k}")
            elif "additionalProperties" in schema:
                out += errors(v, schema["additionalProperties"], root, f"{path}.{k}")
            if "propertyNames" in schema:
                out += errors(k, schema["propertyNames"], root, f"{path}[key {k!r}]")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            out += errors(v, schema["items"], root, f"{path}[{i}]")
    return out
