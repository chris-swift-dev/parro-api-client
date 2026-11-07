"""The command-line client for Parro (talk.parro.com): it reads, and marks items read on request.

Installed, it is the `parro-client` command (`run()`); from a source folder or a release archive,
`python3 parro_cli.py` starts the same program.

Prints JSON on stdout (pipe it into jq) and log messages on stderr. Every command is a thin wrapper
around parro.operations, so the output is the same as that of the matching MCP tool.

Exit codes: 0 ok, 1 API or network error, 2 usage error, 3 not logged in, 4 login halted (a
password was rejected earlier; run `login` once the password is fixed).

Run `parro-client --help` or `parro-client <command> --help` for the commands.
Inspired by fobatai/parro-mcp; independent implementation.
"""

import argparse
import getpass
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from parro import icalendar, naming, operations
from parro.api_client import ParroClient
from parro.attachments import ReadOptions
from parro.cache import write_private_file
from parro.errors import EXIT_OK, EXIT_USAGE_ERROR, ConfigurationError, ParroError
from parro.rendering import RenderOptions, choose_format, render
from parro.settings import LOGIN_METHODS, OUTPUT_FORMATS, Settings

log = logging.getLogger("parro_cli")

EXIT_INTERRUPTED = 130

DESCRIPTION = """\
Client for Parro, the Dutch parent-school app. It reads. The one change it can make is marking
an announcement, calendar item or chat as read, and only when you ask (`mark-read`, or
`--mark-read`); the school can see that. Nothing can be posted, sent or deleted.

Logging in: set PARRO_USERNAME plus PARRO_PASSWORD_FILE (or PARRO_PASSWORD) and run `login`,
or run `login --prompt` to type the password, or use the browser flow: `login-url`, log in in
a browser, then `login-finish '<the address you landed on>'`. A login lasts up to 8 hours
(tokens stored in ~/.parro-mcp/tokens.json); after that, log in again.

The ParnasSys IdP locks the account after a few failed logins. After one rejected password,
nothing logs in automatically any more until you run `login` yourself."""

EPILOG = """\
examples:
  {cli} login --prompt
  {cli} announcements --limit 5 --unread-only
  {cli} attachment 11000000000 --text
  {cli} mark-read announcement 11000000000
  {cli} get /accountsettings
  {cli} token          # paste into Swagger UI → Authorize → bearerToken
exit codes: 0 ok, 1 API/network error, 2 usage, 3 not logged in, 4 login halted"""


# ------------------------------------------------------------------------------- parser


def add_global_options(parser: argparse.ArgumentParser, with_defaults: bool) -> None:
    """Options valid before *and* after the command. Sub-level copies default to "not given"."""

    def default(value: Any) -> Any:
        return value if with_defaults else argparse.SUPPRESS

    parser.add_argument(
        "--login-method",
        choices=LOGIN_METHODS,
        default=default(None),
        help="how to log in with a password (default: PARRO_LOGIN_METHOD or login-form). "
        "login-form: like a browser, 1 password check. password-grant: OAuth2 password grant, "
        "1 check. auto: password grant, then the form once: up to 2 checks.",
    )
    parser.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default=default(None),
        help="output: markdown (readable) or json (for scripts). Default: PARRO_FORMAT, else "
        "auto, which means markdown at a terminal and JSON when the output is piped",
    )
    parser.add_argument(
        "--raw", action="store_true", default=default(False), help="print the untouched API JSON"
    )
    parser.add_argument(
        "--compact", action="store_true", default=default(False), help="print JSON on one line"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        default=default(False),
        help="do not read or write the cache of attachments and calendar details (PARRO_CACHE=off)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=default(0),
        help="log what happens on stderr (-vv for HTTP details; secrets are never logged)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=naming.cli_name(),
        description=DESCRIPTION,
        epilog=EPILOG.format(cli=naming.cli_name()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_global_options(parser, with_defaults=True)
    common = argparse.ArgumentParser(add_help=False)
    add_global_options(common, with_defaults=False)
    commands = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        return commands.add_parser(name, help=help_text, description=help_text, parents=[common])

    add_login_commands(command)
    add_reading_commands(command)
    return parser


CommandFactory = Callable[[str, str], argparse.ArgumentParser]


def add_login_commands(command: CommandFactory) -> None:
    login = command("login", "log in now; spends exactly one password check (auto: up to two)")
    login.add_argument(
        "--prompt", action="store_true", help="type the password (hidden); nothing is stored"
    )
    command("logout", "revoke the tokens at the IdP and forget them")
    command("status", "show the login state; never spends a password check")
    command("token", "print a valid access token, refreshing it if needed")
    command("login-url", "start a browser login: prints the URL to open")
    finish = command("login-finish", "finish a browser login with the address you landed on")
    finish.add_argument("redirect_url", help="https://talk.parro.com/oauth2?code=... (or the code)")


def add_reading_commands(command: CommandFactory) -> None:
    overview = command(
        "overview", "what is new: unread counts, unread announcements and calendar items, chats"
    )
    overview.add_argument(
        "--all",
        action="store_true",
        help="the latest announcements and everything coming up, read or not",
    )
    command("me", "the account: name, e-mail, school")
    add_limit(command("children", "the children linked to the account"), 20)
    privacy = command("privacy", "per child: can you change the privacy choices (photos, data) now")
    privacy.add_argument(
        "--link",
        type=int,
        metavar="CHILD_ID",
        help="the signed link to the page where they are set (a secret: do not share it)",
    )
    groups = command("groups", "groups (classes) with the ids other commands need")
    groups.add_argument("--previous", action="store_true", help="last school year instead")
    add_limit(groups, 50)
    command("unread", "unread counts per category")
    add_full(add_limit(command("system-news", "product news from Parro itself"), 20))

    announcements = command("announcements", "the announcement feed, newest first")
    announcements.add_argument("--group", type=int, help="only this group (see `groups`)")
    add_limit(announcements, 20)
    announcements.add_argument(
        "--unread-only", action="store_true", help="only announcements not read yet"
    )
    add_full(announcements)
    announcement = command("announcement", "one announcement in full, with its author")
    announcement.add_argument("id", type=int, help="announcement id")
    add_mark_read_flag(announcement, "the announcement")

    add_calendar_commands(command)
    add_attachment_command(command)

    chats = add_limit(command("chatrooms", "chat conversations"), 25)
    chats.add_argument("--unread", action="store_true", help="only chats with unread messages")
    chats.add_argument(
        "--archived",
        choices=["only", "include"],
        help="only archived chats, or archived chats too (default: not archived)",
    )
    chats.add_argument("--type", choices=list(operations.CHAT_TYPES), help="only this kind of chat")
    chats.add_argument(
        "--schoolyear",
        type=int,
        metavar="YEAR",
        help="chats started in this school year, e.g. 2025",
    )
    messages = command("chat-messages", "messages in one chat conversation")
    messages.add_argument("chatroom_id", type=int, help="chatroom id (see `chatrooms`)")
    messages.add_argument(
        "--since", metavar="DATE", help="only messages since then, e.g. 2026-10-01 (local time)"
    )
    add_limit(messages, 30)
    add_mark_read_flag(messages, "the chat")
    members = command("chat-members", "who is in a chat conversation")
    members.add_argument("chatroom_id", type=int, help="chatroom id (see `chatrooms`)")
    members.add_argument("--former", action="store_true", help="also members who left")

    add_mark_read_command(command)
    add_local_data_commands(command)
    get = command("get", "GET any API path, e.g. /accountsettings (read-only)")
    get.add_argument("path", help="path below /rest/v2, e.g. /absence/setting")
    get.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="query parameter, repeatable",
    )
    get.add_argument("--limit", type=int, help="page size (sends a Range header)")
    get.add_argument("--offset", type=int, default=0, help="first item of the page")


def add_mark_read_flag(parser: argparse.ArgumentParser, what: str) -> None:
    parser.add_argument(
        "--mark-read",
        action="store_true",
        help=f"after fetching it, mark {what} as read (the school can see this)",
    )


def add_mark_read_command(command: CommandFactory) -> None:
    mark = command(
        "mark-read",
        "mark an announcement, calendar item or chat as read; the school can see this",
    )
    mark.add_argument(
        "kind",
        choices=[*operations.MARK_READ_KINDS, "group"],
        help="what to mark; group: all unread announcements of a group (asks for --yes)",
    )
    mark.add_argument("id", type=int, help="its id (for group: the group id, see `groups`)")
    mark.add_argument(
        "--yes", action="store_true", help="for group: mark them; without it only the count"
    )


def add_calendar_commands(command: CommandFactory) -> None:
    calendar = command("calendar", "calendar items from today on, soonest first")
    calendar.add_argument("--group", type=int, help="only this group (see `groups`)")
    calendar.add_argument(
        "--limit",
        type=int,
        help=f"how many items (default 20; with --ics all upcoming, up to {ICS_MAX_ITEMS})",
    )
    calendar.add_argument(
        "--details",
        action="store_true",
        help="add location, description and attachments (one extra request per item)",
    )
    calendar.add_argument("--past", action="store_true", help="earlier items, latest first")
    calendar.add_argument(
        "--ics",
        metavar="FILE",
        help="write the items as an iCalendar file to import elsewhere ('-' = standard output). "
        "Add --details for locations and descriptions. For automatic updates use calendar-link",
    )

    command("calendar-link", "your personal link to subscribe to the Parro agenda (keep it secret)")


def add_local_data_commands(command: CommandFactory) -> None:
    """The archive (sync) and the cache: commands that write to your own disk."""
    sync = command(
        "sync",
        "save everything as files: announcements, calendar items and chats as markdown (+ JSON), "
        "with their documents; repeat it to update",
    )
    sync.add_argument(
        "--to", type=Path, metavar="DIR", help="archive folder (default: PARRO_DATA_DIR/archive)"
    )
    sync.add_argument(
        "--previous", action="store_true", help="last school year instead of this one"
    )
    sync.add_argument(
        "--photos", action="store_true", help="also save photos (can be several GB per school year)"
    )

    cache = command("cache", "show or empty the local cache of attachments and calendar details")
    cache.add_argument("action", choices=("info", "clear"), help="info (default) or clear")


def add_attachment_command(command: CommandFactory) -> None:
    attachment = command("attachment", "read the attachment(s) of an announcement or calendar item")
    attachment.add_argument("event_id", type=int, help="announcement or calendar item id")
    which = attachment.add_mutually_exclusive_group()
    which.add_argument("--attachment-id", type=int, help="which attachment, when there are several")
    which.add_argument("--all", action="store_true", help="read every attachment")
    attachment.add_argument("--save-to", type=Path, metavar="DIR", help="also save the files here")
    attachment.add_argument(
        "--text", action="store_true", help="print only the extracted text, not JSON"
    )
    attachment.add_argument(
        "--max-chars", type=int, default=40_000, help="cut the text off here (default 40000)"
    )


def add_limit(parser: argparse.ArgumentParser, default: int) -> argparse.ArgumentParser:
    parser.add_argument(
        "--limit", type=int, default=default, help=f"how many items (default {default})"
    )
    return parser


def add_full(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--full", action="store_true", help="markdown: show whole texts instead of a preview"
    )
    return parser


# ------------------------------------------------------------------------------ commands

Handler = Callable[[ParroClient, argparse.Namespace], Any]


def run_login(client: ParroClient, args: argparse.Namespace) -> Any:
    if not args.prompt:
        return operations.login(client, method=args.login_method)
    username = client.settings.username
    if not username:
        print("ParnasSys e-mail address: ", end="", file=sys.stderr, flush=True)
        username = sys.stdin.readline().strip()
    password = getpass.getpass("ParnasSys password (hidden): ")
    return operations.login(client, method=args.login_method, username=username, password=password)


def run_attachment(client: ParroClient, args: argparse.Namespace) -> Any:
    options = ReadOptions(
        max_chars=args.max_chars, include_images=False, save_directory=args.save_to
    )
    report = operations.read_attachments(
        client,
        event_id=args.event_id,
        attachment_id=args.attachment_id,
        read_all=args.all,
        options=options,
    )
    if not args.text:
        return report.summary
    return PlainText(attachment_texts(report.summary))


ICS_MAX_ITEMS = 500


def run_calendar(client: ParroClient, args: argparse.Namespace) -> Any:
    """The agenda, or with --ics the agenda as an iCalendar file."""
    if args.ics and args.raw:
        raise ConfigurationError("--ics writes calendar events; it cannot be combined with --raw.")
    limit = args.limit if args.limit is not None else (ICS_MAX_ITEMS if args.ics else 20)
    agenda = operations.list_calendar(
        client, args.group, limit, raw=args.raw, details=args.details, past=args.past
    )
    if not args.ics:
        return agenda
    text = icalendar.build_icalendar(agenda, operations.current_time())
    if args.ics == "-":
        return ExactText(text)
    path = Path(args.ics).expanduser()
    write_private_file(path, text.encode("utf-8"))
    return {"ics_file": str(path), "events": agenda["count"], "period": agenda["period"]}


def attachment_texts(summary: dict[str, Any]) -> str:
    """The extracted text(s) of an attachment report, separated by a header line per file."""
    if "message" in summary:  # several attachments and none chosen: nothing was read
        raise ConfigurationError(f"{summary['message']} (use --attachment-id or --all)")
    results = summary.get("attachments", [summary])
    parts = []
    for result in results:
        if "text" in result:
            body = result["text"]
        else:
            body = f"[{result.get('error') or result.get('returned_as') or 'no text'}]"
        parts.append(body if len(results) == 1 else f"===== {result.get('filename')}\n{body}")
    return "\n\n".join(parts)


def parse_params(pairs: Sequence[str]) -> dict[str, str]:
    params = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise ConfigurationError(f"--param needs KEY=VALUE, got {pair!r}.")
        params[key] = value
    return params


# The markdown view (parro.rendering) of each command's result.
COMMAND_VIEWS = {
    "login": "status",
    "logout": "logout",
    "status": "status",
    "login-url": "login_url",
    "login-finish": "status",
    "overview": "overview",
    "me": "account",
    "children": "children",
    "groups": "groups",
    "unread": "unread",
    "system-news": "system_news",
    "announcements": "announcements",
    "announcement": "announcement",
    "calendar": "calendar",
    "attachment": "attachment",
    "calendar-link": "calendar_link",
    "privacy": "privacy",
    "chatrooms": "chatrooms",
    "chat-messages": "chat_messages",
    "chat-members": "chat_members",
    "mark-read": "mark_read",
    "get": "get",
    "cache": "cache",
    "sync": "sync",
}


class PlainText(str):
    """Marks command output that is printed as is instead of as JSON."""


class ExactText(PlainText):
    """Plain text whose bytes must not change: iCalendar lines end in CRLF (RFC 5545), and a
    Windows console stream would turn each of those into CR CR LF."""


HANDLERS: dict[str, Handler] = {
    "login": run_login,
    "logout": lambda c, a: operations.logout(c),
    "status": lambda c, a: operations.auth_status(c),
    "token": lambda c, a: PlainText(operations.access_token(c)),
    "login-url": lambda c, a: operations.login_url(c),
    "login-finish": lambda c, a: operations.login_finish(c, a.redirect_url),
    "overview": lambda c, a: operations.show_overview(c, unread_only=not a.all),
    "me": lambda c, a: operations.show_account(c, raw=a.raw),
    "children": lambda c, a: operations.list_children(c, a.limit, raw=a.raw),
    "groups": lambda c, a: operations.list_groups(
        c, "previous" if a.previous else "current", a.limit, raw=a.raw
    ),
    "unread": lambda c, a: operations.show_unread_counts(c, raw=a.raw),
    "system-news": lambda c, a: operations.list_system_news(c, a.limit, raw=a.raw),
    "announcements": lambda c, a: operations.list_announcements(
        c, a.group, a.limit, a.unread_only, raw=a.raw
    ),
    "announcement": lambda c, a: operations.show_announcement(
        c, a.id, raw=a.raw, mark_read=a.mark_read
    ),
    "calendar": lambda c, a: run_calendar(c, a),
    "attachment": run_attachment,
    "calendar-link": lambda c, a: operations.calendar_link(c),
    "privacy": lambda c, a: (
        operations.privacy_link(c, a.link) if a.link is not None else operations.privacy(c, a.raw)
    ),
    "chatrooms": lambda c, a: operations.list_chatrooms(
        c,
        a.limit,
        raw=a.raw,
        chats=operations.ChatFilter(a.unread, a.archived or "exclude", a.type, a.schoolyear),
    ),
    "chat-messages": lambda c, a: operations.list_chat_messages(
        c, a.chatroom_id, a.limit, raw=a.raw, since=a.since, mark_read=a.mark_read
    ),
    "mark-read": lambda c, a: (
        operations.mark_group_announcements_read(c, a.id, confirmed=a.yes)
        if a.kind == "group"
        else operations.mark_read(c, a.kind, a.id)
    ),
    "chat-members": lambda c, a: operations.list_chat_members(
        c, a.chatroom_id, include_former=a.former, raw=a.raw
    ),
    "sync": lambda c, a: operations.sync_archive(
        c,
        operations.SyncOptions(
            target=(a.to or c.settings.data_dir / "archive").expanduser(),
            previous_year=a.previous,
            photos=a.photos,
        ),
    ),
    "cache": lambda c, a: (
        operations.cache_clear(c) if a.action == "clear" else operations.cache_info(c)
    ),
    "get": lambda c, a: operations.get_any(
        c, a.path, parse_params(a.param), a.limit, a.offset, raw=a.raw
    ),
}


# ---------------------------------------------------------------------------------- main


def configure_logging(verbosity: int) -> None:
    level = logging.WARNING if verbosity == 0 else logging.INFO if verbosity == 1 else logging.DEBUG
    logging.basicConfig(level=level, format="parro: %(levelname)s %(message)s", stream=sys.stderr)


def main(
    argv: Sequence[str] | None = None,
    make_client: Callable[[Settings], ParroClient] = ParroClient,
) -> int:
    """Run one command and return its exit code. Tests pass `make_client` with a fake transport."""
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)
    try:
        settings = Settings.from_environment().with_overrides(
            login_method=args.login_method,
            output_format=args.format,
            cache_enabled=False if args.no_cache else None,
        )
        output_format = choose_format(settings.output_format, args.raw, sys.stdout.isatty())
        result = HANDLERS[args.command](make_client(settings), args)
    except ParroError as problem:
        print(f"error: {problem}", file=sys.stderr)
        return problem.exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except ValueError as problem:  # e.g. a negative --limit
        print(f"error: {problem}", file=sys.stderr)
        return EXIT_USAGE_ERROR
    print_result(args, result, output_format)
    return EXIT_OK


def print_result(args: argparse.Namespace, result: Any, output_format: str) -> None:
    """Plain text as is; otherwise markdown or JSON, as chosen."""
    if isinstance(result, ExactText):
        write_exact(result)
    elif isinstance(result, PlainText):
        print(result, end="" if result.endswith("\n") else "\n")
    elif output_format == "markdown":
        options = RenderOptions(audience="cli", full_text=getattr(args, "full", False))
        view = COMMAND_VIEWS.get(args.command, "get")
        if "ics_file" in result:
            view = "ics_export"
        elif args.command == "mark-read" and args.kind == "group":
            view = "mark_group_read"
        print(render(view, result, options), end="")
    else:
        print(operations.to_json_text(result, compact=args.compact))


def write_exact(text: str) -> None:
    """Write UTF-8 bytes to stdout, past any line-ending translation of the text stream."""
    sys.stdout.flush()
    binary = getattr(sys.stdout, "buffer", None)
    if binary is None:  # a stream without bytes underneath (some test harnesses)
        sys.stdout.write(text)
        return
    binary.write(text.encode("utf-8"))
    binary.flush()


def run(program: str = naming.INSTALLED) -> None:
    """The `parro-client` command: UTF-8 output on every system, then main()'s exit code.

    Windows consoles default to a legacy code page, which cannot print markers such as ● and 📌.
    `program` is the name help and hints use: `parro_cli.py` when started with the launcher.
    """
    naming.set_cli_name(program)
    use_utf8_output()
    sys.exit(main())


def use_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


if __name__ == "__main__":
    run()
