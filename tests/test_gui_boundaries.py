"""What keeps the desktop app an optional layer. These run without Qt."""

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from parro_gui import app

ROOT = Path(__file__).resolve().parent.parent
QT_IMPORT = re.compile(r"^\s*(from|import)\s+(PySide6|shiboken6|parro_gui)\b", re.MULTILINE)
NETWORK = re.compile(r"\b(urllib|http\.client|requests|socket|HttpRequest)\b")


def test_the_core_never_imports_qt_or_the_app():
    for path in sorted((ROOT / "parro").glob("*.py")):
        assert not QT_IMPORT.search(path.read_text(encoding="utf-8")), path.name
    for name in ("parro_cli.py", "parro_mcp.py"):
        assert not QT_IMPORT.search((ROOT / name).read_text(encoding="utf-8")), name


def test_the_app_never_talks_to_the_network_itself():
    """Every request goes through parro.operations and ParroClient."""
    for path in sorted((ROOT / "parro_gui").rglob("*.py")):
        assert not NETWORK.search(path.read_text(encoding="utf-8")), path.name


def test_the_core_needs_no_dependency():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r"^dependencies = \[\]$", text, re.MULTILINE)
    assert 'gui = ["PySide6-Essentials' in text


def test_importing_the_entry_point_does_not_need_qt():
    source = (ROOT / "parro_gui" / "app.py").read_text(encoding="utf-8")
    assert not re.search(r"^(from|import)\s+(PySide6|\.window)", source, re.MULTILINE)


def test_without_qt_it_says_what_to_install(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "PySide6", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtGui", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", None)
    monkeypatch.delitem(sys.modules, "parro_gui.window", raising=False)
    monkeypatch.delitem(sys.modules, "parro_gui.worker", raising=False)
    importlib.invalidate_caches()
    with pytest.raises(SystemExit) as stop:
        app.run()
    assert stop.value.code == 2
    assert 'parro-api-client[gui]"' in capsys.readouterr().err


def test_the_real_entry_point_exits_cleanly(tmp_path):
    """In a process of its own: a crash on the way out only shows in the exit code."""
    script = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "QApplication.exec = staticmethod(lambda: 0)\n"
        "from parro_gui import window\n"
        "sys.exit(window.main(['parro-client-gui']))\n"
    )
    environment = {k: v for k, v in os.environ.items() if not k.startswith("PARRO_")}
    environment.update(
        QT_QPA_PLATFORM="offscreen",
        PARRO_TOKEN_FILE=str(tmp_path / "tokens.json"),
        PARRO_DATA_DIR=str(tmp_path / "data"),
    )
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    finished = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr.decode(errors="replace")[-500:]
