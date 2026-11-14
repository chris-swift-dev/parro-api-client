"""What each confirmation dialog says. Everything shown comes through the safe text helpers."""

from typing import Any

from parro.rendering import format_date, format_timestamp, join_parts, member_role

from ..text import bullets, document, heading, meta, paragraph, subheading

ANSWER_WORDS = {"ACCEPT": "Accept", "DECLINE": "Decline", "TENTATIVE": "Tentative"}


def chat_preview(prepared: dict[str, Any]) -> str:
    names = [
        join_parts([person.get("name") or "(no name)", member_role(person)])
        for person in prepared.get("recipients", [])
    ]
    return document(
        heading(f"Message to: {prepared.get('title') or 'chat'}"),
        meta(f"{prepared.get('type') or 'chat'} chat"),
        subheading(f"Who receives it ({len(names)})"),
        bullets(names) if names else paragraph("Nobody else yet."),
        subheading("The message"),
        paragraph(prepared.get("text")),
        paragraph("Real people receive this under your name, and it cannot be taken back."),
    )


def chat_deletion_preview(prepared: dict[str, Any]) -> str:
    """Which message is about to be deleted."""
    return document(
        heading(f"Delete your message in: {prepared.get('title') or 'chat'}"),
        meta(format_timestamp(prepared.get("created_at"))),
        subheading("The message"),
        paragraph(prepared.get("text")),
        paragraph(prepared.get("attachment")),
        paragraph(
            "This cannot be undone. Everyone in the chat will see that a message was deleted."
        ),
    )


def _item_lines(prepared: dict[str, Any]) -> str:
    return meta(prepared.get("title"), format_date(prepared.get("start")))


def helper_preview(prepared: dict[str, Any]) -> str:
    wanted, taken = prepared.get("wanted"), prepared.get("signed_up", 0)
    places = f"{taken} of {wanted} places taken" if wanted is not None else f"{taken} signed up"
    slot = prepared.get("slot") or "Helpers"
    if prepared["action"] == "signup":
        return document(
            heading(f"Sign up: {slot}"),
            _item_lines(prepared),
            meta(places),
            paragraph(f"Your count: {prepared['count']}"),
            paragraph("A sign-up is a promise. The school will see your name on this slot."),
        )
    return document(
        heading(f"Withdraw: {slot}"),
        _item_lines(prepared),
        meta(places),
        paragraph("Your place becomes free. The school will see that you are no longer on it."),
    )


def rsvp_preview(prepared: dict[str, Any]) -> str:
    previous = prepared.get("previous")
    return document(
        heading(f"{ANSWER_WORDS[prepared['answer']]} this invitation"),
        _item_lines(prepared),
        paragraph(f"Your answer now: {ANSWER_WORDS[previous] if previous else 'none yet'}"),
        paragraph(f"New answer: {ANSWER_WORDS[prepared['answer']]}"),
        paragraph("The school will see your answer. You can change it later, but not remove it."),
    )


def group_read_preview(result: dict[str, Any]) -> str:
    return document(
        heading(f"Mark {result['unread']} announcements as read"),
        meta(result.get("group")),
        bullets([title or "(no title)" for title in result.get("titles", [])]),
        paragraph("The school sees what you mark, and so does the Parro app."),
    )
