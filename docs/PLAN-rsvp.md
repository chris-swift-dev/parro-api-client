# Plan 10: answering a calendar item's invitation (RSVP)

*Status: phase 1 done (2026-11-09); decisions taken in §7.*

**Goal:** the spec describes answering a calendar item with `ACCEPT`, `DECLINE` or `TENTATIVE`, and the
client can do it. Source: `findings/accept-calendar-item.har` (git-ignored).

---

## 1. What the capture shows

| | |
| --- | --- |
| Call | `POST /calendaritem/{id}/calendaritemrsvp` (no trailing `/`, no query parameters) |
| Headers | the usual ones: bearer token, role, `parro-app-version`, geon `Accept` and `Content-Type` |
| Body | `{"items":[{"dtype":"calendar.RCalendarItemRSVPPrimer","links":[],"rsvp":"ACCEPT"}]}` |
| Answer | `201`, `Location: …/calendaritemrsvp/{rsvpId}`, body `{"items":[<rsvp: id, lastModifiedAt, guardian, rsvp>]}` |

The capture is clean: placeholder token, role, ids and names, no cookies. It holds the same `ACCEPT`
twice, about nine seconds apart.

**Answering twice changes nothing.** Both calls answer `201`, and the two bodies are identical. That
includes `lastModifiedAt`, which equals the server time of the *first* call, so the second call did
not touch the stored answer. It fits what you saw in the web app: a second tap does not undo the first.

**The answer belongs to the parent.** The response names the `guardian` (with `childNames`), not a
child. Whether two parents of one child answer separately is not known. The response holds personal
data, so the sample needs the privacy scan to cover those fields.

**What it does not show:**

- **Sending `DECLINE` or `TENTATIVE`.** Both exist as stored answers (see the probe results), but
  neither was captured being sent.
- **Replacing an answer.** That `DECLINE` or `TENTATIVE` overwrites an earlier `ACCEPT` is the likely
  behaviour, but it is not captured. Phase 6 checks it.
- **Going back to "no answer".** There is no `DELETE` in the capture, so treat a first answer as
  something you can change but not take away.
- How the API answers for a past or cancelled item, or an item that asks for no RSVP.
- Whether teachers get a notification.

### Probe results (phase 1, 2026-11-09, GET only, 20 items with an RSVP: 5 upcoming, 15 past)

| Question | Answer |
| --- | --- |
| How to read your own answer | **The event's own `rsvp` field**, on `GET /event` and `GET /event/{id}`: `ACCEPT` on the 3 items you answered, absent on the other 17. No extra request is needed |
| `{id}` in the path | The calendar item's own id. It differs from the event id on all 20 items; with the event id the `GET` answers `404` |
| `GET /calendaritem/{id}/calendaritemrsvp` | Answers on 15 of the 20 items and `403` on 5. **It lists every parent the invitation went to, with name, children's names and answer** (`identity.RRespondent`), 829 entries in total over those 15 lists. **The client must not use or show it** |
| Possible answers | `ACCEPT`, `DECLINE`, `TENTATIVE` and `UNKNOWN` all occur in those lists. `UNKNOWN` means not answered yet. Whether sending `UNKNOWN` clears an answer is not known, and is not tried: the app offers no such button |
| Deadline | No deadline field on the item, and no `RSVP` entry in its `permissions` |
| Status | All 20 are `OPEN`, none cancelled, so the answer for a closed or cancelled item stays unknown |
| Places to try it | 5 upcoming items ask for an RSVP; 1 of them is already answered |

## 2. Challenging it: a fourth kind of write

| | Marking as read | Sending a message | Helper commitment | RSVP |
| --- | --- | --- | --- | --- |
| Who notices | the school (a count) | real people, directly | the teacher sees your name | the school sees your answer (probably with your name) |
| Can be undone | no | no (as far as known) | yes: withdraw | **partly**: you can change it, not remove it |
| Free text | no | yes | no | no |
| Repeat | nothing happens | another message | refused | nothing happens (captured) |

- **An answer is a statement to the school.** "We are coming" may decide how many places or how much
  food is arranged.
- **A change overwrites the old answer.** A wrong `DECLINE` replaces an `ACCEPT`, and nothing shows
  that it ever said anything else.
- **An assistant could be steered,** as with sign-ups: a newsletter that says "please accept this".
  There is no free text, so nothing can leak through it, but the answer is given in your name.

**Recommendation: do it, as the fourth and narrow write.** The promise becomes: *it reads; it can
mark items as read, send a text message to a chat you are in, sign you up or withdraw you as a
helper, and answer an invitation, and only when you ask.*

## 3. The design

1. **One fixed call, nothing generic.** `ParroClient.answer_rsvp(item, answer)` builds the captured
   body and accepts only the three answers. The fake API's allowlist gets exactly this path and body.
2. **You think in events, the client finds the id.** `rsvp accept|decline|tentative EVENT [--yes]`
   takes the event id you already see, and resolves the calendar item's own id.
3. **See it before it happens.** First the item, its date, the group, your current answer (from the
   event's `rsvp`) and the new answer, then `Accept this invitation? [y/N]` (or `Decline…`,
   `Answer tentative…`). `--yes` skips the question for scripts. Without a terminal and without
   `--yes`, nothing changes, as with `chat-send` and `helper`.
4. **Refuse what cannot be right, before writing:** an item with `rsvpRequired: false`; an item in the
   past; a cancelled item; an answer other than the three.
5. **The same answer again is not a write.** If your current answer is already the one asked for,
   the client says so and sends nothing, like `mark-read` on an item that is read.
6. **Never repeated on its own.** No retry after a timeout or a `5xx`: the client says the outcome is
   unknown and to look at the item. Running the command again is safe, because the same answer
   changes nothing. The one resend is after a `401`, as for the other writes.
7. **Output says what others see,** and that a first answer can be changed but not removed.
8. **Your answer shows up.** The agenda shows it next to *RSVP needed*, and the details of those
   items are fetched fresh instead of from the cache.
9. **Other parents' answers stay out.** The client has no command for the list of respondents, and
   the MCP tool `parro_get` refuses that path (decision 5). The spec describes it as an operation,
   with a warning about the personal data it returns.

## 4. MCP

One tool, `parro_rsvp` (`event_id`, `answer`, `confirm`), behind its own `PARRO_ALLOW_RSVP=1`. Without
`confirm: true` it returns only the preview. Hints: `readOnlyHint: false`, `destructiveHint: true`
(it overwrites an earlier answer, and a first answer cannot be removed), `idempotentHint: true` (the
capture shows a repeat changes nothing), `openWorldHint: true`. See decision 2.

## 5. Out of scope

Removing an answer (no such call was captured), answering for someone else, a note with the answer,
parent–teacher talk times (other calls, not captured), and answering a whole group of items at once.

## 6. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | ✅ **Live probe, GET only:** see *Probe results* in §1. Only counts and field names were printed | done |
| 2 | **Spec and privacy:** sanitized sample (git-ignored); the `POST` and the `GET` of the respondents under a new *RSVP* section, with what is not known, what others see and the warning about the personal data in that list; the event's `rsvp` field; the privacy scan covers `guardian` and `childNames` | spec validates; scan passes |
| 3 | **Client:** the call, the checks of §3, `rsvp accept\|decline\|tentative`, the answer in the agenda; the fake API accepts exactly this write and keeps the state | tests: nothing changes without confirmation, refusals, no retry, the right id in the path, only the three answers reach the body |
| 4 | **MCP** (per decisions 2 and 5): the tool, its switch and hints; `parro_get` refuses the respondents path | tests, as in `test_tool_hints.py`, and that no spelling of the path gets through |
| 5 | **Docs:** README promise, badge, an *Answering an invitation* section, FAQ, and the "no RSVPs" line under *Helping out*; `SECURITY.md` scope; help text, User-Agent, package description, CODE-TOUR, API-NOTES, CONFIGURATION; spec-operations count; CHANGELOG **0.9.0** | links and pictures checked |
| 6 | **Live check with you:** on the item *you* pick, `TENTATIVE`, then `DECLINE`, then back to the answer you want to end on (the values no capture shows, and replacing an answer); the Parro app agrees after each | in `docs/LIVE-CHECKS.md` |
| 7 | Release **0.9.0** | published |

For phase 6, use the item you already answered in the capture. A first answer cannot be removed, so an
item that is still unanswered would stay answered. Pick one where a short-lived change bothers nobody,
and not close to its date: teachers may be notified of each change.

## 7. Decisions (2026-11-08)

1. **How to confirm:** the same as `chat-send` and `helper`: a question at a terminal and `--yes` for
   scripts.
2. **MCP:** one tool behind a switch of its own, `PARRO_ALLOW_RSVP=1`, with the preview and
   `confirm: true`.
3. **Changing an answer you already gave:** allowed after the same preview and question, showing the
   old and the new answer. It is the only way to correct a mistake.
4. **Which items:** only items with `rsvpRequired: true`.
5. **The list of respondents (added 2026-11-09):** the spec describes
   `GET /calendaritem/{id}/calendaritemrsvp`, and the MCP tool `parro_get` refuses that path, so an
   assistant cannot read other parents' names and answers. The CLI's `get` keeps working: there you
   ask for it yourself.
