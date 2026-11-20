"""
Sync.py: Sync adapter to score-reflector

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

import json
import os
import shutil
import ssl
import tempfile
import threading
import time

from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests

import Events

# The event sync file downloaded from the score reflector's admin UI, saved in the database
# under this key. See docs/sync-api.md in score-reflector.
CONFIG_META_KEY = "sync.config"
SYNC_FILE_FORMAT = "score-reflector-event-sync"
SYNC_FILE_VERSION = 1

# Limits enforced by the score reflector
MAX_TEAM_NUMBER = 99999999
MAX_TEAM_NAME_BYTES = 200
MAX_SCORE = 1000000
MAX_SCORESHEET_TASKS = 500
MAX_SCORESHEET_STRING_BYTES = 64

# Match statuses that are about one match; the others are event-wide and report match 0
MATCH_STATUSES = ("preparing", "running", "scoring")
EVENT_STATUSES = ("practice", "opening_ceremonies", "closing_ceremonies")

# Seconds to wait before each retry after a failure; the last delay repeats
RETRY_DELAYS = (1, 2, 4, 8, 15, 30)

# While the event is finalized, check this often whether an administrator has unfinalized it
FINALIZED_POLL_SECONDS = 60

# Submitting uploads the whole database, which the score reflector allows up to 10 minutes for
MAX_SUBMISSION_BYTES = 64 * 1024 * 1024
SUBMISSION_TIMEOUT = 15 * 60
SUBMISSION_ATTEMPTS = 3


class SyncConfigError(ValueError):
    """The sync file can't be used. The message is suitable for showing to the operator."""


@dataclass(frozen=True)
class SyncConfig:
    """A validated event sync file."""
    eventCode: str
    eventName: str
    syncUrl: str
    caCertificate: str
    clientCertificate: str
    clientKey: str
    expiresAt: datetime

    @staticmethod
    def parse(text: str) -> "SyncConfig":
        """Parse and validate the contents of a sync file. Raises SyncConfigError."""
        try:
            doc = json.loads(text)
        except ValueError:
            raise SyncConfigError("This isn't a score reflector sync file (it isn't valid JSON).")
        if not isinstance(doc, dict) or doc.get("format") != SYNC_FILE_FORMAT:
            raise SyncConfigError("This isn't a score reflector sync file.")
        if doc.get("version") != SYNC_FILE_VERSION:
            raise SyncConfigError(f"This sync file is version {doc.get('version')}, "
                                  f"but this version of the scoring software only supports version {SYNC_FILE_VERSION}.")

        def string(value, name):
            if not isinstance(value, str) or value == "":
                raise SyncConfigError(f"This sync file is damaged (missing {name}).")
            return value

        event = doc.get("event")
        if not isinstance(event, dict):
            raise SyncConfigError("This sync file is damaged (missing event).")

        syncUrl = string(doc.get("syncUrl"), "syncUrl").rstrip("/")
        url = urlsplit(syncUrl)
        if url.scheme != "https" or not url.hostname or url.query or url.fragment:
            raise SyncConfigError("This sync file is damaged (syncUrl must be an https URL).")

        pems = {}
        for name, kind in [("caCertificate", "CERTIFICATE"), ("clientCertificate", "CERTIFICATE"),
                           ("clientKey", "PRIVATE KEY")]:
            pems[name] = string(doc.get(name), name)
            if f"-----BEGIN {kind}-----" not in pems[name]:
                raise SyncConfigError(f"This sync file is damaged ({name} isn't a PEM {kind.lower()}).")

        return SyncConfig(
            eventCode=string(event.get("code"), "event code"),
            eventName=string(event.get("name"), "event name"),
            syncUrl=syncUrl,
            caCertificate=pems["caCertificate"],
            clientCertificate=pems["clientCertificate"],
            clientKey=pems["clientKey"],
            expiresAt=_parseTimestamp(string(doc.get("expiresAt"), "expiresAt")),
        )

    def toJson(self) -> str:
        """Serialize to the sync file format, so that parse(config.toJson()) == config."""
        return json.dumps({
            "format": SYNC_FILE_FORMAT,
            "version": SYNC_FILE_VERSION,
            "event": {"code": self.eventCode, "name": self.eventName},
            "syncUrl": self.syncUrl,
            "caCertificate": self.caCertificate,
            "clientCertificate": self.clientCertificate,
            "clientKey": self.clientKey,
            "expiresAt": self.expiresAt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })

    @property
    def host(self) -> str:
        """Host (and port, if not the default) of the score reflector, for showing to the operator."""
        return urlsplit(self.syncUrl).netloc

    def isExpired(self, now: Optional[datetime] = None) -> bool:
        return (now or datetime.now(UTC)) >= self.expiresAt


def _parseTimestamp(text: str, name: str = "expiresAt") -> datetime:
    # RFC 3339 as written by Go, which may have nanoseconds
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        when = None
    if when is None or when.tzinfo is None:
        raise SyncConfigError(f"This sync file is damaged ({name} isn't a timestamp).")
    # Whole seconds, as toJson() writes it
    return when.astimezone(UTC).replace(microsecond=0)


# Saved configuration

def loadConfig() -> Optional[SyncConfig]:
    """Return the sync configuration saved in the database, or None if sync isn't set up."""
    import Substrate

    text = Substrate.getMeta(CONFIG_META_KEY)
    if text is None:
        return None
    try:
        return SyncConfig.parse(text)
    except SyncConfigError as err:
        print(f"Ignoring saved sync configuration: {err}")
        return None


def saveConfig(config: SyncConfig):
    import Substrate
    Substrate.setMeta(CONFIG_META_KEY, config.toJson())


def removeConfig():
    import Substrate
    Substrate.deleteMeta(CONFIG_META_KEY)


# Transport

class ConnectionFailed(Exception):
    """The request may not have reached the score reflector (network error, timeout, TLS failure)."""

    def __init__(self, message: str, certificateProblem: bool = False):
        super().__init__(message)
        # True when the TLS handshake failed because of a certificate, which retrying won't fix
        self.certificateProblem = certificateProblem


class ReflectorError(Exception):
    """The score reflector answered with an error."""

    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(f"{status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.details = details


class Reflector:
    """Sends requests to one event's sync API, authenticating with the event's client certificate.

    The certificate and key are written to a private temporary directory, because requests can
    only load them from files. Call close() to delete it."""

    def __init__(self, config: SyncConfig, timeout: float = 10):
        self._baseUrl = config.syncUrl
        self._timeout = timeout
        self._dir = tempfile.mkdtemp(prefix="ibss-sync-")  # created with mode 0700
        try:
            caPath = self._writeFile("ca.pem", config.caCertificate)
            certPath = self._writeFile("client.pem", config.clientCertificate)
            keyPath = self._writeFile("client.key", config.clientKey)

            # Fail now, rather than on the first request, if the PEMs can't be loaded
            try:
                ssl.create_default_context(cafile=caPath).load_cert_chain(certPath, keyPath)
            except (ssl.SSLError, ValueError) as err:
                raise SyncConfigError(f"This sync file is damaged (its certificates can't be loaded: {err}).")

            self._session = requests.Session()
            # Otherwise REQUESTS_CA_BUNDLE or CURL_CA_BUNDLE in the environment silently replace
            # verify, and proxy settings apply
            self._session.trust_env = False
            # Trust only the score reflector's own CA, never the system trust store
            self._session.verify = caPath
            self._session.cert = (certPath, keyPath)
        except Exception:
            self.close()
            raise

    def _writeFile(self, name: str, text: str) -> str:
        path = os.path.join(self._dir, name)
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as f:
            f.write(text)
        return path

    def request(self, method: str, path: str, body=None) -> dict:
        """Send a request and return the decoded JSON response. Raises ConnectionFailed or ReflectorError."""
        return self._send(method, path, json=body, timeout=self._timeout)

    def submit(self, database: bytes, baseRevision: int) -> dict:
        """POST /submissions: upload the database file, finalizing the event. Returns the decoded
        JSON response. Raises ConnectionFailed or ReflectorError."""
        return self._send("POST", "/submissions", params={"baseRevision": baseRevision}, data=database,
                          headers={"Content-Type": "application/vnd.sqlite3"},
                          timeout=(self._timeout, SUBMISSION_TIMEOUT))

    def _send(self, method: str, path: str, **kwargs) -> dict:
        try:
            resp = self._session.request(method, self._baseUrl + path, allow_redirects=False, **kwargs)
        except requests.exceptions.SSLError as err:
            raise ConnectionFailed(_describeTlsError(err), certificateProblem=_isCertificateProblem(err))
        except requests.RequestException as err:
            raise ConnectionFailed(f"Couldn't reach the score reflector ({type(err).__name__})")

        try:
            data = resp.json()
        except ValueError:
            data = None
        if resp.status_code >= 400 or not isinstance(data, dict):
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict):
                raise ReflectorError(resp.status_code, str(error.get("code")), str(error.get("message")),
                                     error.get("details"))
            raise ReflectorError(resp.status_code, "unexpected_response",
                                 f"unexpected response from the score reflector (HTTP {resp.status_code})")
        return data

    def close(self):
        if getattr(self, "_session", None) is not None:
            self._session.close()
        shutil.rmtree(self._dir, ignore_errors=True)


def _isCertificateProblem(err: Exception) -> bool:
    text = str(err).upper()
    return any(s in text for s in ("CERTIFICATE", "BAD_CERTIFICATE", "UNKNOWN_CA", "CERTIFICATE_EXPIRED"))


def _describeTlsError(err: Exception) -> str:
    text = str(err).upper()
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return "The server's certificate isn't from this event's score reflector"
    if _isCertificateProblem(err):
        return "The score reflector refused this sync file's certificate (it may have expired, or been replaced by a newer sync file)"
    return "Secure connection to the score reflector failed"


def checkConnection(config: SyncConfig, timeout: float = 10) -> Optional[str]:
    """Try to reach the event on the score reflector. Return None on success, or a description of the problem."""
    if config.isExpired():
        return f"This sync file expired at {config.expiresAt.astimezone():%Y-%m-%d %H:%M}."
    try:
        reflector = Reflector(config, timeout=timeout)
    except SyncConfigError as err:
        return str(err)
    try:
        reflector.request("GET", "/state")
        return None
    except ConnectionFailed as err:
        return f"{err}."
    except ReflectorError as err:
        if err.status == 403:
            return "The score reflector says this sync file is for a different event."
        return f"The score reflector answered with an error: {err.message}"
    finally:
        reflector.close()


# Sync engine

class SyncState(Enum):
    CONNECTING = "connecting"   # Catching the score reflector up with the local data
    OK = "ok"                   # Up to date
    SENDING = "sending"         # Connected, with local changes still to send
    OFFLINE = "offline"         # Couldn't reach the score reflector; retrying
    ATTENTION = "attention"     # Waiting for the operator, or some data couldn't be sent
    REJECTED = "rejected"       # The score reflector refused the certificate; retrying slowly
    SUBMITTING = "submitting"   # Uploading the database to finalize the event
    FINALIZED = "finalized"     # The event is over; changes are kept here, but not sent
    STOPPED = "stopped"


@dataclass(frozen=True)
class Finalized:
    """When the event was finalized on the score reflector."""
    at: Optional[datetime]
    by: Optional[str] = None    # The administrator who finalized it, or None if it was submitted


@dataclass(frozen=True)
class SyncStatus:
    state: SyncState
    message: str = ""
    pending: int = 0
    revision: Optional[int] = None
    lastSuccess: Optional[datetime] = None
    finalized: Optional[Finalized] = None   # Set while the state is FINALIZED


@dataclass(frozen=True)
class Submission:
    """A database the score reflector stored when the event was submitted."""
    id: int
    submittedAt: Optional[datetime]
    revision: int
    sha256: str
    size: int


@dataclass(frozen=True)
class SubmitResult:
    """How SyncEngine.submit() went: a submission, or a problem to show the operator."""
    submission: Optional[Submission] = None
    problem: str = ""
    # Set when the event was already finalized, so there was nothing to submit
    finalized: Optional[Finalized] = None


@dataclass(frozen=True)
class Removals:
    """Data the score reflector has that the local database doesn't."""
    teams: frozenset = frozenset()    # Team numbers
    scores: frozenset = frozenset()   # (team number, round) of scores, for teams in both

    def __bool__(self):
        return bool(self.teams or self.scores)

    def issubset(self, other: "Removals") -> bool:
        return self.teams <= other.teams and self.scores <= other.scores


class _Resync(Exception):
    """Abandon what the worker is doing and reconcile with the score reflector."""


class _Stop(Exception):
    """The engine is stopping."""


class _EventFinalized(Exception):
    """The event is finalized on the score reflector."""

    def __init__(self, finalized: Finalized):
        super().__init__("the event is finalized")
        self.finalized = finalized


class SyncEngine:
    """Keeps one event on the score reflector in sync with the local data.

    load() the local data, then start(). From then on the engine follows the event bus. All
    network traffic happens on the engine's own thread. Callbacks are called on that thread,
    so they must hand off to the UI thread themselves.

    Whenever the engine connects, it compares the score reflector's data with the local data,
    and then makes the score reflector match. If that would remove teams or scores from the
    score reflector, it calls onRemovals and waits for resolveRemovals().

    submit() finishes the event. Once it is finalized, by submitting it or by an administrator,
    the engine stops sending changes, and checks now and then whether it has been unfinalized."""

    def __init__(self, config: SyncConfig, reflector: Optional[Reflector] = None,
                 onStatus: Optional[Callable[[SyncStatus], None]] = None,
                 onRemovals: Optional[Callable[[Removals], None]] = None,
                 retryDelays: tuple = RETRY_DELAYS, finalizedPollSeconds: float = FINALIZED_POLL_SECONDS):
        self.config = config
        # The engine closes the reflector when it stops, unless it was given one
        self._reflector = reflector
        self._ownsReflector = reflector is None
        self._onStatus = onStatus or (lambda status: None)
        self._onRemovals = onRemovals or (lambda removals: None)
        self._retryDelays = retryDelays
        self._finalizedPollSeconds = finalizedPollSeconds

        # Everything below is guarded by _cond
        self._cond = threading.Condition()
        self._teams = {}         # number -> (name, pit)
        self._rounds = {}        # (number, round) -> (score, scoresheet)
        self._matchStatus = None  # (match, status), or None until there is one or it's cleared
        self._matchStatusCleared = False  # The operator cleared it; send that, and keep it clear
        self._selectedMatch = None  # The match number the operator has selected, once known
        # Changes not yet sent, oldest first: key -> generation of its latest change. A key is
        # "teams", "match", or (number, round). The request for a key is built from the data
        # when it's sent, so it's always current.
        self._pending = OrderedDict()
        self._generation = 0
        self._inFlight = None
        # Generation of the latest team deletion, until a team list that includes it is sent
        self._teamsRemovedGeneration = None
        # Removals the operator made here since the last reconcile, which need no confirmation
        self._deletedTeams = set()
        self._clearedScores = set()
        self._resyncRequested = False
        self._removalsAnswer = None  # True/False once the operator answers onRemovals
        self._approvedRemovals = Removals()
        # (database, onDone) passed to submit(), until the worker answers it
        self._submitRequest = None
        self._stopping = False

        self._status = SyncStatus(SyncState.STOPPED)
        self._problems = []      # Data the score reflector refused; shown until the next reconcile
        self._thread = None
        self._subscriptions = [
            (Events.TeamAdded, self._onTeamChanged),
            (Events.TeamUpdated, self._onTeamChanged),
            (Events.TeamDeleted, self._onTeamDeleted),
            (Events.ScoreUpdated, self._onScoreUpdated),
            (Events.ScoreCleared, self._onScoreCleared),
            (Events.MatchSelected, self._onMatchSelected),
            (Events.MatchStarted, self._onMatchStarted),
            (Events.MatchAborted, self._onMatchAborted),
            (Events.MatchCompleted, self._onMatchCompleted),
        ]

    # Control, called from the UI thread

    def load(self, teams: list, scores: list):
        """Set the local data the engine starts from: Substrate.TeamEntry and ScoreEntry lists."""
        with self._cond:
            self._teams = {int(t.teamnumber): (str(t.name), int(t.pit)) for t in teams}
            self._rounds = {(int(s.teamnumber), int(s.round)): (int(s.score), s.scoresheet)
                            for s in scores if int(s.teamnumber) in self._teams}

    def start(self):
        """Start syncing. Raises SyncConfigError if the sync file's certificates can't be used."""
        if self._reflector is None:
            self._reflector = Reflector(self.config)
        for eventType, handler in self._subscriptions:
            Events.subscribe(eventType, handler)
        self._thread = threading.Thread(target=self._run, name="Sync", daemon=True)
        self._thread.start()

    def stop(self, drainTimeout: float = 0):
        """Stop syncing, first waiting up to drainTimeout seconds for pending changes to be sent."""
        for eventType, handler in self._subscriptions:
            Events.unsubscribe(eventType, handler)
        with self._cond:
            if drainTimeout > 0:
                self._cond.wait_for(lambda: not self._hasPending() or self._status.state != SyncState.SENDING,
                                    timeout=drainTimeout)
            self._stopping = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._ownsReflector and self._reflector is not None:
            self._reflector.close()
        self._finishSubmit(SubmitResult(problem="Sync stopped before the event was submitted."))
        self._setStatus(SyncStatus(SyncState.STOPPED))

    def resync(self):
        """Reconcile with the score reflector now, even if the engine thinks it is up to date."""
        with self._cond:
            self._resyncRequested = True
            self._removalsAnswer = None
            self._cond.notify_all()

    def resolveRemovals(self, allow: bool):
        """Answer onRemovals: True to remove the data from the score reflector, False to pause syncing."""
        with self._cond:
            self._removalsAnswer = allow
            self._cond.notify_all()

    def submit(self, database: Callable[[], bytes], onDone: Callable[[SubmitResult], None]):
        """Submit the event: send every pending change, catch the score reflector up, then upload
        the database, which finalizes the event. database() returns a consistent copy of the
        database file; it is called on the engine's thread, after catching up. onDone is called
        once, on the engine's thread, with the result. Nothing is retried: if it fails, the
        operator can try again."""
        with self._cond:
            if self._submitRequest is not None or self._stopping:
                busy = True
            else:
                busy = False
                self._submitRequest = (database, onDone)
                self._cond.notify_all()
        if busy:
            onDone(SubmitResult(problem="The event is already being submitted."))

    def setMatchStatus(self, match: int, status: str):
        """Report a match status: one of MATCH_STATUSES for a match from 1, or one of
        EVENT_STATUSES with match 0."""
        if status in MATCH_STATUSES:
            if int(match) < 1:
                raise ValueError(f"{status} needs a match number from 1")
        elif status in EVENT_STATUSES:
            match = 0
        else:
            raise ValueError(f"unknown match status {status!r}")
        with self._cond:
            self._setMatchStatusLocked(match, status)
        self._publishStatus()

    def clearMatchStatus(self):
        """Report no match status, until the next match starts or one is set."""
        with self._cond:
            self._matchStatus = None
            self._matchStatusCleared = True
            self._markPending("match")
        self._publishStatus()

    @property
    def matchStatus(self) -> Optional[tuple]:
        """The (match, status) being reported, or None if there is none."""
        with self._cond:
            return self._matchStatus

    @property
    def status(self) -> SyncStatus:
        with self._cond:
            return self._status

    # Event handlers, called on the UI thread

    def _onTeamChanged(self, event):
        with self._cond:
            self._teams[event.number] = (str(event.name), int(event.pit))
            self._markPending("teams")
        self._publishStatus()

    def _onTeamDeleted(self, event):
        with self._cond:
            self._teams.pop(event.number, None)
            self._deletedTeams.add(event.number)
            # Removing the team from the score reflector removes its scores too
            for key in [key for key in self._rounds if key[0] == event.number]:
                del self._rounds[key]
            for key in [key for key in self._pending if isinstance(key, tuple) and key[0] == event.number]:
                del self._pending[key]
            self._teamsRemovedGeneration = self._markPending("teams")
        self._publishStatus()

    def _onScoreUpdated(self, event):
        with self._cond:
            if event.teamNumber in self._teams:
                self._rounds[(event.teamNumber, event.round)] = (event.score, event.scoresheet)
                self._markPending((event.teamNumber, event.round))
            # The first score entered after a match ends means the next one is being set up
            if self._matchStatus is not None and self._matchStatus[1] == "scoring":
                match = self._selectedMatch if self._selectedMatch is not None else self._matchStatus[0] + 1
                self._setMatchStatusLocked(match, "preparing")
        self._publishStatus()

    def _onScoreCleared(self, event):
        with self._cond:
            if event.teamNumber in self._teams:
                self._rounds.pop((event.teamNumber, event.round), None)
                self._clearedScores.add((event.teamNumber, event.round))
                self._markPending((event.teamNumber, event.round))
        self._publishStatus()

    # Match status: a match is preparing until its timer starts, running until the timer
    # completes, then scoring until the first score is entered, when the selected match is
    # preparing. Completing a match advances the selected match before the engine hears about
    # the completion, so selecting a match only shows while nothing else is going on: not
    # during another match, nor an event-wide status or a cleared one the operator set.

    def _onMatchSelected(self, event):
        with self._cond:
            self._selectedMatch = int(event.match)
            if (self._matchStatus is None and not self._matchStatusCleared) or \
                    (self._matchStatus is not None and self._matchStatus[1] == "preparing"):
                self._setMatchStatusLocked(event.match, "preparing")
        self._publishStatus()

    def _onMatchStarted(self, event):
        self.setMatchStatus(event.match, "running")

    def _onMatchAborted(self, event):
        # The match will be run again
        self.setMatchStatus(event.match, "preparing")

    def _onMatchCompleted(self, event):
        self.setMatchStatus(event.match, "scoring")

    def _setMatchStatusLocked(self, match: int, status: str):
        self._matchStatus = (int(match), status)
        self._matchStatusCleared = False
        self._markPending("match")

    def _markPending(self, key) -> int:
        # A key that is already pending keeps its place, so the team list still goes before
        # scores for teams that were added after it
        self._generation += 1
        self._pending[key] = self._generation
        state = self._status.state
        if state == SyncState.OK:
            state = SyncState.SENDING
        self._status = replace(self._status, state=state, pending=self._pendingCount())
        self._cond.notify_all()
        return self._generation

    # Worker thread

    def _run(self):
        attempt = 0
        connected = False
        while True:
            failure = None
            try:
                if not connected:
                    self._reconcile()
                    connected = True
                    attempt = 0
                self._sendPending()
                # A submission is due
                self._submit()
                # Catch up, which notices that the event is finalized now
                connected = False
            except _Stop:
                return
            except _Resync:
                connected = False
            except ConnectionFailed as err:
                state = SyncState.REJECTED if err.certificateProblem else SyncState.OFFLINE
                failure = (state, str(err))
            except ReflectorError as err:
                if err.status in (401, 403):
                    failure = (SyncState.REJECTED, "The score reflector refused this sync file's certificate")
                else:
                    failure = (SyncState.OFFLINE, f"The score reflector answered with an error: {err.message}")
            except Exception as err:
                # A bug; keep trying rather than silently stop syncing
                import traceback
                traceback.print_exc()
                failure = (SyncState.OFFLINE, f"Sync error: {err}")

            if failure is not None:
                # Whatever the engine knew about the score reflector may be out of date now
                connected = False
                self._finishSubmit(SubmitResult(problem=f"{failure[1]}."))
                if not self._waitToRetry(attempt, *failure):
                    return
                attempt += 1

    def _waitToRetry(self, attempt: int, state: SyncState, message: str) -> bool:
        """Report a failure and wait before retrying. Returns False if the engine is stopping."""
        delay = self._retryDelays[min(attempt, len(self._retryDelays) - 1)]
        if state == SyncState.REJECTED:
            # Usually needs a new sync file; don't hammer the server
            delay = self._retryDelays[-1]
        print(f"Sync: {message}; retrying in {delay}s")
        with self._cond:
            self._status = SyncStatus(state, message=message, pending=self._pendingCount(),
                                      revision=self._status.revision, lastSuccess=self._status.lastSuccess)
        self._publishStatus()
        with self._cond:
            # Asking to submit retries now, so that the operator hears soon whether it worked
            self._cond.wait_for(lambda: self._stopping or self._resyncRequested or self._submitRequest is not None,
                                timeout=delay)
            return not self._stopping

    def _reconcile(self, waitWhileFinalized: bool = True) -> int:
        """Make the score reflector's data match the local data (step 1 of the sync loop), and
        return the revision that made it so. While the event is finalized, wait until it isn't,
        or with waitWhileFinalized False, raise _EventFinalized."""
        if self._status.state != SyncState.FINALIZED:
            self._updateStatus(SyncState.CONNECTING, "Connecting to the score reflector")
        mismatches = 0
        while True:
            with self._cond:
                self._resyncRequested = False
                if self._stopping:
                    raise _Stop()
            if self.config.isExpired():
                raise ConnectionFailed("This sync file has expired; load a new one", certificateProblem=True)

            remote = self._reflector.request("GET", "/state")

            finalized = _parseFinalized(remote.get("finalized"))
            if finalized is not None:
                if not waitWhileFinalized:
                    raise _EventFinalized(finalized)
                self._waitWhileFinalized(finalized)
                continue

            with self._cond:
                snapshot, removals = self._snapshot(remote)
                needsApproval = removals and not removals.issubset(self._allowedRemovals())

            if needsApproval:
                if not self._askAboutRemovals(removals):
                    continue  # Asked to resync while waiting; start over with fresh data
                with self._cond:
                    self._approvedRemovals = removals

            with self._cond:
                # Build the snapshot again: the local data may have changed while the operator
                # thought about it
                snapshot, removals = self._snapshot(remote)
                allowRemovals = bool(removals) and removals.issubset(self._allowedRemovals())
                snapshotPending = dict(self._pending)
                if self._matchStatus is None:
                    # The snapshot can't clear the match status; send that separately
                    snapshotPending.pop("match", None)
                deletedTeams, clearedScores = set(self._deletedTeams), set(self._clearedScores)

            body = {"baseRevision": remote["revision"], "allowRemovals": allowRemovals, **snapshot}
            try:
                result = self._reflector.request("PUT", "/state", body)
            except ReflectorError as err:
                if err.code in ("revision_mismatch", "removals_not_allowed", "event_finalized"):
                    # The event changed under us; compare again
                    mismatches += 1
                    if mismatches > 3:
                        self._sleepOrStop(1)
                    continue
                raise

            with self._cond:
                # The snapshot included every change pending when it was built; changes made
                # since then are still pending
                for key, generation in snapshotPending.items():
                    if self._pending.get(key) == generation:
                        del self._pending[key]
                self._sentTeams(snapshotPending.get("teams"))
                self._approvedRemovals = Removals()
                self._deletedTeams -= deletedTeams
                self._clearedScores -= clearedScores
            print(f"Sync: caught up (revision {result['revision']}, changes {result.get('changes')})")
            self._succeeded(result["revision"])
            return result["revision"]

    def _waitWhileFinalized(self, finalized: Finalized):
        """Report that the event is finalized, and wait to check again (step 4 of the sync loop).
        Changes made meanwhile stay pending, and go out once an administrator unfinalizes it."""
        with self._cond:
            self._status = self._finalizedStatus(finalized)
        self._publishStatus()
        with self._cond:
            self._cond.wait_for(lambda: self._stopping or self._resyncRequested or self._submitRequest is not None,
                                timeout=self._finalizedPollSeconds)
            if self._stopping:
                raise _Stop()
        self._finishSubmit(SubmitResult(problem="The event is already finalized.", finalized=finalized))

    def _allowedRemovals(self) -> Removals:
        return Removals(self._approvedRemovals.teams | self._deletedTeams,
                        self._approvedRemovals.scores | self._clearedScores)

    def _askAboutRemovals(self, removals: Removals) -> bool:
        """Ask the operator, and wait. Returns True if allowed, False if the worker should start
        over; stays paused while the operator says no."""
        with self._cond:
            self._removalsAnswer = None
            self._status = SyncStatus(SyncState.ATTENTION, message=_describeRemovals(removals),
                                      pending=self._pendingCount(), revision=self._status.revision,
                                      lastSuccess=self._status.lastSuccess)
        self._publishStatus()
        self._onRemovals(removals)
        with self._cond:
            self._cond.wait_for(lambda: self._stopping or self._resyncRequested or self._removalsAnswer is not None)
            if self._stopping:
                raise _Stop()
            if self._removalsAnswer:
                return True
            if self._resyncRequested:
                return False
            # Declined: stay paused until the operator asks to sync again
            self._status = SyncStatus(SyncState.ATTENTION,
                                      message="Sync paused: the score reflector has data this computer doesn't. "
                                              "Use \"Sync now\" to try again.",
                                      pending=self._pendingCount(), revision=self._status.revision,
                                      lastSuccess=self._status.lastSuccess)
        self._publishStatus()
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._stopping or self._resyncRequested or self._submitRequest is not None)
                if self._stopping:
                    raise _Stop()
                if self._resyncRequested:
                    return False
            self._finishSubmit(SubmitResult(problem="Sync is paused, because the score reflector has data this "
                                                    "computer doesn't. Use \"Sync now\" first."))

    def _snapshot(self, remote: dict):
        """Build the PUT /state body from the local data, and what it would remove from remote."""
        teams = []
        localRounds = set()
        problems = []
        for number in sorted(self._teams):
            problem = _teamProblem(number, *self._teams[number])
            if problem:
                problems.append(problem)
                continue
            name, pit = self._teams[number]
            rounds = []
            for roundNum in (1, 2, 3):
                body = self._scoreBody(number, roundNum, problems)
                if body is not None:
                    localRounds.add((number, roundNum))
                rounds.append(body)
            teams.append({"number": number, "name": name, "pit": pit, "rounds": rounds})
        self._problems = problems

        localTeams = {t["number"] for t in teams}
        removedTeams = set()
        removedScores = set()
        for team in remote.get("teams", []):
            if team["number"] not in localTeams:
                removedTeams.add(team["number"])
                continue
            for i, remoteRound in enumerate(team.get("rounds", [])):
                if remoteRound is not None and (team["number"], i + 1) not in localRounds:
                    removedScores.add((team["number"], i + 1))

        matchStatus = None
        if self._matchStatus is not None:
            matchStatus = {"match": self._matchStatus[0], "status": self._matchStatus[1]}
        snapshot = {"matchStatus": matchStatus, "teams": teams}
        return snapshot, Removals(frozenset(removedTeams), frozenset(removedScores))

    def _scoreBody(self, number: int, roundNum: int, problems: list) -> Optional[dict]:
        """The score for a round as the API wants it, or None if it has no (sendable) score."""
        entry = self._rounds.get((number, roundNum))
        if entry is None:
            return None
        score, scoresheet = entry
        if not 0 <= score <= MAX_SCORE:
            problems.append(f"Team {number} round {roundNum}: score {score} is out of range")
            return None
        body = {"score": score}
        if scoresheet:
            if _scoresheetIsValid(scoresheet):
                body["scoresheet"] = {str(k): str(v) for k, v in scoresheet.items()}
            else:
                print(f"Sync: not sending team {number} round {roundNum} scoresheet (too large)")
        return body

    def _sendPending(self):
        """Send changes as they happen (step 2 of the sync loop). Returns once a submission is due
        and every change has been sent."""
        self._updateStatus(None)
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._stopping or self._resyncRequested or self._pending
                                    or self._submitRequest is not None)
                if self._stopping:
                    raise _Stop()
                if self._resyncRequested:
                    raise _Resync()
                if not self._pending:
                    return
                key, generation = self._pending.popitem(last=False)
                request = self._buildRequest(key)
                if request is None:
                    continue
                method, path, body = request
                self._inFlight = key
            self._updateStatus(None)

            try:
                result = self._reflector.request(method, path, body)
            except ReflectorError as err:
                with self._cond:
                    self._inFlight = None
                if err.code in ("team_not_found", "removals_not_allowed", "revision_mismatch", "event_finalized"):
                    # Our idea of the score reflector's data is wrong; compare again
                    print(f"Sync: {err}; reconciling")
                    if err.code == "event_finalized":
                        # Keep the change, in case an administrator unfinalizes the event
                        with self._cond:
                            self._requeue(key, generation)
                    raise _Resync()
                if 400 <= err.status < 500 and err.status not in (401, 403):
                    # Retrying won't help: the data or the request is invalid
                    print(f"Sync: {method} {path} refused: {err}")
                    with self._cond:
                        self._problems.append(f"The score reflector refused an update: {err.message}")
                    self._updateStatus(None)
                    continue
                with self._cond:
                    self._requeue(key, generation)
                raise
            except ConnectionFailed:
                with self._cond:
                    self._inFlight = None
                    self._requeue(key, generation)
                raise

            with self._cond:
                self._inFlight = None
                if key == "teams":
                    self._sentTeams(generation)
            self._succeeded(result.get("revision"))

    def _submit(self):
        """Catch up and upload the database (step 5 of the sync loop), then answer the submit()
        request. Connection failures and errors are raised, and answered by _run()."""
        with self._cond:
            request = self._submitRequest
        database = request[0]
        try:
            for _ in range(SUBMISSION_ATTEMPTS):
                revision = self._reconcile(waitWhileFinalized=False)
                with self._cond:
                    # Answered while catching up, e.g. because the operator paused sync
                    if self._submitRequest is not request:
                        return
                    problems = list(self._problems)
                    generation = self._generation
                if problems:
                    self._finishSubmit(SubmitResult(
                        problem="Some of this event's data couldn't be sent to the score reflector, so it "
                                "can't be submitted yet: " + "; ".join(problems)))
                    return

                data = database()
                with self._cond:
                    if self._stopping:
                        raise _Stop()
                    # Something changed while the database was copied, so the copy may not match
                    # the revision; catch up again
                    changed = self._generation != generation or self._hasPending()
                if changed:
                    continue
                if len(data) > MAX_SUBMISSION_BYTES:
                    self._finishSubmit(SubmitResult(
                        problem=f"The database is too large to submit ({len(data) // (1024 * 1024)} MiB; "
                                f"the limit is {MAX_SUBMISSION_BYTES // (1024 * 1024)} MiB)."))
                    return

                self._updateStatus(SyncState.SUBMITTING, "Uploading the database")
                try:
                    result = self._reflector.submit(data, revision)
                except ReflectorError as err:
                    if err.code in ("revision_mismatch", "event_finalized"):
                        # The event changed since catching up; look again
                        print(f"Sync: submission refused: {err}; catching up")
                        continue
                    raise

                submission = _parseSubmission(result.get("submission"))
                print(f"Sync: submitted revision {submission.revision} as submission {submission.id} "
                      f"({submission.size} bytes, sha256 {submission.sha256})")
                with self._cond:
                    self._status = self._finalizedStatus(Finalized(submission.submittedAt),
                                                         revision=result.get("revision"),
                                                         lastSuccess=datetime.now(UTC))
                self._publishStatus()
                self._finishSubmit(SubmitResult(submission=submission))
                return

            self._finishSubmit(SubmitResult(problem="The event kept changing while it was being submitted. "
                                                    "Try again."))
        except _EventFinalized as err:
            self._finishSubmit(SubmitResult(problem="The event is already finalized.", finalized=err.finalized))

    def _finalizedStatus(self, finalized: Finalized, revision: Optional[int] = None,
                         lastSuccess: Optional[datetime] = None) -> SyncStatus:
        return SyncStatus(SyncState.FINALIZED,
                          message="The score reflector takes no more changes to this event. "
                                  "Only an event administrator can reopen it.",
                          pending=self._pendingCount(),
                          revision=revision if revision is not None else self._status.revision,
                          lastSuccess=lastSuccess or self._status.lastSuccess, finalized=finalized)

    def _finishSubmit(self, result: SubmitResult):
        """Answer the submit() request, if there is one."""
        with self._cond:
            request, self._submitRequest = self._submitRequest, None
        if request is not None:
            try:
                request[1](result)
            except Exception:
                import traceback
                traceback.print_exc()

    def _sentTeams(self, generation: Optional[int]):
        """The team list as of generation reached the score reflector."""
        if generation is not None and self._teamsRemovedGeneration is not None \
                and generation >= self._teamsRemovedGeneration:
            self._teamsRemovedGeneration = None

    def _buildRequest(self, key):
        if key == "teams":
            teams = []
            for number in sorted(self._teams):
                if _teamProblem(number, *self._teams[number]) is None:
                    name, pit = self._teams[number]
                    teams.append({"number": number, "name": name, "pit": pit})
            return "PUT", "/teams", {"teams": teams, "allowRemovals": self._teamsRemovedGeneration is not None}
        if key == "match":
            if self._matchStatus is None:
                return "DELETE", "/match-status", None
            return "PUT", "/match-status", {"match": self._matchStatus[0], "status": self._matchStatus[1]}
        number, roundNum = key
        path = f"/teams/{number}/rounds/{roundNum}"
        if (number, roundNum) not in self._rounds:
            return "DELETE", path, None
        body = self._scoreBody(number, roundNum, self._problems)
        # None if the score can't be sent; leave whatever the score reflector has
        return ("PUT", path, body) if body is not None else None

    def _requeue(self, key, generation: int):
        # Put a failed change back at the front, unless it has changed again since
        self._pending.setdefault(key, generation)
        self._pending.move_to_end(key, last=False)

    def _sleepOrStop(self, seconds: float):
        with self._cond:
            self._cond.wait_for(lambda: self._stopping, timeout=seconds)
            if self._stopping:
                raise _Stop()

    def _hasPending(self) -> bool:
        return bool(self._pending) or self._inFlight is not None

    def _pendingCount(self) -> int:
        return len(self._pending) + (1 if self._inFlight is not None else 0)

    def _succeeded(self, revision: Optional[int]):
        with self._cond:
            self._status = SyncStatus(self._status.state, pending=self._pendingCount(),
                                      revision=revision if revision is not None else self._status.revision,
                                      lastSuccess=datetime.now(UTC))
        self._updateStatus(None)

    def _updateStatus(self, state: Optional[SyncState], message: str = ""):
        """Set the status; with state None, derive it from the pending changes and problems."""
        with self._cond:
            if state is None:
                if self._problems:
                    state, message = SyncState.ATTENTION, "; ".join(self._problems)
                elif self._hasPending():
                    state = SyncState.SENDING
                else:
                    state = SyncState.OK
            self._status = SyncStatus(state, message=message, pending=self._pendingCount(),
                                      revision=self._status.revision, lastSuccess=self._status.lastSuccess)
            self._cond.notify_all()
        self._publishStatus()

    def _setStatus(self, status: SyncStatus):
        with self._cond:
            self._status = status
            self._cond.notify_all()
        self._publishStatus()

    def _publishStatus(self):
        with self._cond:
            status = self._status
        try:
            self._onStatus(status)
        except Exception:
            import traceback
            traceback.print_exc()


def _teamProblem(number: int, name: str, pit: int) -> Optional[str]:
    """Why the score reflector would refuse a team, or None if it wouldn't."""
    if not 1 <= number <= MAX_TEAM_NUMBER:
        return f"Team number {number} is out of range"
    if not 1 <= len(name.encode()) <= MAX_TEAM_NAME_BYTES:
        return f"Team {number} needs a name of 1 to {MAX_TEAM_NAME_BYTES} characters"
    if pit < 0:
        return f"Team {number}'s pit number is negative"
    return None


def _scoresheetIsValid(scoresheet: dict) -> bool:
    return len(scoresheet) <= MAX_SCORESHEET_TASKS and all(
        1 <= len(str(k).encode()) <= MAX_SCORESHEET_STRING_BYTES and len(str(v).encode()) <= MAX_SCORESHEET_STRING_BYTES
        for k, v in scoresheet.items())


def _parseFinalized(value) -> Optional[Finalized]:
    """The "finalized" member of GET /state."""
    if not isinstance(value, dict):
        return None
    by = value.get("by")
    return Finalized(at=_parseServerTimestamp(value.get("at")), by=str(by) if by else None)


def _parseSubmission(value) -> Submission:
    """The "submission" member of a POST /submissions response."""
    if not isinstance(value, dict):
        raise ReflectorError(200, "unexpected_response", "the score reflector didn't describe the submission")
    return Submission(id=int(value.get("id", 0)), submittedAt=_parseServerTimestamp(value.get("submittedAt")),
                      revision=int(value.get("revision", 0)), sha256=str(value.get("sha256", "")),
                      size=int(value.get("size", 0)))


def _parseServerTimestamp(text) -> Optional[datetime]:
    try:
        return _parseTimestamp(text, "timestamp") if isinstance(text, str) else None
    except SyncConfigError:
        return None


def _describeRemovals(removals: Removals) -> str:
    parts = []
    if removals.teams:
        parts.append(f"{len(removals.teams)} team{'s' if len(removals.teams) != 1 else ''}")
    if removals.scores:
        parts.append(f"{len(removals.scores)} score{'s' if len(removals.scores) != 1 else ''}")
    return f"The score reflector has {' and '.join(parts)} that this computer doesn't"


def copyDatabase() -> bytes:
    """A consistent copy of the database file to submit, without the sync file, whose private
    key must stay on this computer."""
    import Substrate
    return Substrate.copyDatabase(excludeMeta=[CONFIG_META_KEY])


def createEngine(config: SyncConfig, **kwargs) -> SyncEngine:
    """Create an engine for config, loaded with the data in the database. Call start() on it."""
    import Substrate

    engine = SyncEngine(config, **kwargs)
    engine.load(Substrate.loadTeams(), Substrate.loadScores())
    return engine
