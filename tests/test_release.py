"""Release metadata stays consistent: one version everywhere, a changelog section for it."""

import re

import parro
import parro_mcp
from parro.http import USER_AGENT
from tests.conftest import PROJECT_ROOT


def test_pyproject_and_package_have_the_same_version():
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    found = re.search(r'^version = "([^"]+)"$', pyproject, re.MULTILINE)
    assert found is not None and found[1] == parro.__version__


def test_the_version_is_used_by_the_server_and_the_user_agent():
    assert parro.__version__ == parro_mcp.SERVER_VERSION
    assert parro.__version__ in USER_AGENT


def test_the_changelog_has_a_section_for_this_version():
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{parro.__version__}] - " in changelog
