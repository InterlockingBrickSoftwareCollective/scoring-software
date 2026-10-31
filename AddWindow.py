"""
AddWindow.py: Manual team entry window

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

import traceback

from PyQt6.QtWidgets import *

from Team import Team

sheet = """
QLabel {
    font-size: 18px;
}

QLineEdit {
    font-size: 16px;
}

QSpinBox {
    font-size: 16px;
}

QPushButton {
    background-color: #000000;
    color: #ffffff;
    border-radius: 3px;
    padding: 6px;
    font-size: 18px;
}
"""


class InvalidTeam(ValueError):
    """A team that can't be added, with a message to show the operator."""

    def __init__(self, message: str, field: str):
        super().__init__(message)
        self.message = message
        # Which input to fix: "number" or "name"
        self.field = field


def validateTeam(numberText: str, nameText: str, teams: list) -> tuple[int, str]:
    """Check a manually entered team, returning its number and name, or raise InvalidTeam."""
    numberText = numberText.strip()
    name = nameText.strip()

    if not numberText:
        raise InvalidTeam("Enter a team number.", "number")
    if not numberText.isdecimal() or int(numberText) == 0:
        raise InvalidTeam(f"\"{numberText}\" isn't a valid team number. Team numbers are whole numbers, like 1234.",
                          "number")
    number = int(numberText)

    existing = next((team for team in teams if team.number == number), None)
    if existing is not None:
        raise InvalidTeam(f"Team {number} ({existing.name}) has already been added. "
                          "To change its name, use Rename on its tile in the scoring display.", "number")

    if not name:
        raise InvalidTeam("Enter a team name.", "name")

    return number, name


class AddWindow(QMainWindow):
    pitNumber = 1  # TODO: query this from the database to get next pit

    def __init__(self, parent):
        try:
            super().__init__()

            self.parent = parent

            self.setWindowTitle("Add Team")
            self.setGeometry(100, 100, 700, 60)

            self.mainWidget = QWidget()
            self.mainWidget.setStyleSheet(sheet)
            self.mainLayout = QHBoxLayout()

            self.mainLayout.addWidget(QLabel("Pit Number:"))
            self.pit = QSpinBox()
            self.pit.setMinimum(1)
            self.pit.setFixedWidth(60)
            self.pit.setValue(AddWindow.pitNumber)
            self.mainLayout.addWidget(self.pit)

            self.mainLayout.addWidget(QLabel("Team Number:"))
            self.number = QLineEdit()
            self.number.setFixedWidth(70)
            self.mainLayout.addWidget(self.number)

            self.mainLayout.addWidget(QLabel("Team Name:"))
            self.name = QLineEdit()
            self.name.returnPressed.connect(self.addTeam)
            self.mainLayout.addWidget(self.name)
            
            self.add = QPushButton("Add Team")
            self.add.clicked.connect(self.addTeam)
            self.mainLayout.addWidget(self.add)

            self.mainWidget.setLayout(self.mainLayout)

            self.setCentralWidget(self.mainWidget)

            self.show()
        except Exception as err:
            print(err)

    def addTeam(self):
        try:
            number, name = validateTeam(self.number.text(), self.name.text(), self.parent.teams)
        except InvalidTeam as err:
            QMessageBox.warning(self, "Can't Add Team", err.message)
            field = self.number if err.field == "number" else self.name
            field.setFocus()
            field.selectAll()
            return

        try:
            self.parent.addSingleTeam(Team(name, number, self.pit.value()))
        except Exception as err:
            traceback.print_exc()
            QMessageBox.critical(self, "Can't Add Team",
                                 f"Something went wrong adding team {number}, so it may not have been saved.\n\n"
                                 f"Details: {err}")
            return

        AddWindow.pitNumber = self.pit.value() + 1
        self.pit.setValue(AddWindow.pitNumber)
        self.name.setText("")
        self.number.setText("")
        self.number.setFocus()
