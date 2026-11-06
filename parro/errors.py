"""Every error this package raises, as one small class hierarchy.

Each class carries the process exit code the CLI uses for it, so the CLI can map an error to
an exit code without a lookup table. Messages are written for the person running the tool: they
say what went wrong and what to do next.

Messages must never contain tokens, passwords or full attachment URLs.
"""

EXIT_OK = 0
EXIT_API_OR_NETWORK_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_NOT_LOGGED_IN = 3
EXIT_LOGIN_HALTED = 4


class ParroError(Exception):
    """Base class: something went wrong talking to Parro or the ParnasSys login server."""

    exit_code = EXIT_API_OR_NETWORK_ERROR


class ConfigurationError(ParroError):
    """A setting or argument is invalid, e.g. an unknown login method or an unreadable file."""

    exit_code = EXIT_USAGE_ERROR


class NetworkError(ParroError):
    """The request never got an HTTP answer (DNS failure, refused connection, timeout)."""


class NotLoggedIn(ParroError):
    """There is no usable token and no way to get one without the user's help."""

    exit_code = EXIT_NOT_LOGGED_IN


class LoginHalted(ParroError):
    """Automatic logins are switched off because an earlier password was rejected.

    The ParnasSys IdP locks the account after a few failed attempts. Only an explicit login
    (CLI `login`, MCP `parro_login`) switches automatic logins back on.
    """

    exit_code = EXIT_LOGIN_HALTED


class CredentialsRejected(LoginHalted):
    """The password was just rejected. Automatic logins are now halted (see LoginHalted)."""


class LoginFailed(ParroError):
    """A login step failed for a reason other than a rejected password.

    Examples: the login page has no recognisable form, the redirect carries no code, or the
    token exchange answered with an error.
    """


class ApiError(ParroError):
    """The Parro API answered with an unexpected HTTP status."""

    def __init__(self, message: str, status: int, application_error: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.application_error = application_error


class TokenRejected(ApiError):
    """The API kept answering 401, even after one refresh.

    Either the token really is invalid, or the endpoint answers 401 for a wrong `dtype`
    (spec: GET /event/{id} with dtype=event.RAnnouncementEvent).
    """


class AttachmentError(ParroError):
    """An attachment could not be found, downloaded or turned into text."""
