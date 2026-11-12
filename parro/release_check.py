"""Is there a newer release? One GET to GitHub, for the desktop app's update check.

Nothing about the user goes with it: no token, no cookie, no Parro data; GitHub sees the IP address
and the User-Agent with this version. Only the release's version number is used from the answer.
The link people are sent to is built here from that number, never taken from the answer.
"""

import re
from dataclasses import dataclass

from . import __version__
from .errors import NetworkError
from .http import HttpRequest, HttpTransport, UrllibTransport

REPOSITORY = "chris-swift-dev/parro-api-client"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
TIMEOUT_SECONDS = 10.0
_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")


@dataclass(frozen=True)
class LatestRelease:
    version: str
    page: str  # where to download it: the release page, never a file


def version_numbers(text: str) -> tuple[int, int, int] | None:
    """`0.12.0` or `v0.12.0` → (0, 12, 0). Anything else, also `1.0.0rc1`, is not a release."""
    found = _VERSION.match(text.strip())
    if not found:
        return None
    major, minor, patch = (int(part) for part in found.groups())
    return major, minor, patch


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = version_numbers(candidate), version_numbers(current)
    return new is not None and old is not None and new > old


def release_page(version: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/tag/v{version}"


def latest_release(transport: HttpTransport | None = None) -> LatestRelease | None:
    """The newest published release, or None when GitHub has none or answers something odd.

    `releases/latest` leaves out drafts and pre-releases. A failed connection raises NetworkError;
    the caller decides whether to say so.
    """
    request = HttpRequest(
        "GET",
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"parro-client-gui/{__version__}",
        },
        log_label="GET api.github.com (latest release)",
    )
    response = (transport or UrllibTransport(TIMEOUT_SECONDS)).send(request)
    if response.status == 404:
        return None
    if response.status != 200:
        raise NetworkError(f"GitHub answered {response.status} for the latest release.")
    try:
        answer = response.json()
    except ValueError:
        return None
    tag = answer.get("tag_name") if isinstance(answer, dict) else None
    if not isinstance(tag, str) or answer.get("draft") or answer.get("prerelease"):
        return None
    numbers = version_numbers(tag)
    if numbers is None:
        return None
    version = ".".join(str(part) for part in numbers)
    return LatestRelease(version, release_page(version))
