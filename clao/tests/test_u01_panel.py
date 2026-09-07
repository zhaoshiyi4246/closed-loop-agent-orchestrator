"""U01 finite static routes and actual Edge workbench interactions.

Playwright/Node are development tools only; no browser dependency is installed
in the product venv. Set U01_NODE and NODE_PATH for the browser test.
"""
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest

from panel import server
from tests.test_f04_panel_boundaries import panel, http_panel, request  # noqa: F401


@pytest.mark.parametrize("path,mime", [
    ("/app.css", "text/css"), ("/app.js", "text/javascript"),
    ("/fixtures.js", "text/javascript"), ("/icons.svg", "image/svg+xml"),
    ("/icons-LICENSE.txt", "text/plain"),
])
def test_only_declared_static_assets_and_existing_host_boundary(http_panel, path, mime):
    status, headers, body = request(http_panel, path=path)
    assert status == 200 and headers["Content-Type"].startswith(mime)
    assert body and headers["X-Content-Type-Options"] == "nosniff"
    assert http_panel.httpd.panel_nonce.encode() not in body
    assert request(http_panel, path=path, headers={"Host": "evil.example"})[0] == 403


@pytest.mark.parametrize("path", [
    "/server.py", "/../config/default.yaml", "/%2e%2e/config/default.yaml",
    "/%252e%252e/config/default.yaml", "/app.js/../server.py", "/icons-LICENSE.txt/secret",
    "/E:/private.txt", "/app%2ejs", "/app.js%00", "/..%5cserver.py",
])
def test_asset_split_does_not_expand_file_access(http_panel, path):
    status, _, body = request(http_panel, path=path)
    assert status in (400, 404) and body.get("ok") is False


def test_icons_are_valid_local_subset_with_complete_license(http_panel):
    _, _, body = request(http_panel, path="/icons.svg")
    root = ET.fromstring(body)  # catches duplicate namespace: empty icons in browsers
    ns = "{http://www.w3.org/2000/svg}"
    symbols = root.findall(ns + "symbol")
    assert {s.get("id") for s in symbols} == {"arrow-left", "arrow-right", "chevron-right", "cpu", "layout-dashboard", "list-checks", "plus", "settings", "shield-check", "sliders-horizontal", "sun", "x"}
    assert all(s.get("viewBox") == "0 0 24 24" and len(s) for s in symbols)
    for node in root.iter():
        assert node.tag.removeprefix(ns) in {"svg", "symbol", "path", "rect", "circle", "line", "polyline", "polygon", "ellipse"}
        assert not any(k.startswith("on") or k in ("href", "style") for k in node.attrib)
    _, _, license_bytes = request(http_panel, path="/icons-LICENSE.txt")
    license_text = license_bytes.decode()
    assert "ISC License" in license_text and "MIT License" in license_text
    assert "Copyright" in license_text and "THE SOFTWARE IS PROVIDED" in license_text


def test_split_scripts_still_require_page_nonce(http_panel):
    _, headers, html = request(http_panel, path="/")
    csp = headers["Content-Security-Policy"]
    assert "script-src 'nonce-" in csp
    script_policy = csp.split("script-src ")[1].split(";")[0]
    assert "unsafe-inline" not in script_policy and "'self'" not in script_policy
    assert html.count(b'nonce="' + http_panel.httpd.panel_nonce.encode() + b'"') == 2
    assert b'src="/app.js"' in html and b'src="/fixtures.js"' in html
    assert b"https://" not in html  # no runtime CDN / remote fonts


def test_edge_workbench_preview_keyboard_themes_and_actual_200_percent_zoom(http_panel, monkeypatch, tmp_path):
    node = os.environ.get("U01_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Development Node/Playwright unavailable; set U01_NODE and NODE_PATH")
    monkeypatch.setattr(server, "_load_ao_projects", lambda: [{"id": "safe-project", "name": "本地测试项目", "path": "测试路径 / 中文 空格", "kind": "git"}])
    output = os.environ.get("U01_SCREENSHOTS") or str(tmp_path / "screenshots")
    result = subprocess.run([node, str(Path(__file__).with_name("u01_browser.cjs")), http_panel.origin, output],
                            capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "U01_BROWSER_PASS" in result.stdout
    print(result.stdout)
