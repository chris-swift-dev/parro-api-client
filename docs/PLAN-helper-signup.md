# Plan 9: signing up and withdrawing as a helper for a calendar item

*Status: planned (2026-11-08); decisions taken in §7 (decision 3 changed: a count above 1). Nothing
implemented yet. One question open in §7.*

**Goal:** the spec describes adding and removing a commitment on a calendar item's helper slot, and
the client can do both. Source: `findings/calendar-event-commitment.har` (git-ignored).

---

## 1. What the capture shows

| | Sign up | Withdraw |
| --- | --- | --- |
| Call | `POST /calendaritem/{id}/resource/{resourceId}/commitment/` (with the trailing `/`) | `DELETE /calendaritem/{id}/resource/{resourceId}/commitment/{commitmentId}` |
| Body | `{"items":[{"dtype":"calendar.RCalendarItemResourceCommitmentPrimer","links":[],"amount":1}]}` | none |
| Answer | `201`, `Location: …/commitment/{commitmentId}`, body `{"items":[<commitment: id, identity, amount>]}` | `204`, no body |

Headers are the usual ones. The capture is clean: placeholder token and ids, placeholder names, no
cookies, no JWTs, no e-mail addresses. It holds two sign-ups and one withdrawal.

**The ids.** `{id}` is the calendar item's own id (`calendarItem.links[rel=self].id`), which is
**not** the event id the client shows everywhere (`#7000000301`). A resource's own link confirms the
path shape: `/calendaritem/{id}/resource/{resourceId}`. This is the same kind of trap as the chat's
`koppeling` id, so the client must resolve the ids itself.

**What it does not show:**

- **How to find your own commitment to withdraw.** Withdrawing needs the commitment id. The samples
  have `commitments: []` even on a slot with `amountCommitted: 2`, so it is unclear when that list is
  filled. This decides the design of withdrawing, and a GET-only probe has to settle it (phase 1).
- **A count above 1.** Teachers may ask how many children a parent can take along, so `amount` can
  be more than 1 (for example 3 in one car). Every capture sends `amount: 1`, so a higher value is
  known from how the app is used, not from a capture: phase 6 checks it live.
- **Whether signing up twice adds up.** `commitedByMe` (sic) is a number, not a flag: probably the
  places you have committed. See the question in §7.
- How the API answers for a full slot, a past item or closed sign-ups.
- Whether teachers get a notification.

`permissions` do not help: a resource lists only `READ`, also where signing up works.

## 2. Challenging it: a third kind of write

| | Marking as read | Sending a message | Helper commitment |
| --- | --- | --- | --- |
| Who notices | the school (a count) | real people, directly | the teacher and other parents (your name on the slot) |
| Can be undone | no | no (as far as known) | **yes**: withdraw |
| Free text | no | yes | **no** |

- **A sign-up is a promise.** It tells a teacher you will drive or help on that day, and it can take
  the last place from another parent.
- **Withdrawing can leave the school short.** It frees the place, and nobody may notice in time.
- **An assistant could be steered,** as with messages: a newsletter that says "sign up for this". There
  is no free text, so nothing can leak through it, and a sign-up can be undone, but the promise is
  still made in your name.

**Recommendation: do it, as the third and narrow write.** The promise becomes: *it reads; it can
mark items as read, send a text message to a chat you are in, and sign you up or withdraw you as a
helper, and only when you ask.*

## 3. The design

1. **Two fixed calls, nothing generic.** `ParroClient.add_helper_commitment(item, resource, count)`
   builds the captured body with `amount: count`, and `remove_helper_commitment(item, resource, commitment)`
   sends the `DELETE`. The fake API's allowlist gets exactly these paths and this body.
2. **You think in events, the client finds the ids.** Commands take the event id you already see;
   `calendar --details` also shows each slot's id. With one slot, `--slot` is not needed.
3. **See it before it happens.** `helper signup EVENT [--slot ID] [--count N]` (default 1, for
   example `--count 3` for three children in your car) and `helper withdraw EVENT [--slot ID]` first
   show the item, its date, the slot, how many places are taken and, for a sign-up, the count, then
   ask `Sign up as helper? [y/N]` (or `Withdraw as helper? [y/N]`). `--yes` skips the question for
   scripts. Without a terminal and without `--yes`, nothing changes, as with `chat-send`.
4. **Refuse what cannot be right, before writing:** an item that asks for no helpers; an item in the
   past; a slot that is full; a count below 1, or above the places left (`amount` − `amountCommitted`,
   when the slot has a limit); an unknown or missing slot when there are several; signing up where you
   already have; withdrawing where you have not. To change the count: withdraw and sign up again.
5. **Never repeated on its own.** No retry after a timeout or a `5xx`: the client says the outcome is
   unknown. Running the command again is safe, because it first reads whether you are signed up. The
   one resend is after a `401`, as for the other writes.
6. **Output says what others see.** Your name is on the slot, for the teacher and other parents.
7. **Details stay fresh.** Items with helper slots are already fetched fresh instead of from the
   cache, so a change shows at once.

## 4. MCP

Two tools, because their hints differ: `parro_helper_signup` (`destructiveHint: false`) and
`parro_helper_withdraw` (`destructiveHint: true`, a place is given up), both `readOnlyHint: false`,
`idempotentHint: true` (a repeat finds nothing to do) and `openWorldHint: true`. Without
`confirm: true` they return only the preview, and `parro_helper_signup` takes an optional `count`.
See decision 2.

## 5. Out of scope

RSVPs and parent–teacher timeslots (other calls, not captured), changing the count of an existing
commitment in place (no such call was captured), and signing up someone else.

## 6. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | **Live probe with you, GET only:** an item with helper slots, in a state where you are signed up if there is one: is your commitment in `commitments[]`? Does `GET …/resource/{id}/commitment` list them? Which id is `{id}` (calendar item, not event)? | each question has an answer, in this plan |
| 2 | **Spec and privacy:** sanitized sample; `POST` and `DELETE` with what is not known and what others see; the privacy scan covers commitments | spec validates; scan passes |
| 3 | **Client:** the two calls, the checks of §3, `helper signup` / `withdraw`, slot ids in `calendar --details`; the fake API accepts exactly these writes and keeps the state | tests: nothing changes without confirmation, refusals (also of a count that does not fit), no retry, the count reaches the body, the event id is never used in the path |
| 4 | **MCP** (per decision 2): the two tools, their switch and hints | tests, as in `test_tool_hints.py` |
| 5 | **Docs:** README promise, badge, a *Helping out* section, FAQ; `SECURITY.md` scope; help text, User-Agent, package description, CODE-TOUR, API-NOTES, CONFIGURATION; CHANGELOG **0.8.0** | links and pictures checked |
| 6 | **Live check with you:** on one slot *you* pick, one sign-up and one withdrawal, with a count above 1 if the slot has room (the value no capture shows); the slot's counts and the Parro app agree after each | in `docs/LIVE-CHECKS.md` |
| 7 | Release **0.8.0** | published |

For phase 6, pick an item where signing up and withdrawing a moment later bothers nobody: a slot with
places left, not a full or nearly full one, and not close to its date.

## 7. Decisions (2026-11-08)

1. **How to confirm:** the same as `chat-send`: a question at a terminal and `--yes` for scripts
   (*recommended*); or always `--yes`.
2. **MCP:** two tools behind one switch of their own, `PARRO_ALLOW_HELPER_SIGNUP=1`, with the preview
   and `confirm: true` as for messages (*recommended*: no free text, and a sign-up can be undone); or
   leave them out.
3. **More than one place (changed on 2026-11-08):** one commitment per person per slot, refusing a
   second, and that commitment can have a **count above 1** (`--count N`), because teachers may ask
   how many children a parent can take along.

**A question only you can answer:** the capture has two sign-ups before the withdrawal. Were they
on the same slot, or on two different ones? All ids in the capture are placeholders, so it does not
say. If the same slot accepted both, signing up twice really does add up, and refusing a second one
(decision 3) matters more. Phase 1 may answer it too: `commitedByMe` on a slot where you are signed up.
