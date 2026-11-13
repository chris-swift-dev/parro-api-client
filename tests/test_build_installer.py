"""tools/build_installer.py and .github/workflows/installers.yml: what they build, and how."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "installers.yml"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_installer", ROOT / "tools" / "build_installer.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()

MANIFEST = """app-id: io.github.chrisswiftdev.parro-gui
default-branch: 0.12.0
runtime: org.kde.Platform
runtime-version: '6.11'
"""


def test_the_flatpak_branch_is_the_same_for_every_version():
    changed = tool.set_flatpak_branch(MANIFEST)
    assert "default-branch: stable\n" in changed and "0.12.0" not in changed
    assert changed.replace("stable", "0.12.0") == MANIFEST, "nothing else changes"


def test_a_manifest_without_a_branch_stops_the_build():
    with pytest.raises(SystemExit):
        tool.set_flatpak_branch("app-id: x\nruntime: y\n")


@pytest.mark.parametrize(
    ("target", "processor", "name"),
    [
        ("windows", "x86_64", "Parro-Client-0.12.0-windows-x64.msi"),
        ("macos", "aarch64", "Parro-Client-0.12.0-macos.dmg"),
        ("flatpak", "x86_64", "Parro-Client-0.12.0-linux-x86_64.flatpak"),
        ("flatpak", "aarch64", "Parro-Client-0.12.0-linux-aarch64.flatpak"),
    ],
)
def test_installer_names(target, processor, name):
    assert tool.installer_name(target, "0.12.0", processor) == name


def test_briefcase_never_asks_and_signs_nothing_for_real():
    for target in tool.TARGETS:
        for command in tool.briefcase_commands(target):
            assert command[:3] == [sys.executable, "-m", "briefcase"]
            assert command[-1] == "--no-input"
            assert "--identity" not in command, "unsigned for now (plan §1.4)"


def test_the_flatpak_is_bundled_by_the_tool_not_by_briefcase():
    """`briefcase package` looks for the version's branch, which set_flatpak_branch replaced."""
    steps = [command[3] for command in tool.briefcase_commands("flatpak")]
    assert steps == ["create"], "the tool runs flatpak-builder itself (FLATPAK_BUILDER)"
    assert [command[3] for command in tool.briefcase_commands("windows")][-1] == "package"


def test_the_flatpak_id_matches_the_briefcase_settings():
    tomllib = pytest.importorskip("tomllib", reason="Python 3.11 and newer read TOML")
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    app = settings["tool"]["briefcase"]["app"][tool.APP]
    assert f"{app['linux']['flatpak']['bundle']}.{tool.APP}" == tool.FLATPAK_ID


def test_the_version_is_the_packages():
    import parro

    assert tool.version() == parro.__version__


def test_the_workflow_builds_all_four_with_the_tool():
    text = WORKFLOW.read_text(encoding="utf-8")
    for line in (
        "{ os: windows-latest, target: windows }",
        "{ os: macos-latest, target: macos }",
        "{ os: ubuntu-24.04, target: flatpak }",
        "{ os: ubuntu-24.04-arm, target: flatpak }",
    ):
        assert line in text
    assert "python tools/build_installer.py ${{ matrix.target }}" in text
    assert "pip install -r requirements-installers.txt" in text
    assert "permissions:\n  contents: read" in text, "the build cannot change the repository"


def test_briefcase_is_pinned():
    lines = (ROOT / "requirements-installers.txt").read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if line and not line.startswith("#")] == ["briefcase==0.4.7"]


def load_release_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_release", ROOT / "tools" / "build_release.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_release_lists_what_the_installers_tool_makes():
    release_tool = load_release_tool()
    made = {
        tool.installer_name("windows", "1.2.3", "x86_64"),
        tool.installer_name("macos", "1.2.3", "aarch64"),
        tool.installer_name("flatpak", "1.2.3", "x86_64"),
        tool.installer_name("flatpak", "1.2.3", "aarch64"),
    }
    assert set(release_tool.installer_names("1.2.3")) == made


def test_the_release_notes_say_which_file_to_pick_and_how_to_check_it():
    release_tool = load_release_tool()
    notes = release_tool.installer_notes("1.2.3")
    assert all(name in notes for name in release_tool.installer_names("1.2.3"))
    assert "blob/v1.2.3/docs/INSTALL-DESKTOP.md" in notes
    assert "gh attestation verify FILE --repo chris-swift-dev/parro-api-client" in notes
    assert "not signed" in notes


def test_the_release_workflow_attaches_and_attests_the_installers():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/installers.yml" in text
    assert "needs: [checks, installers]" in text
    assert "--packages --installers" in text
    assert "actions/attest-build-provenance@v4" in text and "dist/installers/*" in text
    assert "id-token: write" in text and "attestations: write" in text


def test_every_built_app_also_makes_one_real_https_request():
    assert [option for option, _text in tool.CHECKS] == ["--self-check", "--check-connection"]


MANIFEST_RESOURCES = f"""  - name: resources
    buildsystem: simple
    build-commands:
{tool.DESKTOP_INSTALL}      - cp --archive icons /app/share/icons
    sources:
{tool.DESKTOP_SOURCE}      - type: dir
        path: icons/
"""


def test_the_metainfo_is_installed_with_the_desktop_file():
    changed = tool.add_metainfo(MANIFEST_RESOURCES)
    assert f"install -D {tool.METAINFO} /app/share/metainfo/{tool.METAINFO}" in changed
    assert f"path: {tool.METAINFO}" in changed
    assert changed.index(tool.DESKTOP_INSTALL) < changed.index(tool.METAINFO)


def test_a_manifest_that_changed_stops_the_build():
    with pytest.raises(SystemExit):
        tool.add_metainfo("modules: []\n")


def test_the_desktop_file_gets_categories_once():
    entry = "[Desktop Entry]\nType=Application\nName=Parro Client\n"
    once = tool.add_categories(entry)
    assert once.endswith(tool.CATEGORIES) and tool.add_categories(once) == once


def test_flatpak_builder_runs_without_rofiles_and_installs_its_runtime():
    assert "--disable-rofiles-fuse" in tool.FLATPAK_BUILDER
    assert "--install-deps-from=flathub" in tool.FLATPAK_BUILDER
    assert tool.FLATPAK_BUILDER[-2:] == ["build", "manifest.yml"]


def test_the_metainfo_names_the_publisher_from_pyproject():
    import xml.etree.ElementTree as ElementTree

    tomllib = pytest.importorskip("tomllib", reason="Python 3.11 and newer read TOML")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    root = ElementTree.parse(ROOT / "packaging" / tool.METAINFO).getroot()
    assert root.findtext("id") == tool.FLATPAK_ID
    assert root.findtext("developer/name") == project["authors"][0]["name"] == "chris-swift-dev"
    assert root.findtext("url[@type='homepage']") == project["urls"]["Homepage"]
    assert root.findtext("launchable") == f"{tool.FLATPAK_ID}.desktop"
    assert root.findtext("project_license") == project["license"]
    assert {c.text for c in root.iter("category")} >= {"Education"}
    assert "not affiliated" in "".join(root.find("description").itertext())  # type: ignore[union-attr]


def test_no_e_mail_address_is_published():
    tomllib = pytest.importorskip("tomllib", reason="Python 3.11 and newer read TOML")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert all("email" not in author for author in project["authors"])


def test_the_mac_app_names_the_author_in_its_copyright():
    # Briefcase's macOS template has no author line: pyproject.toml's info table gives it one.
    tomllib = pytest.importorskip("tomllib", reason="Python 3.11 and newer read TOML")
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    info = data["tool"]["briefcase"]["app"]["parro-gui"]["macOS"]["info"]
    assert data["project"]["authors"][0]["name"] in info["NSHumanReadableCopyright"]


def test_the_msi_query_gets_its_file_and_name_as_arguments(tmp_path, monkeypatch):
    # With -Command, PowerShell glued them onto the script and the query read nothing (CI).
    seen: dict[str, Any] = {}

    def fake_run(command, folder):
        seen["command"], seen["script"] = command, Path(command[command.index("-File") + 1])
        seen["text"] = seen["script"].read_text(encoding="utf-8")
        return tool.subprocess.CompletedProcess(command, 0, "chris-swift-dev\n", "")

    monkeypatch.setattr(tool, "run", fake_run)
    msi = tmp_path / "Parro-Client.msi"
    assert tool.msi_property(msi, "Manufacturer") == "chris-swift-dev"
    command = seen["command"]
    assert "-Command" not in command and command[-2:] == [str(msi.resolve()), "Manufacturer"]
    assert "$args[0]" in seen["text"] and not seen["script"].exists()


def test_a_failed_msi_query_stops_the_build(tmp_path, monkeypatch):
    failed = tool.subprocess.CompletedProcess([], 1, "", "no such file")
    monkeypatch.setattr(tool, "run", lambda command, folder: failed)
    with pytest.raises(SystemExit):
        tool.msi_property(tmp_path / "Parro-Client.msi", "Manufacturer")
