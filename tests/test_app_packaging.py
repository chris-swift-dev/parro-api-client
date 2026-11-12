"""What the installers are built from: the Briefcase settings, the icon files and the self-check."""

import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from parro import __version__

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def briefcase_app() -> dict[str, object]:
    tomllib = pytest.importorskip("tomllib", reason="Python 3.11 and newer read TOML")
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    app: dict[str, object] = settings["tool"]["briefcase"]["app"]["parro-gui"]
    return app


def png_width(data: bytes) -> int:
    assert data.startswith(PNG_SIGNATURE)
    width, height = struct.unpack(">II", data[16:24])
    assert width == height
    return int(width)


def run_app(*arguments: str, **environment: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", **environment}
    return subprocess.run(
        [sys.executable, "-m", "parro_gui", *arguments],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


# ----------------------------------------------------------------------------- the settings


def test_the_installers_use_the_same_qt_as_the_tests():
    pinned = (ROOT / "requirements-gui.txt").read_text(encoding="utf-8")
    qt = next(r for r in briefcase_app()["requires"] if r.startswith("PySide6"))  # type: ignore[attr-defined]
    assert qt in pinned.splitlines()


def test_pymupdf_is_not_bundled():
    """Its licence, the AGPL, would cover the whole installer."""
    requires = " ".join(briefcase_app()["requires"]).lower()  # type: ignore[arg-type]
    assert "pymupdf" not in requires and "fitz" not in requires


def test_the_app_module_and_its_sources_exist():
    assert (ROOT / "parro_gui" / "__main__.py").is_file(), "Briefcase starts the app's module"
    for source in briefcase_app()["sources"]:  # type: ignore[attr-defined]
        assert (ROOT / source / "__init__.py").is_file(), source


def test_the_name_says_it_is_unofficial():
    assert "unofficial" in str(briefcase_app()["description"]).lower()


# ----------------------------------------------------------------------------- the icon files


def test_linux_gets_a_png_for_each_size():
    for size in (16, 32, 64, 128, 256, 512):
        assert png_width((PACKAGING / f"icon-{size}.png").read_bytes()) == size


def test_the_windows_icon_holds_six_png_images():
    data = (PACKAGING / "icon.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind, count) == (0, 1, 6)
    sizes = []
    for index in range(count):
        side, _, _, _, _, _, length, offset = struct.unpack(
            "<BBBBHHII", data[6 + 16 * index : 22 + 16 * index]
        )
        image = data[offset : offset + length]
        assert png_width(image) == (side or 256)
        sizes.append(side or 256)
    assert sizes == [16, 32, 48, 64, 128, 256]


def test_the_macos_icon_holds_png_images_up_to_1024():
    data = (PACKAGING / "icon.icns").read_bytes()
    assert data[:4] == b"icns" and struct.unpack(">I", data[4:8])[0] == len(data)
    position, widths = 8, {}
    while position < len(data):
        kind, length = (
            data[position : position + 4],
            struct.unpack(">I", data[position + 4 : position + 8])[0],
        )
        widths[kind] = png_width(data[position + 8 : position + length])
        position += length
    assert position == len(data)
    assert widths[b"ic10"] == 1024 and widths[b"icp4"] == 16 and widths[b"ic14"] == 512


# ----------------------------------------------------------------------------- starting the app


def test_version_needs_no_qt():
    answer = run_app("--version")
    assert answer.returncode == 0 and answer.stdout.strip() == f"parro-client-gui {__version__}"


def test_the_self_check_starts_the_app_and_sends_nothing(tmp_path):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    data = tmp_path / "data"
    answer = run_app(
        "--self-check",
        PARRO_USERNAME="ouder@example.org",
        PARRO_PASSWORD="niet-gebruikt",
        PARRO_DATA_DIR=str(data),
    )
    assert answer.returncode == 0, answer.stderr
    assert "self-check: ok" in answer.stdout and f"parro-client-gui {__version__}" in answer.stdout
    assert "request" not in answer.stderr
    assert not data.exists(), "the user's data folder is not touched"
    assert "ouder@example.org" not in answer.stdout + answer.stderr


def test_the_app_icon_is_drawn(application):
    from parro_gui.icons import APP_ICON_SIZES, app_icon, app_icon_image

    image = app_icon_image(64)
    assert image.pixelColor(0, 0).alpha() == 0, "transparent around the square"
    assert image.pixelColor(32, 6).name() == "#2f6feb"
    assert image.pixelColor(32, 32).alpha() == 255
    assert len(app_icon().availableSizes()) == len(APP_ICON_SIZES)


def test_the_flatpak_keeps_every_folder_the_app_writes_to(monkeypatch, tmp_path):
    """The sandbox's home is temporary: what is not kept is gone when the app closes. Losing the
    tokens would cost a password check at every start (found on the live check of 0.12.0)."""
    from parro import settings

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    written = {
        settings.default_token_file().relative_to(tmp_path).parts[0],
        settings.default_data_dir().relative_to(tmp_path).parts[0],
    }
    flatpak = briefcase_app()["linux"]["flatpak"]  # type: ignore[index]
    kept = {
        arg.split("=", 1)[1]
        for arg, on in flatpak["finish_arg"].items()
        if on and arg.startswith("persist=")
    }
    assert written == {".parro-mcp", ".parro"} and written <= kept


def test_the_flatpak_sandbox_opens_no_folder_and_no_sound():
    flatpak = briefcase_app()["linux"]["flatpak"]  # type: ignore[index]
    allowed = {arg for arg, on in flatpak["finish_arg"].items() if on}
    assert not any(arg.startswith("filesystem=") for arg in allowed)
    assert "socket=pulseaudio" not in allowed
