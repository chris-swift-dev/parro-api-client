# Calendar, privacy choices and your own archive

Three things that go beyond reading the feed. Installation and the rest are in the
[README](../README.md).

## The agenda in your own calendar app

- **`calendar-link`** prints Parro's own subscription link (`GET /calendar/sync`). Paste it into
  Google Calendar (*Other calendars → From URL*), Apple Calendar (*New Calendar Subscription*) or
  Outlook (*Subscribe from web*), and the calendar keeps itself up to date. **The link is a secret**:
  anyone who has it can read your Parro calendar without logging in. ParnasSys lists agenda syncing
  as a feature of the paid *Parro Ouderapp*, so not every school may offer it.
- **`calendar --ics FILE`** writes an iCalendar file of the upcoming items (`--past` for earlier
  ones, `--details` for locations and descriptions, `-` for standard output). It works without the
  subscription feature, but it is a snapshot: export again to update. Every event keeps the same
  UID, so importing a newer file updates events instead of duplicating them.

## Your children's privacy choices

Schools ask parents every year what they may do with photos and data of their children.
`parro-client privacy` shows per child whether you can still change those choices, and when and by
whom they were last changed. The choices themselves are not in the API: `privacy --link CHILD_ID`
prints the link to the ParnasSys page where you set them. **That link is a secret too**: it opens
the page without logging in.

## Your own archive: `sync`

`parro-client sync` keeps a local copy of everything your account can see, as files that stay
readable without Parro:

```
~/.parro/data/archive/
  announcements/2026-10-22-nieuwsbrief-nr-3-5000000101.md   (+ .json, + attachments/)
  calendar/2026-11-11-sint-maartenviering-7000000101.md     (+ .json, + attachments/)
  chats/rijden-naar-het-natuurmuseum-8000000001.md          (+ .json)
  index.md                                                  (everything, newest first)
```

- Each `.md` file starts with a small YAML header (id, type, title, date, groups), so notes apps
  such as Obsidian can use it; the `.json` next to it holds the same data for scripts.
- **Run it again to update.** Unchanged items are not rewritten and a saved file is never
  downloaded again. Nothing is ever deleted: an item that disappears from Parro stays, marked
  *(no longer in Parro)* in `index.md`.
- Documents are always saved; photos only with `--photos` (a school year of photos can run to
  several GB). `--to DIR` writes elsewhere.
- **Run `sync --previous` once as well**, especially around the start of a school year: schools
  sometimes post the first dates of the new year in last year's groups.
- The archive holds your children's names, photos and school letters: its folders are readable
  only by you (0700, files 0600), and no file contains a download or avatar link.

**The cache.** Attachments (and their text) and calendar details are also kept in
`~/.parro/data/cache`, so a newsletter is downloaded once, not every time an assistant reads it.
Lists are never cached: they are how the client learns what is new; neither are the details of items
that ask for helpers, because sign-ups change. Same privacy rules as the
archive. `cache info` shows its size, `cache clear` empties it, `--no-cache` switches it off.
