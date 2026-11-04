"""Every fixture the tests feed the client validates against openapi/parro.openapi.json.

Skipped when the full spec or samples/ are absent (both are git-ignored).
"""

import json

import pytest

from tests.conftest import FULL_SPEC_PATH, load_sample

openapi_schema_validator = pytest.importorskip("openapi_schema_validator")

# sample file → (path, method, status) of the response it is an example of.
SAMPLE_RESPONSES = {
    "getAccountMe.200.json": ("/account/me", "get", "200"),
    "getAccountSettings.200.json": ("/accountsettings", "get", "200"),
    "getOrganisation.200.json": ("/organisation/{id}", "get", "200"),
    "listChildren.200.json": ("/child", "get", "206"),
    "getUnreadCounts.200.json": ("/identity/unreadcounts", "get", "206"),
    "listGroups.200.json": ("/group", "get", "206"),
    "listGroups_previous.200.json": ("/group", "get", "206"),
    "listEvents_announcements.200.json": ("/event", "get", "206"),
    "listEvents_calendar-items.200.json": ("/event", "get", "206"),
    "getEvent_announcement.200.json": ("/event/{id}", "get", "200"),
    "getEvent.200.json": ("/event/{id}", "get", "200"),
    "getEvent_attachment.200.json": ("/event/{id}", "get", "200"),
    "getEvent.406.json": ("/event/{id}", "get", "406"),
    "listSystemNews.200.json": ("/systemnews", "get", "206"),
    "getAbsenceSetting.200.json": ("/absence/setting", "get", "206"),
    "listChatrooms.200.json": ("/chatroom", "get", "206"),
    "listChatMessages.200.json": ("/chatroom/{id}/chatmessage", "get", "206"),
    "token.200.json": ("/oauth2/token", "post", "200"),
    "discovery.200.json": ("/.well-known/openid-configuration", "get", "200"),
}


@pytest.fixture(scope="module")
def spec():
    if not FULL_SPEC_PATH.exists():
        pytest.skip("openapi/parro.openapi.json not present (git-ignored)")
    return json.loads(FULL_SPEC_PATH.read_text(encoding="utf-8"))


def response_schema(spec, path: str, method: str, status: str) -> dict[str, object]:
    response = spec["paths"][path][method]["responses"][status]
    if "$ref" in response:
        response = spec["components"]["responses"][response["$ref"].rsplit("/", 1)[-1]]
    (media_type,) = response["content"].values()
    return dict(media_type["schema"], components=spec["components"])


@pytest.mark.parametrize("sample_name", sorted(SAMPLE_RESPONSES))
def test_sample_matches_its_response_schema(spec, sample_name):
    schema = response_schema(spec, *SAMPLE_RESPONSES[sample_name])
    validator = openapi_schema_validator.OAS30Validator(
        schema, format_checker=openapi_schema_validator.oas30_format_checker
    )
    problems = [
        f"/{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}"
        for e in validator.iter_errors(load_sample(sample_name))
    ]
    assert problems == []
