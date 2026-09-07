"""Read-only development preview. Run from the checkout; never shipped.

No PanelState, Controller, AO adapter or runtime is instantiated. The exact
product shell/assets are served, with a development-only transport fixture.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
PANEL = HERE.parents[1] / "clao" / "panel"
ASSETS = {"/" + name: (PANEL / name, mime) for name, mime in {
    "app.js": "text/javascript", "app.css": "text/css",
    "icons.svg": "image/svg+xml", "icons-LICENSE.txt": "text/plain",
}.items()}
ASSETS.update({"/" + name: (HERE / name, "text/javascript")
               for name in ("fixtures.js", "preview.js")})


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        self.send_error(403, "Development preview is read-only")

    def do_GET(self):
        if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
            self.send_error(403)
            return
        path = urlsplit(self.path).path
        nonce = self.server.preview_nonce
        if path in ("/", "/index.html"):
            html = (PANEL / "index.html").read_text(encoding="utf-8")
            html = html.replace('<script src="/app.js"',
                '<script src="/fixtures.js" nonce="__PANEL_NONCE__"></script>\n'
                '<script src="/preview.js" nonce="__PANEL_NONCE__"></script>\n'
                '<script src="/app.js"')
            body, mime = html.replace("__PANEL_NONCE__", nonce).encode(), "text/html"
        elif path in ASSETS:
            file, mime = ASSETS[path]
            body = file.read_bytes()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
            f"default-src 'self'; script-src 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; connect-src 'none'; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)


def make_server(port=0):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), PreviewHandler)
    httpd.preview_nonce = secrets.token_urlsafe(32)
    return httpd


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8768)
    args = parser.parse_args()
    with make_server(args.port) as httpd:
        print(f"Development samples only: http://127.0.0.1:{httpd.server_port}/", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
