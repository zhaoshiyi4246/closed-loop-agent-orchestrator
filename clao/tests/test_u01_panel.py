"""U01 finite static routes and actual Edge workbench interactions.

Playwright/Node are development tools only; no browser dependency is installed
in the product venv. Set U01_NODE and NODE_PATH for the browser test.
"""
import importlib.util
import threading
from types import SimpleNamespace
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
    ("/icons.svg", "image/svg+xml"),
    ("/icons-LICENSE.txt", "text/plain"),
])
def test_only_declared_static_assets_and_existing_host_boundary(http_panel, path, mime):
    status, headers, body = request(http_panel, path=path)
    assert status == 200 and headers["Content-Type"].startswith(mime)
    assert body and headers["X-Content-Type-Options"] == "nosniff"
    assert http_panel.httpd.panel_nonce.encode() not in body
    assert request(http_panel, path=path, headers={"Host": "evil.example"})[0] == 403


@pytest.mark.parametrize("path", [
    "/fixtures.js", "/preview.js", "/dev/panel/fixtures.js", "/dev/panel/preview.py",
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
    assert html.count(b'nonce="' + http_panel.httpd.panel_nonce.encode() + b'"') == 1
    assert b'src="/app.js"' in html and b'fixtures.js' not in html
    assert b"https://" not in html  # no runtime CDN / remote fonts


def test_edge_workbench_preview_keyboard_themes_and_actual_200_percent_zoom(http_panel, monkeypatch, tmp_path):
    node = os.environ.get("U01_NODE") or shutil.which("node")
    if not node:
        pytest.skip("Development Node/Playwright unavailable; set U01_NODE and NODE_PATH")
    monkeypatch.setattr(server, "_load_ao_projects", lambda: [{"id": "safe-project", "name": "本地测试项目", "path": "测试路径 / 中文 空格", "kind": "git"}])
    # Real Panel/SQLite transport with isolated execution facts; no Worker runs.
    import time
    http_panel.state.rt.mission_dict["objective"] = "为订单导入增加格式校验"
    http_panel.store.record_mission("M-F04", {"state": "RUNNING",
        "mission": http_panel.state.rt.mission_dict, "reason": "正在补充输入校验，完成后运行验收命令。"})
    http_panel.store.record_phase("M-F04", {"phase": "observation_wait", "status": "running",
        "started_epoch": time.time() - 32, "attempt": 1, "reason": "等待下次观察"})
    http_panel.state.thread = SimpleNamespace(is_alive=lambda: True)
    dev = Path(__file__).resolve().parents[2] / "dev" / "panel"
    if not dev.is_dir():
        pytest.skip("Development preview is not included in the release")
    spec = importlib.util.spec_from_file_location("u01_preview", dev / "preview.py")
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    httpd = preview.make_server()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    output = os.environ.get("U01_SCREENSHOTS") or str(tmp_path / "screenshots")
    try:
        result = subprocess.run([node, str(dev / "browser.cjs"), http_panel.origin, output,
                                 f"http://127.0.0.1:{httpd.server_port}"],
                                capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "U01_BROWSER_PASS" in result.stdout
    print(result.stdout)


@pytest.mark.parametrize("query", ["?preview=running", "?preview=cancelled", "?state=success"])
def test_old_preview_urls_are_real_product_pages(http_panel, query):
    _, headers, html = request(http_panel, path="/" + query)
    assert html == request(http_panel, path="/")[2]
    assert b"preview" not in html and b"fixtures" not in html
    assert "connect-src 'self'" in headers["Content-Security-Policy"]
    assert request(http_panel)[2]["mission"]["id"] == "M-F04"


def test_development_resources_are_outside_release_mapping():
    root = Path(__file__).resolve().parents[2]
    manifest = root / "packaging" / "release-manifest.txt"
    if not manifest.exists():
        pytest.skip("Source checkout release mapping check")
    sources = [line.split("=>")[0].strip() for line in manifest.read_text(encoding="utf-8").splitlines()
               if "=>" in line and not line.startswith("#")]
    resources = list((root / "dev" / "panel").glob("*"))
    assert {p.name for p in resources} >= {"fixtures.js", "preview.js", "preview.py", "browser.cjs"}
    for path in resources:
        relative = path.relative_to(root).as_posix()
        assert not any(relative == source or source.endswith("/") and relative.startswith(source) for source in sources)
    assert not (server.PANEL_DIR / "fixtures.js").exists()
