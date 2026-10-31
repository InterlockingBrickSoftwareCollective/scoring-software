"""
ScoresheetModel.py: Scoresheet definition and the options selected on it

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

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Self

from PyQt6.QtCore import QPoint, QRect


@dataclass(slots=True, eq=False)
class Option:
    """One answer to a task, drawn as a box on the scoresheet graphic."""
    value: str
    rect: QRect  # In scoresheet graphic coordinates


@dataclass(slots=True, eq=False)
class Task:
    """One question on the scoresheet; at most one of its options is selected."""
    key: str  # Task name the scoresheet backend expects
    options: list[Option]
    # Start point and width of the line marking the task during keyboard entry; older
    # scoresheet definitions don't have one
    line: tuple[int, int, int] | None = None
    selected: Option | None = None

    def toggle(self, option: Option):
        self.selected = None if self.selected is option else option

    def option_with_value(self, value: str | None) -> Option | None:
        return next((option for option in self.options if option.value == value), None)

    def option_for_digit(self, digit: int) -> Option | None:
        """The option a number key picks: 0 and 1 answer yes/no tasks, otherwise the digit is the value."""
        if {option.value for option in self.options} == {"false", "true"}:
            return self.option_with_value({0: "false", 1: "true"}.get(digit))
        return self.option_with_value(str(digit))


@dataclass(slots=True, eq=False)
class Mission:
    label: str  # Mission number, or name for missions without one
    tasks: list[Task]


class IncompleteScoresheet(Exception):
    def __init__(self, mission: Mission):
        super().__init__(f"Missing value in mission {mission.label}")
        self.mission = mission


@dataclass(slots=True, eq=False)
class Game:
    """A scoresheet definition and the options currently selected on it."""
    missions: list[Mission]
    tasks: list[Task] = field(init=False)  # Every task, in scoresheet order

    def __post_init__(self):
        self.tasks = [task for mission in self.missions for task in mission.tasks]

    @classmethod
    def from_xml(cls, root: ET.Element) -> Self:
        """Build from the root of a scoresheet definition file."""
        def rect(element: ET.Element) -> QRect:
            return QRect(*(int(element.attrib[k]) for k in ("x", "y", "width", "height")))

        def line(element: ET.Element) -> tuple[int, int, int] | None:
            try:
                return tuple(int(element.attrib[k]) for k in ("x", "y", "width"))
            except KeyError:
                return None

        return cls([
            Mission(mission.attrib.get("number", mission.attrib["name"]), [
                Task(task.attrib["eh_task_name"],
                     [Option(option.attrib["value"], rect(option)) for option in task.iter("option")],
                     line(task))
                for task in mission.iter("task")])
            for mission in root.iter("mission")])

    def option_at(self, point: QPoint) -> tuple[Task, Option] | None:
        """The task and option whose box contains point, in scoresheet graphic coordinates."""
        for task in self.tasks:
            for option in task.options:
                if option.rect.contains(point):
                    return task, option
        return None

    def selected_options(self) -> list[Option]:
        return [task.selected for task in self.tasks if task.selected is not None]

    def selections(self) -> dict[str, str]:
        """Task key -> selected value, for the tasks that have a selection."""
        return {task.key: task.selected.value for task in self.tasks if task.selected is not None}

    def load(self, scoresheet: dict | None):
        """Select the options recorded in a scoresheet, replacing any current selections. Tasks the
        scoresheet doesn't have a valid value for are left unselected."""
        scoresheet = scoresheet or {}
        for task in self.tasks:
            task.selected = task.option_with_value(scoresheet.get(task.key))

    def clear(self):
        self.load(None)

    def scoresheet(self) -> dict[str, str]:
        """Task key -> selected value for every task, for submitting to the scoresheet backend.
        Raises IncompleteScoresheet for the first mission with an unanswered task."""
        for mission in self.missions:
            if any(task.selected is None for task in mission.tasks):
                raise IncompleteScoresheet(mission)
        return self.selections()

    def placeholder_scoresheet(self) -> dict[str, str]:
        """A scoresheet with the first option of every task, valid to submit but meaningless."""
        return {task.key: task.options[0].value for task in self.tasks}
