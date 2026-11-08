"""All configuration in one immutable Settings object.

Settings are read from the PARRO_* environment variables once, by Settings.from_environment().
Command-line flags then override single fields with Settings.with_overrides(). Nothing else in the
package reads os.environ, so every module can be tested with a hand-made Settings.

The password is never stored in Settings: read_password() reads it on demand, so it lives in
memory only for the duration of one login.
"""

import dataclasses
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .errors import ConfigurationError

LoginMethod = Literal["login-form", "password-grant", "auto"]
LOGIN_METHODS: tuple[LoginMethod, ...] = ("login-form", "password-grant", "auto")
# How the CLI prints results. auto: markdown at a terminal, JSON when piped (PLAN-readable-output).
OutputFormat = Literal["auto", "json", "markdown"]
OUTPUT_FORMATS: tuple[OutputFormat, ...] = ("auto", "json", "markdown")

# Defaults follow the spec (openapi/parro.openapi.json, info.description → Conventions).
DEFAULT_API_BASE_URI = "https://rest-v2.parro.com"
DEFAULT_LOGIN_BASE_URI = "https://inloggen.parnassys.net"
DEFAULT_CONTRACT_VERSION = "224"
DEFAULT_APP_VERSION = "web:2.27.0"
# The public OAuth client of talk.parro.com. It only accepts this exact redirect URI.
DEFAULT_CLIENT_ID = "MQygAaSBUcAgPU2WInKt"
DEFAULT_REDIRECT_URI = "https://talk.parro.com/oauth2"
# offline_access is granted, but does not lengthen a login: the refresh token still expires 8 hours
# after the login, however often it is used (measured 2026-11-06, docs/LOGIN.md).
DEFAULT_SCOPE = "openid offline_access"
# Same path as the original MCP server, so existing logins keep working.
DEFAULT_CACHE_MAX_MB = 500


def default_token_file() -> Path:
    """~/.parro-mcp/tokens.json: the original server's path, so existing logins keep working.

    Resolved when Settings are made (not when this module is imported), so HOME is respected.
    """
    return Path.home() / ".parro-mcp" / "tokens.json"


def default_data_dir() -> Path:
    """~/.parro/data: the cache (and later the archive) live here (PLAN-readable-output §3b)."""
    return Path.home() / ".parro" / "data"


DEFAULT_LOGIN_METHOD: LoginMethod = "login-form"
DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 1400


@dataclass(frozen=True)
class Settings:
    """Everything the client needs to know before it sends its first request."""

    username: str | None = None
    password_from_env: str | None = dataclasses.field(default=None, repr=False)
    password_file: Path | None = None
    token_file: Path = dataclasses.field(default_factory=default_token_file)
    role_override: str | None = None
    bootstrap_access_token: str | None = dataclasses.field(default=None, repr=False)
    api_base_uri: str = DEFAULT_API_BASE_URI
    login_base_uri: str = DEFAULT_LOGIN_BASE_URI
    contract_version: str = DEFAULT_CONTRACT_VERSION
    app_version: str = DEFAULT_APP_VERSION
    client_id: str = DEFAULT_CLIENT_ID
    redirect_uri: str = DEFAULT_REDIRECT_URI
    scope: str = DEFAULT_SCOPE
    login_method: LoginMethod = DEFAULT_LOGIN_METHOD
    http_timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS
    output_format: OutputFormat = "auto"
    data_dir: Path = dataclasses.field(default_factory=default_data_dir)
    cache_enabled: bool = True
    # The MCP tool parro_mark_read exists only with PARRO_ALLOW_MARK_READ=1 (off by default).
    allow_mark_read: bool = False
    # The MCP tool parro_send_chat_message exists only with PARRO_ALLOW_SEND_CHAT=1 (default off).
    allow_send_chat: bool = False
    # The MCP tools parro_helper_signup and parro_helper_withdraw exist only with
    # PARRO_ALLOW_HELPER_SIGNUP=1 (off by default).
    allow_helper_signup: bool = False
    cache_max_bytes: int = DEFAULT_CACHE_MAX_MB * 1_000_000

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> "Settings":
        """Build Settings from PARRO_* variables. Unset or empty variables keep the default."""
        env = os.environ if environment is None else environment

        def text(name: str, default: str) -> str:
            return env.get(name, "").strip() or default

        def optional_text(name: str) -> str | None:
            return env.get(name, "").strip() or None

        password_file = optional_text("PARRO_PASSWORD_FILE")
        return cls(
            username=optional_text("PARRO_USERNAME"),
            password_from_env=env.get("PARRO_PASSWORD") or None,
            password_file=Path(password_file).expanduser() if password_file else None,
            token_file=Path(text("PARRO_TOKEN_FILE", str(default_token_file()))).expanduser(),
            role_override=optional_text("PARRO_ROLE"),
            bootstrap_access_token=optional_text("PARRO_ACCESS_TOKEN"),
            api_base_uri=text("PARRO_BASE_URI", DEFAULT_API_BASE_URI).rstrip("/"),
            login_base_uri=text("PARRO_LOGIN_URI", DEFAULT_LOGIN_BASE_URI).rstrip("/"),
            contract_version=text("PARRO_CONTRACT_VERSION", DEFAULT_CONTRACT_VERSION),
            app_version=text("PARRO_APP_VERSION", DEFAULT_APP_VERSION),
            client_id=text("PARRO_CLIENT_ID", DEFAULT_CLIENT_ID),
            redirect_uri=text("PARRO_REDIRECT_URI", DEFAULT_REDIRECT_URI),
            scope=text("PARRO_SCOPE", DEFAULT_SCOPE),
            login_method=parse_login_method(text("PARRO_LOGIN_METHOD", DEFAULT_LOGIN_METHOD)),
            http_timeout_seconds=parse_number(env, "PARRO_TIMEOUT", DEFAULT_HTTP_TIMEOUT_SECONDS),
            max_download_bytes=int(
                parse_number(env, "PARRO_MAX_DOWNLOAD", DEFAULT_MAX_DOWNLOAD_BYTES)
            ),
            max_image_pixels=int(parse_number(env, "PARRO_MAX_IMAGE_PX", DEFAULT_MAX_IMAGE_PIXELS)),
            output_format=parse_output_format(text("PARRO_FORMAT", "auto")),
            data_dir=Path(text("PARRO_DATA_DIR", str(default_data_dir()))).expanduser(),
            cache_enabled=parse_switch(env, "PARRO_CACHE", default=True),
            allow_mark_read=parse_switch(env, "PARRO_ALLOW_MARK_READ", default=False),
            allow_send_chat=parse_switch(env, "PARRO_ALLOW_SEND_CHAT", default=False),
            allow_helper_signup=parse_switch(env, "PARRO_ALLOW_HELPER_SIGNUP", default=False),
            # Megabytes as people count them (1 MB = 1,000,000 bytes), like the sizes shown.
            cache_max_bytes=int(parse_number(env, "PARRO_CACHE_MAX_MB", DEFAULT_CACHE_MAX_MB))
            * 1_000_000,
        )

    def with_overrides(self, **changes: object) -> "Settings":
        """Return a copy with some fields replaced; None values are ignored (flag not given)."""
        given = {name: value for name, value in changes.items() if value is not None}
        if "login_method" in given:
            given["login_method"] = parse_login_method(str(given["login_method"]))
        if "output_format" in given:
            given["output_format"] = parse_output_format(str(given["output_format"]))
        return dataclasses.replace(self, **given)  # type: ignore[arg-type]

    @property
    def api_root(self) -> str:
        """Base URL of every API path, e.g. https://rest-v2.parro.com/rest/v2."""
        return f"{self.api_base_uri}/rest/v2"

    @property
    def geon_media_type(self) -> str:
        """The Accept (and Content-Type) value that selects the API contract version."""
        return f"application/vnd.topicus.geon+json;version={self.contract_version}"

    @property
    def authorize_endpoint(self) -> str:
        return f"{self.login_base_uri}/idp/oauth2/authorize"

    @property
    def token_endpoint(self) -> str:
        return f"{self.login_base_uri}/idp/oauth2/token"

    @property
    def revoke_endpoint(self) -> str:
        return f"{self.login_base_uri}/idp/oauth2/revoke"

    def has_credentials(self) -> bool:
        """True when a username and some password source are configured."""
        return bool(self.username) and (
            self.password_file is not None or bool(self.password_from_env)
        )

    def read_password(self) -> str | None:
        """Return the configured password, preferring PARRO_PASSWORD_FILE over PARRO_PASSWORD.

        A file is the safer choice: some hosts (Dokploy, see DEPLOY.md) cut environment values
        at a '#', which silently turns the password into a wrong one. Only trailing line breaks
        are removed from the file, because spaces can be part of a password.
        """
        if self.password_file is None:
            return self.password_from_env
        try:
            content = self.password_file.read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigurationError(
                f"PARRO_PASSWORD_FILE {self.password_file} cannot be read: {error.strerror}"
            ) from None
        return content.rstrip("\r\n") or None


def parse_login_method(value: str) -> LoginMethod:
    """Validate a login method name from an env var or a flag."""
    cleaned = value.strip().lower()
    if cleaned not in LOGIN_METHODS:
        allowed = ", ".join(LOGIN_METHODS)
        raise ConfigurationError(f"Unknown login method {value!r}. Choose one of: {allowed}.")
    return cleaned  # mypy narrows the str to LoginMethod through the `in` check above


def parse_output_format(value: str) -> OutputFormat:
    """Validate an output format from PARRO_FORMAT or --format."""
    cleaned = value.strip().lower()
    if cleaned not in OUTPUT_FORMATS:
        allowed = ", ".join(OUTPUT_FORMATS)
        raise ConfigurationError(f"Unknown output format {value!r}. Choose one of: {allowed}.")
    return cleaned  # narrowed to OutputFormat by the `in` check above


def parse_switch(environment: Mapping[str, str], name: str, default: bool) -> bool:
    """on/off, true/false, yes/no, 1/0 from the environment."""
    raw_value = environment.get(name, "").strip().lower()
    if not raw_value:
        return default
    if raw_value in ("on", "true", "yes", "1"):
        return True
    if raw_value in ("off", "false", "no", "0"):
        return False
    raise ConfigurationError(f"{name} must be on or off, got {raw_value!r}.")


def parse_number(environment: Mapping[str, str], name: str, default: float) -> float:
    """Read a positive number from the environment, with a clear error for typos."""
    raw_value = environment.get(name, "").strip()
    if not raw_value:
        return default
    try:
        number = float(raw_value)
    except ValueError:
        raise ConfigurationError(f"{name} must be a number, got {raw_value!r}.") from None
    if number <= 0:
        raise ConfigurationError(f"{name} must be greater than zero, got {raw_value!r}.")
    return number
