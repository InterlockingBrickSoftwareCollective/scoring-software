"""
SyncControl.py: Score reflector sync setup and status display

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

import html
import json
import threading

from datetime import UTC, datetime, timedelta
from typing import Optional

from PyQt6.QtCore import *
from PyQt6.QtGui import QActionGroup
from PyQt6.QtWidgets import *

import Substrate
import Sync
from SetupReceiver import PORT as RECEIVER_PORT, SetupReceiver
from Sync import Finalized, Removals, SubmitResult, SyncConfig, SyncConfigError, SyncState, SyncStatus

# Seconds to wait for pending changes to reach the score reflector when the application closes
SHUTDOWN_DRAIN_SECONDS = 2

# Warn about the sync file expiring this long beforehand
EXPIRY_WARNING = timedelta(hours=24)

# State -> (label, background color)
_STATE_DISPLAY = {
    SyncState.CONNECTING: ("Connecting…", "#aaaaaa"),
    SyncState.OK: ("OK", "#7ccf7c"),
    SyncState.SENDING: ("Sending", "#7ccf7c"),
    SyncState.OFFLINE: ("Offline", "#f5b041"),
    SyncState.ATTENTION: ("Needs attention", "#f5b041"),
    SyncState.REJECTED: ("Rejected", "#ED1C24"),
    SyncState.SUBMITTING: ("Submitting…", "#7ccf7c"),
    SyncState.FINALIZED: ("Event finalized", "#85c1e9"),
    SyncState.STOPPED: ("Stopped", "#aaaaaa"),
}


class SyncController(QObject):
    """Runs the sync engine for the main window, and the operator's side of setting it up."""

    # Emitted on the UI thread whenever there's something new to show; the argument is a
    # SyncStatus, or None when sync isn't set up
    statusChanged = pyqtSignal(object)
    # Engine callbacks arrive on the engine's thread; these carry them to the UI thread
    _engineStatus = pyqtSignal(object, object)
    _engineRemovals = pyqtSignal(object, object)
    _engineSubmitted = pyqtSignal(object)
    # And these carry the setup receiver's, from its thread
    _receiving = pyqtSignal(object)
    _receiveFailed = pyqtSignal(str)
    _receivedSyncFile = pyqtSignal(object, object)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self._window = parent
        self._engine: Optional[Sync.SyncEngine] = None
        self._engineStatus.connect(self._onEngineStatus)
        self._engineRemovals.connect(self._onEngineRemovals)
        self._engineSubmitted.connect(self._onSubmitted)
        self._submitProgress: Optional[QProgressDialog] = None
        self._receiver: Optional[SetupReceiver] = None
        self._setupDialog: Optional[SyncSetupDialog] = None
        self._loadingFile = False
        self._receiving.connect(self._onReceiving)
        self._receiveFailed.connect(self._onReceiveFailed)
        self._receivedSyncFile.connect(self._onReceivedSyncFile)

    @property
    def config(self) -> Optional[SyncConfig]:
        return self._engine.config if self._engine is not None else None

    @property
    def status(self) -> Optional[SyncStatus]:
        return self._engine.status if self._engine is not None else None

    def startFromSavedConfig(self):
        """Resume syncing with the configuration saved in the database, if there is one."""
        config = Sync.loadConfig()
        if config is not None:
            self._start(config)
        else:
            self.statusChanged.emit(None)

    def shutdown(self):
        if self._setupDialog is not None:
            self._setupDialog.reject()
        self._stop(SHUTDOWN_DRAIN_SECONDS)

    def syncNow(self):
        if self._engine is not None:
            self._engine.resync()

    @property
    def matchStatus(self) -> Optional[tuple]:
        """The (match, status) the scores pages are told, or None."""
        return self._engine.matchStatus if self._engine is not None else None

    def setMatchStatus(self, match: int, status: str):
        if self._engine is not None:
            self._engine.setMatchStatus(match, status)

    def clearMatchStatus(self):
        if self._engine is not None:
            self._engine.clearMatchStatus()

    def finalize(self):
        """Submit the event to the score reflector, which finalizes it, after asking the operator."""
        config, engine = self.config, self._engine
        if config is None or engine is None or self._submitProgress is not None:
            return
        confirm = QMessageBox.question(
            self._window, "Finalize Event",
            f"Submit {config.eventName} ({config.eventCode}) to the score reflector and finalize it?\n\n"
            "The scores pages will show the event as completed, and the score reflector will take no more "
            "changes to it. Only an event administrator can reopen it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._submitProgress = QProgressDialog("Submitting the event to the score reflector…", None, 0, 0,
                                               self._window)
        self._submitProgress.setWindowTitle("Finalize Event")
        self._submitProgress.setWindowModality(Qt.WindowModality.WindowModal)
        self._submitProgress.setMinimumDuration(0)
        self._submitProgress.show()
        engine.submit(Sync.copyDatabase, self._engineSubmitted.emit)

    def _onSubmitted(self, result: SubmitResult):
        # Shown even if sync was removed meanwhile, so that the operator knows it didn't happen
        if self._submitProgress is not None:
            self._submitProgress.close()
            self._submitProgress.deleteLater()
            self._submitProgress = None

        box = QMessageBox(self._window)
        box.setWindowTitle("Finalize Event")
        if result.submission is not None:
            submission = result.submission
            Substrate.writeLogEntry("sync_submitted", json.dumps({
                "id": submission.id, "revision": submission.revision, "sha256": submission.sha256,
                "size": submission.size}))
            box.setIcon(QMessageBox.Icon.Information)
            box.setText("The event is finalized.")
            box.setInformativeText("The scores pages show the event as completed.")
        elif result.finalized is not None:
            box.setIcon(QMessageBox.Icon.Information)
            box.setText(f"The event was already {_describeFinalized(result.finalized)}.")
            box.setInformativeText("Only an event administrator can reopen it.")
        else:
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("The event couldn't be submitted.")
            box.setInformativeText(result.problem)
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        box.open()

    def setUp(self):
        """Wait for credentials from the score reflector's setup page, or let the operator load them
        from a file."""
        if self._setupDialog is not None:
            self._setupDialog.raise_()
            self._setupDialog.activateWindow()
            return

        self._receiver = SetupReceiver(self._receiveSyncFile)
        try:
            self._receiver.start()
        except OSError as err:
            print(f"Can't receive sync credentials from the setup page: {err}")
            self._receiver = None

        self._setupDialog = SyncSetupDialog(self._window, receiving=self._receiver is not None)
        self._setupDialog.loadFromFile.connect(self._loadFromFile)
        self._setupDialog.finished.connect(self._endSetUp)
        self._setupDialog.show()

    def _endSetUp(self):
        if self._receiver is not None:
            self._receiver.stop()
            self._receiver = None
        if self._setupDialog is not None:
            self._setupDialog.deleteLater()
            self._setupDialog = None

    def _receiveSyncFile(self, config: SyncConfig) -> Optional[str]:
        """Called on the receiver's thread with credentials from the setup page. Returns None once
        they're in use, or why they weren't used, for the setup page to show."""
        self._receiving.emit(config)
        problem = Sync.checkConnection(config)
        if problem is not None:
            self._receiveFailed.emit(problem)
            return f"It couldn't connect to the score reflector. {problem}"
        reply = _Reply()
        self._receivedSyncFile.emit(config, reply)
        return reply.wait()

    def _onReceiving(self, config: SyncConfig):
        if self._setupDialog is not None:
            self._setupDialog.showConnecting(config)

    def _onReceiveFailed(self, problem: str):
        if self._setupDialog is not None:
            self._setupDialog.showProblem(problem)

    def _onReceivedSyncFile(self, config: SyncConfig, reply: "_Reply"):
        if self._setupDialog is None:
            reply.answer("Sync setup was cancelled in the scoring software.")
            return
        if self._loadingFile:
            reply.answer("The scoring software is loading credentials from a file instead.")
            return
        previous = self._use(config)
        reply.answer(None)
        self._setupDialog.accept()
        self._showSetUp(config, previous)

    def _loadFromFile(self):
        """Load credentials from a sync file downloaded from the score reflector, check them, and
        start syncing with them."""
        parent = self._setupDialog or self._window
        filename, _ = QFileDialog.getOpenFileName(parent, "Load Sync Credentials", "",
                                                  "Sync files (*.sync.json);;JSON files (*.json);;All files (*)")
        if not filename:
            return

        try:
            with open(filename, "r", encoding="utf-8") as f:
                config = SyncConfig.parse(f.read())
        except SyncConfigError as err:
            QMessageBox.critical(parent, "Set Up Sync", str(err))
            return
        except (OSError, UnicodeDecodeError) as err:
            QMessageBox.critical(parent, "Set Up Sync", f"Couldn't read the sync file: {err}")
            return

        if config.isExpired():
            QMessageBox.critical(parent, "Set Up Sync",
                                 f"These credentials expired at {_localTime(config.expiresAt)}.\n"
                                 "Ask an event administrator to reopen sync setup on the score reflector.")
            return

        current = self.config
        if current is not None and current.eventCode != config.eventCode:
            confirm = QMessageBox.question(
                parent, "Set Up Sync",
                f"This database already syncs to {current.eventName} ({current.eventCode}).\n\n"
                f"Sync to {config.eventName} ({config.eventCode}) instead?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if confirm != QMessageBox.StandardButton.Yes:
                return

        # Credentials arriving from the setup page meanwhile are turned away
        self._loadingFile = True
        try:
            problem = _runWithProgress(parent, "Testing connection…",
                                       lambda: Sync.checkConnection(config))
            if problem is not None:
                confirm = QMessageBox.warning(
                    parent, "Set Up Sync",
                    f"Couldn't connect to the score reflector:\n{problem}\n\n"
                    "Use these credentials anyway? Sync will keep trying to connect.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if confirm != QMessageBox.StandardButton.Yes:
                    return
        finally:
            self._loadingFile = False

        previous = self._use(config)
        if self._setupDialog is not None:
            self._setupDialog.accept()
        if problem is None:
            self._showSetUp(config, previous)

    def _use(self, config: SyncConfig) -> Optional[SyncConfig]:
        """Save config and start syncing with it. Returns the configuration it replaced, if any."""
        previous = self.config
        Sync.saveConfig(config)
        self._stop()
        self._start(config)
        return previous

    def _showSetUp(self, config: SyncConfig, previous: Optional[SyncConfig]):
        text = f"Sync for {config.eventName} ({config.eventCode}) is now live."
        if previous is not None and previous.eventCode != config.eventCode:
            text += f"\n\nIt replaces sync for {previous.eventName} ({previous.eventCode})."
        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Sync Is Set Up")
        box.setText(text)
        box.setInformativeText(f"The credentials are valid until {_localTime(config.expiresAt)}.")
        box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        # Bring the scoring software back from the browser
        self._window.raise_()
        self._window.activateWindow()
        box.open()

    def remove(self):
        """Stop syncing, and delete the sync configuration from the database."""
        config = self.config
        if config is None:
            return
        confirm = QMessageBox.question(
            self._window, "Remove Sync",
            f"Stop syncing to {config.eventName} ({config.eventCode})?\n\n"
            "Scores already published stay on the score reflector. "
            "To sync again, an event administrator will have to reopen sync setup, "
            "unless you still have the sync file.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._stop()
        Sync.removeConfig()
        self.statusChanged.emit(None)

    def showDetails(self):
        """Show what sync is doing, with a way to sync now."""
        config, status = self.config, self.status
        if config is None or status is None:
            return

        rows = [
            ("Event", f"{config.eventName} ({config.eventCode})"),
            ("Status", describe(status, config)),
        ]
        if status.message:
            rows.append(("Details", status.message))
        if status.pending:
            rows.append(("Changes waiting", str(status.pending)))
        rows.append(("Last update", _localTime(status.lastSuccess) if status.lastSuccess else "Never"))
        rows.append(("Credentials expire", _localTime(config.expiresAt)))

        box = QMessageBox(self._window)
        box.setWindowTitle("Sync Status")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText("<table>" + "".join(
            f"<tr><td><b>{html.escape(k)}:</b>&nbsp;</td><td>{html.escape(v)}</td></tr>" for k, v in rows)
            + "</table>")
        syncNow = box.addButton("Sync Now", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is syncNow:
            self.syncNow()

    def _start(self, config: SyncConfig):
        try:
            engine = Sync.createEngine(
                config,
                onStatus=lambda status: self._engineStatus.emit(engine, status),
                onRemovals=lambda removals: self._engineRemovals.emit(engine, removals))
            engine.start()
        except SyncConfigError as err:
            QMessageBox.critical(self._window, "Sync", f"Sync couldn't start: {err}")
            self.statusChanged.emit(None)
            return
        self._engine = engine
        self.statusChanged.emit(engine.status)

    def _stop(self, drainTimeout: float = 0):
        if self._engine is not None:
            engine, self._engine = self._engine, None
            engine.stop(drainTimeout)

    def _onEngineStatus(self, engine, status):
        # Ignore anything a stopped engine said on its way out
        if engine is self._engine:
            self.statusChanged.emit(status)

    def _onEngineRemovals(self, engine, removals: Removals):
        if engine is not self._engine:
            return

        lines = []
        if removals.teams:
            lines.append("Teams: " + ", ".join(str(n) for n in sorted(removals.teams)))
        if removals.scores:
            lines.append("Scores: " + ", ".join(f"team {n} round {r}" for n, r in sorted(removals.scores)))

        box = QMessageBox(self._window)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Sync")
        box.setText(f"The score reflector has {_count(len(removals.teams), 'team')}"
                    f"{' and ' if removals.teams and removals.scores else ''}"
                    f"{_count(len(removals.scores), 'score') if removals.scores else ''} "
                    "that this database doesn't.")
        box.setInformativeText(
            "This happens when the scoring software opens a new database partway through an event, "
            "or when another computer syncs to the same event.\n\n"
            "Remove them from the published scores, or pause sync until you've checked?")
        box.setDetailedText("\n".join(lines))
        remove = box.addButton("Remove From Published Scores", QMessageBox.ButtonRole.DestructiveRole)
        pause = box.addButton("Pause Sync", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(pause)
        box.exec()
        if engine is self._engine:
            engine.resolveRemovals(box.clickedButton() is remove)


class EventStatusMenu(QMenu):
    """Toybox > Event status: what the scores pages say is going on. Matches are reported
    automatically as they run; the rest are set by hand."""

    # (label, status) of the event-wide statuses
    _EVENT_STATUSES = [
        ("Practice", "practice"),
        ("Opening ceremonies", "opening_ceremonies"),
        ("Closing ceremonies", "closing_ceremonies"),
    ]

    def __init__(self, controller: "SyncController", currentMatch, parent: QWidget):
        super().__init__("Event status", parent)
        self._controller = controller
        self._currentMatch = currentMatch
        group = QActionGroup(self)

        def add(label, slot):
            action = self.addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(slot)
            return action

        self._matches = add("Matches", self._showMatches)
        self._actions = {status: add(label, lambda checked, s=status: self._set(s))
                         for label, status in self._EVENT_STATUSES}
        self.addSeparator()
        self._none = add("None", self._clear)
        self.aboutToShow.connect(self._updateChecks)

    def _updateChecks(self):
        current = self._controller.matchStatus
        if current is None:
            self._none.setChecked(True)
        elif current[1] in Sync.MATCH_STATUSES:
            self._matches.setChecked(True)
        else:
            self._actions[current[1]].setChecked(True)

    def _showMatches(self):
        current = self._controller.matchStatus
        # Already following the matches
        if current is not None and current[1] in Sync.MATCH_STATUSES:
            return
        self._controller.setMatchStatus(self._currentMatch(), "preparing")

    def _set(self, status: str):
        self._controller.setMatchStatus(0, status)

    def _clear(self):
        self._controller.clearMatchStatus()


class _Reply:
    """An answer the UI thread hands back to a waiting receiver thread."""

    # Give up waiting if the UI never answers, e.g. because the application is closing
    TIMEOUT = 60

    def __init__(self):
        self._done = threading.Event()
        self._problem: Optional[str] = "The scoring software didn't respond."

    def answer(self, problem: Optional[str]):
        self._problem = problem
        self._done.set()

    def wait(self) -> Optional[str]:
        self._done.wait(self.TIMEOUT)
        return self._problem


class SyncSetupDialog(QDialog):
    """Shown while waiting for credentials from the score reflector's setup page."""

    loadFromFile = pyqtSignal()

    def __init__(self, parent: QWidget, receiving: bool):
        super().__init__(parent)
        self.setWindowTitle("Set Up Sync")
        self.setModal(False)

        instructions = QLabel()
        instructions.setWordWrap(True)
        self._status = QLabel()
        self._status.setWordWrap(True)
        self._busy = QProgressBar()
        self._busy.setRange(0, 0)
        self._busy.setTextVisible(False)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self._loadButton = buttons.addButton("Load Credentials from File…", QDialogButtonBox.ButtonRole.ActionRole)
        self._loadButton.clicked.connect(lambda: self.loadFromFile.emit())
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(instructions)
        layout.addSpacing(8)
        layout.addWidget(self._status)
        layout.addWidget(self._busy)
        layout.addSpacing(8)
        layout.addWidget(buttons)
        self.setMinimumWidth(460)

        if receiving:
            instructions.setText(
                "In a web browser on this computer, open the sync setup link from your event "
                "administrator. Click Connect to the scoring software, then enter the passcode.")
            self.showWaiting()
        else:
            instructions.setText(
                f"The scoring software can't receive credentials from a browser, because port "
                f"{RECEIVER_PORT} is in use. Another copy of the scoring software may be setting up sync; "
                f"close it and try again.\n\nOr load the credentials from a sync file.")
            self._status.setVisible(False)
            self._busy.setVisible(False)

    def showWaiting(self):
        self._status.setText("Waiting for credentials…")
        self._busy.setVisible(True)
        self._loadButton.setEnabled(True)

    def showConnecting(self, config: SyncConfig):
        self._status.setText(f"Received credentials for {config.eventName} ({config.eventCode}). "
                             "Testing connection…")
        self._loadButton.setEnabled(False)

    def showProblem(self, problem: str):
        self._status.setText(f"Couldn't connect to the score reflector: {problem}\n\n"
                             "Waiting for credentials… Try again on the setup page, or download the "
                             "sync file there and use Load Credentials from File.")
        self._loadButton.setEnabled(True)


class SyncStatusButton(QPushButton):
    """Shows the sync status next to the Toybox; click for details. Hidden while sync isn't set up."""

    def __init__(self, controller: SyncController):
        super().__init__()
        self._controller = controller
        self.setVisible(False)
        self.clicked.connect(controller.showDetails)
        controller.statusChanged.connect(self._update)

        # Re-check expiry now and then, since nothing else changes when it gets close
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self._update(controller.status))
        self._timer.start(60 * 1000)

    def _update(self, status: Optional[SyncStatus]):
        config = self._controller.config
        if status is None or config is None:
            self.setVisible(False)
            return

        label, color = _STATE_DISPLAY[status.state]
        if status.state == SyncState.SENDING and status.pending:
            label = f"Sending ({status.pending})"
        if status.state in (SyncState.OK, SyncState.SENDING) and _expiresSoon(config):
            label, color = "Expires soon", "#f7dc6f"
        self.setText(f"Sync: {label}")
        self.setStyleSheet(f"background-color: {color}; color: black")
        self.setToolTip(describe(status, config) + (f"\n{status.message}" if status.message else ""))
        self.setVisible(True)


class FinalizeEventButton(QPushButton):
    """Submits the event to the score reflector. Shown once every team has a score for every round,
    while sync is set up and the event isn't finalized."""

    def __init__(self, controller: SyncController):
        super().__init__("Finalize Event")
        self._controller = controller
        self._scoresComplete = False
        self.setVisible(False)
        self.clicked.connect(controller.finalize)
        controller.statusChanged.connect(self._update)

    def setScoresComplete(self, complete: bool):
        self._scoresComplete = complete
        self._update(self._controller.status)

    def _update(self, status: Optional[SyncStatus]):
        self.setVisible(self._scoresComplete and status is not None and status.state != SyncState.FINALIZED)
        self.setEnabled(status is not None and status.state != SyncState.SUBMITTING)


def describe(status: SyncStatus, config: SyncConfig) -> str:
    """One line about the sync status, for the operator."""
    if status.state == SyncState.OK:
        text = "Up to date"
    elif status.state == SyncState.SENDING:
        text = f"Sending {_count(status.pending, 'change')}"
    elif status.state == SyncState.CONNECTING:
        text = "Connecting to the score reflector"
    elif status.state == SyncState.OFFLINE:
        text = "Can't reach the score reflector; retrying"
    elif status.state == SyncState.ATTENTION:
        text = "Needs attention"
    elif status.state == SyncState.REJECTED:
        text = "The score reflector refused the connection; retrying"
    elif status.state == SyncState.SUBMITTING:
        text = "Submitting the event"
    elif status.state == SyncState.FINALIZED:
        text = "Event " + _describeFinalized(status.finalized or Finalized(None))
        if status.pending:
            text += f"; {_count(status.pending, 'change')} made since can't be sent"
    else:
        text = "Stopped"
    if config.isExpired():
        text += " (credentials expired; ask an event administrator to reopen sync setup)"
    elif _expiresSoon(config):
        text += f" (credentials expire {_localTime(config.expiresAt)})"
    return text


def _describeFinalized(finalized: Finalized) -> str:
    text = "finalized"
    if finalized.at is not None:
        text += f" at {_localTime(finalized.at)}"
    if finalized.by:
        text += f" by {finalized.by}"
    return text


def _expiresSoon(config: SyncConfig) -> bool:
    return datetime.now(UTC) + EXPIRY_WARNING >= config.expiresAt


def _localTime(when: datetime) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M")


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _runWithProgress(parent: QWidget, text: str, fn):
    """Run fn on another thread, showing a busy dialog until it returns, and return its result."""
    result = {}
    loop = QEventLoop()

    class Done(QObject):
        finished = pyqtSignal()

    done = Done()
    done.finished.connect(loop.quit)

    def run():
        try:
            result["value"] = fn()
        except Exception as err:
            result["error"] = err
        done.finished.emit()

    progress = QProgressDialog(text, None, 0, 0, parent)
    progress.setWindowTitle("Set Up Sync")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.show()

    threading.Thread(target=run, daemon=True).start()
    loop.exec()
    progress.close()

    if "error" in result:
        raise result["error"]
    return result["value"]
