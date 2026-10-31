"""
Team.py: Team object definition

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

from typing import Optional

import Events

# Rank given to teams that have no scores yet ("not placed")
UNRANKED = 1E10


class Team:
    def __init__(self, name, number, pit=0, from_db=False):
        try:
            self.name = name
            self.number = int(number)
            self.pit = pit
            # None means the team hasn't played that round yet
            self.scores: list[Optional[int]] = [None, None, None]
            # Scoresheet entered for each round's score; None for rounds scored without one
            self.scoresheets: list[Optional[dict]] = [None, None, None]
            self.highScoreIndex = None
            self.rank = UNRANKED
            if not from_db:
                Events.publish(Events.TeamAdded(self.number, name, pit))
        except Exception as err:
            print(err)

    def __lt__(self, other):
        return self.number < other.number

    def setScore(self, roundNum: int, score: int, scoresheet: Optional[dict] = None, from_db=False):
        try:
            self.scores[roundNum - 1] = score
            self.scoresheets[roundNum - 1] = scoresheet
            self._updateHighScore()
            if not from_db:
                Events.publish(Events.ScoreUpdated(self.number, roundNum, score, scoresheet))
        except Exception as err:
            print(err)

    def clearScore(self, roundNum: int):
        """Forget the team's score for a round, as if the round hadn't been played."""
        try:
            if self.scores[roundNum - 1] is None:
                return
            self.scores[roundNum - 1] = None
            self.scoresheets[roundNum - 1] = None
            self._updateHighScore()
            Events.publish(Events.ScoreCleared(self.number, roundNum))
        except Exception as err:
            print(err)

    def hasScores(self) -> bool:
        return any(score is not None for score in self.scores)

    def rankingKey(self) -> tuple:
        """Sort key, highest first: best score, then second best, then third best, then lowest team number."""
        # An unplayed round ranks below any played round, including one that scored 0
        played = sorted((score for score in self.scores if score is not None), reverse=True)
        played += [-1] * (3 - len(played))
        return (*played, -self.number)

    def _updateHighScore(self):
        played = [i for i, score in enumerate(self.scores) if score is not None]
        self.highScoreIndex = max(played, key=lambda i: self.scores[i]) if played else None


def rank(teams: list):
    """Sort teams in place by ranking, and set each team's rank (UNRANKED for teams without scores)."""
    teams.sort(key=Team.rankingKey, reverse=True)
    for i, team in enumerate(teams):
        team.rank = i + 1 if team.hasScores() else UNRANKED
