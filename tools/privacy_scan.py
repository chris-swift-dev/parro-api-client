"""Find personal data and live links in the spec and the samples (used by validate_spec.py).

Samples come from real captures and are sanitized by hand; this scan checks that it was done.
Every value under a name or address field must be a placeholder, and every signed or secret link
must end in a placeholder. So must every link field (`url`, `…Url`, `avatar`), an organisation's
`code`, `uploadId`, and the text of a chat message. A finding names the place (file, JSON path,
length), never the value, so the scan's own output cannot leak what it found.

In an OpenAPI document only the examples are checked for names (that is where sample data ends
up); links are checked everywhere.

Placeholders: Voornaam, Achternaam, Voorbeeld, REDACTED, example(.com), and numbers made of runs
such as 1000000000 (the ids and usernames of the samples).

Standard library only.  Usage:
    python3 tools/privacy_scan.py [FILE.json | DIR ...]   (default: samples/ and the full spec)
"""

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Fields that hold a name (of a person, class or school) or an address. Values may be strings or
# lists of strings.
NAME_FIELDS = {
    "firstname", "surname", "lastname", "name", "lastEditedBy", "username", "externalUsername",
    "guardianNames", "childNames", "memberNames",
    "city", "street", "address", "postalCode", "zipCode", "phone", "phoneNumber", "mobile",
}  # fmt: skip
PLACEHOLDER_WORD = re.compile(r"(?i)voornaam|achternaam|voorbeeld|redacted|example")
PLACEHOLDER_NUMBER = re.compile(r"^\d*(0{6}|1{6}|123456|9{6})\d*$")

# Links that work without a login once someone has them. What follows the marker must be a
# placeholder: REDACTED, a spec template such as <token>, or runs of 1s like the sample links.
SECRET_LINKS = {
    "signed privacy link": re.compile(r"signedpermission=([^\"&\s\\]*)"),
    "calendar subscription link": re.compile(r"calendar\.parro\.com/ical/([^\"\s\\?]*)"),
    "avatar link": re.compile(r"bao/image\?req=([^\"&\s\\]*)"),
}
PLACEHOLDER_LINK = re.compile(r"^(REDACTED|<|[\d/]*1a111111)")

# Other values that must be placeholders (PLAN-read-state-and-filters phase 2). Each kind has its
# own test of what counts as a placeholder.
#   link:   any `url`, `…Url` or `avatar` field (download and avatar links carry access keys);
#   code:   an organisation's `code` (identifies the school);
#   upload: `uploadId` (identifies a file);
#   text:   the `text` of a chat message (written by people, stored verbatim).
LINK_FIELDS = re.compile(r"^(url|.*Url|avatar)$")
PLACEHOLDER_LINK_VALUE = re.compile(r"(?i)redacted|example|<|123456|000000|abcdef")
PLACEHOLDER_CODE = re.compile(r"^00[A-Z]{2}$")
PLACEHOLDER_UPLOAD = re.compile(r"(?i)^0{8}-0{4}-|redacted|example")


def is_placeholder(value: str) -> bool:
    return bool(PLACEHOLDER_WORD.search(value) or PLACEHOLDER_NUMBER.match(value)) or not value


def walk(value: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """(json path, string) for every string under a name field, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}/{key}"
            if key in NAME_FIELDS:
                strings = item if isinstance(item, list) else [item]
                for index, text in enumerate(strings):
                    if isinstance(text, str):
                        yield (f"{here}/{index}" if isinstance(item, list) else here), text
            yield from walk(item, here)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}/{index}")


def other_values(value: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    """(json path, kind, string) for every link, school code, upload id and chat text."""
    if isinstance(value, dict):
        dtype = str(value.get("dtype") or "")
        for key, item in value.items():
            here = f"{path}/{key}"
            if not isinstance(item, str):
                yield from other_values(item, here)
            elif LINK_FIELDS.match(key):
                yield here, "link", item
            elif key == "code" and "organisation" in path.lower():
                yield here, "code", item
            elif key == "uploadId":
                yield here, "upload", item
            elif key == "text" and dtype.startswith("chat.") and dtype.endswith("Message"):
                yield here, "text", item
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from other_values(item, f"{path}/{index}")


def other_is_placeholder(kind: str, value: str) -> bool:
    tests = {
        "link": PLACEHOLDER_LINK_VALUE.search,
        "code": PLACEHOLDER_CODE.match,
        "upload": PLACEHOLDER_UPLOAD.search,
        "text": PLACEHOLDER_WORD.search,
    }
    return not value or bool(tests[kind](value))


def example_values(spec: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """In an OpenAPI document: the `example` / `examples` subtrees, where sample data ends up.

    Everything else (tags, parameter names, descriptions) is the spec's own text.
    """
    if isinstance(spec, dict):
        for key, item in spec.items():
            if key in ("example", "examples"):
                yield f"{path}/{key}", item
            else:
                yield from example_values(item, f"{path}/{key}")
    elif isinstance(spec, list):
        for index, item in enumerate(spec):
            yield from example_values(item, f"{path}/{index}")


def scan_text(text: str, source: str) -> list[str]:
    """Findings for one JSON document: a sample, or a whole OpenAPI spec (its examples only)."""
    findings = []
    try:
        document = json.loads(text)
    except ValueError:
        return [f"{source}: not JSON"]
    is_spec = isinstance(document, dict) and "openapi" in document
    roots = list(example_values(document)) if is_spec else [("", document)]
    names = [(f"{root}{path}", value) for root, part in roots for path, value in walk(part)]
    for path, value in names:
        if not is_placeholder(value):
            findings.append(f"{source}: {path}: not a placeholder ({len(value)} characters)")
    others = [(f"{root}{path}", kind, value) for root, part in roots
              for path, kind, value in other_values(part)]  # fmt: skip
    for path, kind, value in others:
        if not other_is_placeholder(kind, value):
            findings.append(f"{source}: {path}: {kind} not a placeholder ({len(value)} characters)")
    for label, pattern in SECRET_LINKS.items():
        for match in pattern.finditer(text):
            if not PLACEHOLDER_LINK.match(match.group(1)):
                findings.append(f"{source}: {label} that is not redacted")
    return findings


def scan_paths(paths: list[Path]) -> list[str]:
    findings = []
    for path in paths:
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        for file in files:
            text = file.read_text(encoding="utf-8")
            if text.strip():
                findings += scan_text(text, file.name)
    return findings


def main(argv: list[str]) -> int:
    defaults = [ROOT / "samples", ROOT / "openapi" / "parro.openapi.json"]
    paths = [Path(arg) for arg in argv] or [path for path in defaults if path.exists()]
    findings = scan_paths(paths)
    for finding in findings:
        print(finding)
    print("privacy scan: " + ("OK" if not findings else f"{len(findings)} finding(s)"))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
