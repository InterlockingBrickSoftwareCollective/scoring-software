"""
AwardsEntryWindow.py: Entering the awards, who won them, and the advancing teams

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

import copy
from typing import Callable, Optional

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import (QComboBox, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                             QListWidget, QMainWindow, QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout,
                             QWidget)

import Events
from Awards import MAX_ADVANCING, Advancement, Award, ordinal

MAX_RUNNERS_UP = 5


class TeamPicker(QComboBox):
    """Chooses one of the event's teams, or none."""

    def __init__(self, teams: list):
        super().__init__()
        self.setTeams(teams)
        self.setMinimumWidth(320)

    def setTeams(self, teams: list, exclude=()):
        """Offer teams, except those numbered in exclude, keeping the chosen one if it's still offered."""
        chosen = self.team()
        self.blockSignals(True)
        self.clear()
        self.addItem("(not chosen)", None)
        for team in sorted(teams, key=lambda t: t.number):
            if team.number not in exclude:
                self.addItem(f"{team.number}  {team.name}", team.number)
        self.setTeam(None if chosen in exclude else chosen)
        self.blockSignals(False)

    def team(self) -> Optional[int]:
        return self.currentData()

    def setTeam(self, number: Optional[int]):
        index = self.findData(number)
        if index < 0:
            # A team that has since been deleted keeps its place until another is chosen
            self.addItem(f"{number}  (not in the team list)", number)
            index = self.count() - 1
        self.setCurrentIndex(index)


class AwardsEntryWindow(QMainWindow):
    """Enter the awards in the order they're presented, each with its winner and runners-up, and
    the teams advancing to the next event, on separate tabs. A window rather than a dialog, so
    the rest of the program stays usable while it's open."""

    def __init__(self, loadAwards: Callable[[], list], loadAdvancement: Callable[[], Advancement],
                 teams: Callable[[], list]):
        """loadAwards, loadAdvancement: return the saved awards and advancing teams. teams: returns
        the event's teams."""
        super().__init__()
        self.setWindowTitle("Enter Awards and Advancement")
        self.loadAwards = loadAwards
        self.loadAdvancement = loadAdvancement
        self.getTeams = teams
        self.teams = []
        self.awards = []
        self.advancing = []  # Team numbers, in presentation order
        self.loading = False  # While the editor is filled in from an award, so it isn't written back
        self.changed = False  # Whether there are changes that haven't been saved

        # The awards, in presentation order
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self.showAward)
        self.addButton = QPushButton("Add")
        self.addButton.clicked.connect(self.addAward)
        self.removeButton = QPushButton("Remove")
        self.removeButton.clicked.connect(self.removeAward)
        self.upButton = QPushButton("Move Up")
        self.upButton.clicked.connect(lambda: self.moveAward(-1))
        self.downButton = QPushButton("Move Down")
        self.downButton.clicked.connect(lambda: self.moveAward(1))
        listButtons = QHBoxLayout()
        for button in (self.addButton, self.removeButton, self.upButton, self.downButton):
            listButtons.addWidget(button)
        listLayout = QVBoxLayout()
        listLayout.addWidget(QLabel("Awards, in the order they're presented:"))
        listLayout.addWidget(self.list)
        listLayout.addLayout(listButtons)

        # The selected award
        self.nameEdit = QLineEdit()
        self.nameEdit.textEdited.connect(self.onNameEdited)
        self.winnerPicker = TeamPicker(self.teams)
        self.winnerPicker.currentIndexChanged.connect(self.saveEditor)
        self.runnersUpSpin = QSpinBox()
        self.runnersUpSpin.setRange(0, MAX_RUNNERS_UP)
        self.runnersUpSpin.valueChanged.connect(self.onRunnersUpCount)
        self.runnerUpPickers = []
        self.form = QFormLayout()
        self.form.addRow("Award name", self.nameEdit)
        self.form.addRow("Winner", self.winnerPicker)
        self.form.addRow("Runners-up", self.runnersUpSpin)
        self.editor = QGroupBox("Award")
        self.editor.setLayout(self.form)

        columns = QHBoxLayout()
        columns.addLayout(listLayout, 1)
        columns.addWidget(self.editor, 1)
        awardsTab = QWidget()
        awardsTab.setLayout(columns)

        self.tabs = QTabWidget()
        self.tabs.addTab(awardsTab, "Awards")
        self.tabs.addTab(self.makeAdvancementTab(), "Advancement")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        self.resize(900, 480)

        # Teams added, renamed or deleted while the window is open. TeamAdded comes before the
        # team joins the team list, so look at the list once the event has been handled.
        for eventType in (Events.TeamAdded, Events.TeamUpdated, Events.TeamDeleted):
            Events.subscribe(eventType, lambda event: QTimer.singleShot(0, self.refreshTeams))

        self.load()

    def makeAdvancementTab(self) -> QWidget:
        self.nextEventEdit = QLineEdit()
        self.nextEventEdit.setPlaceholderText("e.g. the State Championship")
        self.nextEventEdit.textEdited.connect(self.onNextEventEdited)
        self.titlePreview = QLabel()
        self.titlePreview.setStyleSheet("color: gray")
        form = QFormLayout()
        form.addRow("Advancing to", self.nextEventEdit)
        form.addRow("", self.titlePreview)

        self.advList = QListWidget()
        self.advList.currentRowChanged.connect(lambda row: self.updateAdvancingButtons())
        self.advPicker = TeamPicker(self.teams)
        self.advPicker.currentIndexChanged.connect(lambda index: self.updateAdvancingButtons())
        self.advAddButton = QPushButton("Add Team")
        self.advAddButton.clicked.connect(self.addAdvancing)
        self.advRemoveButton = QPushButton("Remove")
        self.advRemoveButton.clicked.connect(self.removeAdvancing)
        self.advUpButton = QPushButton("Move Up")
        self.advUpButton.clicked.connect(lambda: self.moveAdvancing(-1))
        self.advDownButton = QPushButton("Move Down")
        self.advDownButton.clicked.connect(lambda: self.moveAdvancing(1))
        self.advCount = QLabel()

        adding = QHBoxLayout()
        adding.addWidget(self.advPicker, 1)
        adding.addWidget(self.advAddButton)
        listButtons = QHBoxLayout()
        for button in (self.advRemoveButton, self.advUpButton, self.advDownButton):
            listButtons.addWidget(button)
        listButtons.addStretch()
        listButtons.addWidget(self.advCount)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(QLabel("Advancing teams, in the order they're revealed:"))
        layout.addWidget(self.advList)
        layout.addLayout(listButtons)
        layout.addLayout(adding)
        tab = QWidget()
        tab.setLayout(layout)
        return tab

    def load(self):
        """Start over from the saved awards and advancing teams, and the current teams."""
        self.teams = list(self.getTeams())
        # The runner-up pickers are made for each award, but the winner picker is made once, so give it the teams
        self.winnerPicker.setTeams(self.teams)
        self.advPicker.setTeams(self.teams)
        advancement = self.loadAdvancement()
        self.nextEventEdit.setText(advancement.nextEvent)
        self.advancing = list(advancement.teams)
        self.showAdvancing()
        self.awards = [copy.deepcopy(award) for award in sorted(self.loadAwards(), key=lambda a: a.order)]
        self.list.blockSignals(True)
        self.list.clear()
        for award in self.awards:
            self.list.addItem(self.listText(award))
        self.list.blockSignals(False)
        self.list.setCurrentRow(0 if self.awards else -1)
        self.showAward(self.list.currentRow())
        self.changed = False

    def refreshTeams(self):
        self.teams = list(self.getTeams())
        for picker in [self.winnerPicker, self.advPicker] + self.runnerUpPickers:
            picker.setTeams(self.teams)
        self.showAdvancing()

    @staticmethod
    def listText(award: Award) -> str:
        return award.name or "(unnamed award)"

    def current(self) -> Optional[Award]:
        row = self.list.currentRow()
        return self.awards[row] if 0 <= row < len(self.awards) else None

    # The award list

    def addAward(self):
        award = Award(name="", order=len(self.awards) + 1)
        self.awards.append(award)
        self.list.addItem(self.listText(award))
        self.list.setCurrentRow(len(self.awards) - 1)
        self.nameEdit.setFocus()
        self.changed = True
        self.updateButtons()

    def removeAward(self):
        row = self.list.currentRow()
        if row < 0:
            return
        del self.awards[row]
        self.list.takeItem(row)
        self.changed = True
        self.updateButtons()

    def moveAward(self, by: int):
        row = self.list.currentRow()
        to = row + by
        if row < 0 or not 0 <= to < len(self.awards):
            return
        self.awards[row], self.awards[to] = self.awards[to], self.awards[row]
        self.list.insertItem(to, self.list.takeItem(row))
        self.list.setCurrentRow(to)
        self.changed = True
        self.updateButtons()

    def updateButtons(self):
        row = self.list.currentRow()
        self.removeButton.setEnabled(row >= 0)
        self.upButton.setEnabled(row > 0)
        self.downButton.setEnabled(0 <= row < len(self.awards) - 1)
        self.editor.setEnabled(row >= 0)

    # The selected award's editor

    def showAward(self, row: int):
        award = self.current()
        self.loading = True
        try:
            self.nameEdit.setText(award.name if award else "")
            self.winnerPicker.setTeam(award.winner if award else None)
            self.setRunnerUpPickers(award.runnersUp if award else [])
        finally:
            self.loading = False
        self.updateButtons()

    def setRunnerUpPickers(self, runnersUp: list):
        for picker in self.runnerUpPickers:
            self.form.removeRow(picker)
        self.runnerUpPickers = []
        self.runnersUpSpin.setValue(len(runnersUp))
        for place, team in enumerate(runnersUp, start=2):
            picker = TeamPicker(self.teams)
            picker.setTeam(team)
            picker.currentIndexChanged.connect(self.saveEditor)
            self.form.addRow(f"{ordinal(place)} place", picker)
            self.runnerUpPickers.append(picker)

    def onRunnersUpCount(self, count: int):
        if self.loading:
            return
        award = self.current()
        if award is None:
            return
        runnersUp = [picker.team() for picker in self.runnerUpPickers][:count]
        runnersUp += [None] * (count - len(runnersUp))
        award.runnersUp = runnersUp
        self.changed = True
        self.loading = True
        try:
            self.setRunnerUpPickers(runnersUp)
        finally:
            self.loading = False

    def onNameEdited(self, text: str):
        self.saveEditor()
        row = self.list.currentRow()
        if row >= 0:
            self.list.item(row).setText(self.listText(self.awards[row]))

    def saveEditor(self):
        award = self.current()
        if self.loading or award is None:
            return
        award.name = self.nameEdit.text().strip()
        award.winner = self.winnerPicker.team()
        award.runnersUp = [picker.team() for picker in self.runnerUpPickers]
        self.changed = True

    # Advancing teams

    def teamText(self, number: int) -> str:
        for team in self.teams:
            if team.number == number:
                return f"{team.number}  {team.name}"
        return f"{number}  (not in the team list)"

    def showAdvancing(self, row: Optional[int] = None):
        """Show the advancing teams, selecting row (or keeping the selection)."""
        row = self.advList.currentRow() if row is None else row
        self.advList.blockSignals(True)
        self.advList.clear()
        for number in self.advancing:
            self.advList.addItem(self.teamText(number))
        self.advList.setCurrentRow(min(row, len(self.advancing) - 1))
        self.advList.blockSignals(False)
        # Teams already advancing aren't offered again
        self.advPicker.setTeams(self.teams, exclude=set(self.advancing))
        self.titlePreview.setText(f"Shown as \"{self.enteredAdvancement().title()}\"")
        self.updateAdvancingButtons()

    def updateAdvancingButtons(self):
        row = self.advList.currentRow()
        chosen = self.advPicker.team()
        self.advAddButton.setEnabled(chosen is not None and chosen not in self.advancing
                                     and len(self.advancing) < MAX_ADVANCING)
        self.advRemoveButton.setEnabled(row >= 0)
        self.advUpButton.setEnabled(row > 0)
        self.advDownButton.setEnabled(0 <= row < len(self.advancing) - 1)
        self.advCount.setText(f"{len(self.advancing)} of {MAX_ADVANCING} teams")

    def addAdvancing(self):
        team = self.advPicker.team()
        if team is None or team in self.advancing or len(self.advancing) >= MAX_ADVANCING:
            return
        self.advancing.append(team)
        self.changed = True
        self.advPicker.setTeam(None)
        self.showAdvancing(len(self.advancing) - 1)

    def removeAdvancing(self):
        row = self.advList.currentRow()
        if row < 0:
            return
        del self.advancing[row]
        self.changed = True
        self.showAdvancing(row)

    def moveAdvancing(self, by: int):
        row = self.advList.currentRow()
        to = row + by
        if row < 0 or not 0 <= to < len(self.advancing):
            return
        self.advancing[row], self.advancing[to] = self.advancing[to], self.advancing[row]
        self.changed = True
        self.showAdvancing(to)

    def onNextEventEdited(self, text: str):
        self.changed = True
        self.titlePreview.setText(f"Shown as \"{self.enteredAdvancement().title()}\"")

    def enteredAdvancement(self) -> Advancement:
        return Advancement(nextEvent=self.nextEventEdit.text().strip(), teams=list(self.advancing))

    # Saving

    def problems(self) -> list:
        """What has to be fixed before the awards can be saved."""
        problems = []
        for award in self.awards:
            name = award.name or "An unnamed award"
            if not award.name:
                problems.append("Every award needs a name.")
            if any(team is None for team in award.runnersUp):
                problems.append(f"{name}: choose a team for every runner-up place, or have fewer runners-up.")
            if award.runnersUp and award.winner is None:
                problems.append(f"{name}: choose the winner as well as the runners-up.")
            chosen = [team for team in award.places() if team is not None]
            if len(chosen) != len(set(chosen)):
                problems.append(f"{name}: a team can only have one place.")
        return list(dict.fromkeys(problems))

    def save(self) -> bool:
        """Save the awards and close the window, or explain what has to be fixed first."""
        problems = self.problems()
        if problems:
            QMessageBox.warning(self, "Enter Awards and Advancement", "\n".join(problems))
            return False
        Events.publish(Events.AwardsChanged(tuple(self.enteredAwards())))
        advancement = self.enteredAdvancement()
        Events.publish(Events.AdvancementChanged(advancement.nextEvent, tuple(advancement.teams)))
        self.changed = False
        self.close()
        return True

    def closeWithoutSaving(self):
        """Close, dropping any unsaved changes (e.g. when the program quits)."""
        self.changed = False
        self.close()

    def closeEvent(self, event):
        if self.changed:
            answer = QMessageBox.question(
                self, "Enter Awards and Advancement", "Save the changes to the awards and advancement?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel or (answer == QMessageBox.StandardButton.Save and not self.save()):
                event.ignore()
                return
            self.changed = False
        event.accept()

    def enteredAwards(self) -> list:
        """The awards as entered, numbered in presentation order."""
        return [Award(name=award.name, order=order, winner=award.winner, runnersUp=list(award.runnersUp))
                for order, award in enumerate(self.awards, start=1)]
