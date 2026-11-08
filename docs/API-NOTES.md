# API facts the client relies on

The full description is the OpenAPI spec ([Swagger UI](https://chris-swift-dev.github.io/parro-api-client/),
[`openapi/parro.public.openapi.json`](../openapi/parro.public.openapi.json)). These are the facts
the client depends on most. Back to the [README](../README.md).

All in the spec; the important ones:

- Headers: `Authorization: Bearer`, `Accept` (and `Content-Type`)
  `application/vnd.topicus.geon+json;version=224`, `parro-app-version: web:2.27.0`,
  `parro-authorization-role: GUARDIAN:{guardianId}` (not on `/account/me`, which it is derived from).
- Collections are `Range: items=0-49` paged and answer `206` with a `Content-Range` total.
- `GET /event/{id}` needs a `dtype`: without one it answers `406 EVENT_BAD_TYPE`. For announcements
  use `event.RAnnouncementEventPrimer`: `event.RAnnouncementEvent` answers **401**, which looks like
  an expired token but is not.
- Attachments: announcements keep them in `attachments[]`, calendar items in
  `calendarItem.attachments[]`. Each carries an unsigned CloudFront URL that must be fetched
  **without** the Parro `Authorization` header and is never logged.
- Calendar items of `type: VOLUNTEER` or `SCHOOLWIDE_VOLUNTEER` ask parents to help. The slots are in
  `calendarItem.resources[]` of `GET /event/{id}` (or `GET /calendaritem/{id}`): `amount` wanted,
  `amountCommitted`, and `commitedByMe` (the API's spelling). The list only carries the type.
- Privacy: `GET /child?currentSchoolYear=true&dtype=identity.RPrivacySettingChild` gives per child
  the state of the privacy choices; `GET /child/{id}/privacy` a **signed link** to the page where
  they are set. Like the calendar subscription link, it works without a login and is never logged.
- Chats: a chat room's id is the id of its `rel: self` link. Its first link is `koppeling` (the
  membership); that id answers `403 CHAT_NOT_ACTIVE_MEMBER` on every chat call. `GET /chatroom`
  leaves archived chats out unless `archived=TRUE` (only archived) or `BOTH`; the values are
  uppercase only. `chatRoom.type` is one of `SINGLE`, `BOT`, `CALENDAR`, `GROUP`, `FAMILY`.
- Chat messages: `createdSince` / `modifiedSince` take an ISO time with `Z`. `sort=desc-stream` is
  oldest first and `asc-stream` newest first (the opposite of the names), and both add system
  messages (`chat.RChatStatusMessage`); the client sends no `sort`.
- `GET /event` ignores `read=false`; the client filters unread items itself.
- Read state: `PUT /event/{id}/read` (an announcement or calendar item),
  `PUT /event/markannouncementsasread?group={id}` (all announcements of a group) and
  `PUT /chatroom/{id}/read`, each with an empty body, answer `204`. **The school sees the result**
  (read counts on announcements, read receipts in chats), and so does the Parro app.
- Sending: `POST /chatroom/{id}/chatmessage` with
  `{"items":[{"dtype":"chat.RChatTextMessage","links":[],"deleted":false,"text":"…","allRead":false}]}`
  answers `201`, `Location` and the new message. There is no idempotency key, and the capture shows
  no way to take a message back. Not known: the longest text, the answer to empty text, and the answer
  for a chat that cannot be written to.
- Helper slots: an item's `resources[]` are its slots (`type` `VOLUNTEER` or `EQUIPMENT`).
  `POST /calendaritem/{id}/resource/{resourceId}/commitment/` (with the trailing `/`) and
  `{"items":[{"dtype":"calendar.RCalendarItemResourceCommitmentPrimer","links":[],"amount":1}]}`
  answers `201` and `Location`; `DELETE …/commitment/{commitmentId}` answers `204`. `{id}` is the
  calendar item's own id (`calendarItem.links[rel=self].id`); the event id answers `404`.
  `resources[].commitments[]` lists only your own commitment, so a parent learns how many signed up
  (`amountCommitted`), not who. `commitedByMe` (the API's spelling) is the number of places you committed, and `amount` above 1
  works (checked with 2). Not known: how a
  full slot, a past item or closed sign-ups are answered, and whether teachers get a notification.
- Invitations: `POST /calendaritem/{id}/calendaritemrsvp` with
  `{"items":[{"dtype":"calendar.RCalendarItemRSVPPrimer","links":[],"rsvp":"ACCEPT"}]}` answers `201`
  and `Location`. The same answer again changes nothing: an identical body, with the first call's
  `lastModifiedAt`. `{id}` is the calendar item's own id; the event id answers `404`. Your own answer
  is the event's `rsvp` field, absent until you answer. `GET` on that path lists everyone the
  invitation went to, parents and teachers, with names, children's names and answers (`UNKNOWN` =
  not answered), or answers `403` (5 of 20 items, reason not known). All three answers were sent in a live
  check, and each replaced the one before. Not known: the answer for a past or cancelled item, and whether teachers get a notification.
- `/conversations` and `/timeslot`, found in the web app's code, answer `404`. CORS preflights allow
  every method on every path, so they say nothing about what a path supports.
