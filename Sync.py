"""
Sync.py: Sync adapter to score-reflector

Copyright (C) 2024 Interlocking Brick Software Collective

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

import queue
import threading

from dataclasses import dataclass, asdict
from typing import List

import requests

from Team import Team

@dataclass
class TeamSyncObject:
    name: str
    teamnumber: int
    pit: int


@dataclass
class TeamStateSync:
    name: str
    teamnumber: int
    pit: int
    round1: int
    round2: int
    round3: int

    def json(self):
        return {"name": self.name, "teamnumber": self.teamnumber, "pit": self.pit,
                "round1": self.round1, "round2": self.round2, "round3": self.round3}


class TeamSync:
    def __init__(self, teams: List[TeamSyncObject]):
        self.teams = teams

    def json(self):
        return [{"name": t.name, "number": t.teamnumber, "pit": t.pit} for t in self.teams]


@dataclass
class MatchSync:
    match_num: int
    status: str

    def json(self):
        return {"match": self.match_num, "status": self.status}

 
@dataclass
class ScoreSync:
    teamnumber: int
    match: int
    score: int

    def json(self):
        return {"team": self.teamnumber, "match": self.match, "score": self.score}


@dataclass
class EventSync:
    match_num: int
    status: str
    teams: List[TeamStateSync]

    def json(self):
        return {"match": self.match_num, "status": self.status, "teams": self.teams}


sync_url = None
event_code = None
apikey = None
setup_event = threading.Event()
request_queue = queue.Queue()

def setup_sync(settings: dict):
    global sync_url, event_code, apikey

    sync_url = settings["sync_url"]
    event_code = settings["event_code"]
    apikey = settings["apikey"]

    setup_event.set()


def post_teams(teams_list: List[Team]):
    team_sync_objs = [TeamSyncObject(t.name, t.number, t.pit) for t in teams_list]
    team_sync = TeamSync(team_sync_objs)
    request_queue.put(team_sync)


def post_match_status(match_num: int, status: str):
    request_queue.put(MatchSync(match_num=match_num, status=status))


def post_score(team: int, round: int, score: int):
    request_queue.put(ScoreSync(team, round, score))


def sync_event(match_number: str, match_state: str, teams: List[Team]):
    event_state = EventSync(match_number, match_state, [])
    for t in teams:
        event_state.teams.append(TeamStateSync(t.name, t.number,
                                                  int(t.pit), t.scores[0],
                                                  t.scores[1], t.scores[2]))
    #request_queue.put(event_state)
    reflector_base = f"{sync_url}/{event_code}"
    auth = {"apikey": apikey}
    print(asdict(event_state))
    resp = requests.post(f"{reflector_base}/sync", headers=auth, json=asdict(event_state), timeout=5)
    print(resp)


def request_thread():
    # Wait for setup before pushing queued requests
    setup_event.wait()

    reflector_base = f"{sync_url}/{event_code}"
    auth = {"apikey": apikey}

    while True:
        try:
            req = request_queue.get()
            if req is None:  # stop request
                break

            if isinstance(req, TeamSync):
                resp = requests.post(f"{reflector_base}/teams", headers=auth, json=req.json(), timeout=5)
                print(resp)
            elif isinstance(req, MatchSync):
                resp = requests.post(f"{reflector_base}/match", headers=auth, json=req.json(), timeout=5)
                print(resp)
            elif isinstance(req, ScoreSync):
                resp = requests.post(f"{reflector_base}/scores", headers=auth, json=req.json(), timeout=5)
                print(resp)
            elif isinstance(req, EventSync):
                resp = requests.post(f"{reflector_base}/sync", headers=auth, json=req.json(), timeout=5)
                print(resp)
        except:
            return