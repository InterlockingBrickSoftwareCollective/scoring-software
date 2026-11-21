"""
AwardsWindow.py: Awards and advancement presentation control

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

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
                             QSizePolicy, QVBoxLayout, QWidget)

import Awards
import Events

# Keys that move through the presentation: the spacebar, arrow keys, and what presentation clickers send
NEXT_KEYS = {Qt.Key.Key_Space, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_PageDown, Qt.Key.Key_Return,
             Qt.Key.Key_Enter}
BACK_KEYS = {Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_PageUp, Qt.Key.Key_Backspace}
# Keys that blank the screen and bring it back: what presentation clickers send for "blank screen"
BLANK_KEYS = {Qt.Key.Key_B, Qt.Key.Key_Period}


class AwardsWindow(QMainWindow):
    """Steps the audience display through the awards (for each award, its intro, then each place
    from last up to the winner, before and after the team is revealed), the advancing teams one
    at a time, and the thank-you screen."""

    def __init__(self, audience, loadAwards: Callable[[], list], loadAdvancement: Callable[[], Awards.Advancement],
                 showAwards: Callable[[], None]):
        """audience: the AudienceWindow. loadAwards, loadAdvancement: return the saved awards and
        advancing teams. showAwards: switches the audience display to the awards presentation."""
        super().__init__()
        self.setWindowTitle("Awards and Advancement Presentation Control")
        self.audience = audience
        self.loadAwards = loadAwards
        self.loadAdvancement = loadAdvancement
        self.showAwards = showAwards
        self.steps = []
        self.blank = False  # Whether the blank award screen shows in place of the selected step

        # What's showing: the award (or the welcome screen) in large type, then which part of it
        self.nowLabel = QLabel()
        font = self.nowLabel.font()
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        self.nowLabel.setFont(font)
        self.nowDetail = QLabel()
        font = self.nowDetail.font()
        font.setPointSizeF(font.pointSizeF() * 1.3)
        self.nowDetail.setFont(font)
        self.nextLabel = QLabel()
        self.emptyLabel = QLabel("No awards or advancing teams have been entered yet. "
                                 "Enter them with Toybox → Enter Awards and Advancement...")
        for label in (self.nowLabel, self.nowDetail, self.nextLabel, self.emptyLabel):
            label.setWordWrap(True)
            # Never squeezed shorter than their text to make room for the list
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        # A main window's layout doesn't make room for wrapped text, so leave room for two lines
        for label in (self.nowLabel, self.nextLabel):
            label.setMinimumHeight(label.fontMetrics().lineSpacing() * 2 + 4)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        # Every step; clicking one shows it. Nothing here takes the keyboard focus, so the
        # spacebar and the clicker's keys always reach the window.
        self.list = QListWidget()
        self.list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list.currentRowChanged.connect(self.onRowChanged)

        self.backButton = QPushButton("◀  Back")
        self.backButton.clicked.connect(self.back)
        self.nextButton = QPushButton("Next  ▶")
        self.nextButton.clicked.connect(self.next)
        self.welcomeButton = QPushButton("Show Welcome")
        self.welcomeButton.clicked.connect(lambda: self.goTo(0))
        self.blankButton = QPushButton("Show Blank")
        self.blankButton.clicked.connect(self.showBlank)
        buttons = QHBoxLayout()
        for button in (self.backButton, self.welcomeButton, self.blankButton, self.nextButton):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setMinimumHeight(48)
            buttons.addWidget(button)

        hint = QLabel("Next: Space, → or Page Down (presentation clicker).  Back: ← or Page Up.  Blank: B or .")
        hint.setStyleSheet("color: gray")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Now showing:"))
        layout.addWidget(self.nowLabel)
        layout.addWidget(self.nowDetail)
        layout.addSpacing(6)
        layout.addWidget(self.nextLabel)
        layout.addLayout(buttons)
        layout.addWidget(hint)
        layout.addWidget(self.emptyLabel)
        layout.addWidget(self.list, 1)
        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.resize(560, 640)

        for eventType in (Events.AwardsChanged, Events.AdvancementChanged):
            Events.subscribe(eventType, lambda event: self.reload())
        for eventType in (Events.TeamUpdated, Events.TeamDeleted):
            Events.subscribe(eventType, lambda event: self.relabel())

        self.reload()

    # Moving through the presentation

    def currentRow(self) -> int:
        return max(0, self.list.currentRow())

    def currentStep(self) -> Awards.Step:
        return self.steps[self.currentRow()]

    def next(self):
        if self.currentRow() < len(self.steps) - 1:
            self.goTo(self.currentRow() + 1)

    def back(self):
        if self.blank:
            self.display(self.currentRow())  # Back to the step the blank screen replaced
        elif self.currentRow() > 0:
            self.goTo(self.currentRow() - 1)

    def showBlank(self):
        """Show the award screen with no award or team in place of the selected step. Back returns
        to the step, and Next carries on to the one after it."""
        if not self.audience.isShowingAwards():
            self.showAwards()
        self.blank = True
        self.audience.showAwardStep(Awards.Step(Awards.BLANK))
        self.updateControls()

    def goTo(self, row: int):
        if row == self.list.currentRow():
            self.display(row)
        else:
            self.list.setCurrentRow(row)  # Shows it, through onRowChanged

    def onRowChanged(self, row: int):
        if 0 <= row < len(self.steps):
            self.display(row)

    def display(self, row: int):
        """Show step row on the audience display, switching it to the awards presentation if needed."""
        if not self.audience.isShowingAwards():
            self.showAwards()
        self.blank = False
        self.audience.showAwardStep(self.steps[row])
        self.updateControls()

    # Keeping up with the awards and teams

    def reload(self):
        """Load the saved awards and advancing teams, staying on the same step (with any corrections)
        if it's still there."""
        current = self.steps[self.currentRow()].key() if self.steps else None
        self.steps = Awards.presentationSteps(self.loadAwards(), self.loadAdvancement(),
                                              advancingScreen=self.audience.themeHasScreen("advancing"),
                                              thanksScreen=self.audience.themeHasScreen("thank_you"))
        keys = [step.key() for step in self.steps]
        row = keys.index(current) if current in keys else 0
        self.list.blockSignals(True)
        self.list.clear()
        for step in self.steps:
            item = QListWidgetItem()
            if step.kind not in (Awards.REVEAL, Awards.ADVANCING):
                font = QFont(item.font())
                font.setBold(True)
                item.setFont(font)
            self.list.addItem(item)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self.relabel()
        # Show corrections to what's on screen, without taking over the display if it's showing something else
        if not self.blank:
            self.audience.showAwardStep(self.steps[row])
        self.emptyLabel.setVisible(all(step.kind in (Awards.WELCOME, Awards.THANKS) for step in self.steps))

    def relabel(self):
        for row, step in enumerate(self.steps):
            self.list.item(row).setText(Awards.describe(step, self.audience.teamName(step.team) if step.team else None))
        self.updateControls()

    def updateControls(self):
        row = self.currentRow()
        step = self.steps[row]
        heading, detail = self.title(step)
        if self.blank:
            self.nowLabel.setText("Blank screen")
            self.nowDetail.setText("Back returns to: " + ", ".join(filter(None, (heading, detail))))
        else:
            self.nowLabel.setText(heading)
            self.nowDetail.setText(detail)
        if row < len(self.steps) - 1:
            following = self.steps[row + 1]
            nextHeading, nextDetail = self.title(following)
            if following.section() == step.section() and not self.blank:
                self.nextLabel.setText(f"Next: {nextDetail}")
            else:
                self.nextLabel.setText("Next: " + ", ".join(filter(None, (nextHeading, nextDetail))))
        else:
            self.nextLabel.setText("Next: nothing; this is the last step")
        self.backButton.setEnabled(row > 0 or self.blank)
        self.blankButton.setEnabled(not self.blank)
        self.nextButton.setEnabled(row < len(self.steps) - 1)
        self.list.scrollToItem(self.list.item(row))

    def title(self, step: Awards.Step) -> tuple:
        """(heading, detail) describing step."""
        if step.kind == Awards.WELCOME:
            return "Welcome screen", ""
        if step.kind == Awards.INTRO:
            return step.award.name, "Intro"
        if step.kind == Awards.THANKS:
            return "Thank you screen", ""
        if step.kind == Awards.ADVANCING_TITLE:
            return step.advancement.title(), "Title only"
        if step.kind == Awards.ADVANCING:
            count = len(step.advancement.teams)
            if step.shown == 0:
                return step.advancement.title(), f"Blank list: {count} team{'s' if count != 1 else ''}"
            teamName = self.audience.teamName(step.team)
            return step.advancement.title(), f"Team {step.shown} of {count}: {step.team} {teamName}".rstrip()
        place = "Winner" if step.place == 1 else f"{Awards.ordinal(step.place)} place"
        if not step.revealed:
            return step.award.name, f"{place}: blank display (team not shown yet)"
        teamName = self.audience.teamName(step.team)
        return step.award.name, f"{place}: {step.team} {teamName}".rstrip()

    def keyPressEvent(self, event):
        if event.key() in NEXT_KEYS:
            self.next()
        elif event.key() in BACK_KEYS:
            self.back()
        elif event.key() in BLANK_KEYS:
            if self.blank:
                self.back()
            else:
                self.showBlank()
        else:
            super().keyPressEvent(event)
