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

import Substrate


class Team:
    def __init__(self, name, number):
        try:
            self.name = name
            self.number = int(number)
            self.scores = [-1, -1, -1]
            self.highScore = -1
            self.highScoreIndex = -1
            self.secondHighest = -1
            self.thirdHighest = -1
            self.rank = 1E10
            Substrate.saveTeam(number, name)
        except Exception as err:
            print(err)

    def __del__(self):
        Substrate.deleteTeam(self.number)

    def setScore(self, roundNum, score):
        try:
            self.scores[roundNum - 1] = score
            Substrate.saveScore(self.number, roundNum, score)

            # Continuously update high score, second highest, and third highest
            rankings = list(self.scores)
            rankings.sort(reverse=True)
            self.highScore = rankings[0]
            self.highScoreIndex = self.scores.index(self.highScore)
            rankings.remove(self.highScore)
            self.secondHighest = rankings[0]
            rankings.remove(self.secondHighest)
            self.thirdHighest = rankings[0]

        except Exception as err:
            print(err)
