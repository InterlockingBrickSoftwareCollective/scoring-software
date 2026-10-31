"""The sync transport against a real TLS server, checking how it authenticates."""

import http.server
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

import Sync
from Sync import Reflector, SyncConfig

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl command")


def openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def makeCa(dir, name):
    openssl("req", "-x509", "-sha256", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-pkeyopt", "ec_param_enc:named_curve", "-nodes", "-days", "2",
            "-subj", f"/CN={name}", "-keyout", f"{name}.key", "-out", f"{name}.crt", cwd=dir)


def issue(dir, ca, name, extension):
    with open(os.path.join(dir, f"{name}.ext"), "w") as f:
        f.write(extension)
    openssl("req", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-pkeyopt", "ec_param_enc:named_curve", "-nodes", "-subj", f"/CN={name}",
            "-keyout", f"{name}.key", "-out", f"{name}.csr", cwd=dir)
    openssl("x509", "-req", "-sha256", "-in", f"{name}.csr", "-CA", f"{ca}.crt", "-CAkey", f"{ca}.key", "-CAcreateserial",
            "-days", "2", "-extfile", f"{name}.ext", "-out", f"{name}.crt", cwd=dir)
    # PKCS#8, as in the sync file
    openssl("pkcs8", "-topk8", "-nocrypt", "-in", f"{name}.key", "-out", f"{name}.pk8", cwd=dir)


@pytest.fixture(scope="module")
def pki(tmp_path_factory):
    dir = tmp_path_factory.mktemp("pki")
    for ca in ("reflector-ca", "other-ca"):
        makeCa(dir, ca)
    issue(dir, "reflector-ca", "server", "subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth")
    issue(dir, "other-ca", "impostor", "subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth")
    issue(dir, "reflector-ca", "client", "extendedKeyUsage=clientAuth")
    issue(dir, "other-ca", "stranger", "extendedKeyUsage=clientAuth")
    return lambda name: str(dir / name)


class Server:
    """A sync API that requires a client certificate from clientCa, like the score reflector's."""

    def __init__(self, pki, serverName="server", clientCa="reflector-ca"):
        self.clientNames = []
        self.uploads = []      # (path, Content-Type, body) of every POST
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                cert = self.connection.getpeercert()
                server.clientNames.append(dict(x[0] for x in cert["subject"])["commonName"])
                body = json.dumps({"revision": 0, "matchStatus": None, "teams": []}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                server.uploads.append((self.path, self.headers["Content-Type"], body))
                reply = json.dumps({"revision": 12, "submission": {
                    "id": 3, "submittedAt": "2026-11-01T18:30:00Z", "revision": 11, "sha256": "9f86d0",
                    "size": len(body)}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(reply)))
                self.end_headers()
                self.wfile.write(reply)

            def log_message(self, *args):
                pass

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.load_cert_chain(pki(f"{serverName}.crt"), pki(f"{serverName}.key"))
        context.load_verify_locations(pki(f"{clientCa}.crt"))
        context.verify_mode = ssl.CERT_REQUIRED

        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.socket = context.wrap_socket(self.httpd.socket, server_side=True)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(pki):
    servers = []

    def make(**kwargs):
        s = Server(pki, **kwargs)
        servers.append(s)
        return s

    yield make
    for s in servers:
        s.close()


def config(pki, port, client="client", ca="reflector-ca"):
    read = lambda name: open(pki(name)).read()
    return SyncConfig.parse(json.dumps({
        "format": "score-reflector-event-sync",
        "version": 1,
        "event": {"code": "fall-qual", "name": "Fall Qualifier"},
        "syncUrl": f"https://localhost:{port}/api/v1/events/fall-qual",
        "caCertificate": read(f"{ca}.crt"),
        "clientCertificate": read(f"{client}.crt"),
        "clientKey": read(f"{client}.pk8"),
        "expiresAt": (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }))


def test_connects_with_the_sync_files_client_certificate(pki, server):
    s = server()
    assert Sync.checkConnection(config(pki, s.port)) is None
    assert s.clientNames == ["client"]


def test_a_server_not_certified_by_the_sync_files_ca_is_refused(pki, server, monkeypatch):
    s = server(serverName="impostor")
    # Trusting the impostor's CA through the environment must not matter
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", pki("other-ca.crt"))
    monkeypatch.setenv("CURL_CA_BUNDLE", pki("other-ca.crt"))

    problem = Sync.checkConnection(config(pki, s.port))
    assert problem is not None and "server's certificate" in problem
    assert s.clientNames == []


def test_a_certificate_the_server_does_not_accept_is_reported(pki, server):
    s = server(clientCa="other-ca")
    problem = Sync.checkConnection(config(pki, s.port))
    assert problem is not None
    assert "refused" in problem and "certificate" in problem


def test_an_unreachable_server_is_reported(pki):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    problem = Sync.checkConnection(config(pki, port), timeout=2)
    assert problem is not None and "reach" in problem


def test_an_expired_sync_file_is_reported_without_connecting(pki, server):
    s = server()
    expired = replace(config(pki, s.port), expiresAt=datetime.now(UTC) - timedelta(minutes=1))
    problem = Sync.checkConnection(expired)
    assert problem is not None and "expired" in problem
    assert s.clientNames == []


def test_a_sync_file_with_a_mismatched_key_is_refused(pki):
    mismatched = replace(config(pki, 1), clientKey=open(pki("stranger.pk8")).read())
    with pytest.raises(Sync.SyncConfigError):
        Reflector(mismatched)


def test_closing_leaves_no_key_material_on_disk(pki, server, tmp_path, monkeypatch):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    s = server()
    reflector = Reflector(config(pki, s.port))
    reflector.request("GET", "/state")
    assert list(tmp_path.iterdir())
    reflector.close()
    assert list(tmp_path.iterdir()) == []


def test_submitting_uploads_the_database_file(pki, server):
    s = server()
    reflector = Reflector(config(pki, s.port))
    try:
        database = b"SQLite format 3\x00" + bytes(range(256)) * 64
        result = reflector.submit(database, 11)
    finally:
        reflector.close()
    assert s.uploads == [("/api/v1/events/fall-qual/submissions?baseRevision=11", "application/vnd.sqlite3", database)]
    assert result["submission"]["size"] == len(database)
