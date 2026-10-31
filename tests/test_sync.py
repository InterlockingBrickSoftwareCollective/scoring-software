import json
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

import Events
import Substrate
import Sync
from Substrate import ScoreEntry, TeamEntry
from Sync import SyncConfig, SyncConfigError, SyncEngine, SyncState
from fakereflector import FakeReflector

PEM_CERT = "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n"
PEM_KEY = "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----\n"
# Stands in for a database file when submitting
DATABASE = b"SQLite format 3\x00" + b"\x00" * 100


def syncFile(**overrides) -> dict:
    doc = {
        "format": "score-reflector-event-sync",
        "version": 1,
        "event": {"code": "fall-qual", "name": "Fall Qualifier"},
        "syncUrl": "https://scores.example.org:8443/api/v1/events/fall-qual",
        "caCertificate": PEM_CERT,
        "clientCertificate": PEM_CERT,
        "clientKey": PEM_KEY,
        "expiresAt": (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    doc.update(overrides)
    return doc


def waitFor(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def teamsOn(reflector):
    """Team number -> (name, pit, [score or None] * 3), as the score reflector shows them."""
    return {t["number"]: (t["name"], t["pit"], [r["score"] if r else None for r in t["rounds"]])
            for t in reflector.state()["teams"]}


class Harness:
    """A sync engine attached to a fake score reflector, recording what it tells the operator."""

    def __init__(self, reflector, teams=(), scores=()):
        self.reflector = reflector
        self.statuses = []
        self.removalPrompts = []
        self.engine = SyncEngine(SyncConfig.parse(json.dumps(syncFile())), reflector=reflector,
                                 onStatus=self.statuses.append, onRemovals=self.removalPrompts.append,
                                 retryDelays=(0.05,), finalizedPollSeconds=0.1)
        self.engine.load(list(teams), list(scores))

    def start(self):
        self.engine.start()
        return self

    def waitUntilSynced(self):
        waitFor(lambda: self.engine.status.state == SyncState.OK)

    def submit(self, database=lambda: DATABASE):
        """Submit the event and wait for the result."""
        results = []
        self.engine.submit(database, results.append)
        waitFor(lambda: results)
        assert len(results) == 1
        return results[0]

    def stop(self):
        self.engine.stop()


@pytest.fixture
def reflector():
    return FakeReflector()


@pytest.fixture
def harness(reflector):
    harnesses = []

    def make(teams=(), scores=()):
        h = Harness(reflector, teams, scores)
        harnesses.append(h)
        return h

    yield make
    for h in harnesses:
        h.stop()


# The sync file

def test_sync_file_round_trips_through_its_saved_form():
    config = SyncConfig.parse(json.dumps(syncFile(expiresAt="2026-11-06T00:05:09Z")))
    assert config.eventCode == "fall-qual"
    assert config.eventName == "Fall Qualifier"
    assert config.host == "scores.example.org:8443"
    assert config.expiresAt == datetime(2026, 11, 6, 0, 5, 9, tzinfo=UTC)
    assert SyncConfig.parse(config.toJson()) == config


@pytest.mark.parametrize("overrides", [
    {"format": "something-else"},
    {"version": 2},
    {"syncUrl": "http://scores.example.org:8443/api/v1/events/fall-qual"},
    {"clientKey": ""},
    {"caCertificate": "not a certificate"},
    {"event": None},
    {"expiresAt": "next week"},
    {"expiresAt": "2026-11-06T00:05:09"},
])
def test_unusable_sync_files_are_refused(overrides):
    with pytest.raises(SyncConfigError):
        SyncConfig.parse(json.dumps(syncFile(**overrides)))


def test_expiry_with_nanoseconds_and_an_offset_round_trips():
    config = SyncConfig.parse(json.dumps(syncFile(expiresAt="2026-11-05T19:05:09.123456789-05:00")))
    assert config.expiresAt == datetime(2026, 11, 6, 0, 5, 9, tzinfo=UTC)
    assert SyncConfig.parse(config.toJson()) == config


def test_non_json_is_refused():
    with pytest.raises(SyncConfigError):
        SyncConfig.parse("hello")


def test_expiry():
    config = SyncConfig.parse(json.dumps(syncFile(expiresAt="2026-11-06T00:05:09Z")))
    assert not config.isExpired(datetime(2026, 11, 6, 0, 5, 8, tzinfo=UTC))
    assert config.isExpired(datetime(2026, 11, 6, 0, 5, 9, tzinfo=UTC))


def test_saved_configuration_survives_a_relaunch_and_can_be_removed(database):
    assert Sync.loadConfig() is None
    config = SyncConfig.parse(json.dumps(syncFile()))
    Sync.saveConfig(config)

    database()
    assert Sync.loadConfig() == config

    Sync.removeConfig()
    database()
    assert Sync.loadConfig() is None


# Catching up

def test_startup_makes_the_score_reflector_match_the_local_data(harness, reflector):
    h = harness(
        teams=[TeamEntry("Bricks", 42, 3), TeamEntry("Studs", 7, 0)],
        scores=[ScoreEntry(42, 1, 180, "", {"m01a": "true"}), ScoreEntry(42, 3, 0, ""), ScoreEntry(7, 2, 95, "")],
    ).start()
    h.waitUntilSynced()

    assert teamsOn(reflector) == {7: ("Studs", 0, [None, 95, None]), 42: ("Bricks", 3, [180, None, 0])}
    assert reflector.state()["teams"][1]["rounds"][0] == {"score": 180, "scoresheet": {"m01a": "true"}}
    assert h.engine.status.revision == reflector.state()["revision"]
    assert h.removalPrompts == []


def test_startup_keeps_reflector_data_the_local_data_also_has(harness, reflector):
    reflector.seed(42, "Bricks", 3, [{"score": 180}, None, None])
    h = harness(teams=[TeamEntry("Bricks", 42, 3)], scores=[ScoreEntry(42, 1, 180, "")]).start()
    h.waitUntilSynced()
    assert teamsOn(reflector) == {42: ("Bricks", 3, [180, None, None])}
    assert h.removalPrompts == []


def test_a_concurrent_change_on_the_reflector_is_never_overwritten_by_a_stale_snapshot(harness, reflector):
    reflector.seed(42, "Bricks", 3)
    # Another writer changes the event between the engine's GET /state and PUT /state
    reflector.beforePutState = lambda r: r.seed(99, "Interloper")
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()

    # The engine compared again, and found data it would have to remove
    waitFor(lambda: h.removalPrompts)
    assert 99 in teamsOn(reflector)
    assert h.removalPrompts[-1].teams == {99}


# Asking before removing data

def test_reflector_data_missing_locally_is_not_removed_without_asking(harness, reflector):
    # E.g., the scoring software opened a new, empty database the day after the event started
    reflector.seed(42, "Bricks", 3, [{"score": 180}, None, None])
    reflector.seed(7, "Studs", 0, [None, {"score": 95}, None])
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()

    waitFor(lambda: h.removalPrompts)
    removals = h.removalPrompts[0]
    assert removals.teams == {7}
    assert removals.scores == {(42, 1)}
    assert h.engine.status.state == SyncState.ATTENTION

    # Declining pauses sync, leaving the reflector alone, even as local changes happen
    h.engine.resolveRemovals(False)
    Events.publish(Events.TeamUpdated(42, "Blocks", 3))
    time.sleep(0.2)
    assert teamsOn(reflector) == {7: ("Studs", 0, [None, 95, None]), 42: ("Bricks", 3, [180, None, None])}
    assert h.engine.status.state == SyncState.ATTENTION

    # Syncing again asks again; allowing it removes the data
    h.engine.resync()
    waitFor(lambda: len(h.removalPrompts) == 2)
    h.engine.resolveRemovals(True)
    h.waitUntilSynced()
    assert teamsOn(reflector) == {42: ("Blocks", 3, [None, None, None])}


def test_removals_made_locally_while_offline_need_no_confirmation(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3), TeamEntry("Studs", 7, 0)],
                scores=[ScoreEntry(42, 1, 180, ""), ScoreEntry(7, 1, 95, "")]).start()
    h.waitUntilSynced()

    reflector.offline = True
    Events.publish(Events.TeamDeleted(7))
    Events.publish(Events.ScoreCleared(42, 1))
    waitFor(lambda: h.engine.status.state == SyncState.OFFLINE)
    reflector.offline = False

    h.waitUntilSynced()
    assert teamsOn(reflector) == {42: ("Bricks", 3, [None, None, None])}
    assert h.removalPrompts == []


# Following local changes

def test_local_changes_are_sent_as_they_happen(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()

    Events.publish(Events.TeamAdded(7, "Studs", 1))
    Events.publish(Events.ScoreUpdated(7, 1, 95, {"m01a": "true"}))
    Events.publish(Events.ScoreUpdated(42, 2, 0))
    Events.publish(Events.TeamUpdated(42, "Blocks", 4))
    h.waitUntilSynced()
    assert teamsOn(reflector) == {7: ("Studs", 1, [95, None, None]), 42: ("Blocks", 4, [None, 0, None])}
    assert reflector.state()["teams"][0]["rounds"][0]["scoresheet"] == {"m01a": "true"}

    Events.publish(Events.ScoreCleared(7, 1))
    Events.publish(Events.TeamDeleted(42))
    h.waitUntilSynced()
    assert teamsOn(reflector) == {7: ("Studs", 1, [None, None, None])}
    assert h.removalPrompts == []


@pytest.mark.parametrize("eventType, expected", [
    ("MatchSelected", {"match": 4, "status": "preparing"}),
    ("MatchStarted", {"match": 4, "status": "running"}),
    ("MatchAborted", {"match": 4, "status": "preparing"}),
    ("MatchCompleted", {"match": 4, "status": "scoring"}),
])
def test_match_status_follows_the_timer(harness, reflector, eventType, expected):
    h = harness().start()
    h.waitUntilSynced()
    Events.publish(getattr(Events, eventType)(4))
    waitFor(lambda: reflector.state()["matchStatus"] == expected)


def completeMatch(match):
    """Complete a match the way the main window sees it: it advances the match number before
    the sync engine hears that the match completed."""
    def advance(event):
        Events.unsubscribe(Events.MatchCompleted, advance)
        Events.publish(Events.MatchSelected(event.match + 1))
    Events._subscribers.setdefault(Events.MatchCompleted, []).insert(0, advance)
    Events.publish(Events.MatchCompleted(match))


def test_a_completed_match_is_scoring_until_a_score_is_entered(harness, reflector):
    h = harness(teams=[TeamEntry("Studs", 7, 1)]).start()
    h.waitUntilSynced()
    Events.publish(Events.MatchSelected(4))
    Events.publish(Events.MatchStarted(4))
    completeMatch(4)
    h.waitUntilSynced()
    assert reflector.state()["matchStatus"] == {"match": 4, "status": "scoring"}

    # Changing the match number while scoring doesn't end scoring, but picks the next match
    Events.publish(Events.MatchSelected(6))
    h.waitUntilSynced()
    assert reflector.state()["matchStatus"] == {"match": 4, "status": "scoring"}

    Events.publish(Events.ScoreUpdated(7, 1, 120, None))
    waitFor(lambda: reflector.state()["matchStatus"] == {"match": 6, "status": "preparing"})

    # Further scores don't change it
    Events.publish(Events.ScoreUpdated(7, 2, 130, None))
    h.waitUntilSynced()
    assert reflector.state()["matchStatus"] == {"match": 6, "status": "preparing"}


def test_selecting_a_match_while_one_runs_doesnt_hide_it(harness, reflector):
    h = harness().start()
    h.waitUntilSynced()
    Events.publish(Events.MatchStarted(4))
    Events.publish(Events.MatchSelected(5))
    h.waitUntilSynced()
    assert reflector.state()["matchStatus"] == {"match": 4, "status": "running"}


def test_changes_made_while_offline_are_delivered_on_reconnect(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()

    reflector.offline = True
    Events.publish(Events.ScoreUpdated(42, 1, 180))
    waitFor(lambda: h.engine.status.state == SyncState.OFFLINE)
    Events.publish(Events.MatchStarted(2))
    assert h.engine.status.pending > 0
    assert teamsOn(reflector)[42][2] == [None, None, None]

    reflector.offline = False
    h.waitUntilSynced()
    assert teamsOn(reflector)[42][2] == [180, None, None]
    assert reflector.state()["matchStatus"] == {"match": 2, "status": "running"}
    assert h.engine.status.pending == 0


def test_the_latest_value_wins_when_changes_pile_up(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()

    reflector.offline = True
    Events.publish(Events.ScoreUpdated(42, 1, 10))
    waitFor(lambda: h.engine.status.state == SyncState.OFFLINE)
    Events.publish(Events.ScoreUpdated(42, 1, 20))
    Events.publish(Events.ScoreCleared(42, 1))
    Events.publish(Events.ScoreUpdated(42, 1, 30))
    reflector.offline = False

    h.waitUntilSynced()
    assert teamsOn(reflector)[42][2] == [30, None, None]


# Problems the operator should see

def test_a_team_the_reflector_would_refuse_is_reported_without_blocking_the_others(harness, reflector):
    h = harness(teams=[TeamEntry("", 42, 3), TeamEntry("Studs", 7, 0)]).start()
    waitFor(lambda: h.engine.status.state == SyncState.ATTENTION)
    assert "42" in h.engine.status.message
    assert teamsOn(reflector) == {7: ("Studs", 0, [None, None, None])}


def test_a_refused_certificate_is_reported(harness, reflector):
    reflector.rejectCertificate = True
    h = harness().start()
    waitFor(lambda: h.engine.status.state == SyncState.REJECTED)

    # Retried: a new sync file isn't needed if the problem was elsewhere
    reflector.rejectCertificate = False
    h.waitUntilSynced()


def test_an_unreachable_reflector_is_reported(harness, reflector):
    reflector.offline = True
    h = harness().start()
    waitFor(lambda: h.engine.status.state == SyncState.OFFLINE)
    assert h.engine.status.message


def test_status_updates_report_progress(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    states = [s.state for s in h.statuses]
    assert states[0] == SyncState.CONNECTING
    assert states[-1] == SyncState.OK
    assert h.statuses[-1].lastSuccess is not None


def test_stopping_sends_pending_changes_first(harness, reflector):
    gate = threading.Event()
    original = reflector.request

    def slowRequest(method, path, body=None):
        if path.startswith("/teams/"):
            gate.wait(1)
        return original(method, path, body)

    reflector.request = slowRequest
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()

    Events.publish(Events.ScoreUpdated(42, 1, 180))
    threading.Timer(0.2, gate.set).start()
    h.engine.stop(drainTimeout=3)

    assert teamsOn(reflector)[42][2] == [180, None, None]
    assert h.engine.status.state == SyncState.STOPPED


def test_stopped_engine_ignores_further_changes(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    h.engine.stop()
    requests = len(reflector.requests)
    Events.publish(Events.ScoreUpdated(42, 1, 180))
    time.sleep(0.1)
    assert len(reflector.requests) == requests


@pytest.mark.parametrize("status", ["practice", "opening_ceremonies", "closing_ceremonies"])
def test_event_wide_statuses_report_match_0(harness, reflector, status):
    h = harness().start()
    h.waitUntilSynced()
    Events.publish(Events.MatchSelected(4))
    h.engine.setMatchStatus(7, status)
    waitFor(lambda: reflector.state()["matchStatus"] == {"match": 0, "status": status})

    # Changing the match number doesn't end it, but starting a match does
    Events.publish(Events.MatchSelected(5))
    h.waitUntilSynced()
    assert reflector.state()["matchStatus"] == {"match": 0, "status": status}
    Events.publish(Events.MatchStarted(5))
    waitFor(lambda: reflector.state()["matchStatus"] == {"match": 5, "status": "running"})


@pytest.mark.parametrize("match, status", [(0, "preparing"), (1, "queueing")])
def test_invalid_match_statuses_are_refused(harness, match, status):
    h = harness()
    with pytest.raises(ValueError):
        h.engine.setMatchStatus(match, status)


def test_clearing_the_match_status(harness, reflector):
    h = harness().start()
    h.waitUntilSynced()
    h.engine.setMatchStatus(0, "practice")
    waitFor(lambda: reflector.state()["matchStatus"] is not None)
    h.engine.clearMatchStatus()
    waitFor(lambda: reflector.state()["matchStatus"] is None)
    assert ("DELETE", "/match-status", None) in reflector.requests

    # It stays clear when the match number changes
    Events.publish(Events.MatchSelected(5))
    h.waitUntilSynced()
    assert reflector.state()["matchStatus"] is None


def test_clearing_while_offline_is_sent_on_reconnect(harness, reflector):
    h = harness().start()
    h.waitUntilSynced()
    h.engine.setMatchStatus(0, "practice")
    waitFor(lambda: reflector.state()["matchStatus"] is not None)
    reflector.offline = True
    h.engine.clearMatchStatus()
    waitFor(lambda: h.engine.status.state == SyncState.OFFLINE)
    reflector.offline = False
    waitFor(lambda: reflector.state()["matchStatus"] is None)


# Submitting and finalizing

def test_submitting_sends_every_change_then_finalizes_the_event(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    h.engine.setMatchStatus(0, "closing_ceremonies")
    Events.publish(Events.ScoreUpdated(42, 3, 210))

    result = h.submit()
    assert result.problem == ""
    assert result.submission is not None and result.submission.size == len(DATABASE)

    # The submission is of the state with every change in it
    submission, database = reflector.submissions[0]
    assert database == DATABASE
    assert teamsOn(reflector) == {42: ("Bricks", 3, [None, None, 210])}
    assert submission["revision"] == reflector.state()["revision"] - 1
    assert reflector.state()["finalized"] is not None
    assert h.engine.status.state == SyncState.FINALIZED
    assert h.engine.status.finalized.by is None


def test_changes_after_finalizing_wait_until_the_event_is_unfinalized(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    assert h.submit().submission is not None

    Events.publish(Events.ScoreUpdated(42, 1, 180))
    waitFor(lambda: h.engine.status.pending == 1)
    time.sleep(0.3)
    assert h.engine.status.state == SyncState.FINALIZED
    assert teamsOn(reflector) == {42: ("Bricks", 3, [None, None, None])}

    reflector.unfinalize()
    h.waitUntilSynced()
    assert teamsOn(reflector) == {42: ("Bricks", 3, [180, None, None])}


def test_an_event_an_administrator_finalized_stops_sync(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    reflector.finalize(by="alice")

    Events.publish(Events.ScoreUpdated(42, 1, 180))
    waitFor(lambda: h.engine.status.state == SyncState.FINALIZED)
    assert h.engine.status.finalized.by == "alice"
    assert h.engine.status.pending == 1
    assert teamsOn(reflector) == {42: ("Bricks", 3, [None, None, None])}

    # Submitting it isn't possible until it's unfinalized
    result = h.submit()
    assert result.submission is None
    assert result.finalized is not None and result.finalized.by == "alice"
    assert reflector.submissions == []


def test_a_change_while_copying_the_database_catches_up_before_uploading(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    copies = []

    def database():
        if not copies:
            Events.publish(Events.ScoreUpdated(42, 1, 180))
        copies.append(DATABASE)
        return DATABASE

    assert h.submit(database).submission is not None
    assert len(copies) == 2
    assert teamsOn(reflector) == {42: ("Bricks", 3, [180, None, None])}
    assert reflector.submissions[0][0]["revision"] == reflector.state()["revision"] - 1


def test_submitting_while_offline_reports_the_problem(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    reflector.offline = True
    result = h.submit()
    assert result.submission is None and "reach" in result.problem
    assert reflector.submissions == []

    # Sync carries on, and submitting works once the score reflector can be reached
    reflector.offline = False
    h.waitUntilSynced()
    assert h.submit().submission is not None


def test_an_event_with_data_the_reflector_refused_isnt_submitted(harness, reflector):
    h = harness(teams=[TeamEntry("", 42, 3), TeamEntry("Studs", 7, 0)]).start()
    waitFor(lambda: h.engine.status.state == SyncState.ATTENTION)
    result = h.submit()
    assert result.submission is None and "42" in result.problem
    assert reflector.submissions == []


def test_submitting_while_sync_is_paused_doesnt_submit_later(harness, reflector):
    reflector.seed(7, "Studs", 0)
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    waitFor(lambda: h.removalPrompts)
    h.engine.resolveRemovals(False)
    waitFor(lambda: "paused" in h.engine.status.message)

    result = h.submit()
    assert result.submission is None and "paused" in result.problem

    h.engine.resync()
    waitFor(lambda: len(h.removalPrompts) == 2)
    h.engine.resolveRemovals(True)
    h.waitUntilSynced()
    assert reflector.submissions == []


def test_stopping_while_copying_the_database_doesnt_submit(harness, reflector):
    h = harness(teams=[TeamEntry("Bricks", 42, 3)]).start()
    h.waitUntilSynced()
    copying = threading.Event()
    results = []

    def database():
        copying.set()
        time.sleep(0.3)
        return DATABASE

    h.engine.submit(database, results.append)
    copying.wait(2)
    h.engine.stop()
    assert len(results) == 1 and "stopped" in results[0].problem
    assert reflector.submissions == []


def test_the_database_copy_leaves_out_the_sync_file(database, tmp_path):
    Sync.saveConfig(SyncConfig.parse(json.dumps(syncFile())))
    Substrate.setMeta("other", "kept")
    Events.publish(Events.TeamAdded(42, "Bricks", 3))
    Events.publish(Events.ScoreUpdated(42, 1, 180, {"m01a": "true"}))

    data = Sync.copyDatabase()
    assert data.startswith(b"SQLite format 3\x00")
    assert b"PRIVATE KEY" not in data

    path = tmp_path / "copy.db"
    path.write_bytes(data)
    copy = sqlite3.connect(path)
    try:
        assert copy.execute("SELECT key, value FROM meta").fetchall() == [("other", "kept")]
        assert copy.execute("SELECT teamnumber, name, pit FROM teams").fetchall() == [(42, "Bricks", 3)]
        assert copy.execute("SELECT teamnumber, round, score FROM scores").fetchall() == [(42, 1, 180)]
    finally:
        copy.close()

    # The database itself still has it
    assert Sync.loadConfig() is not None
