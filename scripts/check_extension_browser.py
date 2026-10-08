"""Optional Chromium smoke test with synthetic cookies, never a real Google account.

Install playwright and its Chromium in a disposable test environment first.
The temporary manifest pre-grants loopback access to emulate accepting the host
permission prompt. Real permission UI and Google authentication remain manual tests.
"""

import datetime as dt
import json
import shutil
import ssl
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from playwright.sync_api import expect, sync_playwright


def main():
    uploads = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Synthetic YT Music</h1>")

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/connect/youtube":
                uploads.append((self.path, self.headers.get("Authorization"), json.loads(raw)))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, *args):
            pass  # No credential-bearing HTTP diagnostics.

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="pms-extension-test-") as temp:
            root = Path(temp)
            extension = root / "extension"
            shutil.copytree(Path(__file__).resolve().parents[1] / "extension", extension)
            manifest = json.loads((extension / "manifest.json").read_text())
            manifest["host_permissions"].append("http://127.0.0.1/*")
            (extension / "manifest.json").write_text(json.dumps(manifest))
            # Real local TLS traffic is needed: Playwright route.fulfill bypasses
            # Chrome's network stack and therefore the webRequest header event.
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "music.youtube.com")])
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1))
                    .not_valid_after(dt.datetime.now(dt.UTC) + dt.timedelta(days=1))
                    .add_extension(x509.SubjectAlternativeName([x509.DNSName("music.youtube.com")]),
                                   critical=False).sign(key, hashes.SHA256()))
            cert_path, key_path = root / "cert.pem", root / "key.pem"
            cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                 serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            music_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(cert_path, key_path)
            music_server.socket = tls.wrap_socket(music_server.socket, server_side=True)
            threading.Thread(target=music_server.serve_forever, daemon=True).start()
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(root / "profile"), channel="chromium", headless=True,
                    args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}",
                          "--ignore-certificate-errors", "--no-proxy-server",
                          f"--host-resolver-rules=MAP music.youtube.com 127.0.0.1:{music_server.server_port}"],
                )
                try:
                    context.add_cookies([{
                        "name": "__Secure-3PAPISID", "value": "synthetic-secret",
                        "domain": "music.youtube.com", "path": "/", "secure": True,
                        "httpOnly": True, "sameSite": "None",
                    }])
                    worker = (context.service_workers[0] if context.service_workers
                              else context.wait_for_event("serviceworker"))
                    extension_id = worker.url.split("/")[2]
                    ui = context.new_page()
                    ui.goto(f"chrome-extension://{extension_id}/connect.html")
                    ui.locator("#server").fill(f"http://127.0.0.1:{server.server_port}")
                    ui.locator("#code").fill("a" * 32)
                    ui.locator("#consent").check()
                    try:
                        with context.expect_page(timeout=5000) as opened:
                            ui.locator("button[type=submit]").click()
                    except Exception:
                        print("Connection UI:", ui.locator("#status").inner_text())
                        raise
                    music = opened.value
                    music.wait_for_url("https://music.youtube.com/library")
                    music.wait_for_load_state()
                    trigger = "fetch('/youtubei/v1/browse', {method:'POST', headers:{'x-goog-authuser':'2'}})"
                    music.evaluate(trigger)
                    expect(ui.locator("#status")).to_contain_text("/now", timeout=10000)
                    assert len(uploads) == 1
                    path, bearer, body = uploads[0]
                    assert path == "/connect/youtube" and bearer == "Bearer " + "a" * 32
                    assert body["headers"]["x-goog-authuser"] == "2"
                    assert "synthetic-secret" in body["headers"]["cookie"]
                    assert body["headers"]["authorization"].startswith("SAPISIDHASH ")
                    music.evaluate(trigger)
                    assert await_pending(worker) is None
                    assert len(uploads) == 1
                    print("Chromium: UI -> isolated tab -> HttpOnly cookie capture -> one upload: OK")
                finally:
                    context.close()
                    music_server.shutdown()
                    music_server.server_close()
    finally:
        server.shutdown()
        server.server_close()


def await_pending(worker):
    return worker.evaluate("async () => (await chrome.storage.session.get('pending')).pending || null")


if __name__ == "__main__":
    main()
