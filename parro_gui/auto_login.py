"""Logging in by itself: the e-mail address and the path of a password file, never the password.

The CLI and the MCP server log in again by themselves when PARRO_USERNAME and PARRO_PASSWORD_FILE
are set. Those still work for the app when it is started from a terminal. An app started from a
menu or the dock does not see them, so the login dialog can remember the two in a small file in
the data folder. The password stays in the user's own file; the core reads it at the moment of
the login and keeps it no longer than that call.

The same rules as the CLI: one password check, through the core's automatic path, and the latch
decides. After a rejected password nothing logs in by itself until a login by hand.
"""

import dataclasses
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from parro import operations
from parro.api_client import ParroClient
from parro.errors import ConfigurationError
from parro.settings import Settings

from . import app_file

FILE_NAME = app_file.FILE_NAME
PART = "auto_login"


@dataclass(frozen=True)
class Remembered:
    username: str
    password_file: Path


def remembered_path(data_dir: Path) -> Path:
    return app_file.path_in(data_dir)


def load_remembered(data_dir: Path) -> Remembered | None:
    try:
        auto = app_file.read_part(data_dir, PART)
        return Remembered(str(auto["username"]), Path(str(auto["password_file"])))
    except (KeyError, TypeError):
        return None


def save_remembered(data_dir: Path, remembered: Remembered | None) -> None:
    """Write the e-mail address and the file's path, or forget them (None)."""
    if remembered is None:
        app_file.write_part(data_dir, PART, None)
        return
    part = {"username": remembered.username, "password_file": str(remembered.password_file)}
    app_file.write_part(data_dir, PART, part)


def app_settings(environment: Any = None) -> Settings:
    """The settings the app uses: the PARRO_* variables, else what the login dialog remembered.

    Always the login form, also when PARRO_LOGIN_METHOD says otherwise: `auto` can spend two
    password checks, and the app spends one.
    """
    settings = Settings.from_environment(environment)
    remembered = load_remembered(settings.data_dir)
    if remembered is not None and not settings.has_credentials():
        settings = dataclasses.replace(
            settings, username=remembered.username, password_file=remembered.password_file
        )
    return dataclasses.replace(settings, login_method="login-form")


def password_file_problem(path: Path | None) -> str | None:
    """Why this file must not be used, or None. Only its permissions are looked at, not its text."""
    if path is None:
        return None
    try:
        info = path.stat()
    except OSError as error:
        return f"The password file {path} cannot be read: {error.strerror}."
    if not stat.S_ISREG(info.st_mode):
        return f"The password file {path} is not a file."
    if os.name == "nt":
        return None if os.access(path, os.R_OK) else f"The password file {path} cannot be read."
    if info.st_uid != os.getuid():
        return f"The password file {path} belongs to someone else, so it is not used."
    if info.st_mode & 0o077:
        return (
            f"Others on this computer can read the password file {path}, so it is not used. "
            f"Make it private (chmod 600 {path}) and log in once by hand."
        )
    return None


def log_in(client: ParroClient) -> dict[str, Any]:
    """Runs in the background. A valid login is kept; else a refresh; else one password check.

    The core's automatic path: it refuses while the latch is set, and sets the latch when the
    password is rejected. It never clears the latch.
    """
    problem = password_file_problem(client.settings.password_file)
    if problem:
        raise ConfigurationError(problem)
    client.authenticator.get_access_token()
    return operations.auth_status(client)
