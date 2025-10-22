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

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import About
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


# In Python, the module import process happens once per program execution,
# no matter how many times a module is imported, so these variables end up
# being singletons shared across the entire program
_db = None
_cur = None


def init():
    """Initialize Substrate layer."""
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
        writeAuditEntry("db_created", {"ibss_version": About.getVersion(), "pack_version": ResourceManager.getResourcePackVersion()})
    else:
        writeAuditEntry("db_opened", {"ibss_version": About.getVersion(), "pack_version": ResourceManager.getResourcePackVersion()})


def deinit():
    """Deinitialize Substrate layer."""
    writeAuditEntry("db_closed", {})
    _db.close()


def loadTeams() -> list:
    """Return a list of TeamEntry objects representing all saved teams."""
    _cur.execute("SELECT teamnumber, name, pit FROM teams")
    return [TeamEntry(teamnumber=t[0], name=t[1], pit=t[2]) for t in _cur.fetchall()]


def loadScores() -> list:
    """Return a list of ScoreEntry objects representing all saved scores."""
    _cur.execute("SELECT teamnumber, round, score, comments FROM scores")
    return [ScoreEntry(teamnumber=s[0], round=s[1], score=s[2], comments=s[3]) for s in _cur.fetchall()]


def saveTeam(teamnumber: int, name: str, pit: int):
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
        writeAuditEntry("team_add", auditEntry)
    else:
        auditEntry = {
            "teamnumber": teamnumber,
            "old_name": old_team[0],
            "new_name": name,
            "old_pit": old_team[1],
            "new_pit": pit
        }
        writeAuditEntry("team_update", auditEntry)


def saveScore(teamnumber: int, round: int, score: int, comments: str = ""):
    """Create or update a match score, writing an audit log entry to note the change."""
    slug = f"{teamnumber}-{round}"
    # Check if previous score exists
    _cur.execute("SELECT score FROM scores WHERE teamnumber = ? AND round = ?", (teamnumber, round))
    maybe_old_score = _cur.fetchall()
    old_score = None if len(maybe_old_score) == 0 else maybe_old_score[0][0]

    # Allow updating existing scores by using INSERT OR REPLACE INTO
    _cur.execute("INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?, ?)",
                 (slug, teamnumber, round, score, comments))

    auditEntry = {
        "teamnumber": teamnumber,
        "round": round,
        "old_score": old_score,
        "new_score": score
    }
    writeAuditEntry("score_update", auditEntry)


def saveScoresheet(teamnumber: int, round: int, scoresheet: str):
    """Create or update a match scoresheet, writing an audit log entry to note the change."""
    slug = f"{teamnumber}-{round}"
    # Check if previous score exists
    _cur.execute("SELECT scoresheet FROM scoresheets WHERE teamnumber = ? AND round = ?", (teamnumber, round))
    maybe_old_scoresheet = _cur.fetchall()
    old_scoresheet = None if len(maybe_old_scoresheet) == 0 else maybe_old_scoresheet[0][0]

    # Allow updating existing scoresheets by using INSERT OR REPLACE INTO
    _cur.execute("INSERT OR REPLACE INTO scoresheets VALUES (?, ?, ?, ?)",
                 (slug, teamnumber, round, scoresheet))

    auditEntry = {
        "teamnumber": teamnumber,
        "round": round,
        "old_score": old_scoresheet,
        "new_score": scoresheet
    }
    writeAuditEntry("scoresheet_update", auditEntry)

def deleteTeam(teamnumber: int):
    """Delete a team, including its associated scores."""
    # Delete the team
    writeAuditEntry("team_delete", {"teamnumber": teamnumber})
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
        writeAuditEntry("score_delete", audit_entry)
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
        writeAuditEntry("score_delete", audit_entry)
        _cur.execute("DELETE FROM scoresheets WHERE slug = ?", (entry[0],))

    _db.commit()


def writeAuditEntry(tag: str, data: dict):
    """Write an audit log entry."""
    timestamp = datetime.now().timestamp()

    # Add timestamp and tag to entry data to make processing offline easier
    data["timestamp"] = timestamp
    data["tag"] = tag
    entryData = json.dumps(data)

    _cur.execute("INSERT INTO audit VALUES (?, ?, ?)", (timestamp, tag, entryData))
    _db.commit()


def writeLogEntry(tag: str, message: str):
    """Write an internal program log entry, primarily intended for debugging and capturing stack traces."""
    timestamp = datetime.now().timestamp()
    _cur.execute("INSERT INTO log VALUES (?, ?, ?)", (timestamp, tag, message))
    _db.commit()


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
                       PRAGMA user_version = 3;
                       CREATE TABLE teams(teamnumber type UNIQUE, name, pit);
                       CREATE TABLE scores(slug type UNIQUE, teamnumber, round, score, comments);
                       CREATE TABLE audit(timestamp, tag, data);
                       CREATE TABLE log(timestamp, tag, message);
                       CREATE TABLE scoresheets(slug type UNIQUE, teamnumber, round, scoresheet);
                       CREATE TABLE meta(key type UNIQUE, value);
                       """)
    _db.commit()
