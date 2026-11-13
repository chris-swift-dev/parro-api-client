"""The landing page of the GitHub Pages site, and Swagger UI's move to api/ (Plan 16 §5)."""

import importlib.util
import re
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parent.parent
GITHUB = "https://github.com/chris-swift-dev/parro-api-client"


def load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_landing", ROOT / "tools" / "build_landing.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = load_tool()
NAMES = tool.build_release().installer_names("0.12.0")
SIZES = [96, 141, 82, 79]


def release(tag: str = "v0.12.0", names: list[str] = NAMES, **extra: Any) -> dict[str, Any]:
    assets = [{"name": n, "size": s * 1024 * 1024} for n, s in zip(names, SIZES, strict=False)]
    assets.append({"name": "SHA256SUMS", "size": 900})
    return {"tag_name": tag, "draft": False, "prerelease": False, "assets": assets, **extra}


class Page(HTMLParser):
    """Every address on the page, with the tag and attribute it is in."""

    def __init__(self) -> None:
        super().__init__()
        self.addresses: list[tuple[str, str, str]] = []
        self.ids: set[str] = set()
        self.head_scripts: list[dict[str, str | None]] = []
        self.meta: dict[str, str] = {}
        self._in_head = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "head":
            self._in_head = True
        if tag == "script" and self._in_head:
            self.head_scripts.append(values)
        if tag == "meta" and values.get("http-equiv"):
            self.meta[str(values["http-equiv"])] = str(values.get("content"))
        if values.get("id"):
            self.ids.add(str(values["id"]))
        for name in ("href", "src"):
            if values.get(name):
                self.addresses.append((tag, name, str(values[name])))
        for part in str(values.get("srcset") or "").split(","):
            if part.strip():
                self.addresses.append((tag, "srcset", part.split()[0]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._in_head = False


def build(out: Path, answer: dict[str, Any] | None) -> tuple[str | None, str, Page]:
    (out / "api").mkdir(parents=True)
    for name in ("api/index.html", "api/parro.openapi.json", "parro.openapi.json"):
        (out / name).write_text("{}", encoding="utf-8")
    version = tool.build(out, answer)
    text = (out / "index.html").read_text(encoding="utf-8")
    page = Page()
    page.feed(text)
    return version, text, page


@pytest.fixture
def built(tmp_path) -> tuple[Path, str, Page]:
    _version, text, page = build(tmp_path, release())
    return tmp_path, text, page


# ----------------------------------------------------------------------------- the downloads


def test_the_buttons_carry_the_latest_releases_installers(built):
    _out, text, _page = built
    for name, size in zip(NAMES, SIZES, strict=True):
        assert f'href="{GITHUB}/releases/download/v0.12.0/{name}"' in text
        assert f"{size} MB" in text
    assert "Version 0.12.0." in text and f"{GITHUB}/releases/tag/v0.12.0" in text


def test_the_buttons_are_named_like_the_release_files():
    _version, items = tool.downloads(release())
    assert [item.url.rsplit("/", 1)[-1] for item in items] == NAMES
    assert [item.key for item in items] == ["windows", "macos", "linux-x86_64", "linux-aarch64"]


@pytest.mark.parametrize(
    "answer",
    [
        None,  # no answer from GitHub
        release("v0.11.0", names=[]),  # a release from before the installers
        release(names=NAMES[:3]),  # one installer missing
        release(draft=True),
        release(prerelease=True),
        release("v0.12.0rc1"),
        release('v0.12.0"><script>alert(1)</script>'),
        {"tag_name": 12},
    ],
    ids=["none", "old", "missing", "draft", "prerelease", "rc", "odd-tag", "not-text"],
)
def test_without_a_release_with_installers_the_buttons_go_to_the_releases_page(tmp_path, answer):
    version, text, page = build(tmp_path, answer)
    assert version is None
    buttons = [a for tag, name, a in page.addresses if "/releases" in a and tag == "a"]
    assert f"{GITHUB}/releases" in buttons
    assert "/download/" not in text and "<script>alert" not in text
    assert text.count("on the releases page") == 4


def test_nothing_from_the_answer_but_the_version_and_sizes_reaches_the_page(tmp_path):
    answer = release()
    for asset in answer["assets"]:
        asset["browser_download_url"] = "https://example.com/evil.msi"
    answer["html_url"] = "https://example.com/release"
    _version, text, _page = build(tmp_path, answer)
    assert "example.com" not in text


# ----------------------------------------------------------------------------- what is on it


def test_every_link_works_or_goes_to_github(built):
    out, _text, page = built
    for _tag, _name, address in page.addresses:
        parsed = urlparse(address)
        if parsed.scheme:
            assert parsed.scheme == "https" and parsed.netloc == "github.com", address
            assert parsed.path.startswith("/chris-swift-dev/parro-api-client"), address
        elif address.startswith("#"):
            assert address[1:] in page.ids, address
        else:
            assert (out / parsed.path).exists(), address


def test_nothing_is_loaded_from_another_site(built):
    _out, _text, page = built
    loaded = [a for tag, name, a in page.addresses if name in ("src", "srcset") or tag == "link"]
    assert loaded and all(not urlparse(address).scheme for address in loaded)
    policy = page.meta["Content-Security-Policy"]
    assert "default-src 'none'" in policy
    assert all(f"{kind} 'self'" in policy for kind in ("img-src", "style-src", "script-src"))
    assert "connect-src" not in policy, "default-src 'none' already allows no requests"


def test_the_script_makes_no_requests():
    script = (ROOT / "site" / "landing" / "landing.js").read_text(encoding="utf-8")
    for request in ("fetch(", "XMLHttpRequest", "sendBeacon", "import(", "WebSocket", "http"):
        assert request not in script


def test_the_disclaimer_is_at_the_top_and_in_the_footer(built):
    _out, text, _page = built
    assert "not affiliated with Topicus, ParnasSys or Parro" in text
    assert "Not affiliated with or endorsed by Topicus, ParnasSys or Parro" in text
    assert "invented example data" in text.lower()


def test_the_pictures_are_the_invented_ones_from_docs(built):
    out, _text, page = built
    pictures = {a for tag, name, a in page.addresses if tag in ("img", "source")}
    assert pictures <= {path for path in tool.IMAGES.values()}
    for source, target in tool.IMAGES.items():
        assert (out / target).read_bytes() == source.read_bytes()


def test_every_placeholder_is_filled(built):
    _out, text, _page = built
    assert "{{" not in text and "}}" not in text


def test_the_page_needs_swagger_ui_in_api(tmp_path):
    with pytest.raises(SystemExit):
        tool.build(tmp_path, release())


# ----------------------------------------------------------------------------- old links


def test_old_swagger_ui_links_are_sent_to_api(built):
    _out, _text, page = built
    assert page.head_scripts == [{"src": "landing.js"}], "in <head>, not deferred: before drawing"
    script = (ROOT / "site" / "landing" / "landing.js").read_text(encoding="utf-8")
    forward = re.search(r"function toSwaggerUi\(\) \{(.*?)\n\}", script, re.DOTALL)
    assert forward is not None
    assert 'hash.indexOf("#/") === 0' in forward.group(1)
    assert 'location.replace("api/" + window.location.hash)' in forward.group(1)
    assert "toSwaggerUi();" in script and '"hashchange", toSwaggerUi' in script


def test_the_site_puts_swagger_ui_in_api_and_keeps_the_old_spec_address():
    script = (ROOT / "tools" / "build_site.sh").read_text(encoding="utf-8")
    assert 'cp "$dist/$f" "$out/api/"' in script
    assert 'cp "$spec" "$out/api/parro.openapi.json"' in script
    assert 'cp "$spec" "$out/parro.openapi.json"' in script
    assert script.rstrip().endswith('python3 tools/build_landing.py "$out" "$@"')
    initializer = (ROOT / "site" / "swagger-initializer.js").read_text(encoding="utf-8")
    assert 'url: "parro.openapi.json"' in initializer, "relative: it finds the copy in api/"


def test_links_in_this_repository_point_to_the_new_places():
    site = "https://chris-swift-dev.github.io/parro-api-client/"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"[Swagger UI]({site}api/)" in readme and f'<a href="{site}api/">' in readme
    assert f"[Swagger UI]({site}api/)" in (ROOT / "docs" / "API-NOTES.md").read_text(
        encoding="utf-8"
    )
    screenshots = (ROOT / "tools" / "swagger_screenshots.py").read_text(encoding="utf-8")
    assert f'PAGES_SITE = "{site}api/"' in screenshots


# ----------------------------------------------------------------------------- the workflow


def test_the_site_is_built_again_when_a_release_is_published():
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    assert "release:\n    types: [published]" in workflow
    follow = workflow[workflow.index("  follow-release:") : workflow.index("  build:")]
    assert "if: github.event_name == 'release'" in follow
    assert "actions: write" in follow
    assert 'gh workflow run pages.yml --ref main --repo "$GITHUB_REPOSITORY"' in follow
    build_job = workflow[workflow.index("  build:") : workflow.index("  deploy:")]
    assert "if: github.event_name != 'release'" in build_job
    assert "GITHUB_TOKEN: ${{ github.token }}" in build_job
    assert "if: github.ref == 'refs/heads/main'" in workflow[workflow.index("  deploy:") :]


def test_the_token_is_never_printed():
    source = (ROOT / "tools" / "build_landing.py").read_text(encoding="utf-8")
    prints = re.findall(r"print\((.*?)\)\n", source, re.DOTALL)
    assert prints and all("token" not in call.lower() for call in prints)


def test_every_github_file_link_names_a_file_in_this_repository(built):
    # Such a file reaches main with the merge that also deploys the page (Pages deploys from main).
    _out, _text, page = built
    prefix = f"{GITHUB}/blob/main/"
    files = [a.removeprefix(prefix) for _tag, _name, a in page.addresses if a.startswith(prefix)]
    assert "docs/INSTALL-DESKTOP.md" in files
    assert all((ROOT / name).is_file() for name in files), files
