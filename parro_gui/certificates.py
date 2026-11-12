"""HTTPS certificates checked by the operating system, as a browser does it.

Python checks certificates with OpenSSL and its own list of trusted roots. The installers bring
their own Python, and that list is missing (macOS) or holds only what Windows has fetched so far
(Windows): connections then fail with CERTIFICATE_VERIFY_FAILED (live check of 0.12.0). The
`truststore` library makes Python ask the operating system instead: Windows' certificate service,
which fetches missing roots, macOS's Keychain, and OpenSSL's system files on Linux. Certificates a
company installs on the computer then work too.

This applies to the desktop app's process only; the core in parro/ stays standard library only,
and the command line and the MCP server keep Python's own check.
"""

import sys

SYSTEM = "the operating system's (truststore)"
PYTHON = "Python's own"


def use_system_certificates() -> str:
    """Hand the check to the operating system when truststore is there; say which check is used."""
    try:
        import truststore
    except ImportError:
        return PYTHON
    truststore.inject_into_ssl()
    return SYSTEM


def check_connection() -> int:
    """`parro-client-gui --check-connection`: one HTTPS request, the one the update check makes.

    It asks GitHub for the latest release: nothing about anyone goes with it. For the installers'
    build, where the offline self-check cannot see a certificate problem.
    """
    from parro.errors import ParroError
    from parro.release_check import LATEST_RELEASE_API, latest_release

    used = use_system_certificates()
    print(f"certificates: {used}")
    try:
        release = latest_release()
    except ParroError as problem:
        print(f"connection: failed: {problem}", file=sys.stderr)
        return 1
    found = release.version if release else "none"
    print(f"connection: ok ({LATEST_RELEASE_API} answered; latest release {found})")
    return 0
