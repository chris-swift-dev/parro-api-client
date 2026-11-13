"""HTTPS certificates checked by the operating system (parro_gui/certificates.py).

Found on the live check of 0.12.0: the installers' own Python had no roots on macOS and only some on
Windows. These tests replace truststore with a stand-in, so they run without it too.
"""

import os
import sys
import types
from typing import Any

import pytest

from parro.errors import NetworkError
from parro.release_check import LatestRelease
from parro_gui import app, certificates, self_check


@pytest.fixture
def truststore(monkeypatch) -> types.SimpleNamespace:
    calls = types.SimpleNamespace(injected=0)
    module: Any = types.ModuleType("truststore")
    module.inject_into_ssl = lambda: setattr(calls, "injected", calls.injected + 1)
    monkeypatch.setitem(sys.modules, "truststore", module)
    return calls


@pytest.fixture
def no_truststore(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "truststore", None)


@pytest.fixture
def own_environment(monkeypatch) -> None:
    """run_self_check() empties the PARRO_* variables: on a copy, not the test run's own."""
    monkeypatch.setattr(os, "environ", dict(os.environ))


def test_with_truststore_the_system_checks(truststore):
    assert certificates.use_system_certificates() == certificates.SYSTEM
    assert truststore.injected == 1


def test_without_it_pythons_own_check_stays(no_truststore):
    assert certificates.use_system_certificates() == certificates.PYTHON


def test_check_connection_says_ok(truststore, monkeypatch, capsys):
    monkeypatch.setattr(
        "parro.release_check.latest_release", lambda: LatestRelease("0.12.0", "https://x")
    )
    assert certificates.check_connection() == 0
    out = capsys.readouterr().out
    assert f"certificates: {certificates.SYSTEM}" in out and "connection: ok" in out
    assert truststore.injected == 1, "the system's check before the request"


def test_check_connection_shows_a_certificate_failure(no_truststore, monkeypatch, capsys):
    def fails() -> None:
        raise NetworkError("No answer for GET api.github.com: [SSL: CERTIFICATE_VERIFY_FAILED]")

    monkeypatch.setattr("parro.release_check.latest_release", fails)
    assert certificates.check_connection() == 1
    assert "connection: failed" in capsys.readouterr().err


def test_check_connection_counts_a_refusal_from_github_as_a_connection(
    no_truststore, monkeypatch, capsys
):
    # CI of 0.12.0: the macOS runners share addresses, and GitHub may refuse with 403 for too
    # many requests. The connection and its certificate worked, which is what is checked.
    from parro.http import HttpResponse

    class Refuses:
        def __init__(self, _timeout: float) -> None:
            pass

        def send(self, request):
            return HttpResponse(403, {}, b'{"message": "rate limit"}', request.url)

    monkeypatch.setattr("parro.release_check.UrllibTransport", Refuses)
    assert certificates.check_connection() == 0
    out = capsys.readouterr().out
    assert "connection: ok" in out and "answered 403" in out


def test_the_app_option_needs_no_qt(monkeypatch):
    # What follows the version gate, also on Python 3.10 (CI of 0.12.0).
    monkeypatch.setattr(app, "MINIMUM_PYTHON", (3, 0))
    monkeypatch.setattr(sys, "argv", ["parro-client-gui", "--check-connection"])
    monkeypatch.setattr(certificates, "check_connection", lambda: 7)
    monkeypatch.setitem(sys.modules, "PySide6", None)
    with pytest.raises(SystemExit) as stop:
        app.run()
    assert stop.value.code == 7


def test_the_app_uses_the_system_check_before_anything_connects(truststore, monkeypatch):
    """run() hands HTTPS to the system before the window module is even imported."""
    # What follows the version gate, also on Python 3.10 (CI of 0.12.0).
    monkeypatch.setattr(app, "MINIMUM_PYTHON", (3, 0))
    monkeypatch.setattr(sys, "argv", ["parro-client-gui"])
    order: list[str] = []
    real = certificates.use_system_certificates

    def use_system_certificates() -> str:
        order.append("certificates")
        return real()

    def main(_argv: list[str]) -> int:
        order.append("window")
        return 0

    monkeypatch.setattr(certificates, "use_system_certificates", use_system_certificates)
    window: Any = types.ModuleType("parro_gui.window")
    window.main = main
    monkeypatch.setitem(sys.modules, "parro_gui.window", window)
    with pytest.raises(SystemExit):
        app.run()
    assert order == ["certificates", "window"] and truststore.injected == 1


def test_an_installer_without_truststore_fails_its_self_check(
    no_truststore, own_environment, monkeypatch, capsys
):
    monkeypatch.setattr(self_check, "_check_the_window", lambda: ([], 0))
    monkeypatch.setattr(self_check, "_in_an_installer", lambda: True)
    assert self_check.run_self_check() == 1
    assert "truststore is missing" in capsys.readouterr().err


def test_a_pipx_install_without_it_still_passes(
    no_truststore, own_environment, monkeypatch, capsys
):
    monkeypatch.setattr(self_check, "_check_the_window", lambda: ([], 0))
    monkeypatch.setattr(self_check, "_in_an_installer", lambda: False)
    assert self_check.run_self_check() == 0
    assert f"HTTPS certificates: {certificates.PYTHON}" in capsys.readouterr().out
