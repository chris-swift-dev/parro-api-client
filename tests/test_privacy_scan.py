"""tools/privacy_scan.py: names must be placeholders, secret links redacted, findings never leak.

The scan guards the samples (sanitized by hand from real captures) and the spec built from them.
"""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

TOOL = Path(__file__).resolve().parent.parent / "tools" / "privacy_scan.py"
PUBLIC_SPEC = TOOL.parent.parent / "openapi" / "parro.public.openapi.json"
INVENTED_NAME = "Marieke Hoogland"  # stands in for a real name a capture might contain


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("privacy_scan", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = load_tool()


def findings(document: object) -> list[str]:
    result: list[str] = scan.scan_text(json.dumps(document), "sample.json")
    return result


def child(**setting: object) -> dict[str, object]:
    return {
        "dtype": "identity.RPrivacySettingChild",
        "firstname": "Voornaam",
        "surname": "Achternaam",
        "cachedAvatarUrl": "https://start.parnassys.net/bao/image?req=REDACTED%3D",
        "guardianNames": [],
        "setting": {"dtype": "privacy.RPrivacyCentreSetting", **setting},
    }


def test_placeholders_pass():
    sample = {"items": [child(lastEditedBy="Voornaam Achternaam")], "username": "10000000000"}
    assert findings(sample) == []


def test_a_real_looking_name_is_found_but_not_repeated():
    found = findings({"items": [child(lastEditedBy=INVENTED_NAME)]})
    assert found == [
        "sample.json: /items/0/setting/lastEditedBy: not a placeholder (16 characters)"
    ]
    assert not any("Marieke" in line or "Hoogland" in line for line in found)


def test_names_in_lists_and_nested_objects():
    sample = {
        "owner": {"firstname": "Voornaam", "surname": "Jansen"},
        "guardianNames": ["Voornaam", "Piet"],
    }
    assert [line.split(": ")[1] for line in findings(sample)] == [
        "/owner/surname",
        "/guardianNames/1",
    ]


def test_a_name_in_a_helper_commitment_is_found():
    commitment = {
        "items": [
            {
                "dtype": "calendar.RCalendarItemResourceCommitmentPrimer",
                "amount": 1,
                "identity": {"dtype": "identity.RIdentityPrimer", "surname": INVENTED_NAME},
            }
        ]
    }
    findings = load_tool().scan_text(json.dumps(commitment), "addCommitment.201.json")
    assert len(findings) == 1 and INVENTED_NAME not in findings[0]
    assert "/items/0/identity/surname" in findings[0]


def test_address_fields_are_checked_too():
    school = {"name": "Basisschool Voorbeeld", "city": "Zwolle"}
    assert findings(school) == ["sample.json: /city: not a placeholder (6 characters)"]
    assert findings({"city": "Voorbeeldstad"}) == []


def test_secret_links_must_be_redacted():
    redacted = {"url": "https://start.parnassys.net/bao/privacy?signedpermission=REDACTED"}
    live = {"url": "https://start.parnassys.net/bao/privacy?signedpermission=a8Fk2q"}
    calendar = {"strings": ["https://calendar.parro.com/ical/4812/9f8e7d6c?noCache=1"]}
    assert findings(redacted) == []
    assert findings(live) == [
        "sample.json: /url: link not a placeholder (63 characters)",  # every link field
        "sample.json: signed privacy link that is not redacted",  # and the link itself
    ]
    assert findings(calendar) == ["sample.json: calendar subscription link that is not redacted"]


def test_in_a_spec_only_the_examples_are_checked_for_names():
    spec = {
        "openapi": "3.0.3",
        "tags": [{"name": "Account"}],
        "paths": {
            "/child": {
                "get": {
                    "parameters": [{"name": "dtype"}],
                    "responses": {"200": {"examples": {"x": {"value": child(lastEditedBy="Jan")}}}},
                }
            }
        },
    }
    assert findings(spec) == [
        "sample.json: /paths//child/get/responses/200/examples/x/value/setting/lastEditedBy: "
        "not a placeholder (3 characters)"
    ]


def test_the_published_spec_is_clean():
    text = PUBLIC_SPEC.read_text(encoding="utf-8")
    assert scan.scan_text(text, PUBLIC_SPEC.name) == []


# ------------------------------------------- links, school codes, upload ids, chat texts


def test_every_link_field_must_be_a_placeholder():
    live = {
        "url": "https://d3k9f8a7b6c5e4.cloudfront.net/attachments/9f8e7d6c5b4a39281706f5e4d3c2b1a0/1-x",
        "cachedAvatarUrl": "https://img.cdnhost.net/u/48213",
        "avatar": "https://start.parnassys.net/bao/avatar/77231",
    }
    found = findings(live)
    assert [line.split(": ")[1] for line in found] == ["/url", "/cachedAvatarUrl", "/avatar"]
    assert all("link not a placeholder" in line for line in found)
    assert not any("48213" in line or "cloudfront" in line for line in found), "values never shown"
    placeholders = {
        "url": "https://d111111abcdef8.cloudfront.net/REDACTED/0/1-0",
        "cachedAvatarUrl": "https://start.parnassys.net/bao/image?req=REDACTED",
        "avatar": "REDACTED",
        "downloadUrl": "",
    }
    assert findings(placeholders) == []


def test_school_codes_upload_ids_and_chat_texts():
    sample = {
        "organisation": {"code": "07QX"},
        "group": {"code": "GROUP3"},  # not an organisation: a code like this is the API's own
        "attachments": [{"uploadId": "3f9c1e2a-7b4d-4e8a-9c21-5d6e7f8a9b0c"}],
        "message": {"dtype": "chat.RChatTextMessage", "text": "Morgen ben ik er niet."},
        "announcement": {"dtype": "event.RAnnouncementEventPrimer", "text": "not a chat message"},
    }
    assert [line.split(": ", 2)[1:] for line in findings(sample)] == [
        ["/organisation/code", "code not a placeholder (4 characters)"],
        ["/attachments/0/uploadId", "upload not a placeholder (36 characters)"],
        ["/message/text", "text not a placeholder (22 characters)"],
    ]
    clean = {
        "organisation": {"code": "00AB"},
        "attachments": [{"uploadId": "00000000-0000-4000-8000-000000000001"}],
        "message": {"dtype": "chat.RChatStatusMessage", "text": "Voorbeeldtekst"},
    }
    assert findings(clean) == []
