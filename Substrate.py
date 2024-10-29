"""This file is part of Interlocking Brick Scoring Software.

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


@dataclass
class TeamEntry:
    name: str
    teamnumber: int


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

    # By default, open a database with today's date, since we assume that
    # multiple events won't be run on the same computer on the same day...
    _db = sqlite3.connect(f"{datetime.now().strftime('%Y%m%d')}-event.db")
    _cur = _db.cursor()

    # Check if database is empty (i.e., has no tables)
    _cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = _cur.fetchall()

    if len(tables) == 0:
        _createTables()
        writeAuditEntry("db_created", {})
    else:
        writeAuditEntry("db_opened", {})


def deinit():
    """Deinitialize Substrate layer."""
    writeAuditEntry("db_closed", {})
    _db.close()


def loadTeams() -> list:
    """Return a list of TeamEntry objects representing all saved teams."""
    _cur.execute("SELECT teamnumber, name FROM teams")
    return [TeamEntry(teamnumber=t[0], name=t[1]) for t in _cur.fetchall()]


def loadScores() -> list:
    """Return a list of ScoreEntry objects representing all saved scores."""
    _cur.execute("SELECT teamnumber, round, score, comments FROM scores")
    return [ScoreEntry(teamnumber=s[0], round=s[1], score=s[2], comments=s[3]) for s in _cur.fetchall()]


def saveTeam(teamnumber: int, name: str):
    """Create or update a team (number and name)."""
    # Allow renaming teams by using INSERT OR REPLACE INTO
    _cur.execute("INSERT OR REPLACE INTO teams VALUES (?, ?)", (teamnumber, name))
    _db.commit()


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


def deleteTeam(teamnumber: int):
    """Delete a team, including its associated scores."""
    # Delete the team
    writeAuditEntry("team_delete", {"teamnumber": teamnumber})
    _cur.execute("DELETE FROM teams WHERE teamnumber = ?", (teamnumber,))

    # Find all associated scores, audit log the deletion, then perform the deletion
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


def _createTables():
    """Internal method to create tables for a freshly-initialized database."""
    _cur.executescript("""
                       PRAGMA application_id = 0;
                       PRAGMA user_version = 0;
                       CREATE TABLE teams(teamnumber type UNIQUE, name);
                       CREATE TABLE scores(slug type UNIQUE, teamnumber, round, score, comments);
                       CREATE TABLE audit(timestamp, tag, data);
                       CREATE TABLE log(timestamp, tag, message);
                       """)
    _db.commit()
