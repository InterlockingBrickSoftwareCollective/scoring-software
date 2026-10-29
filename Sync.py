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
import queue
import threading

from dataclasses import dataclass, field

import requests

import Events
import Substrate

SETTINGS_FILE = "sync.json"


@dataclass
class TeamState:
    name: str
    pit: int
    scores: list = field(default_factory=lambda: [-1, -1, -1])


# Sync keeps its own mirror of the event state, built from the database at
# startup and then kept current from events. The mirror is only touched on the
# main thread (where events are published); the request thread only ever sees
# fully-built request payloads, so no locking is needed.
_teams = {}
_match = 1
_matchStatus = "queueing"

_reflectorBase = None
_auth = None
_requestQueue = queue.Queue()


def init() -> bool:
    """Start syncing to score-reflector if configured. Must be called after Substrate.init()."""
    global _reflectorBase, _auth

    try:
        with open(SETTINGS_FILE, "r") as f:
            settings = json.load(f)
        _reflectorBase = f"{settings['sync_url']}/{settings['event_code']}"
        _auth = {"apikey": settings["apikey"]}
    except FileNotFoundError:
        print("Sync disabled (no sync settings)")
        return False
    except Exception as err:
        print(f"Sync disabled (invalid sync settings: {err})")
        return False

    for team in Substrate.loadTeams():
        _teams[int(team.teamnumber)] = TeamState(team.name, int(team.pit))
    for score in Substrate.loadScores():
        if int(score.teamnumber) in _teams:
            _teams[int(score.teamnumber)].scores[score.round - 1] = score.score

    Events.subscribe(Events.TeamAdded, _onTeamChanged)
    Events.subscribe(Events.TeamUpdated, _onTeamChanged)
    Events.subscribe(Events.TeamDeleted, _onTeamDeleted)
    Events.subscribe(Events.ScoreUpdated, _onScoreUpdated)
    Events.subscribe(Events.MatchSelected, lambda e: _onMatchStatus(e.match, "queueing"))
    Events.subscribe(Events.MatchStarted, lambda e: _onMatchStatus(e.match, "running"))
    Events.subscribe(Events.MatchAborted, lambda e: _onMatchStatus(e.match, "aborted"))

    threading.Thread(target=_requestThread, daemon=True).start()

    # Bring the reflector up to date with anything that changed while we weren't syncing
    forceSync()
    return True


def forceSync():
    """Send the complete event state, overwriting whatever the reflector has."""
    teams = [{"name": t.name, "teamnumber": number, "pit": t.pit,
              "round1": t.scores[0], "round2": t.scores[1], "round3": t.scores[2]}
             for number, t in _teams.items()]
    _post("sync", {"match": _match, "status": _matchStatus, "teams": teams})


def _onTeamChanged(event):
    if event.number in _teams:
        _teams[event.number].name = event.name
        _teams[event.number].pit = int(event.pit)
    else:
        _teams[event.number] = TeamState(event.name, int(event.pit))
    _postTeams()


def _onTeamDeleted(event):
    _teams.pop(event.number, None)
    _postTeams()


def _onScoreUpdated(event):
    if event.teamNumber in _teams:
        _teams[event.teamNumber].scores[event.round - 1] = event.score
    _post("scores", {"team": event.teamNumber, "match": event.round, "score": event.score})


def _onMatchStatus(match: int, status: str):
    global _match, _matchStatus
    _match = match
    _matchStatus = status
    _post("match", {"match": match, "status": status})


def _postTeams():
    _post("teams", [{"name": t.name, "number": number, "pit": t.pit} for number, t in _teams.items()])


def _post(endpoint: str, payload):
    _requestQueue.put((endpoint, payload))


def _requestThread():
    # Requests are sent one at a time, in order, so the reflector sees changes in the order they happened
    while True:
        endpoint, payload = _requestQueue.get()
        try:
            resp = requests.post(f"{_reflectorBase}/{endpoint}", headers=_auth, json=payload, timeout=5)
            print(f"Sync {endpoint}: {resp.status_code}")
        except requests.RequestException as err:
            # Drop the request rather than retrying; a force sync recovers any lost state
            print(f"Sync {endpoint} failed: {err}")
