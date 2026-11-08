"""An in-memory score reflector that enforces the sync API contract in score-reflector's docs/sync-api.md."""

import copy
import hashlib
import re
import threading

from Sync import ConnectionFailed, ReflectorError


class FakeReflector:
    def __init__(self):
        self.lock = threading.Lock()
        self.revision = 0
        self.matchStatus = None
        self.matchStarts = {}      # match -> startedAt, the latest start sent for each match
        self.teams = {}            # number -> {"name", "pit", "rounds": [score body or None] * 3}
        self.offline = False       # Requests fail as if the network were down
        self.rejectCertificate = False
        self.requests = []         # (method, path, body) of every request that reached the server
        self.beforePutState = None  # Called before a PUT /state is applied, e.g. to simulate another writer
        self.finalized = None      # {"at": …} or {"at": …, "by": …} while the event is finalized
        self.submissions = []      # (submission, database) of every database stored

    # What the public scores pages would show

    def state(self) -> dict:
        with self.lock:
            return self._state()

    def _state(self):
        return {
            "revision": self.revision,
            "finalized": copy.deepcopy(self.finalized),
            "matchStatus": copy.deepcopy(self.matchStatus),
            "teams": [{"number": n, "name": t["name"], "pit": t["pit"], "rounds": copy.deepcopy(t["rounds"])}
                      for n, t in sorted(self.teams.items())],
            "matchStarts": [{"match": m, "startedAt": s} for m, s in sorted(self.matchStarts.items())],
        }

    def seed(self, number, name, pit=0, rounds=(None, None, None)):
        """Data some earlier sync put there."""
        with self.lock:
            self.teams[number] = {"name": name, "pit": pit, "rounds": list(rounds)}
            self.revision += 1

    def finalize(self, by="alice"):
        """An administrator finalizes the event from the admin page."""
        with self.lock:
            self._finalize({"at": "2026-11-01T18:30:00Z", "by": by})

    def unfinalize(self):
        with self.lock:
            self.finalized = None
            self.revision += 1

    def _finalize(self, finalized):
        self.finalized = finalized
        self.matchStatus = None
        self.revision += 1

    # The API

    def _connect(self):
        if self.offline:
            raise ConnectionFailed("Couldn't reach the score reflector (ConnectionError)")
        if self.rejectCertificate:
            raise ConnectionFailed("The score reflector refused this sync file's certificate", certificateProblem=True)

    def submit(self, database, baseRevision):
        """POST /submissions"""
        self._connect()
        with self.lock:
            self.requests.append(("POST", "/submissions", baseRevision))
            self._check(database.startswith(b"SQLite format 3\x00"), "not an SQLite database")
            sha256 = hashlib.sha256(database).hexdigest()
            if self.finalized is not None:
                # A retry of the submission that finalized it gets the same answer
                if self.submissions:
                    last = self.submissions[-1][0]
                    if last["sha256"] == sha256 and last["revision"] == baseRevision:
                        return {"revision": self.revision, "submission": copy.deepcopy(last)}
                raise ReflectorError(409, "event_finalized", "the event is finalized")
            if baseRevision != self.revision:
                raise ReflectorError(409, "revision_mismatch", "the event has changed",
                                     {"currentRevision": self.revision})
            submission = {"id": len(self.submissions) + 1, "submittedAt": "2026-11-01T18:30:00Z",
                          "revision": baseRevision, "sha256": sha256, "size": len(database)}
            self.submissions.append((submission, database))
            self._finalize({"at": submission["submittedAt"]})
            return {"revision": self.revision, "submission": copy.deepcopy(submission)}

    def request(self, method, path, body=None):
        self._connect()
        if method == "PUT" and path == "/state" and self.beforePutState is not None:
            hook, self.beforePutState = self.beforePutState, None
            hook(self)
        with self.lock:
            self.requests.append((method, path, copy.deepcopy(body)))
            parts = path.strip("/").split("/")
            if method == "GET" and parts == ["state"]:
                return self._state()
            if method == "PUT" and parts == ["state"]:
                return self._putState(body)
            if method == "PUT" and parts == ["match-status"]:
                status, starts = self._matchStatus(body)
                starts = self._newStarts(starts)

                def apply():
                    self.matchStatus = status
                    self.matchStarts.update(starts)
                return {"revision": self._write(apply, self.matchStatus != status or bool(starts))}
            if method == "DELETE" and parts == ["match-status"]:
                return {"revision": self._write(lambda: setattr(self, "matchStatus", None),
                                                self.matchStatus is not None)}
            if method == "PUT" and parts == ["teams"]:
                return self._putTeams(body)
            if len(parts) == 4 and parts[0] == "teams" and parts[2] == "rounds":
                number, roundNum = int(parts[1]), int(parts[3])
                self._check(1 <= roundNum <= 3)
                if number not in self.teams:
                    raise ReflectorError(404, "team_not_found", "the team is not in the event's team list")
                rounds = self.teams[number]["rounds"]
                value = None if method == "DELETE" else self._score(body)
                changed = rounds[roundNum - 1] != value
                return {"revision": self._write(lambda: rounds.__setitem__(roundNum - 1, value), changed)}
            raise ReflectorError(404, "not_found", "no such endpoint")

    def _write(self, apply, changed):
        if changed:
            if self.finalized is not None:
                raise ReflectorError(409, "event_finalized", "the event is finalized")
            apply()
            self.revision += 1
        return self.revision

    @staticmethod
    def _check(ok, message="invalid request"):
        if not ok:
            raise ReflectorError(400, "invalid_request", message)

    def _matchStatus(self, m):
        """The match status without its start, and the start as a list of match starts."""
        self._check(set(m) in ({"match", "status"}, {"match", "status", "startedAt"}))
        if m["status"] in ("preparing", "running", "scoring"):
            self._check(m["match"] >= 1)
        else:
            self._check(m["status"] in ("practice", "opening_ceremonies", "closing_ceremonies") and m["match"] == 0)
            self._check("startedAt" not in m)
        starts = [{"match": m["match"], "startedAt": m["startedAt"]}] if "startedAt" in m else []
        return {"match": m["match"], "status": m["status"]}, self._matchStarts(starts)

    def _matchStarts(self, starts):
        self._check(len(starts) <= 1000)
        for s in starts:
            self._check(set(s) == {"match", "startedAt"} and 1 <= s["match"] <= 99999)
            self._check(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", s["startedAt"]) is not None)
            self._check("2000" <= s["startedAt"] < "2200")
        self._check(len({s["match"] for s in starts}) == len(starts))
        return starts

    def _newStarts(self, starts):
        """The starts that are new or later than the ones the server has."""
        return {s["match"]: s["startedAt"] for s in starts
                if s["startedAt"] > self.matchStarts.get(s["match"], "")}

    def _team(self, t):
        self._check(set(t) <= {"number", "name", "pit", "rounds"})
        self._check(1 <= t["number"] <= 99999999 and 1 <= len(t["name"].encode()) <= 200 and t["pit"] >= 0)

    def _score(self, s):
        self._check(set(s) <= {"score", "scoresheet"} and 0 <= s["score"] <= 1000000)
        sheet = s.get("scoresheet") or None
        if sheet is not None:
            self._check(all(isinstance(v, str) for v in sheet.values()))
        return {"score": s["score"], **({"scoresheet": sheet} if sheet else {})}

    def _removals(self, newNumbers, allowRemovals, newRounds=None):
        removed = {"teams": sorted(set(self.teams) - newNumbers), "scores": []}
        if newRounds is not None:
            for number, rounds in newRounds.items():
                old = self.teams.get(number)
                if old is not None:
                    removed["scores"] += [[number, i + 1] for i in range(3) if old["rounds"][i] and not rounds[i]]
        if (removed["teams"] or removed["scores"]) and not allowRemovals:
            raise ReflectorError(409, "removals_not_allowed", "the write would remove data", removed)

    def _putTeams(self, body):
        self._check(set(body) <= {"teams", "allowRemovals"})
        for t in body["teams"]:
            self._team(t)
        numbers = {t["number"] for t in body["teams"]}
        self._check(len(numbers) == len(body["teams"]))
        self._removals(numbers, body.get("allowRemovals", False))
        new = {t["number"]: {"name": t["name"], "pit": t["pit"],
                             "rounds": self.teams.get(t["number"], {"rounds": [None] * 3})["rounds"]}
               for t in body["teams"]}
        return {"revision": self._write(lambda: setattr(self, "teams", new), new != self.teams)}

    def _putState(self, body):
        self._check(set(body) <= {"baseRevision", "allowRemovals", "matchStatus", "teams", "matchStarts"})
        if body["baseRevision"] != self.revision:
            raise ReflectorError(409, "revision_mismatch", "the event has changed",
                                 {"currentRevision": self.revision})
        for t in body["teams"]:
            self._team(t)
            self._check(len(t["rounds"]) == 3)
        rounds = {t["number"]: [self._score(r) if r else None for r in t["rounds"]] for t in body["teams"]}
        self._removals(set(rounds), body.get("allowRemovals", False), rounds)
        new = {t["number"]: {"name": t["name"], "pit": t["pit"], "rounds": rounds[t["number"]]} for t in body["teams"]}
        starts = self._matchStarts(body.get("matchStarts") or [])
        match = self.matchStatus
        if body["matchStatus"] is not None:
            match, statusStarts = self._matchStatus(body["matchStatus"])
            starts = starts + statusStarts
        starts = self._newStarts(starts)

        def apply():
            self.teams = new
            self.matchStatus = match
            self.matchStarts.update(starts)
        changed = new != self.teams or match != self.matchStatus or bool(starts)
        return {"revision": self._write(apply, changed), "changes": {}}
