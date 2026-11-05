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
