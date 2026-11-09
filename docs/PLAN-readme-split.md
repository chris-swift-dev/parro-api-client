# Plan 11: splitting the README again

*Status: phases 1–4 done (2026-11-09); decisions taken in §6.*

**Goal:** the README answers "what is this, what does it promise, and how do I start?", and links to
the rest. It goes from 544 lines to about 300. **Moving, not rewriting:** the text stays as it is,
except for the rules the four write sections repeat, which are stated once.

---

## 1. Where the lines are

| Section | Lines | Words |
| --- | --- | --- |
| Marking as read, Sending a chat message, Helping out, Answering an invitation | 143 | 1,408 |
| MCP server | 73 | 690 |
| Calendar app, privacy choices, `sync` | 51 | 485 |
| Command line | 44 | 343 |
| The OpenAPI specification | 26 | 248 |
| Everything else | 207 | 1,584 |

Plan 4 did this once, at 435 lines, by moving reference material out. Since then each new write added
about 40 lines to the middle of the page.

## 2. The new shape

| Section | What happens | Goes to |
| --- | --- | --- |
| Opening, badges, picture, Quick start | stays | |
| What it does, What it looks like | stays | |
| Command line | examples stay; the full list of commands and flags collapses (decision 2) | |
| **Changing things in Parro** (new, short) | replaces the four sections: the promise, a table of the four writes (what, command, MCP switch, who sees it), one combined warning about assistants | `docs/CHANGING-THINGS.md` |
| MCP server | the example, the setup and manual testing stay; the tool table moves, with a one-line summary left behind | `docs/MCP.md` |
| Logging in | stays | |
| **Also in the box** (new, short) | one line each for the calendar app, privacy choices and `sync` | `docs/CALENDAR-AND-ARCHIVE.md` |
| The OpenAPI specification | a paragraph, the Swagger link and the picture; the rest is already in `openapi/README.md` or moves there | `openapi/README.md` |
| FAQ, Development, Credits, License | stays, with links updated | |

### `docs/CHANGING-THINGS.md`

1. **The rules for all of them:** nothing happens on its own; a preview and a question first; `--yes`
   for scripts; nothing without a terminal or `--yes`; never repeated after a timeout or a server
   error; a switch of its own for each MCP tool; a preview unless `confirm: true`.
2. **One section per write,** keeping today's headings so the anchors stay recognisable, with only
   what is specific to it: the commands, who sees it, what can be undone, what it refuses.
3. **The warnings about assistants.** Each stays with its own write, because the risks differ.

## 3. What must not get lost

- **The promise stays in the README:** the opening sentence, the badge, the paragraph under *What it
  does* and the FAQ answer.
- **One combined warning stays in the README.** Someone who switches on a write tool from the README
  alone must still read that an assistant also reads what others write, and to keep approval on.
- **The README's warning about other people's answers** moves with the RSVP section, and the FAQ gets
  a short answer that points to it.
- **The changelog says to read "the warning in the README".** That stays true because of the combined
  warning, so old release notes need no change.

## 4. What the split has to handle

| Point | What to do |
| --- | --- |
| The README is also the PyPI page | Links to the new documents use full GitHub addresses, as the current `docs/` links do. Links within a document stay `#anchors` |
| Release archives ship `docs/` files by name | Add the three new documents to `INCLUDED_FILES` in `tools/build_release.py`. The README's full addresses keep working from a download, but the relative links between shipped documents do not, and a guide should come with the download |
| Links into sections that move | `SECURITY.md` (3), `docs/CONFIGURATION.md` (4), and the README's own 11. `docs/LOGIN.md` links to *Logging in*, which stays |
| Pictures | `tests/test_readme_images.py` and the swagger picture keep working; no picture moves |
| Spec text | Nothing in `tools/build_spec.py` points at the moved sections |

**Two guards, so this does not depend on care:**

- A committed link test (today's link check is a throwaway script): every relative link and `#anchor`
  in tracked Markdown resolves, and every `blob/main/...` address in the README names a tracked file.
- A test that the guides the README links to are in `INCLUDED_FILES`, apart from an explicit list of
  developer documents, and that relative links in shipped documents stay inside the archive.

**A content check for this one change:** every sentence of the old README is found in the new README or
one of the new documents, except a written list of the ones deliberately merged in §2. It is a
throwaway script; its result goes in the PR description.

## 5. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | ✅ **The guards:** the link test and the archive test, passing on today's files | tests pass |
| 2 | ✅ **`docs/CHANGING-THINGS.md`:** move the four sections, state the shared rules once; README table and combined warning | content check; links pass |
| 3 | ✅ **`docs/MCP.md` and `docs/CALENDAR-AND-ARCHIVE.md`;** the rest of the README trimmed per §2 | content check; links pass; README about 300 lines (it came to 352, with the collapsed blocks included) |
| 4 | ✅ **Links and packaging:** `SECURITY.md`, `CONFIGURATION.md`, `CODE-TOUR`, `INCLUDED_FILES`; a look at the result on GitHub and with `twine check` | release archive holds the new files; rendering checked |
| 5 | **PR**, then release **0.9.0** with the shorter README on PyPI | published |

No code changes, so no live check against Parro is needed.

## 6. Decisions (2026-11-09)

1. **The four writes:** one document, with the shared rules once.
2. **The full list of commands and flags:** collapsed in the README with `<details>`, the same way the
   pictures already are.
3. **Timing:** split first, then release 0.9.0.
