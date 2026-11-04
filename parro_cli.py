#!/usr/bin/env python3
"""parro_cli.py: a read-only command-line client for Parro (talk.parro.com).

Prints JSON on stdout (pipe it into jq) and log messages on stderr. Every command is a thin wrapper
around parro.operations, so the output is the same as that of the matching MCP tool.

Exit codes: 0 ok, 1 API or network error, 2 usage error, 3 not logged in, 4 login halted (a
password was rejected earlier; run `login` once the password is fixed).

Run `parro_cli.py --help` or `parro_cli.py <command> --help` for the commands.
Inspired by fobatai/parro-mcp; independent implementation.
"""

import argparse
import getpass
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from parro import operations
from parro.api_client import ParroClient
from parro.attachments import ReadOptions
from parro.errors import EXIT_OK, EXIT_USAGE_ERROR, ConfigurationError, ParroError
from parro.settings import LOGIN_METHODS, Settings

log = logging.getLogger("parro_cli")

EXIT_INTERRUPTED = 130

DESCRIPTION = """\
Read-only client for Parro, the Dutch parent-school app. It only ever reads: nothing can be
posted, changed or deleted.

Logging in: set PARRO_USERNAME plus PARRO_PASSWORD_FILE (or PARRO_PASSWORD) and run `login`,
or run `login --prompt` to type the password, or use the browser flow: `login-url`, log in in
a browser, then `login-finish '<the address you landed on>'`. After that, tokens refresh on
their own (stored in ~/.parro-mcp/tokens.json).

The ParnasSys IdP locks the account after a few failed logins. After one rejected password,
nothing logs in automatically any more until you run `login` yourself."""

EPILOG = """\
examples:
  parro_cli.py login --prompt
  parro_cli.py announcements --limit 5 --unread-only
  parro_cli.py attachment 11000000000 --text
  parro_cli.py get /accountsettings
  parro_cli.py token          # paste into Swagger UI → Authorize → bearerToken
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
        "--raw", action="store_true", default=default(False), help="print the untouched API JSON"
    )
    parser.add_argument(
        "--compact", action="store_true", default=default(False), help="print JSON on one line"
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
        prog="parro_cli.py",
        description=DESCRIPTION,
        epilog=EPILOG,
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
    command("me", "the account: name, e-mail, school")
    add_limit(command("children", "the children linked to the account"), 20)
    groups = command("groups", "groups (classes) with the ids other commands need")
    groups.add_argument("--previous", action="store_true", help="last school year instead")
    add_limit(groups, 50)
    command("unread", "unread counts per category")
    add_limit(command("system-news", "product news from Parro itself"), 20)

    announcements = command("announcements", "the announcement feed, newest first")
    announcements.add_argument("--group", type=int, help="only this group (see `groups`)")
    add_limit(announcements, 20)
    announcements.add_argument(
        "--unread-only", action="store_true", help="only announcements not read yet"
    )
    announcement = command("announcement", "one announcement in full, with its author")
    announcement.add_argument("id", type=int, help="announcement id")

    calendar = command("calendar", "calendar items, soonest first")
    calendar.add_argument("--group", type=int, help="only this group (see `groups`)")
    add_limit(calendar, 20)

    add_attachment_command(command)

    add_limit(command("chatrooms", "chat conversations"), 25)
    messages = command("chat-messages", "messages in one chat conversation")
    messages.add_argument("chatroom_id", type=int, help="chatroom id (see `chatrooms`)")
    add_limit(messages, 30)

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


def add_limit(parser: argparse.ArgumentParser, default: int) -> None:
    parser.add_argument(
        "--limit", type=int, default=default, help=f"how many items (default {default})"
    )


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


class PlainText(str):
    """Marks command output that is printed as is instead of as JSON."""


HANDLERS: dict[str, Handler] = {
    "login": run_login,
    "logout": lambda c, a: operations.logout(c),
    "status": lambda c, a: operations.auth_status(c),
    "token": lambda c, a: PlainText(operations.access_token(c)),
    "login-url": lambda c, a: operations.login_url(c),
    "login-finish": lambda c, a: operations.login_finish(c, a.redirect_url),
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
    "announcement": lambda c, a: operations.show_announcement(c, a.id, raw=a.raw),
    "calendar": lambda c, a: operations.list_calendar(c, a.group, a.limit, raw=a.raw),
    "attachment": run_attachment,
    "chatrooms": lambda c, a: operations.list_chatrooms(c, a.limit, raw=a.raw),
    "chat-messages": lambda c, a: operations.list_chat_messages(
        c, a.chatroom_id, a.limit, raw=a.raw
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
        settings = Settings.from_environment().with_overrides(login_method=args.login_method)
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
    if isinstance(result, PlainText):
        print(result)
    else:
        print(operations.to_json_text(result, compact=args.compact))
    return EXIT_OK


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    sys.exit(main())
