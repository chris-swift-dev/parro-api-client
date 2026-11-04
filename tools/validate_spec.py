#!/usr/bin/env python3
"""Validate openapi/parro.openapi.json.

1. The document against the OpenAPI 3.0 meta-schema (openapi-spec-validator).
2. Every embedded response example (= every sample) against its response schema
   (openapi-schema-validator, OAS 3.0 dialect, refs resolved within the spec).
3. A scan for things that must never be in the spec: e-mail addresses other than
   example.com, tokens, real-looking CloudFront paths.

Dev-only dependencies:  pip install openapi-spec-validator openapi-schema-validator
Usage:  python3 tools/validate_spec.py [openapi/parro.openapi.json]
"""
import json
import os
import re
import sys

from openapi_spec_validator import validate as validate_spec
from openapi_schema_validator import OAS30Validator, oas30_format_checker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "openapi", "parro.openapi.json")
with open(path, encoding="utf-8") as fh:
    text = fh.read()
spec = json.loads(text)

validate_spec(spec)
print("1. OpenAPI 3.0 structure: OK")

failures, checked = 0, 0
for p, item in spec["paths"].items():
    for method, op in item.items():
        if not isinstance(op, dict) or "responses" not in op:
            continue
        for status, resp in op["responses"].items():
            for media, mt in (resp.get("content") or {}).items():
                for name, ex in (mt.get("examples") or {}).items():
                    checked += 1
                    schema = dict(mt["schema"], components=spec["components"])
                    errors = sorted(OAS30Validator(schema, format_checker=oas30_format_checker).iter_errors(ex["value"]),
                                    key=lambda e: list(e.absolute_path))
                    if errors:
                        failures += 1
                        print("   FAIL {} {} {} [{}]".format(method.upper(), p, status, name))
                        for e in errors[:5]:
                            print("        at /{}: {}".format("/".join(map(str, e.absolute_path)), e.message[:160]))
print("2. Examples vs schemas: {} checked, {} failed".format(checked, failures))

leaks = []
for m in set(re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)):
    if not m.endswith("example.com"):
        leaks.append("e-mail " + m)
if re.search(r'"(access|refresh|id)_token":\s*"(?!REDACTED)', text):
    leaks.append("unredacted token")
if re.search(r"eyJ[\w-]{10,}\.[\w-]{10,}\.", text):
    leaks.append("JWT-looking string")
def placeholder(h):
    return any(run in h for run in ("123456", "000000", "abcdef"))
for m in set(re.findall(r"cloudfront\.net/\w+/([0-9a-f]{32})/1-([0-9a-f]{32})", text)):
    if not all(placeholder(h) for h in m):
        leaks.append("real-looking CloudFront path " + "/".join(m))
print("3. Privacy scan: " + ("OK" if not leaks else "FOUND " + "; ".join(sorted(leaks))))

sys.exit(1 if failures or leaks else 0)
