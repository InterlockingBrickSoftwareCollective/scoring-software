"""
Substrate.py: Database layer

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
import sqlite3
import traceback

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import About
import Events
import ResourceManager

@dataclass
class TeamEntry:
    name: str
    teamnumber: int
    pit: int


@dataclass
class ScoreEntry:
    teamnumber: int
    round: int
    score: int
    comments: str
    scoresheet: Optional[dict] = None


# In Python, the module import process happens once per program execution,
# no matter how many times a module is imported, so these variables end up
# being singletons shared across the entire program
_db = None
_cur = None

# All database access happens on a single dedicated thread, which keeps slow
# disk writes off the UI thread and satisfies SQLite's requirement that a
# connection only be used from the thread that created it. Work runs in the
# order it was submitted, so reads always see every previously-submitted write.
#
# Functions prefixed with an underscore must only run on the database thread.
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Substrate")


def _run(fn, *args):
    """Run fn on the database thread and wait for its result."""
    return _executor.submit(fn, *args).result()


def _write(fn, *args):
    """Queue fn to run on the database thread without waiting for it."""
    _executor.submit(fn, *args).add_done_callback(_reportWriteError)


def _reportWriteError(future):
    if future.exception() is not None:
        print("Database write failed:")
        traceback.print_exception(future.exception())


def init():
    """Initialize Substrate layer, then persist events to the database from here on."""
    _run(_open)

    Events.subscribe(Events.TeamAdded, lambda e: _write(_saveTeam, e.number, e.name, e.pit))
    Events.subscribe(Events.TeamUpdated, lambda e: _write(_saveTeam, e.number, e.name, e.pit))
    Events.subscribe(Events.TeamDeleted, lambda e: _write(_deleteTeam, e.number))
    Events.subscribe(Events.ScoreUpdated, lambda e: _write(_saveScore, e.teamNumber, e.round, e.score, e.scoresheet))
    Events.subscribe(Events.ScoreCleared, lambda e: _write(_clearScore, e.teamNumber, e.round))
    Events.subscribe(Events.MatchStarted, lambda e: _write(_writeLogEntry, "match_start", f"{e.match}"))


def deinit():
    """Deinitialize Substrate layer, waiting for all pending writes to finish."""
    _run(_close)
    _executor.shutdown()


def loadTeams() -> list:
    """Return a list of TeamEntry objects representing all saved teams."""
    return _run(_loadTeams)


def loadScores() -> list:
    """Return a list of ScoreEntry objects representing all saved scores, with their scoresheets."""
    return _run(_loadScores)


def retrieveMatchStartTimes() -> list:
    """Return (match number, start timestamp) for the latest start of each match."""
    return _run(_retrieveMatchStartTimes)


def getMeta(key: str) -> Optional[str]:
    """Return a value saved with setMeta(), or None if there is none."""
    return _run(_getMeta, key)


def setMeta(key: str, value: str):
    """Save a value in the database, replacing any previous value for key."""
    _run(_setMeta, key, value)


def deleteMeta(key: str):
    """Delete a value saved with setMeta(), if there is one."""
    _run(_deleteMeta, key)


def copyDatabase(excludeMeta: list = ()) -> bytes:
    """Return a consistent copy of the database file, as of every previously-submitted write,
    leaving out the meta values for the keys in excludeMeta."""
    return _run(_copyDatabase, list(excludeMeta))


def writeLogEntry(tag: str, message: str):
    """Write an internal program log entry, primarily intended for debugging and capturing stack traces."""
    _write(_writeLogEntry, tag, message)


def _open():
    global _db, _cur

    # Check if a precreated database has been populated
    dbFilename = _findPrecreatedDb()
    if dbFilename is None:
        # If no precreated database is available, open a database with today's date,
        # since we assume that multiple events won't be run on the same computer on the same day...
        dbFilename = f"{datetime.now().strftime('%Y%m%d')}-event.db"

    _db = sqlite3.connect(dbFilename)
    _cur = _db.cursor()

    # Check if database is empty (i.e., has no tables)
    _cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = _cur.fetchall()

    if len(tables) == 0:
        _createTables()
        _writeAuditEntry("db_created", {"ibss_version": About.getVersion(), "pack_version": ResourceManager.getResourcePackVersion()})
    else:
        _writeAuditEntry("db_opened", {"ibss_version": About.getVersion(), "pack_version": ResourceManager.getResourcePackVersion()})


def _close():
    _writeAuditEntry("db_closed", {})
    _db.close()


def _loadTeams() -> list:
    _cur.execute("SELECT teamnumber, name, pit FROM teams")
    return [TeamEntry(teamnumber=t[0], name=t[1], pit=t[2]) for t in _cur.fetchall()]


def _loadScores() -> list:
    _cur.execute("""
        SELECT scores.teamnumber, scores.round, scores.score, scores.comments, scoresheets.scoresheet
        FROM scores LEFT JOIN scoresheets ON scores.slug = scoresheets.slug
    """)
    return [ScoreEntry(teamnumber=s[0], round=s[1], score=s[2], comments=s[3],
                       scoresheet=json.loads(s[4]) if s[4] is not None else None)
            for s in _cur.fetchall()]


def _saveTeam(teamnumber: int, name: str, pit: int):
    """Create or update a team (number and name)."""
    # Check if team already exists
    _cur.execute("SELECT name, pit FROM teams WHERE teamnumber = ?", (teamnumber,))
    maybe_old_team = _cur.fetchall()
    old_team = None if len(maybe_old_team) == 0 else (maybe_old_team[0][0], maybe_old_team[0][1])

    # Allow renaming teams by using INSERT OR REPLACE INTO
    _cur.execute("INSERT OR REPLACE INTO teams VALUES (?, ?, ?)", (teamnumber, name, pit))

    if old_team is None:
        auditEntry = {
            "teamnumber": teamnumber,
            "name": name
        }
        _writeAuditEntry("team_add", auditEntry)
    else:
        auditEntry = {
            "teamnumber": teamnumber,
            "old_name": old_team[0],
            "new_name": name,
            "old_pit": old_team[1],
            "new_pit": pit
        }
        _writeAuditEntry("team_update", auditEntry)


def _saveScore(teamnumber: int, round: int, score: int, scoresheet: Optional[dict]):
    """Create or update a match score and its scoresheet, writing audit log entries to note the change."""
    slug = f"{teamnumber}-{round}"
    # Check if previous score exists
    _cur.execute("SELECT score FROM scores WHERE slug = ?", (slug,))
    maybe_old_score = _cur.fetchall()
    old_score = None if len(maybe_old_score) == 0 else maybe_old_score[0][0]

    # Allow updating existing scores by using INSERT OR REPLACE INTO
    _cur.execute("INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?, ?)",
                 (slug, teamnumber, round, score, ""))

    auditEntry = {
        "teamnumber": teamnumber,
        "round": round,
        "old_score": old_score,
        "new_score": score
    }
    _writeAuditEntry("score_update", auditEntry)

    # A score entered without a scoresheet replaces any scoresheet the previous score had
    _setScoresheet(teamnumber, round, json.dumps(scoresheet) if scoresheet is not None else None)
    _db.commit()


def _clearScore(teamnumber: int, round: int):
    """Delete a match score and its scoresheet, writing audit log entries to note the change."""
    slug = f"{teamnumber}-{round}"
    _cur.execute("SELECT score FROM scores WHERE slug = ?", (slug,))
    maybe_old_score = _cur.fetchall()
    if len(maybe_old_score) > 0:
        _writeAuditEntry("score_delete", {
            "teamnumber": teamnumber,
            "round": round,
            "old_score": maybe_old_score[0][0],
            "new_score": None
        })
        _cur.execute("DELETE FROM scores WHERE slug = ?", (slug,))

    _setScoresheet(teamnumber, round, None)
    _db.commit()


def _setScoresheet(teamnumber: int, round: int, scoresheet: Optional[str]):
    """Create, update or (if scoresheet is None) delete a match scoresheet, writing an audit log entry if it changed."""
    slug = f"{teamnumber}-{round}"
    _cur.execute("SELECT scoresheet FROM scoresheets WHERE slug = ?", (slug,))
    maybe_old_scoresheet = _cur.fetchall()
    old_scoresheet = None if len(maybe_old_scoresheet) == 0 else maybe_old_scoresheet[0][0]

    if old_scoresheet == scoresheet:
        return

    if scoresheet is None:
        _cur.execute("DELETE FROM scoresheets WHERE slug = ?", (slug,))
    else:
        _cur.execute("INSERT OR REPLACE INTO scoresheets VALUES (?, ?, ?, ?)",
                     (slug, teamnumber, round, scoresheet))

    auditEntry = {
        "teamnumber": teamnumber,
        "round": round,
        "old_scoresheet": old_scoresheet,
        "new_scoresheet": scoresheet
    }
    _writeAuditEntry("scoresheet_update", auditEntry)

def _deleteTeam(teamnumber: int):
    """Delete a team, including its associated scores."""
    # Delete the team
    _writeAuditEntry("team_delete", {"teamnumber": teamnumber})
    _cur.execute("DELETE FROM teams WHERE teamnumber = ?", (teamnumber,))

    # Find all associated scores, scoresheets, audit log the deletion, then perform the deletion
    _cur.execute("SELECT slug, round, score FROM scores WHERE teamnumber = ?", (teamnumber,))
    maybe_delete_scores = _cur.fetchall()
    for score_entry in maybe_delete_scores:
        audit_entry = {
            "teamnumber": teamnumber,
            "round": score_entry[1],
            "old_score": score_entry[2],
            "new_score": None
        }
        _writeAuditEntry("score_delete", audit_entry)
        _cur.execute("DELETE FROM scores WHERE slug = ?", (score_entry[0],))

    _cur.execute("SELECT slug, round, scoresheet FROM scoresheets WHERE teamnumber = ?", (teamnumber,))
    maybe_delete_scoresheets = _cur.fetchall()
    for entry in maybe_delete_scoresheets:
        audit_entry = {
            "teamnumber": teamnumber,
            "round": entry[1],
            "old_scoresheet": entry[2],
            "new_scoresheet": None
        }
        _writeAuditEntry("score_delete", audit_entry)
        _cur.execute("DELETE FROM scoresheets WHERE slug = ?", (entry[0],))

    _db.commit()


def _writeAuditEntry(tag: str, data: dict):
    """Write an audit log entry."""
    timestamp = datetime.now().timestamp()

    # Add timestamp and tag to entry data to make processing offline easier
    data["timestamp"] = timestamp
    data["tag"] = tag
    entryData = json.dumps(data)

    _cur.execute("INSERT INTO audit VALUES (?, ?, ?)", (timestamp, tag, entryData))
    _db.commit()


def _getMeta(key: str) -> Optional[str]:
    _cur.execute("SELECT value FROM meta WHERE key = ?", (key,))
    row = _cur.fetchone()
    return row[0] if row is not None else None


def _setMeta(key: str, value: str):
    _cur.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))
    # Only the key is audited: values may be secrets (e.g., the sync client key)
    _writeAuditEntry("meta_update", {"key": key})


def _deleteMeta(key: str):
    _cur.execute("DELETE FROM meta WHERE key = ?", (key,))
    _writeAuditEntry("meta_delete", {"key": key})


def _copyDatabase(excludeMeta: list) -> bytes:
    _db.commit()
    copy = sqlite3.connect(":memory:")
    try:
        _db.backup(copy)
        hasMeta = copy.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone()
        if excludeMeta and hasMeta:
            copy.executemany("DELETE FROM meta WHERE key = ?", [(key,) for key in excludeMeta])
            copy.commit()
            # Rebuild the database, so that nothing of the deleted values is left in free pages
            copy.execute("VACUUM")
        return copy.serialize()
    finally:
        copy.close()


def _writeLogEntry(tag: str, message: str):
    timestamp = datetime.now().timestamp()
    _cur.execute("INSERT INTO log VALUES (?, ?, ?)", (timestamp, tag, message))
    _db.commit()

def _retrieveMatchStartTimes():
    # Query for all match_start entries, getting the latest timestamp for each match
    _cur.execute('''
        SELECT message, MAX(timestamp) as latest_timestamp
        FROM log
        WHERE tag = 'match_start'
        GROUP BY message
        ORDER BY CAST(message AS INTEGER)
    ''')

    return _cur.fetchall()


def _findPrecreatedDb() -> Optional[str]:
    """Find the precreated event database closest to today's date that is not in the past."""
    import os
    import re

    # Precreated databases follow the pattern of EVENTCODE-YYYYMMDD.db
    pattern = re.compile(r"^([a-zA-Z][a-zA-Z0-9]+)-(\d{8})\.db")

    today = datetime.today().date()
    closestFile = None
    closestDate = None

    for filename in os.listdir(os.getcwd()):
        match = pattern.match(filename)
        if match:
            # Extract the date string (second group)
            date_str = match.group(2)
            try:
                fileDate = datetime.strptime(date_str, '%Y%m%d').date()
                # Check if the file's date is not in the past
                if fileDate >= today:
                    # Find the closest date without being in the past
                    if closestDate is None or fileDate < closestDate:
                        closestDate = fileDate
                        closestFile = filename
            except ValueError:
                # Skip files with invalid date formats
                continue

    return closestFile


def _createTables():
    """Internal method to create tables for a freshly-initialized database."""
    _cur.executescript("""
                       PRAGMA application_id = 0;
                       PRAGMA user_version = 4;
                       CREATE TABLE teams(teamnumber type UNIQUE, name, pit);
                       CREATE TABLE scores(slug type UNIQUE, teamnumber, round, score, comments);
                       CREATE TABLE audit(timestamp, tag, data);
                       CREATE TABLE log(timestamp, tag, message);
                       CREATE TABLE scoresheets(slug type UNIQUE, teamnumber, round, scoresheet);
                       CREATE TABLE meta(key type UNIQUE, value);
                       """)
    _db.commit()
