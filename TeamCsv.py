"""
TeamCsv.py: Reading and writing team lists and scores as CSV files

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

Two formats are read:
  * Current: Pit #,Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score
  * Older (before pit numbers): Team Name,Team Number[,Round 1 Score,...]
Columns are matched by header name, so their order doesn't matter, and the score
columns may be left out entirely for a plain team list.
"""

import csv
from collections.abc import Iterable
from dataclasses import dataclass, field

ROUNDS = 3

PIT = "Pit #"
NAME = "Team Name"
NUMBER = "Team Number"
SCORES = [f"Round {i} Score" for i in range(1, ROUNDS + 1)]
HEADER = [PIT, NAME, NUMBER, *SCORES]

# Header spellings accepted for the pit column, compared after normalizing
_PIT_ALIASES = {"pit #", "pit", "pit number", "pit no", "pit no."}

# Pit number for teams that don't have one
NO_PIT = 0


@dataclass
class TeamRecord:
    name: str
    number: int
    pit: int = NO_PIT
    # None means the round hasn't been played
    scores: list[int | None] = field(default_factory=lambda: [None] * ROUNDS)


def _normalize(header: str) -> str:
    return " ".join(header.strip().lower().split())


def _parseScore(value: str | None) -> int | None:
    try:
        score = int(value.strip())
    except (AttributeError, ValueError):  # missing column or blank entry: round not played
        return None
    # Older exports wrote -1 for rounds that hadn't been played
    return score if score >= 0 else None


def _parsePit(value: str | None) -> int:
    try:
        return int(value.strip())
    except (AttributeError, ValueError):  # no pit column (older format), or blank pit
        return NO_PIT


def _readText(path: str) -> str:
    # Our own exports are UTF-8; files saved by Excel may carry a BOM, or be in the
    # system's legacy encoding (as exports from older versions of this software are)
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            return f.read()
    except UnicodeDecodeError:
        with open(path, newline="") as f:
            return f.read()


def parseTeams(lines: Iterable[str]) -> list[TeamRecord]:
    """Parse CSV text (an iterable of lines) in either the current or the older format."""
    reader = csv.reader(lines)
    try:
        header = next(reader)
    except StopIteration:
        return []

    columns = {_normalize(h): i for i, h in enumerate(header)}

    def index(name: str) -> int | None:
        return columns.get(_normalize(name))

    nameCol, numberCol = index(NAME), index(NUMBER)
    if nameCol is None or numberCol is None:
        raise ValueError(f'CSV file must have "{NAME}" and "{NUMBER}" columns')
    pitCol = next((i for h, i in columns.items() if h in _PIT_ALIASES), None)
    scoreCols = [index(s) for s in SCORES]

    def cell(row: list[str], col: int | None) -> str | None:
        return row[col] if col is not None and col < len(row) else None

    teams = []
    for row in reader:
        if not any(value.strip() for value in row):  # blank line, e.g. trailing rows from Excel
            continue
        lineNum = reader.line_num
        name = (cell(row, nameCol) or "").strip()
        numberText = (cell(row, numberCol) or "").strip()
        try:
            number = int(numberText)
        except ValueError:
            raise ValueError(f"Line {lineNum}: invalid team number {numberText!r}") from None

        teams.append(TeamRecord(
            name=name,
            number=number,
            pit=_parsePit(cell(row, pitCol)),
            scores=[_parseScore(cell(row, col)) for col in scoreCols],
        ))
    return teams


def readTeams(path: str) -> list[TeamRecord]:
    """Read teams, and their scores where present, from a CSV file in either format."""
    return parseTeams(_readText(path).splitlines())


def _exportOrder(team) -> int:
    # Sorted by pit, which is how the Online Judging System is typically ordered
    return team.pit if team.pit != NO_PIT else team.number


def formatTeams(teams: Iterable) -> list[list[str]]:
    """Rows (header first) for teams; each needs name, number, pit and scores attributes."""
    rows = [list(HEADER)]
    for team in sorted(teams, key=_exportOrder):
        scores = ["" if score is None else str(score) for score in team.scores]
        rows.append([str(team.pit), team.name, str(team.number), *scores])
    return rows


def writeTeams(path: str, teams: Iterable):
    """Write teams and scores to a CSV file in the current format."""
    # BOM so Excel recognizes the file as UTF-8; readTeams accepts it either way
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(formatTeams(teams))
