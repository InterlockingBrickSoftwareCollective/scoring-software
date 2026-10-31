"""
SetupReceiver.py: Receives credentials from the score reflector's sync setup page

This file is part of Interlocking Brick Scoring Software.

Interlocking Brick Scoring Software is free software: you can
redistribute it and/or modify it under the terms of version 3 of
the GNU General Public License as published by the Free Software
Foundation.

Interlocking Brick Scoring Software is distributed in the hope
that it will be useful, but WITHOUT ANY WARRANTY; without even the
implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

# The score reflector's setup page, open in a browser on this computer, redeems the event's
# passcode for a sync file. It opens this receiver's own page in a window and hands it the sync
# file with postMessage, and that page posts it here. See docs/sync-setup.md in score-reflector
# for the protocol.

import http.server
import json
import socket
import threading

from typing import Callable, Optional
from urllib.parse import urlsplit

from Sync import SyncConfig, SyncConfigError

ADDRESS = "127.0.0.1"
PORT = 27526
RECEIVER_FORMAT = "score-reflector-setup-receiver"
RECEIVER_VERSION = 2

# A sync file is a few KB; refuse anything much bigger without reading it
MAX_BODY_BYTES = 64 * 1024


class SetupReceiver:
    """The receiver the setup page hands the sync file to. Only run it while the operator is
    setting up sync.

    onSyncFile is called on a receiver thread with each sync file that passes the checks, one at
    a time. It returns None once the sync file is saved, or a message for the setup page saying
    why it was refused."""

    def __init__(self, onSyncFile: Callable[[SyncConfig], Optional[str]], port: int = PORT):
        self._onSyncFile = onSyncFile
        self._busy = threading.Lock()
        self._server = _Server((ADDRESS, port), _Handler, bind_and_activate=False)
        self._server.receiver = self
        self._thread: Optional[threading.Thread] = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    def start(self):
        """Start listening. Raises OSError if the port can't be used, e.g. because another copy of
        the scoring software is already waiting for setup."""
        try:
            self._server.server_bind()
            self._server.server_activate()
        except OSError:
            self._server.server_close()
            raise
        self._thread = threading.Thread(target=self._server.serve_forever, name="SetupReceiver", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop listening. A sync file already being handled still gets its answer."""
        if self._thread is not None:
            self._server.shutdown()
            self._thread = None
        self._server.server_close()


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # On Windows, SO_REUSEADDR would let a second copy of the scoring software (or anything
        # else) bind the same port; ask for the port to ourselves instead
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _httpsOriginHost(origin) -> Optional[str]:
    """The host of an https:// origin, or None if it isn't one."""
    if not isinstance(origin, str):
        return None
    try:
        url = urlsplit(origin)
        host = url.hostname
    except ValueError:
        return None
    if url.scheme != "https" or not host or url.path or url.query or url.fragment:
        return None
    return host


# The receiver's window. Its messages are in docs/sync-setup.md; there's no confirmation step, so
# it only waits for the scoring software to try the credentials.
_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scoring Software Sync Setup</title>
<style>
	body { font: 15px/1.5 system-ui, sans-serif; margin: 2rem; color: #1c1917; background: #fafaf9; }
	@media (prefers-color-scheme: dark) { body { color: #f5f5f4; background: #0c0a09; } }
	[hidden] { display: none; }
</style>
<script defer src="/v2/setup.js"></script>
</head>
<body>
	<h1>Scoring Software Sync Setup</h1>
	<p id="waiting">Connected to the scoring software. Enter the passcode on the setup page.</p>
	<p id="no-opener" hidden>Open the event's setup page in your browser and connect from there.</p>
	<p id="testing" hidden>The scoring software is testing the connection…</p>
	<p id="done" hidden>Setup is complete. This window closes by itself.</p>
	<p id="refused" hidden>The scoring software didn't accept the credentials: <span id="message"></span> Go back to the setup page.</p>
</body>
</html>
"""

_SCRIPT = """const FORMAT = "%(format)s";
const VERSION = %(version)d;

const opener = window.opener;
let busy = false;

function show(id) {
	for (const p of document.querySelectorAll("body > p")) {
		p.hidden = p.id !== id;
	}
}

window.addEventListener("message", async (event) => {
	const data = event.data;
	// Only the window that opened this one, and only an HTTPS page. The receiver checks that the
	// page is on the sync server's host.
	if (event.source !== opener || !event.origin.startsWith("https://")) return;
	if (data?.format !== FORMAT || data?.version !== VERSION || data?.type !== "sync-file" || busy) return;

	busy = true;
	show("testing");
	let ok = false;
	let message = "";
	try {
		const response = await fetch("/v2/sync-file", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ origin: event.origin, syncFile: data.syncFile }),
		});
		ok = response.ok;
		if (!ok) {
			const body = await response.json().catch(() => null);
			message = body?.error?.message || `Error ${response.status}.`;
		}
	} catch {
		message = "The scoring software stopped responding.";
	}
	busy = false;

	event.source.postMessage({ format: FORMAT, version: VERSION, type: "result", ok, ...(ok ? {} : { message }) }, event.origin);
	if (ok) {
		show("done");
		setTimeout(() => window.close(), 1500);
	} else {
		document.getElementById("message").textContent = message;
		show("refused");
	}
});

if (opener) {
	// Nothing secret: any page that opened this window may learn that the receiver is listening.
	opener.postMessage({ format: FORMAT, version: VERSION, type: "ready" }, "*");
} else {
	show("no-opener");
}
""" % {"format": RECEIVER_FORMAT, "version": RECEIVER_VERSION}

_PAGES = {
    "/v2/setup": (_PAGE, "text/html; charset=utf-8"),
    "/v2/setup.js": (_SCRIPT, "text/javascript; charset=utf-8"),
}


class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "ScoringSoftware"
    # Don't let a connection that never sends a request hold a thread forever
    timeout = 30

    def log_message(self, format, *args):
        pass

    @property
    def _origin(self) -> str:
        return f"http://{ADDRESS}:{self.server.server_address[1]}"

    def do_GET(self):
        if not self._checkHost():
            return
        page = _PAGES.get(self.path)
        if page is None:
            return self._error(404, "Not found.")
        self._send(200, page[0].encode("utf-8"), page[1])

    def do_POST(self):
        if not self._checkHost():
            return
        if self.path != "/v2/sync-file":
            return self._error(404, "Not found.")
        # Only the receiver's own page may post here. Browsers send Origin with every POST, so this
        # refuses requests from any other site, and requests without one.
        if self.headers.get("Origin") != self._origin:
            return self._error(403, "Only the scoring software's setup window may send credentials.")
        if self.headers.get_content_type() != "application/json":
            return self._error(415, "The credentials must be sent as JSON.")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return self._error(411, "Content-Length is required.")
        if length < 0 or length > MAX_BODY_BYTES:
            return self._error(413, "That's too big to be a sync file.")

        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return self._error(400, "That isn't JSON.")
        if not isinstance(body, dict):
            return self._error(400, "This isn't a score reflector sync file.")
        try:
            config = SyncConfig.parse(json.dumps(body.get("syncFile")))
        except SyncConfigError as err:
            return self._error(400, str(err))

        # The setup page is on the same host as the sync API
        if _httpsOriginHost(body.get("origin")) != urlsplit(config.syncUrl).hostname:
            return self._error(403, "The setup page isn't on this event's score reflector.")

        receiver = self.server.receiver
        if not receiver._busy.acquire(blocking=False):
            return self._error(409, "The scoring software is already handling a sync file. Try again in a moment.")
        try:
            problem = receiver._onSyncFile(config)
        finally:
            receiver._busy.release()
        if problem is not None:
            return self._error(422, problem)
        self._json(200, {})

    def _checkHost(self) -> bool:
        """Refuse requests for any other host name, which defeats DNS rebinding."""
        if self.headers.get("Host") != f"{ADDRESS}:{self.server.server_address[1]}":
            self._error(421, "Wrong host.")
            return False
        return True

    def _send(self, status: int, data: bytes, contentType: str):
        self.send_response(status)
        self.send_header("Content-Type", contentType)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # No framing by other sites. No Cross-Origin-Opener-Policy either: it would cut the page
        # off from the setup page that opened it.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'unsafe-inline'; "
                         "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status: int, body: dict):
        self._send(status, json.dumps(body).encode("utf-8"), "application/json")

    def _error(self, status: int, message: str):
        self._json(status, {"error": {"message": message}})
