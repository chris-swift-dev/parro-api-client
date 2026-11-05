#!/usr/bin/env python3
"""Write tests/fixtures/api/*.json: invented API responses for the tests.

Everything here is made up: a family (Sanne de Vries with Mila and Daan), their school
"Basisschool De Linde", its groups, announcements, calendar items and chats. Nothing is taken from
samples/, which holds real data and stays private. The shapes follow the spec, and
tests/test_contract.py checks every file against the committed public spec.

The files are committed. After changing this script, run it and commit the result:

    python3 tests/fixtures/make_api_fixtures.py

File names follow the samples/ convention: <operationId>[_<variant>].<status>.json
"""

import json
from pathlib import Path
from typing import Any

OUTPUT = Path(__file__).resolve().parent / "api"
API = "https://rest-v2.parro.com/rest/v2"
CDN = "https://d111111abcdef8.cloudfront.net"  # the AWS documentation's example host

GUARDIAN_ID = 2000000001
SCHOOL_ID = 400100
MILA_ID, DAAN_ID = 3000000001, 3000000002
SCHOOLWIDE_GROUP, GROUP_3, GROUP_6 = 4000000001, 4000000002, 4000000003
EVA_ID, TOM_ID, LOTTE_ID = 2100000001, 2100000002, 2100000003


# --------------------------------------------------------------------------------- builders


def geon(dtype: str, object_id: int | None = None, **fields: Any) -> dict[str, Any]:
    """A geon object: dtype, links with the self link, permissions, then the fields."""
    built: dict[str, Any] = {"dtype": dtype}
    if object_id is not None:
        resource = dtype.split(".")[-1].removeprefix("R").lower()
        built["links"] = [
            {"id": object_id, "rel": "self", "type": dtype, "href": f"{API}/{resource}/{object_id}"}
        ]
        built["permissions"] = [
            {
                "full": f"{dtype}:READ:INSTANCE({object_id})",
                "type": dtype,
                "operations": ["READ"],
                "instances": [f"INSTANCE({object_id})"],
            }
        ]
        built["additionalObjects"] = {}
    built.update(fields)
    return built


def person(dtype: str, person_id: int, first: str, last: str, role: str) -> dict[str, Any]:
    return geon(
        dtype,
        person_id,
        lastModifiedAt="2026-08-20T09:00:00.000+02:00",
        firstname=first,
        surname=last,
        role=role,
    )


def teacher(person_id: int, first: str, last: str) -> dict[str, Any]:
    return person("identity.RIdentityPrimer", person_id, first, last, "TEACHER")


def avatar(child_id: int, first: str) -> dict[str, Any]:
    return geon(
        "identity.RAvatar",
        None,
        id=child_id,
        roleId=child_id,
        firstname=first,
        surname="de Vries",
        cachedAvatarUrl="https://start.parnassys.net/bao/image?req=EXAMPLE",
    )


def group(
    group_id: int,
    name: str,
    kind: str,
    home: bool,
    counts: tuple[int, int, int],
    dtype: str = "identity.RHomeGroup",
    year: int = 2026,
    **extra: Any,
) -> dict[str, Any]:
    children, guardians, teachers = counts
    return geon(
        dtype,
        group_id,
        lastModifiedAt="2026-09-01T08:00:00.000+02:00",
        name=name,
        schooljaar=year,
        stamgroep=home,
        type=kind,
        unreadCount=extra.pop("unreadCount", 0),
        memberMuted=False,
        memberAbsenceNotificationsMuted=False,
        numberOfChildren=children,
        numberOfGuardians=guardians,
        numberOfTeachers=teachers,
        childAvatars=extra.pop("childAvatars", []),
        **extra,
    )


def entry(
    entry_id: int,
    kind: str,
    url: str,
    size: int,
    content_type: str,
    filename: str | None = None,
    image: bool = False,
) -> dict[str, Any]:
    dtype = "attachment.RAttachmentImageEntry" if image else "attachment.RAttachmentDocumentEntry"
    fields: dict[str, Any] = {
        "lastModifiedAt": "2026-10-01T10:00:00.000+02:00",
        "type": kind,
        "url": url,
        "size": size,
        "contentType": content_type,
    }
    if filename:
        fields["filename"] = filename
        fields["expiresAt"] = "2027-10-01T10:00:00.000+02:00"
    if image:
        fields.update(height=400, width=300)
    return geon(dtype, entry_id, **fields)


def document(
    attachment_id: int,
    upload: str,
    filename: str,
    content_type: str,
    size: int,
    kind: str = "PDF",
    dtype: str = "attachment.RAnnouncementAttachment",
) -> dict[str, Any]:
    key = f"{attachment_id:032x}"
    url = f"{CDN}/application/{key}/1-{key}{Path(filename).suffix}"
    return geon(
        dtype,
        attachment_id,
        lastModifiedAt="2026-10-01T10:00:00.000+02:00",
        attachmentType=kind,
        uploadId=upload,
        entries=[entry(attachment_id + 1, "SOURCE", url, size, content_type, filename)],
        index=0,
    )


def photo(
    attachment_id: int,
    filename: str,
    index: int = 0,
    dtype: str = "attachment.RAnnouncementAttachment",
) -> dict[str, Any]:
    key = f"{attachment_id:032x}"
    # A photo's SOURCE entry is a *document* entry (spec). Only calendar-item photos get the
    # THUMBNAIL image entry: the spec has seen image entries there, not on announcements.
    entries = [
        entry(
            attachment_id + 1,
            "SOURCE",
            f"{CDN}/image/{key}/1-{key}.jpeg",
            1_333_337,
            "image/jpeg",
            filename,
        ),
    ]
    if dtype == "attachment.RCalendarItemAttachment":
        entries.append(
            entry(
                attachment_id + 2,
                "THUMBNAIL",
                f"{CDN}/thumbnail/{key}/1-{key}.jpeg",
                96_614,
                "image/jpg",
                image=True,
            )
        )
    return geon(
        dtype,
        attachment_id,
        lastModifiedAt="2026-10-31T18:00:00.000+01:00",
        attachmentType="IMAGE",
        uploadId=f"00000000-0000-4000-8000-{attachment_id:012d}",
        entries=entries,
        index=index,
    )


def read_count(read: int, total: int, liked: int | None = None) -> dict[str, Any]:
    counts: dict[str, Any] = {"read": read, "total": total}
    if liked is not None:
        counts = {"liked": liked, **counts}
    return geon("event.REventReadCount", None, **counts)


def announcement(
    event_id: int,
    title: str,
    when: str,
    author: dict[str, Any],
    contents: str,
    read: bool,
    attachments: list[dict[str, Any]] | None = None,
    pinned: bool = False,
    liked: bool = False,
) -> dict[str, Any]:
    return geon(
        "event.RAnnouncementEventPrimer",
        event_id,
        lastModifiedAt=when,
        createdAt=when,
        sortDate=when,
        deleted=False,
        read=read,
        archived=False,
        cancelled=False,
        liked=liked,
        realisationReason="RECIPIENT",
        readCount=read_count(31, 45, liked=4),
        title=title,
        contents=contents,
        likeable=True,
        attachments=attachments or [],
        owner=author,
        lastEditedBy=author,
        draft=False,
        pinned=pinned,
    )


def calendar_item(
    event_id: int,
    title: str,
    start: str,
    end: str,
    kind: str,
    rsvp: bool,
    groups: list[dict[str, Any]],
    days: list[str],
    read: bool = True,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A calendar event; `detail` turns the list primer into the full RCalendarItemEvent."""
    item_fields: dict[str, Any] = {
        "lastModifiedAt": "2026-10-28T13:00:00.000+01:00",
        "type": kind,
        "title": title,
        "rsvpRequired": rsvp,
        "startDate": start,
        "endDate": end,
        "dayDates": days,
        "imported": False,
        "status": "OPEN",
    }
    if detail is not None:
        item_fields.update(detail)
    item_dtype = "calendar.RCalendarItem" if detail is not None else "calendar.RCalendarItemPrimer"
    event_dtype = (
        "event.RCalendarItemEvent" if detail is not None else "event.RCalendarItemEventPrimer"
    )
    return geon(
        event_dtype,
        event_id,
        lastModifiedAt="2026-10-28T13:00:00.000+01:00",
        createdAt="2026-10-20T09:00:00.000+02:00",
        sortDate=start,
        deleted=False,
        read=read,
        archived=False,
        cancelled=False,
        liked=False,
        readCount=read_count(12, 45),
        children=[geon("event.RCalendarItemEventChild", None, child=avatar(DAAN_ID, "Daan"))],
        contributed=False,
        dayNumber=1,
        groups=groups,
        numberOfDays=len(days),
        calendarItem=geon(item_dtype, event_id + 50, **item_fields),
    )


def chat_message(message_id: int, author: dict[str, Any], when: str, text: str) -> dict[str, Any]:
    return geon(
        "chat.RChatTextMessage",
        message_id,
        lastModifiedAt=when,
        identity=author,
        createdAt=when,
        deleted=False,
        text=text,
        allRead=False,
    )


# ---------------------------------------------------------------------------- the world

EVA = teacher(EVA_ID, "Eva", "Jansen")
TOM = teacher(TOM_ID, "Tom", "Smit")
LOTTE = teacher(LOTTE_ID, "Lotte", "Bakker")
SANNE = person("identity.RIdentityPrimer", GUARDIAN_ID, "Sanne", "de Vries", "GUARDIAN")
SCHOOL = geon(
    "auth.ROrganisationPrimer",
    SCHOOL_ID,
    lastModifiedAt="2026-11-01T04:00:00.000+01:00",
    code="99XX",
    name="Basisschool De Linde",
    active=True,
    system=False,
    pricingPlan="STANDARD",
    pricingPlanStartDate="2021-08-01",
    city="Voorbeeldstad",
)
GUARDIAN = geon(
    "identity.RGuardianPrimer",
    GUARDIAN_ID,
    lastModifiedAt="2026-01-19T21:09:45.779+01:00",
    firstname="Sanne",
    surname="de Vries",
    role="GUARDIAN",
    accountActive=True,
    numberOfExternalIdentities=1,
    numberOfActiveExternalIdentities=1,
    childNames=["Mila", "Daan"],
)

CURRENT_GROUPS = [
    group(
        SCHOOLWIDE_GROUP,
        "Basisschool De Linde",
        "SCHOOLWIDE",
        False,
        (0, 412, 38),
        lastAnnouncement=geon(
            "event.RAnnouncementEventPreview",
            None,
            title="Studiedag vrijdag 13 november",
            date="2026-11-02T12:28:51.570+01:00",
        ),
    ),
    group(
        GROUP_3,
        "Groep 3 - juf Eva",
        "NORMAL",
        True,
        (27, 45, 2),
        unreadCount=2,
        childAvatars=[avatar(DAAN_ID, "Daan")],
        lastAnnouncement=geon(
            "event.RAnnouncementEventPreview",
            None,
            title="Gym op dinsdag",
            date="2026-10-29T08:10:00.000+01:00",
        ),
    ),
    group(
        GROUP_6,
        "Groep 6 - meester Tom",
        "NORMAL",
        True,
        (29, 50, 2),
        childAvatars=[avatar(MILA_ID, "Mila")],
    ),
]
PREVIOUS_GROUPS = [
    group(
        4000000101,
        "Basisschool De Linde",
        "SCHOOLWIDE",
        False,
        (0, 398, 36),
        dtype="identity.RGroupPrimer",
        year=2025,
    ),
    group(
        4000000102,
        "Groep 5 - juf Iris",
        "NORMAL",
        True,
        (28, 47, 2),
        dtype="identity.RGroupPrimer",
        year=2025,
    ),
]


def group_primer(group_id: int) -> dict[str, Any]:
    source = next(g for g in CURRENT_GROUPS if g["links"][0]["id"] == group_id)
    counts = (source["numberOfChildren"], source["numberOfGuardians"], source["numberOfTeachers"])
    return group(
        group_id,
        source["name"],
        source["type"],
        source["stamgroep"],
        counts,
        dtype="identity.RGroupPrimer",
    )


NEWSLETTER = announcement(
    5000000101,
    "Nieuwsbrief nr. 3",
    "2026-10-22T11:25:58.012+02:00",
    LOTTE,
    "Beste ouders en verzorgers,\n\nIn de bijlage vindt u nieuwsbrief nr. 3 met de agenda tot de "
    "kerstvakantie.\n\nMet vriendelijke groet,\nLotte Bakker\nadministratie\n",
    read=True,
    attachments=[
        document(
            6000000101,
            "11111111-2222-4333-8444-555555555555",
            "Nieuwsbrief-3.pdf",
            "application/pdf",
            1_500_108,
        ),
    ],
)
STUDY_DAY = announcement(
    5000000102,
    "Studiedag vrijdag 13 november",
    "2026-11-02T12:28:51.570+01:00",
    LOTTE,
    "Beste ouders,\n\nOp vrijdag 13 november hebben alle leerkrachten een studiedag. De kinderen "
    "zijn die dag vrij.\nDe BSO is gewoon open.\n\nMet vriendelijke groet,\nLotte Bakker\n",
    read=False,
    pinned=True,
)
AUTUMN_WALK = announcement(
    5000000103,
    "Foto's herfstwandeling",
    "2026-10-31T18:39:56.227+01:00",
    LOTTE,
    "Wat een mooie herfstwandeling hebben we gemaakt! Hierbij een paar foto's.",
    read=True,
    liked=True,
    attachments=[photo(6000000201 + 10 * i, f"herfst-{i + 1}.jpg", i) for i in range(3)],
)
GYM = announcement(
    5000000201,
    "Gym op dinsdag",
    "2026-10-29T08:10:00.000+01:00",
    EVA,
    "Hallo allemaal,\n\nVanaf volgende week hebben we gym op dinsdag in plaats van donderdag.\n"
    "Willen jullie de gymtas op dinsdag meegeven?\n\nGroetjes,\njuf Eva\n",
    read=False,
)
MUSEUM_HELP = announcement(
    5000000301,
    "Excursie Natuurmuseum: hulp gezocht",
    "2026-10-27T15:02:00.000+01:00",
    TOM,
    "Beste ouders,\n\nOp 12 november gaan we naar het Natuurmuseum. We zoeken nog twee ouders die "
    "willen rijden. Wilt u het toestemmingsformulier invullen?\n\nGroet,\nmeester Tom\n",
    read=True,
    attachments=[
        document(
            6000000301,
            "66666666-7777-4888-8999-000000000000",
            "Toestemmingsformulier.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            24_576,
            kind="DOCUMENT",
        ),
    ],
)
# Studiedag is sent to the whole school *and* to group 3: it comes back in both feeds.
ANNOUNCEMENTS_BY_GROUP = {
    SCHOOLWIDE_GROUP: [STUDY_DAY, AUTUMN_WALK, NEWSLETTER],
    GROUP_3: [STUDY_DAY, GYM],
    GROUP_6: [MUSEUM_HELP],
}

ST_MARTIN = calendar_item(
    7000000101,
    "Sint-Maartenviering",
    "2026-11-11T17:30:00+01:00",
    "2026-11-11T19:00:00+01:00",
    "SCHOOLWIDE_ACTIVITY",
    False,
    [group_primer(SCHOOLWIDE_GROUP)],
    ["2026-11-11T00:00:00+01:00"],
)
CHRISTMAS = calendar_item(
    7000000102,
    "Kerstvakantie",
    "2026-12-21T00:00:00+01:00",
    "2027-01-01T00:00:00+01:00",
    "HOLIDAY",
    False,
    [group_primer(SCHOOLWIDE_GROUP)],
    [f"2026-12-{day}T00:00:00+01:00" for day in (21, 22, 23, 24, 25)],
)
PARENT_EVENINGS = calendar_item(
    7000000201,
    "Oudergesprekken groep 3",
    "2026-11-17T15:00:00+01:00",
    "2026-11-17T19:00:00+01:00",
    "ACTIVITY",
    True,
    [group_primer(GROUP_3)],
    ["2026-11-17T00:00:00+01:00"],
    read=False,
)
MUSEUM_TRIP = calendar_item(
    7000000301,
    "Excursie Natuurmuseum",
    "2026-11-12T00:00:00+01:00",
    "2026-11-12T00:00:00+01:00",
    "ACTIVITY",
    True,
    [group_primer(GROUP_6)],
    ["2026-11-12T00:00:00+01:00"],
)
# Past items (before 5 Nov 2026, the date the tests treat as today).
SCHOOL_START = calendar_item(
    7000000103,
    "Eerste schooldag",
    "2026-08-31T00:00:00+02:00",
    "2026-08-31T00:00:00+02:00",
    "SCHOOLWIDE_ACTIVITY",
    False,
    [group_primer(SCHOOLWIDE_GROUP)],
    ["2026-08-31T00:00:00+02:00"],
)
LIBRARY_VISIT = calendar_item(
    7000000302,
    "Bezoek bibliotheek",
    "2026-10-07T08:30:00+02:00",
    "2026-10-07T10:30:00+02:00",
    "ACTIVITY",
    False,
    [group_primer(GROUP_6)],
    ["2026-10-07T00:00:00+02:00"],
)
# Far-future items: the real API lists these *first* (see below).
STUDY_DAY_2027 = calendar_item(
    7000000104,
    "Studiedag",
    "2027-02-15T00:00:00+01:00",
    "2027-02-15T00:00:00+01:00",
    "SCHOOLWIDE_ACTIVITY",
    False,
    [group_primer(SCHOOLWIDE_GROUP)],
    ["2027-02-15T00:00:00+01:00"],
)
SUMMER_2027 = calendar_item(
    7000000105,
    "Zomervakantie",
    "2027-07-17T00:00:00+02:00",
    "2027-08-29T00:00:00+02:00",
    "HOLIDAY",
    False,
    [group_primer(SCHOOLWIDE_GROUP)],
    [f"2027-07-{day}T00:00:00+02:00" for day in (19, 20, 21, 22, 23)],
)


def furthest_future_first(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The real API's order for calendar lists: newest first, starting with the furthest future
    (seen live 2026-11-05: the whole-school group's first 50 of 100 items ran May-Aug 2027)."""
    return sorted(items, key=lambda item: item["sortDate"], reverse=True)


CALENDAR_BY_GROUP = {
    SCHOOLWIDE_GROUP: furthest_future_first(
        [SCHOOL_START, ST_MARTIN, CHRISTMAS, STUDY_DAY_2027, SUMMER_2027]
    ),
    GROUP_3: furthest_future_first([PARENT_EVENINGS]),
    GROUP_6: furthest_future_first([LIBRARY_VISIT, MUSEUM_TRIP]),
}

TEACHER_TOM = geon(
    "identity.RTeacherPrimer",
    TOM_ID,
    lastModifiedAt="2021-10-28T10:18:43.076+02:00",
    firstname="Tom",
    surname="Smit",
    role="TEACHER",
    active=True,
    accountActive=True,
)
MUSEUM_TRIP_DETAIL = calendar_item(
    7000000301,
    "Excursie Natuurmuseum",
    "2026-11-12T00:00:00+01:00",
    "2026-11-12T00:00:00+01:00",
    "ACTIVITY",
    True,
    [group_primer(GROUP_6)],
    ["2026-11-12T00:00:00+01:00"],
    detail={
        "description": "We vertrekken om 8.45 uur met de auto. Neem een lunchpakket mee.",
        "location": "Natuurmuseum Voorbeeldstad",
        "pending": False,
        "owner": TEACHER_TOM,
        "lastEditedBy": TEACHER_TOM,
        "numberOfResources": 0,
        "numberOfTimeslots": 0,
        "numberOfOpenTimeslots": 0,
        "numberOfUncommittedChildren": 0,
        "timeslotInterval": 0,
        "slack": 0,
        "reminderInterval": 0,
        "totalRespondents": 0,
        "resources": [],
        "respondents": [],
        "attachments": [
            photo(6000000401, "Route.jpg", dtype="attachment.RCalendarItemAttachment"),
        ],
    },
)
ST_MARTIN_DETAIL = calendar_item(
    7000000101,
    "Sint-Maartenviering",
    "2026-11-11T17:30:00+01:00",
    "2026-11-11T19:00:00+01:00",
    "SCHOOLWIDE_ACTIVITY",
    False,
    [group_primer(SCHOOLWIDE_GROUP)],
    ["2026-11-11T00:00:00+01:00"],
    detail={
        "description": "Lampionnenoptocht door de wijk. Verzamelen om 17.30 uur op het plein.",
        "location": "Schoolplein",
        "pending": False,
        "owner": TEACHER_TOM,
        "lastEditedBy": TEACHER_TOM,
        "resources": [],
        "respondents": [],
        "attachments": [],
    },
)

PARENT_EVENINGS_DETAIL = calendar_item(
    7000000201,
    "Oudergesprekken groep 3",
    "2026-11-17T15:00:00+01:00",
    "2026-11-17T19:00:00+01:00",
    "ACTIVITY",
    True,
    [group_primer(GROUP_3)],
    ["2026-11-17T00:00:00+01:00"],
    read=False,
    detail={
        "description": "Kies een tijd van tien minuten. Laat het weten als geen enkele tijd past.",
        "location": "Lokaal groep 3",
        "pending": False,
        "resources": [],
        "respondents": [],
        "attachments": [],
    },
)
# A holiday has no location, description or attachments: the details stay empty.
CHRISTMAS_DETAIL = calendar_item(
    7000000102,
    "Kerstvakantie",
    "2026-12-21T00:00:00+01:00",
    "2027-01-01T00:00:00+01:00",
    "HOLIDAY",
    False,
    [group_primer(SCHOOLWIDE_GROUP)],
    [f"2026-12-{day}T00:00:00+01:00" for day in (21, 22, 23, 24, 25)],
    detail={"pending": False, "resources": [], "respondents": [], "attachments": []},
)

CHATROOMS = [
    geon(
        "chat.RChatRoomPrimer",
        8000000001,
        lastModifiedAt="2026-11-03T16:28:35.509+01:00",
        sortDate="2026-11-03T16:28:35.509+01:00",
        muted=False,
        todo=False,
        unreadCount=1,
        admin=False,
        active=True,
        archived=False,
        type="CALENDAR",
        title="Rijden naar het Natuurmuseum",
        numberOfMembers=4,
        hasGuardians=True,
        memberNames=["Tom", "Sanne", "Joris", "Fatima"],
        childNames=[],
        repliesEnabled=True,
        dnd=False,
        lastMessage=chat_message(
            8100000003,
            TOM,
            "2026-11-03T16:28:35.509+01:00",
            "Top, dan zijn we compleet. Tot de 12e!",
        ),
    ),
    geon(
        "chat.RChatRoomPrimer",
        8000000002,
        lastModifiedAt="2026-06-30T12:00:00.000+02:00",
        sortDate="2026-06-30T12:00:00.000+02:00",
        muted=False,
        todo=False,
        unreadCount=0,
        admin=False,
        active=False,
        archived=True,
        type="CALENDAR",
        title="Hulp bij het zomerfeest",
        numberOfMembers=6,
        hasGuardians=True,
        memberNames=["Iris", "Sanne", "Joris", "Fatima", "Kees", "Noor"],
        childNames=[],
        repliesEnabled=True,
        dnd=False,
        lastMessage=chat_message(
            8100000101, SANNE, "2026-06-30T12:00:00.000+02:00", "Ik neem de limonade mee."
        ),
    ),
]
# Delivered newest first on purpose: the conversation view must sort them itself.
CHAT_MESSAGES = [
    chat_message(
        8100000003, TOM, "2026-11-03T16:28:35.509+01:00", "Top, dan zijn we compleet. Tot de 12e!"
    ),
    chat_message(
        8100000002,
        SANNE,
        "2026-11-02T20:15:00.000+01:00",
        "Ik kan rijden, ik heb plek voor drie kinderen.",
    ),
    chat_message(
        8100000001,
        TOM,
        "2026-11-02T19:02:00.000+01:00",
        "Dag allemaal, wie kan er op 12 november rijden?",
    ),
]

SYSTEM_NEWS = [
    geon(
        "systemnews.RSystemNewsEvent",
        9000000001,
        lastModifiedAt="2026-08-11T11:01:46.526+02:00",
        createdAt="2026-08-11T10:00:45.807+02:00",
        scheduleDate="2026-08-11T00:00:00+02:00",
        title="Nieuw in de app: donkere modus",
        contents="<p>Je kunt Parro nu ook <i>donker</i> gebruiken.</p><br/><p>Zet het aan onder "
        "<i>Instellingen</i>.</p>",
        pricingPlanAudience="STANDARD",
        audience="GUARDIANS",
        attachments=[],
    ),
    geon(
        "systemnews.RSystemNewsEvent",
        9000000002,
        lastModifiedAt="2026-07-16T14:59:24.376+02:00",
        createdAt="2026-07-16T14:23:11.652+02:00",
        scheduleDate="2026-07-16T00:00:00+02:00",
        title="Fijne zomervakantie",
        contents="<p>Het team wenst iedereen een fijne zomer!</p>",
        pricingPlanAudience="STANDARD",
        audience="EVERYONE",
        attachments=[],
    ),
]


def account() -> dict[str, Any]:
    identity = geon(
        "identity.RIdentity",
        GUARDIAN_ID,
        lastModifiedAt="2026-01-19T21:09:45.779+01:00",
        firstname="Sanne",
        surname="de Vries",
        role="GUARDIAN",
        email="sanne@example.com",
        guardians=[GUARDIAN],
        children=[],
        teachers=[],
    )
    return geon(
        "auth.RAccount",
        GUARDIAN_ID,
        lastModifiedAt="2026-08-05T10:55:21.062+02:00",
        username="20000000001",
        externalUsername="svdvries",
        email="sanne@example.com",
        organisation=SCHOOL,
        lastAccountSynchronize="2026-11-01T20:34:16.631+01:00",
        accountType="GUARDIAN",
        identity=identity,
        avgId="00000000-0000-4000-8000-000000000001",
        capabilities=[],
        accountPermissions=[],
        portalAccess=False,
        state="ACTIVE",
        numberOfExternalIdentities=1,
        numberOfActiveExternalIdentities=1,
    )


def children() -> list[dict[str, Any]]:
    return [
        geon(
            "identity.RChildPrimer",
            child_id,
            lastModifiedAt="2026-10-30T09:58:21.777+01:00",
            firstname=first,
            surname="de Vries",
            cachedAvatarUrl="https://start.parnassys.net/bao/image?req=EXAMPLE",
            role="CHILD",
            archived=False,
            enrolledSince=since,
            numberOfGuardians=2,
            guardianNames=[],
        )
        for child_id, first, since in (
            (MILA_ID, "Mila", "2022-08-29"),
            (DAAN_ID, "Daan", "2024-08-26"),
        )
    ]


def details_without_extras(primer: dict[str, Any]) -> dict[str, Any]:
    """The full RCalendarItemEvent of a list item that has no location, description or files."""
    item = primer["calendarItem"]
    return calendar_item(
        primer["links"][0]["id"],
        item["title"],
        item["startDate"],
        item["endDate"],
        item["type"],
        item["rsvpRequired"],
        primer["groups"],
        item["dayDates"],
        read=primer["read"],
        detail={"pending": False, "resources": [], "respondents": [], "attachments": []},
    )


def files() -> dict[str, Any]:
    """File name → content."""
    written: dict[str, Any] = {
        "getAccountMe.200.json": account(),
        "getAccountSettings.200.json": geon(
            "auth.RAccountSettings",
            None,
            id=GUARDIAN_ID,
            email="sanne@example.com",
            username="20000000001",
            digestPreference="DAILY",
            translationPreference=geon(
                "identity.RTranslationPreferenceSettings",
                None,
                enabled="DISABLED",
                preferredLanguage="nl",
            ),
            digestHour=7,
            active=True,
            chatPreference=geon("identity.RChatPreference", None, sendMessagesWithShiftEnter=False),
        ),
        "getOrganisation.200.json": SCHOOL,
        "listChildren.200.json": {"items": children()},
        "getUnreadCounts.200.json": {
            "items": [
                geon(
                    "identity.RUnreadCount",
                    None,
                    numberOfUnreadAnnouncements=2,
                    numberOfUnreadCalendarItems=1,
                    numberOfUnreadSystemNewsItems=0,
                    numberOfUnreadChatRooms=1,
                    numberOfUnreadPortalNotifications=0,
                    guardian=GUARDIAN,
                )
            ]
        },
        "listGroups.200.json": {"items": CURRENT_GROUPS},
        "listGroups_previous.200.json": {"items": PREVIOUS_GROUPS},
        "getEvent_announcement.200.json": NEWSLETTER,
        "getEvent_calendar-7000000301.200.json": MUSEUM_TRIP_DETAIL,
        "getEvent_calendar-7000000101.200.json": ST_MARTIN_DETAIL,
        "getEvent_calendar-7000000102.200.json": CHRISTMAS_DETAIL,
        "getEvent_calendar-7000000201.200.json": PARENT_EVENINGS_DETAIL,
        **{
            f"getEvent_calendar-{event['links'][0]['id']}.200.json": details_without_extras(event)
            for event in (SCHOOL_START, LIBRARY_VISIT, STUDY_DAY_2027, SUMMER_2027)
        },
        "getEvent.406.json": {
            "code": 406,
            "reason": "Not Acceptable",
            "exception": "nl.topicus.cobra.restcontract.exception.RestWebApplicationException",
            "message": "HTTP 406 Not Acceptable",
            "applicationError": "EVENT_BAD_TYPE",
            "errorDetails": ["nl.topicus.geon.restcontract.model.event.RAbstractEvent"],
        },
        "listSystemNews.200.json": {"items": SYSTEM_NEWS},
        "getAbsenceSetting.200.json": {"items": []},
        "listChatrooms.200.json": {"items": CHATROOMS},
        "listChatMessages.200.json": {"items": CHAT_MESSAGES},
        # Shape of GET /calendar/sync (captured 2026-11-05); id, token and noCache are invented.
        "getCalendarSync.200.json": {
            "dtype": "Strings",
            "strings": [
                f"https://calendar.parro.com/ical/{GUARDIAN_ID}/"
                "00000000-0000-4000-8000-0000000000aa?noCache=00000000-0000-4000-8000-0000000000bb"
            ],
        },
        "token.200.json": {
            "access_token": "EXAMPLE-ACCESS-TOKEN",
            "refresh_token": "EXAMPLE-REFRESH-TOKEN",
            "scope": "openid offline_access",
            "id_token": "EXAMPLE-ID-TOKEN",
            "token_type": "Bearer",
            "expires_in": 3599,
        },
    }
    for group_id, events in ANNOUNCEMENTS_BY_GROUP.items():
        written[f"listEvents_announcements-{group_id}.200.json"] = {"items": events}
    for group_id, events in CALENDAR_BY_GROUP.items():
        written[f"listEvents_calendar-{group_id}.200.json"] = {"items": events}
    return written


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    for old in OUTPUT.glob("*.json"):
        old.unlink()
    for name, content in sorted(files().items()):
        text = json.dumps(content, ensure_ascii=False, indent=2) + "\n"
        (OUTPUT / name).write_text(text, encoding="utf-8")
    print(f"wrote {len(files())} files to {OUTPUT}")


if __name__ == "__main__":
    main()
