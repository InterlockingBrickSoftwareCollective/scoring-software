"""The receiver for credentials from the score reflector's sync setup page."""

import http.client
import json
import socket
import threading

import pytest

from SetupReceiver import SetupReceiver
from test_sync import syncFile

ORIGIN = "https://scores.example.org"


@pytest.fixture
def receiver():
    received = []
    answers = []

    def onSyncFile(config):
        received.append(config)
        return answers.pop(0) if answers else None

    r = SetupReceiver(onSyncFile, port=0)
    r.start()
    r.received, r.answers = received, answers
    yield r
    r.stop()


def request(receiver, method, path, body=None, host=None, **headers):
    conn = http.client.HTTPConnection("127.0.0.1", receiver.port, timeout=5)
    conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
    conn.putheader("Host", host or f"127.0.0.1:{receiver.port}")
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers.setdefault("Content-Type", "application/json")
        headers.setdefault("Content-Length", str(len(data)))
    for name, value in headers.items():
        conn.putheader(name.replace("_", "-"), value)
    conn.endheaders(data)
    response = conn.getresponse()
    payload = response.read()
    conn.close()
    response.body = payload
    response.json = json.loads(payload) if response.getheader("Content-Type") == "application/json" else None
    return response


def delivery(origin=ORIGIN, **overrides):
    return {"origin": origin, "syncFile": syncFile(**overrides)}


def post(receiver, body=None, **headers):
    headers.setdefault("Origin", f"http://127.0.0.1:{receiver.port}")
    return request(receiver, "POST", "/v2/sync-file", delivery() if body is None else body, **headers)


@pytest.mark.parametrize("path, contentType", [
    ("/v2/setup", "text/html; charset=utf-8"),
    ("/v2/setup.js", "text/javascript; charset=utf-8"),
])
def test_serves_its_setup_window(receiver, path, contentType):
    response = request(receiver, "GET", path)
    assert response.status == 200
    assert response.getheader("Content-Type") == contentType
    assert "frame-ancestors 'none'" in response.getheader("Content-Security-Policy")
    # It would cut the window off from the setup page
    assert response.getheader("Cross-Origin-Opener-Policy") is None


def test_the_setup_window_speaks_version_2(receiver):
    script = request(receiver, "GET", "/v2/setup.js").body.decode()
    assert 'const FORMAT = "score-reflector-setup-receiver";' in script
    assert "const VERSION = 2;" in script


@pytest.mark.parametrize("host", ["localhost:{port}", "127.0.0.1", "evil.example:{port}", "127.0.0.1:1"])
def test_other_hosts_are_refused(receiver, host):
    # DNS rebinding sends the attacker's host name
    host = host.format(port=receiver.port)
    assert request(receiver, "GET", "/v2/setup", host=host).status == 421
    assert post(receiver, host=host).status == 421
    assert receiver.received == []


@pytest.mark.parametrize("origin", [None, "null", "https://scores.example.org", "http://localhost:{port}"])
def test_only_the_setup_window_may_post(receiver, origin):
    headers = {"Origin": origin.format(port=receiver.port)} if origin is not None else {}
    if origin is None:
        response = request(receiver, "POST", "/v2/sync-file", delivery())
    else:
        response = post(receiver, **headers)
    assert response.status == 403
    assert receiver.received == []


def test_a_sync_file_from_its_setup_page_is_accepted(receiver):
    response = post(receiver)
    assert response.status == 200
    assert response.getheader("Access-Control-Allow-Origin") is None
    [config] = receiver.received
    assert config.eventName == "Fall Qualifier"
    assert config.host == "scores.example.org:8443"


@pytest.mark.parametrize("origin", ["https://evil.example", "http://scores.example.org", None, "https://scores.example.org/x"])
def test_the_setup_page_must_be_on_the_sync_file_host(receiver, origin):
    response = post(receiver, delivery(origin=origin))
    assert response.status == 403
    assert receiver.received == []


def test_a_refusal_is_explained_to_the_setup_page(receiver):
    receiver.answers.append("Couldn't reach the score reflector.")
    response = post(receiver)
    assert response.status == 422
    assert response.json == {"error": {"message": "Couldn't reach the score reflector."}}


@pytest.mark.parametrize("body", [delivery(version=2), {"origin": ORIGIN}, ["not", "an", "object"]])
def test_an_unusable_sync_file_is_refused_without_bothering_the_operator(receiver, body):
    response = post(receiver, body)
    assert response.status == 400
    assert response.json["error"]["message"]
    assert receiver.received == []


def test_the_sync_file_must_be_json(receiver):
    assert post(receiver, Content_Type="text/plain").status == 415


def test_an_oversized_body_is_refused_unread(receiver):
    assert post(receiver, {"x": "y" * 70000}).status == 413


def test_one_sync_file_is_handled_at_a_time(receiver):
    release = threading.Event()
    entered = threading.Event()

    def slow(config):
        entered.set()
        release.wait(5)
        return None

    receiver._onSyncFile = slow
    first = {}
    thread = threading.Thread(target=lambda: first.update(
        response=post(receiver)))
    thread.start()
    assert entered.wait(5)
    assert post(receiver).status == 409
    release.set()
    thread.join(5)
    assert first["response"].status == 200


def test_listens_only_on_loopback_and_stops(receiver):
    port = receiver.port
    assert receiver._server.server_address[0] == "127.0.0.1"
    receiver.stop()
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1)


def test_a_port_in_use_is_reported(receiver):
    with pytest.raises(OSError):
        SetupReceiver(lambda config: None, port=receiver.port).start()
