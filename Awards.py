"""
Awards.py: Awards, advancing teams, and the steps of presenting them

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

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Award:
    """An award, presented in order (1, 2, 3...), with its winner and runners-up (2nd place, 3rd
    place...) as team numbers. The winner is None until it's entered."""
    name: str
    order: int
    winner: Optional[int] = None
    runnersUp: list = field(default_factory=list)

    def places(self) -> list:
        """The team numbers by place: the winner first, then the runners-up."""
        return [self.winner] + list(self.runnersUp)


# The most teams that can advance; the advancing screen has room for 12
MAX_ADVANCING = 12


@dataclass
class Advancement:
    """The teams advancing from this event to the next one, as team numbers in the order
    they're presented. nextEvent is empty when the next event isn't named."""
    nextEvent: str = ""
    teams: list = field(default_factory=list)

    def title(self) -> str:
        return f"Advancing to {self.nextEvent}" if self.nextEvent else "Advancing from this event"


# The kinds of step in an awards presentation
WELCOME = "welcome"                  # The welcome screen, before the first award
INTRO = "intro"                      # The award intro screen
REVEAL = "reveal"                    # The award's screen for one place, before or after the team is revealed
ADVANCING_TITLE = "advancing_title"  # The advancing screen with just its title
ADVANCING = "advancing"              # The advancing screen's rows, with the first `shown` teams revealed
THANKS = "thanks"                    # The thank-you screen, at the end
BLANK = "blank"                      # The award screen with no award or team, shown in between steps


@dataclass(frozen=True)
class Step:
    kind: str
    award: Optional[Award] = None
    place: int = 0  # 1 for the winner, 2 for 2nd place...
    team: Optional[int] = None  # The team revealed, or about to be revealed
    revealed: bool = False
    advancement: Optional[Advancement] = None
    shown: int = 0  # How many advancing teams are revealed

    def key(self) -> tuple:
        """What identifies the step across edits to the awards, to stay on it when they change
        (e.g. a misspelled award name fixed during the ceremony)."""
        order = self.award.order if self.award is not None else None
        return (self.kind, order, self.place, self.revealed, self.shown)

    def section(self):
        """Which part of the presentation the step belongs to: an award, the advancing teams, or
        the welcome or thank-you screen."""
        if self.award is not None:
            return ("award", self.award.order)
        if self.kind in (ADVANCING_TITLE, ADVANCING):
            return ("advancing",)
        return (self.kind,)


def ordinal(n: int) -> str:
    """'1st', '2nd', '3rd', '4th', ... '11th', '12th', '13th', ... '21st'."""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def placeLabel(award: Award, place: int) -> Optional[str]:
    """What the reveal screen says about the place: 'WINNER' or '2ND PLACE', or nothing for an
    award without runners-up."""
    if not award.runnersUp:
        return None
    return "WINNER" if place == 1 else f"{ordinal(place).upper()} PLACE"


def presentationSteps(awards: list, advancement: Optional[Advancement] = None,
                      advancingScreen: bool = True, thanksScreen: bool = True) -> list:
    """Every step of presenting awards and advancement: the welcome screen, then for each award
    in order, its intro and then each place from last up to the winner, without and then with
    the team. Places without a team entered are left out. Then, if any teams advance and
    advancingScreen, the advancing screen with just its title, then with a blank row for each
    team, then revealing one more team at a time. Last, the thank-you screen if thanksScreen."""
    steps = [Step(WELCOME)]
    for award in sorted(awards, key=lambda a: a.order):
        steps.append(Step(INTRO, award))
        places = award.places()
        for place in range(len(places), 0, -1):
            team = places[place - 1]
            if team is None:
                continue
            steps.append(Step(REVEAL, award, place, team, revealed=False))
            steps.append(Step(REVEAL, award, place, team, revealed=True))
    if advancement is not None and advancement.teams and advancingScreen:
        steps.append(Step(ADVANCING_TITLE, advancement=advancement))
        steps.append(Step(ADVANCING, advancement=advancement, shown=0))
        for shown, team in enumerate(advancement.teams, start=1):
            steps.append(Step(ADVANCING, team=team, advancement=advancement, shown=shown))
    if thanksScreen:
        steps.append(Step(THANKS))
    return steps


def describe(step: Step, teamName: Optional[str] = None) -> str:
    """The step as the presentation control lists it."""
    if step.kind == WELCOME:
        return "Welcome screen"
    if step.kind == INTRO:
        return f"{step.award.name}: intro"
    if step.kind == THANKS:
        return "Thank you screen"
    if step.kind == ADVANCING_TITLE:
        return "Advancing: title only"
    if step.kind == ADVANCING:
        if step.shown == 0:
            count = len(step.advancement.teams)
            return f"    Blank list ({count} team{'s' if count != 1 else ''})"
        team = f"{step.team} {teamName}" if teamName else str(step.team)
        return f"    {step.shown}: {team}"
    place = "Winner" if step.place == 1 else f"{ordinal(step.place)} place"
    if not step.revealed:
        return f"    {place}: blank display"
    team = f"{step.team} {teamName}" if teamName else str(step.team)
    return f"    {place}: {team}"
