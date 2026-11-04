"""Helpers for the Topicus "geon" JSON format the Parro API speaks.

Every geon object carries bookkeeping next to its data: a `dtype`, `links` (the object's id hides in
the `rel: self` link), `permissions` and often an empty `additionalObjects`. Collections come as
{"items": [...]} with the total in the Content-Range header. See the spec's "Conventions" section.

These functions only reshape data; they never send requests.
"""

from typing import Any

# Keys that carry no information for a reader of the data.
GEON_BOOKKEEPING_KEYS = frozenset({"dtype", "links", "permissions", "additionalObjects"})


def get_object_id(geon_object: Any) -> int | None:
    """The object's id: the `id` of its `rel: self` link, else a plain `id` field, else None."""
    if not isinstance(geon_object, dict):
        return None
    for link in geon_object.get("links") or []:
        if isinstance(link, dict) and link.get("rel") == "self" and "id" in link:
            return link["id"]  # type: ignore[no-any-return]
    plain_id = geon_object.get("id")
    return plain_id if isinstance(plain_id, int) else None


def short_type_name(dtype: str) -> str:
    """'event.RAnnouncementEventPrimer' → 'RAnnouncementEventPrimer'."""
    return dtype.rsplit(".", 1)[-1]


def strip_geon_metadata(value: Any) -> Any:
    """Return a copy of a geon payload without the bookkeeping, recursively.

    For every object:
      * `id` comes first, taken from the self link (see get_object_id);
      * `type` comes next: the short dtype name, unless the object has its own `type` field
        (groups, calendar items and chat rooms do, e.g. "SCHOOLWIDE"), which then wins;
      * links, permissions, dtype and additionalObjects are dropped;
      * fields that are None, [] or {} are dropped, because they say nothing.
    Lists and plain values pass through (lists element by element).
    """
    if isinstance(value, list):
        return [strip_geon_metadata(element) for element in value]
    if not isinstance(value, dict):
        return value

    stripped: dict[str, Any] = {}
    object_id = get_object_id(value)
    if object_id is not None:
        stripped["id"] = object_id
    dtype = value.get("dtype")
    if isinstance(dtype, str) and dtype:
        stripped["type"] = short_type_name(dtype)
    for key, field_value in value.items():
        if key in GEON_BOOKKEEPING_KEYS or (key == "id" and "id" in stripped):
            continue
        if is_empty(field_value):
            continue
        stripped[key] = strip_geon_metadata(field_value)
    return stripped


def is_empty(value: Any) -> bool:
    """None, an empty list or an empty dict. False and 0 are *not* empty: they are information."""
    return value is None or value == [] or value == {}


def get_collection_items(payload: Any) -> list[Any]:
    """The elements of a collection response.

    {"items": [...]} gives the list; a bare list is returned as is; any other object is treated as
    a collection of one; None (empty body) gives an empty list.
    """
    if payload is None:
        return []
    if isinstance(payload, dict) and "items" in payload:
        items = payload["items"]
        return items if isinstance(items, list) else []
    if isinstance(payload, list):
        return payload
    return [payload]


def parse_total_from_content_range(content_range: str | None) -> int | None:
    """The total after the slash in 'items 0-1/2' (→ 2). None when absent or unknown ('*')."""
    if not content_range or "/" not in content_range:
        return None
    total_text = content_range.rpartition("/")[2].strip()
    return int(total_text) if total_text.isdigit() else None


def build_range_header(offset: int, limit: int) -> str:
    """The Range header for `limit` items starting at `offset`: zero-based and inclusive."""
    if offset < 0 or limit < 1:
        raise ValueError(f"invalid range: offset={offset}, limit={limit}")
    return f"items={offset}-{offset + limit - 1}"


def full_name(person: Any) -> str:
    """'firstname surname' of a geon person object, skipping missing parts."""
    if not isinstance(person, dict):
        return ""
    parts = [person.get("firstname"), person.get("surname")]
    return " ".join(part for part in parts if isinstance(part, str) and part)
