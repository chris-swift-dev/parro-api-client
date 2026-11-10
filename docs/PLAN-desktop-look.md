# Plan 13: a more modern look for the desktop app

*Status: planned (2026-11-10); decisions taken in §6. No phase started yet.*

**Goal:** the app looks like a current desktop app, in light and dark, with nothing lost in safety or
behaviour. Today it uses Qt's default widgets without any styling, and plain text rows.

---

## 1. The options, tried on the app's own Calendar screen with invented data

| | **Own theme on Qt Widgets** | Qt Quick / QML, Material style | `qt-material` | Fluent widgets | Other add-ons |
| --- | --- | --- | --- | --- | --- |
| What it is | a stylesheet, colour tokens and a drawn list row | a new UI in QML, with Python behind it | a ready-made stylesheet for Widgets | a widget library | dark stylesheets |
| New dependency | none | none: `QtQuick` and Material are in the PySide6 we use | `qt-material`, `Jinja2` | `PySide6-Fluent-Widgets` and two more | `pyqtdarktheme`, `qdarkstyle` |
| Licence | ours | LGPL (as now) | BSD-2 | **GPLv3 or paid: does not fit** | MIT |
| Result on our screen | clean, calm, readable in light and dark | modern, but looks like a phone app | ALL-CAPS buttons, body text turned blue, thick outlines | not tried | not tried |
| Light and dark | follows the system, ours to tune | built in | separate themes | built in | dark only |
| Work | small: the views stay | **a rewrite** of about 1,500 lines of views | an afternoon | a rewrite of the widgets | small |
| The 137 window tests | keep working | **rewritten**: they drive widgets | keep working | rewritten | keep working |
| Safe display of text from others | unchanged (`SafeTextBrowser`) | built again, and tested again | unchanged | unchanged | unchanged |
| Maintained | us | Qt | last release April 2025 | active | `pyqtdarktheme` last released 2022 and excludes Python 3.12 |

Tried by rendering: the own theme (light and dark), `qt-material` and a QML Material mock-up. The QML
test ran with Qt's software renderer, which does not show everything (its filled button stayed blank),
so it undersells Material a little.

## 2. Recommendation: an own theme on Qt Widgets

- **Most of the "old-fashioned" feeling comes from three things,** and a theme fixes all of them: flat
  grey surfaces, plain text rows, and default buttons. The trial took about 80 lines.
- **QML is a rewrite with no gain in what the app does.** It would redo 1,500 lines of working views,
  137 tests, and the safety work that was just finished, in a second language with a bridge to Python.
- **Material is a phone design.** It is fine, but it is not what a desktop app on macOS or Windows
  looks like, and its dense variant is still roomy for a list-and-detail screen.

**What we give up:** animations and ripple effects, which QML does well. If those are the point, QML is
the right choice and the cost above applies.

## 3. The design

1. **`parro_gui/theme.py`:** colour tokens for light and dark, one stylesheet built from them, on Qt's
   Fusion style so the app looks the same everywhere. It follows the system's light or dark setting.
2. **List rows are drawn:** a bold title, a quieter second line, a dot for unread, and small labels for
   *RSVP needed* or *helpers wanted*. Text is elided rather than wrapped.
3. **Layout:** a real sidebar with icons, detail panes as cards, more space, one consistent margin.
4. **Buttons have a hierarchy, carefully:** the coloured button is used only for **Confirm** in the
   dialogs. Accept, Decline and Tentative stay equal, so the design does not push an answer. (The
   trial picture highlights Accept only to show what a coloured button looks like.)
5. **Empty and loading states** say something useful instead of showing a blank pane.
6. **Text from others is still only text.** The theme styles the display, and never what it may load.

## 4. Accessibility

Text and buttons meet WCAG AA contrast in both themes, checked by a test on the tokens. Keyboard focus
stays visible. Sizes are in points, so the system's font size is respected.

## 5. Phases

| # | Phase | Done when |
| --- | --- | --- |
| 1 | **Theme:** tokens, stylesheet, Fusion, following light and dark | every dialog and section styled; contrast test passes |
| 2 | **Rows and sidebar:** drawn rows, labels, icons | tests: rows show the same information as now |
| 3 | **Layout, cards, dialogs, empty states** | all sections and dialogs checked in both themes |
| 4 | **Look at it on real screens:** Linux and macOS, with you | you are happy with it |
| 5 | **Docs and picture**, then release | new picture, light and dark |

No behaviour changes, so the existing 137 window tests must keep passing as they are.

## 6. Decisions (2026-11-10)

1. **Approach:** an own theme on Qt Widgets.
2. **Timing:** on the current branch, so that 0.10.0 makes a good first impression.
3. **Sidebar icons:** a small set from [Lucide](https://lucide.dev), ISC licence, shipped as SVG files.
4. **Light and dark:** follow the system.
