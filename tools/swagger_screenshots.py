"""Screenshots of Swagger UI for the README (make_readme_images.py --swagger).

The page is the one the GitHub Pages site serves: stock Swagger UI showing
openapi/parro.public.openapi.json (the spec without any sample values). It is served from a local
server on 127.0.0.1 and photographed by Firefox without a window. Nothing talks to Parro: no
"Try it out", no token, so a screenshot can only show documentation.

Two pictures:
  swagger-operations.png    the title and the operations of the four main sections
  swagger-calendar-sync.png GET /calendar/sync expanded (its description; no parameters, no
                            "Try it out")

Swagger UI files: node_modules/swagger-ui-dist when present (npm ci --ignore-scripts), otherwise
downloaded once from the project's own Pages site.

Firefox takes its screenshot at the page's load event, but Swagger UI finishes drawing a bit later.
So the page also loads one image from the local server that answers only after SETTLE_SECONDS;
that holds the load event back until the drawing is done.

Firefox photographs the window, not the whole page. So each picture is taken twice: the first time
the page reports its drawn height to the local server, the second time the window has that height.
"""

import json
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "openapi" / "parro.public.openapi.json"
LOCAL_DIST = ROOT / "node_modules" / "swagger-ui-dist"
PAGES_SITE = "https://chris-swift-dev.github.io/parro-api-client/"
ASSETS = ["swagger-ui.css", "index.css", "swagger-ui-bundle.js"]
SETTLE_SECONDS = 4
WIDTH = 1200
MEASURING_HEIGHT = 300  # the first pass: smaller than any page, so the page's own height counts
# A transparent 1×1 GIF, the answer of the delayed request.
PIXEL = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f904010000000"
    "02c000000000100010000020144003b"
)

# Per picture: Swagger UI options, extra CSS and the address part after '#'.
VIEWS: dict[str, dict[str, Any]] = {
    "swagger-operations": {
        "options": {"docExpansion": "list"},
        # Only the four sections a reader of the README cares about.
        "css": ".opblock-tag-section:has(#operations-tag-Auth),"
        ".opblock-tag-section:has(#operations-tag-Misc){display:none !important}",
        "anchor": "",
    },
    "swagger-calendar-sync": {
        "options": {"docExpansion": "list", "filter": "Events"},
        "css": ".information-container,.scheme-container,.filter-container,"
        ".parameters-container,.responses-wrapper,.opblock-section-header{display:none !important}",
        "anchor": "#/Events/getCalendarSync",
    },
}

PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Parro REST API (unofficial)</title>
<link rel="stylesheet" href="swagger-ui.css"><link rel="stylesheet" href="index.css">
<style>html,body{{margin:0;background:#fff;overflow:hidden}}
.swagger-ui .wrapper{{padding-bottom:24px}} {css}</style>
</head><body>
<div id="swagger-ui"></div>
<img src="settle.gif" alt="" width="1" height="1" style="position:absolute;top:0">
<script>
setTimeout(function () {{
  var height = document.documentElement.scrollHeight;
  new Image().src = "height.gif?view={name}&height=" + height;
}}, {report_after_ms});
</script>
<script src="swagger-ui-bundle.js"></script>
<script>
window.ui = SwaggerUIBundle(Object.assign({{
  url: "parro.openapi.json", dom_id: "#swagger-ui", deepLinking: true,
  defaultModelsExpandDepth: -1, validatorUrl: null,
  presets: [SwaggerUIBundle.presets.apis], layout: "BaseLayout"
}}, {options}));
</script></body></html>
"""


def take_screenshots(images: Path) -> list[Path]:
    """Write both pictures into `images`; returns their paths."""
    firefox = shutil.which("firefox")
    if firefox is None:
        raise SystemExit("--swagger needs Firefox (firefox on the PATH)")
    with tempfile.TemporaryDirectory(prefix="parro-swagger-") as temporary:
        site = Path(temporary) / "site"
        site.mkdir()
        copy_assets(site)
        (site / "parro.openapi.json").write_text(json.dumps(short_spec()), encoding="utf-8")
        for name, view in VIEWS.items():
            page = PAGE.format(
                css=view["css"],
                options=json.dumps(view["options"]),
                name=name,
                report_after_ms=(SETTLE_SECONDS - 1) * 1000,
            )
            (site / f"{name}.html").write_text(page, encoding="utf-8")
        server = _Server(site)
        with server as port:
            written = []
            for name, view in VIEWS.items():
                target = images / f"{name}.png"
                url = f"http://127.0.0.1:{port}/{name}.html{view['anchor']}"
                profile = Path(temporary) / "profile"
                screenshot(firefox, profile, url, target, height=MEASURING_HEIGHT)
                height = server.heights.get(name)
                if height is None:
                    raise SystemExit(f"{name}: the page did not report its height")
                screenshot(firefox, profile, url, target, height=height)
                written.append(target)
    return written


def short_spec() -> Any:
    """The public spec with only the first paragraph of its long introduction."""
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec["info"]["description"] = spec["info"]["description"].split("\n\n")[0]
    return spec


def copy_assets(site: Path) -> None:
    for name in ASSETS:
        local = LOCAL_DIST / name
        if local.exists():
            shutil.copyfile(local, site / name)
            continue
        with urllib.request.urlopen(PAGES_SITE + name, timeout=30) as response:  # noqa: S310
            (site / name).write_bytes(response.read())


class _Server:
    def __init__(self, site: Path) -> None:
        heights: dict[str, int] = {}
        self.heights = heights

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(site), **kwargs)

            def do_GET(self) -> None:  # noqa: N802 (the name http.server calls)
                if self.path.startswith("/settle.gif"):
                    time.sleep(SETTLE_SECONDS)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/gif")
                    self.send_header("Content-Length", str(len(PIXEL)))
                    self.end_headers()
                    self.wfile.write(PIXEL)
                    return
                if self.path.startswith("/height.gif?"):
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    heights[query["view"][0]] = int(query["height"][0])
                    self.send_response(204)
                    self.end_headers()
                    return
                super().do_GET()

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)

    def __enter__(self) -> int:
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return int(self.httpd.server_address[1])

    def __exit__(self, *exc: object) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


def screenshot(firefox: str, profile: Path, url: str, target: Path, height: int) -> None:
    """A screenshot of the window, with a profile of its own (a running Firefox does not matter)."""
    profile.mkdir(exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    command = [
        firefox, "--headless", "--no-remote", "--profile", str(profile),
        f"--window-size={WIDTH},{height}", "--screenshot", str(target), url,
    ]  # fmt: skip
    subprocess.run(command, check=True, capture_output=True, timeout=120)
    if not target.exists():
        raise SystemExit(f"Firefox wrote no screenshot for {url}")
