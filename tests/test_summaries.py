"""Summaries built from every fixture in tests/fixtures/api/, and fix 5 (unread before limit)."""

import copy
import json

from parro import summaries
from parro.api_client import ApiResponse, FeedEvent
from parro.authenticator import LoginStatus
from tests.conftest import load_sample


def collection(sample_name: str) -> ApiResponse:
    payload = load_sample(sample_name)
    count = len(payload["items"])
    return ApiResponse(payload, f"items 0-{max(count - 1, 0)}/{count}")


def assert_no_geon_bookkeeping(data) -> None:
    text = json.dumps(data)
    for key in ('"links"', '"permissions"', '"dtype"', '"additionalObjects"'):
        assert key not in text


def test_account_summary():
    summary = summaries.summarize_account(load_sample("getAccountMe.200.json"), "GUARDIAN:1")
    assert summary["name"] == "Sanne de Vries"
    assert summary["organisation"]["name"] == "Basisschool De Linde"
    assert summary["organisation"]["id"] == 400100
    assert summary["children"] is None, "a guardian's identity.children is empty"
    assert_no_geon_bookkeeping(summary)


def test_children_summary():
    summary = summaries.summarize_children(collection("listChildren.200.json"))
    assert summary["total"] == 2
    assert summary["children"][0] == {
        "id": 3000000001,
        "name": "Mila de Vries",
        "archived": False,
        "enrolledSince": "2022-08-29",
        "numberOfGuardians": 2,
    }


def test_group_summaries_for_both_school_years():
    current = summaries.summarize_groups(collection("listGroups.200.json"), "current")
    assert current["total"] == 3
    home_group = current["groups"][1]
    assert home_group["isHomeGroup"] is True and home_group["children"] == ["Daan"]
    assert home_group["counts"] == {"children": 27, "guardians": 45, "teachers": 2}
    previous = summaries.summarize_groups(collection("listGroups_previous.200.json"), "previous")
    assert [g["schoolyear"] for g in previous["groups"]] == [2025, 2025]


def test_unread_counts_summary():
    (summary,) = summaries.summarize_unread_counts(collection("getUnreadCounts.200.json"))
    assert summary["for"] == "Sanne de Vries"
    assert summary["announcements"] == 2 and summary["children"] == ["Mila", "Daan"]


def test_announcement_summary_lists_the_pdf():
    events = load_sample("listEvents_announcements-4000000001.200.json")["items"]
    with_pdf = summaries.summarize_announcement(events[2], "Basisschool De Linde")
    assert with_pdf["from"] == "Basisschool De Linde"
    (attachment,) = with_pdf["attachments"]
    assert attachment["kind"] == "PDF" and attachment["readable"] is True
    assert attachment["filename"] == "Nieuwsbrief-3.pdf"
    assert "hint" in with_pdf
    without = summaries.summarize_announcement(events[0])
    assert "attachments" not in without and "from" not in without


def test_announcement_detail_has_the_author():
    detail = summaries.summarize_announcement_detail(load_sample("getEvent_announcement.200.json"))
    assert detail["author"] == "Lotte Bakker"
    assert detail["attachments"][0]["contentType"] == "application/pdf"


def make_feed(read_flags: list[bool]) -> list[FeedEvent]:
    template = load_sample("listEvents_announcements-4000000002.200.json")["items"][1]
    feed = []
    for position, already_read in enumerate(read_flags):
        event = copy.deepcopy(template)
        event["read"] = already_read
        event["sortDate"] = f"2026-11-{30 - position:02d}T12:00:00+01:00"
        event["links"][0]["id"] = position
        feed.append(FeedEvent(event, None))
    return feed


def test_unread_only_filters_before_the_limit():  # fix 5
    feed = make_feed([True, True, True, False, False])
    result = summaries.summarize_announcement_feed(feed, limit=2, unread_only=True)
    assert result["count"] == 2
    assert [a["id"] for a in result["announcements"]] == [3, 4]


def test_feed_is_newest_first_and_limited():
    feed = list(reversed(make_feed([True, True, True])))
    result = summaries.summarize_announcement_feed(feed, limit=2)
    assert [a["id"] for a in result["announcements"]] == [0, 1]


def test_calendar_summary_counts_what_it_shows_and_lists_each_item_once():
    schoolwide = load_sample("listEvents_calendar-4000000001.200.json")["items"]
    group_6 = load_sample("listEvents_calendar-4000000003.200.json")["items"]
    st_martin = next(e for e in schoolwide if e["links"][0]["id"] == 7000000101)
    museum_trip = next(e for e in group_6 if e["links"][0]["id"] == 7000000301)
    feed = [
        FeedEvent(museum_trip, "B"),
        FeedEvent(st_martin, "A"),
        FeedEvent(st_martin, "C"),  # the same item, found through another group
    ]
    result = summaries.summarize_calendar_feed(feed, limit=1)
    assert result["count"] == 1 and len(result["items"]) == 1
    assert result["items"][0]["id"] == 7000000101, "soonest first"
    assert result["items"][0]["group"] == "A", "the first group it was found through"
    everything = summaries.summarize_calendar_feed(feed, limit=10)
    assert everything["count"] == 2, "the duplicate is merged"
    assert everything["items"][1]["calendarItem"]["type"] == "VOLUNTEER"
    assert_no_geon_bookkeeping(result)


def test_calendar_details_summary():
    details = summaries.summarize_calendar_details(
        load_sample("getEvent_calendar-7000000301.200.json")
    )
    assert details["location"] == "Natuurmuseum Voorbeeldstad"
    assert details["description"].startswith("We vertrekken")
    assert details["attachments"][0]["filename"] == "Route.jpg"


def test_chat_summaries():
    rooms = summaries.summarize_chatrooms(collection("listChatrooms.200.json"))
    assert rooms["total"] == 2 and rooms["chatrooms"][0]["id"] == 8000000001
    messages = summaries.summarize_chat_messages(collection("listChatMessages.200.json"))
    assert messages["messages"][0]["text"].startswith("Top")
    assert_no_geon_bookkeeping([rooms, messages])


def test_generic_summary_for_every_remaining_sample():
    for name in (
        "getAccountSettings.200.json",
        "getOrganisation.200.json",
        "getAbsenceSetting.200.json",
        "listSystemNews.200.json",
        "getEvent_calendar-7000000101.200.json",
        "getEvent_calendar-7000000301.200.json",
    ):
        summary = summaries.summarize_any_response(ApiResponse(load_sample(name), None))
        assert_no_geon_bookkeeping(summary)
        raw = summaries.summarize_any_response(ApiResponse(load_sample(name), None), raw=True)
        assert raw["body"] == load_sample(name)


def test_login_status_summary_mentions_the_latch_without_secrets():
    status = LoginStatus(
        token_file="/tmp/t.json",
        has_access_token=True,
        has_refresh_token=True,
        access_token_expires_in_seconds=-5,
        credentials_configured=True,
        login_method="login-form",
        login_halted_reason="wrong password",
    )
    summary = summaries.summarize_login_status(status, "openid offline_access", "https://x")
    assert summary["automatic_login_halted"] == "wrong password"
    assert "parro_login" in summary["how_to_resume"]
    assert summary["access_token_valid"] is False
