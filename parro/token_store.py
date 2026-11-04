"""TokenStore: the token file on disk (default ~/.parro-mcp/tokens.json).

The file holds the OAuth tokens, the "login halted" latch and, during a browser login, the PKCE
verifier. It is a small JSON object; the key names are those of the original MCP server, so a file
written by either program works with the other:

    access_token, refresh_token   the tokens themselves
    expires_at, obtained_at       Unix timestamps (expires_at already has a safety margin removed)
    login_failed                  reason text; present = automatic logins are halted (the latch)
    pending_verifier, pending_state   an unfinished browser login (login-url → login-finish)

Rules for this module:
  * It never deletes the refresh token or the latch because of a 401. Only an explicit logout
    removes tokens, and only a successful or explicit login clears the latch.
  * The file is written with mode 0600 (owner read/write only), atomically, so a crash cannot
    leave half a file behind.
  * Unknown keys in the file are kept as they are.
"""

import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Treat an access token as expired this long before the IdP says it is, so a request never
# leaves with a token that dies on the way.
EXPIRY_SAFETY_MARGIN_SECONDS = 60
# The IdP's usual lifetime (token.200.json: expires_in 3599), used when it does not say.
DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS = 3600

TOKEN_KEYS = ("access_token", "refresh_token", "expires_at", "obtained_at")
LATCH_KEY = "login_failed"
PENDING_KEYS = ("pending_verifier", "pending_state")


@dataclass(frozen=True)
class TokenSet:
    """The tokens we hold. `expires_at` None means "unknown": use it until the API refuses it."""

    access_token: str | None = field(default=None, repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    expires_at: float | None = None
    obtained_at: float | None = None

    def has_fresh_access_token(self, now: float) -> bool:
        if not self.access_token:
            return False
        return self.expires_at is None or self.expires_at > now


@dataclass(frozen=True)
class PendingBrowserLogin:
    """What login-url saved for login-finish: the PKCE verifier and the expected state."""

    verifier: str = field(repr=False)
    state: str | None


class TokenStore:
    """Reads and writes the token file. One instance per process; the file is read once."""

    def __init__(
        self,
        path: Path,
        bootstrap_access_token: str | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.path = path
        self.bootstrap_access_token = bootstrap_access_token
        self.clock = clock
        self._contents: dict[str, Any] | None = None

    # ----------------------------------------------------------------------------- tokens

    def get_tokens(self) -> TokenSet:
        """The stored tokens, or the PARRO_ACCESS_TOKEN bootstrap token if the file has none."""
        contents = self._read()
        if not contents.get("access_token") and self.bootstrap_access_token:
            # A token pasted by the user: no refresh token, unknown expiry, never written to disk.
            return TokenSet(access_token=self.bootstrap_access_token)
        return TokenSet(
            access_token=contents.get("access_token"),
            refresh_token=contents.get("refresh_token"),
            expires_at=_as_float(contents.get("expires_at")),
            obtained_at=_as_float(contents.get("obtained_at")),
        )

    def save_token_response(self, token_response: dict[str, Any]) -> TokenSet:
        """Store the tokens from an IdP token response (RFC 6749 §5.1) and return them.

        A refresh response may leave out refresh_token; the one we had then stays valid.
        A pending browser login is finished by definition, so it is removed.
        """
        now = self.clock()
        lifetime = _as_float(token_response.get("expires_in"))
        if lifetime is None:
            lifetime = DEFAULT_ACCESS_TOKEN_LIFETIME_SECONDS
        contents = self._read()
        contents["access_token"] = token_response.get("access_token")
        contents["refresh_token"] = token_response.get("refresh_token") or contents.get(
            "refresh_token"
        )
        contents["expires_at"] = now + lifetime - EXPIRY_SAFETY_MARGIN_SECONDS
        contents["obtained_at"] = now
        for key in PENDING_KEYS:
            contents.pop(key, None)
        self._write(contents)
        log.info("stored new tokens in %s", self.path)
        return self.get_tokens()

    def forget_tokens(self) -> None:
        """Remove tokens and any pending login (logout). The latch stays: it is about the password.

        The file is deleted when nothing else is left in it.
        """
        contents = self._read()
        for key in (*TOKEN_KEYS, *PENDING_KEYS):
            contents.pop(key, None)
        if contents:
            self._write(contents)
        else:
            self._delete_file()

    # ------------------------------------------------------------------------------ latch

    def get_login_halted_reason(self) -> str | None:
        """Why automatic logins are halted, or None when they are allowed."""
        reason = self._read().get(LATCH_KEY)
        return str(reason) if reason else None

    def halt_logins(self, reason: str) -> None:
        """Set the latch. Saved to disk at once, so other processes see it too."""
        contents = self._read()
        contents[LATCH_KEY] = reason
        self._write(contents)
        log.warning("automatic logins halted: %s", reason)

    def clear_login_halt(self) -> None:
        contents = self._read()
        if contents.pop(LATCH_KEY, None) is not None:
            self._write(contents)
            log.info("automatic logins allowed again")

    # ------------------------------------------------------------------ browser login state

    def get_pending_browser_login(self) -> PendingBrowserLogin | None:
        contents = self._read()
        verifier = contents.get("pending_verifier")
        if not verifier:
            return None
        return PendingBrowserLogin(verifier=str(verifier), state=contents.get("pending_state"))

    def save_pending_browser_login(self, pending: PendingBrowserLogin) -> None:
        contents = self._read()
        contents["pending_verifier"] = pending.verifier
        contents["pending_state"] = pending.state
        self._write(contents)

    # --------------------------------------------------------------------------- file I/O

    def reload(self) -> None:
        """Forget the cached contents, so the next access reads the file again."""
        self._contents = None

    def _read(self) -> dict[str, Any]:
        if self._contents is None:
            self._contents = _load_json_object(self.path)
        return self._contents

    def _write(self, contents: dict[str, Any]) -> None:
        self._contents = contents
        try:
            _write_private_json_file(self.path, contents)
        except OSError as error:
            # Keep working in memory; the user only loses persistence across runs.
            log.error("could not save %s: %s", self.path, error.strerror)

    def _delete_file(self) -> None:
        self._contents = {}
        try:
            self.path.unlink(missing_ok=True)
        except OSError as error:
            log.error("could not delete %s: %s", self.path, error.strerror)


def _load_json_object(path: Path) -> dict[str, Any]:
    """The file's JSON object; {} when the file is missing, unreadable or not an object."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        log.warning("ignoring unreadable token file %s (%s)", path, type(error).__name__)
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_private_json_file(path: Path, contents: dict[str, Any]) -> None:
    """Write JSON so that only the owner can read it, replacing the old file in one step."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=".tokens-")
    try:
        os.chmod(temporary_name, 0o600)  # mkstemp already uses 0600; be explicit about it.
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(contents, temporary_file, indent=1)
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
