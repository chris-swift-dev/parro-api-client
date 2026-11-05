"""The README's terminal pictures (docs/images/terminal-*.svg) match the snapshot files.

They are drawn by tools/make_readme_images.py from tests/snapshots/, which test_rendering.py keeps
in step with the code. After a layout change, update the snapshots, then:

    python3 tools/make_readme_images.py
"""

import importlib.util
import xml.dom.minidom
from pathlib import Path
from types import ModuleType

import pytest

TOOL = Path(__file__).resolve().parent.parent / "tools" / "make_readme_images.py"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_readme_images", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()
IMAGES = tool.all_images()


@pytest.mark.parametrize("path", list(IMAGES), ids=[p.name for p in IMAGES])
def test_picture_matches_its_snapshot(path):
    assert path.exists(), f"{path.name} missing: run python3 tools/make_readme_images.py"
    assert path.read_text(encoding="utf-8") == IMAGES[path], (
        f"{path.name} is out of date: run python3 tools/make_readme_images.py"
    )


@pytest.mark.parametrize("path", list(IMAGES), ids=[p.name for p in IMAGES])
def test_picture_is_valid_svg_with_a_title(path):
    document = xml.dom.minidom.parseString(IMAGES[path])
    titles = document.getElementsByTagName("title")
    title_text = titles[0].firstChild if titles else None
    assert isinstance(title_text, xml.dom.minidom.Text)
    assert "invented example data" in title_text.data


def test_every_picture_has_a_light_and_a_dark_variant():
    names = {p.name for p in IMAGES}
    for picture in tool.PICTURES:
        assert {
            f"terminal-{picture.snapshot}-light.svg",
            f"terminal-{picture.snapshot}-dark.svg",
        } <= names


def test_wide_characters_take_two_cells():
    assert tool.cell_width("abc") == 3
    assert tool.cell_width("📌 x") == 4
