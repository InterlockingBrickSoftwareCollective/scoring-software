"""
Main.py: Entry point to Interlocking Brick Scoring Software

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

import csv
import math
import os
import sys

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *

import Substrate
from AddWindow import AddWindow
from Audience import AudienceWindow
from Insert import Insert
from Team import Team

sheet = """
QLineEdit{
    font-size: 20px;
    background-color: white;
    border: 1px solid gray;
    border-radius: 4px;
    padding: 2px;
}

QLabel {
    font-size: 12px
}

QLabel #config_area {
    font-size: 20px;
}

QMenuBar {
    background-color: #F8B4B6;
    border: 1px solid gray;
    padding: 12px;
    font-size: 18px;
}

QAction {
    font-size: 16px;
    margin: 8px;
}

QWidget #team_card {
    background-color: #F8B4B6;
    border: 1px solid gray;
    padding: 1px;
    border-radius: 4px;
}

QPushButton {
    background-color: #000000;
    color: white;
    border-radius: 4px;
    padding: 6px;
}

QSpinBox {
    font-size: 20px;
    background-color: white;
    border: 2px solid black;
    border-radius: 4px;
    padding: 2px;
}
"""


class MainWindow(QMainWindow):
    scoresEntered = 0
    sortByRank = True

    def __init__(self, application):
        self.app = application
        self.dlg = None
        try:
            super().__init__()
            self.setWindowTitle("Scoring Display")

            Substrate.init()

            # Find size of monitor and launch app
            screen = QGuiApplication.primaryScreen().geometry()
            self.setGeometry(30, 50, screen.width() - 40, screen.height() - 60)

            self.teams = []
            self.insertWindow = None
            self.addWindow = None

            self.mainWidget = QWidget()
            self.mainLayout = QGridLayout()

            self.audienceDisplay = AudienceWindow(self)

            self.menuBar().setNativeMenuBar(False)

            self.addTeamsMenu = QMenu("Add Teams")
            self.menuBar().addMenu(self.addTeamsMenu)

            self.fromCsv = QAction("Add Teams from CSV")
            self.fromCsv.triggered.connect(self.openCsvDialog)
            self.fromCsvScores = QAction("Add Teams and Scores from CSV")
            self.fromCsvScores.triggered.connect(self.openCsvDialogWithScores)
            self.manually = QAction("Add Team Manually")
            self.manually.triggered.connect(self.openAddTeamWindow)
            self.addTeamsMenu.addActions([self.fromCsv, self.fromCsvScores, self.manually])

            self.insert = QAction("Insert Scores")
            self.insert.triggered.connect(self.openInsertPane)
            self.export = QAction("Export Scores")
            self.export.triggered.connect(self.exportCsv)

            # Audience menu options
            self.audienceMenu = QMenu("Audience Display Options")
            self.menuBar().addMenu(self.audienceMenu)

            self.timerMode = QAction("Change Audience to Timer")
            self.timerMode.triggered.connect(self.changeMode)
            self.timerStart = QAction("Start Timer")
            self.timerStart.triggered.connect(self.startTimer)
            self.timerReset = QAction("Reset Timer")
            self.timerReset.triggered.connect(self.audienceDisplay.timer.resetTimer)
            self.rankingsTop = QAction("Scroll to Top of Rankings")
            self.rankingsTop.triggered.connect(self.audienceDisplay.scrollToTop)
            self.testAudio = QAction("Test Sound")
            self.testAudio.triggered.connect(self.audienceDisplay.testSound)

            # Add menus to bar
            self.audienceMenu.addActions(
                [self.timerMode, self.timerStart, self.timerReset, self.rankingsTop, self.testAudio])
            self.menuBar().addActions([self.insert, self.export])
            self.menuBar().addMenu(self.audienceMenu)

            # Create config area
            self.configLayout = QGridLayout()

            # Match number selection
            self.matchNumLabel = QLabel("Match #")
            self.matchNumLabel.setStyleSheet("font-size: 20px")
            self.matchNumLabel.setFixedWidth(60)
            self.matchNum = QSpinBox()
            self.matchNum.setMinimum(1)
            self.matchNum.setFixedWidth(60)
            self.matchNum.valueChanged.connect(self.updateMatchNumber)

            # Scores inputted counter
            self.scoresEnteredLabel = QLabel("Scores Entered: 0")
            self.scoresEnteredLabel.setStyleSheet("font-size: 20px")
            self.scoresEnteredLabel.setFixedWidth(200)

            # Sort type
            self.sortNum = QPushButton("Sort by Team Number")
            self.sortNum.setFixedWidth(180)
            self.sortNum.setStyleSheet("background-color: #F8B4B6; color: black")
            self.sortNum.pressed.connect(self.sortTeamsByNumber)

            self.sortRank = QPushButton("Sort by Team Rank")
            self.sortRank.setFixedWidth(180)
            self.sortRank.setStyleSheet("background-color: #aaaaaa; color: black")
            self.sortRank.pressed.connect(self.sortTeamsByRank)
            self.sortRank.setEnabled(False)

            self.configLayout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.configLayout.addWidget(self.matchNumLabel, 0, 0)
            self.configLayout.addWidget(self.matchNum, 0, 1)
            self.configLayout.addWidget(QLabel(" " * 6), 0, 2)
            self.configLayout.addWidget(self.scoresEnteredLabel, 0, 3)
            self.configLayout.addWidget(QLabel(" " * 6), 0, 4)
            self.configLayout.addWidget(self.sortNum, 0, 5)
            self.configLayout.addWidget(self.sortRank, 0, 6)

            self.configWidget = QWidget()
            self.configWidget.setLayout(self.configLayout)

            # Create application area
            self.scroll = QScrollArea()
            self.widget = QWidget()
            self.teamGrid = QGridLayout()
            self.widget.setLayout(self.teamGrid)
            self.loadAllTeams()

            # Scroll Area Properties
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setWidgetResizable(True)
            self.scroll.setWidget(self.widget)

            self.mainLayout.addWidget(self.scroll, 1, 0, 1, 7)
            self.mainLayout.addWidget(self.configWidget, 0, 0)
            self.mainWidget.setLayout(self.mainLayout)
            self.setCentralWidget(self.mainWidget)
            self.setStyleSheet(sheet)

            # Restore any teams and scores in the database
            self.addTeams([Team(team.name, team.teamnumber) for team in Substrate.loadTeams()])

            for score in Substrate.loadScores():
                team = self.fetchTeam(score.teamnumber)
                team.setScore(score.round, score.score)

            self.rerank()
            self.show()

            # Render audience window, then bring focus back to main scoring window
            self.audienceDisplay.show()
            self.raise_()
            self.activateWindow()

            application.exec()
        except Exception as err:
            print(err)

    def openCsvDialogWithScores(self):
        self.openCsvDialog(scores=True)

    def openCsvDialog(self, scores=False):
        try:
            dialog = QFileDialog()
            filename = dialog.getOpenFileName(self)[0]

            if ".csv" in filename:
                with open(filename, 'r') as n:
                    data = csv.DictReader(n)
                    for row in data:
                        team = Team(row["Team Name"], row["Team Number"])

                        if scores:
                            for i in range(1, 4):
                                try:
                                    if int(row[f"Round {i} Score"]) > 0:
                                        team.setScore(i, int(row[f"Round {i} Score"]))
                                except ValueError:  # probably blank entry, haven't played round
                                    team.setScore(i, -1)
                                # unexpected exceptions get rethrown and caught below

                        self.teams.append(team)
                    self.rerank()

            dialog.close()
        except Exception as err:
            print(err)

    def exportCsv(self):
        try:
            dialog = QFileDialog()
            filename = dialog.getSaveFileName()[0]

            if len(filename) == 0:
                return False

            if not filename.endswith(".csv"):
                filename += ".csv"

            sort = sorted(self.teams, key=lambda x: x.number, reverse=False)
            with open(filename, "w") as f:
                f.write("Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score\n")
                for team in sort:
                    f.write(f"{team.name},{team.number},{team.scores[0]},{team.scores[1]},{team.scores[2]}\n")

            dialog.close()
            return True
        except Exception as err:
            print(err)
            return False

    def closeEvent(self, event):
        try:
            if len(self.teams) > 0:
                confirm = QMessageBox.question(self, "Confirmation",
                                               "Are you sure you want to close the application?",
                                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            else:
                confirm = QMessageBox.StandardButton.Yes

            if confirm == QMessageBox.StandardButton.Yes:
                Substrate.deinit()

                if self.insertWindow is not None:
                    self.insertWindow.close()
                if self.addWindow is not None:
                    self.addWindow.close()

                self.audienceDisplay.scroll.scroll.go = False
                self.audienceDisplay.close()

                QApplication.quit()
                super().closeEvent(event)
                event.accept()
            else:
                event.ignore()

        except Exception as err:
            print(err)

    def openInsertPane(self):
        try:
            self.insertWindow = Insert(self)
        except Exception as err:
            print(err)

    def fetchTeam(self, number):
        try:
            for team in self.teams:
                if team.number == number:
                    return team
        except Exception as err:
            print(err)

    def openAddTeamWindow(self):
        try:
            self.addWindow = AddWindow(self)
        except Exception as err:
            print(err)

    def addSingleTeam(self, team):
        try:
            self.teams.append(team)
            self.rerank()
        except Exception as err:
            print(err)

    def addTeams(self, teams):
        try:
            self.teams.extend(teams)
            self.rerank()
        except Exception as err:
            print(err)

    def loadAllTeams(self):
        try:
            self.scoresEntered = 0

            if self.sortByRank:
                teamList = sorted(self.teams, key=lambda x: x.rank, reverse=False)
            else:
                teamList = sorted(self.teams, key=lambda x: x.number, reverse=False)

            for i, team in enumerate(teamList):
                widget = self.makeTeamWidget(team)

                row = i % (math.ceil(len(teamList) / 2))
                col = i // math.ceil(len(teamList) / 2)
                self.teamGrid.addWidget(widget, row, col)

                self.scoresEntered += sum([1 for score in team.scores if score >= 0])

            self.scoresEnteredLabel.setText(f"Scores Entered: {self.scoresEntered}")
        except Exception as err:
            print(err)

    def clearTeamWidgets(self):
        try:
            for i in reversed(range(self.teamGrid.count() - 1)):
                self.teamGrid.itemAt(i).widget().setParent(None)
        except Exception as err:
            print(err)

    def sortTeamsByNumber(self):
        self.sortByRank = False
        self.sortButtons()

    def sortTeamsByRank(self):
        self.sortByRank = True
        self.sortButtons()

    def sortButtons(self):
        self.rerank()
        self.sortNum.setEnabled(self.sortByRank)
        self.sortRank.setEnabled(not self.sortByRank)

        if self.sortByRank:
            self.sortNum.setStyleSheet("background-color: #F8B4B6; color: black")
            self.sortRank.setStyleSheet("background-color: #aaaaaa; color: black")
        else:
            self.sortNum.setStyleSheet("background-color: #aaaaaa; color: black")
            self.sortRank.setStyleSheet("background-color: #F8B4B6; color: black")

    def makeTeamWidget(self, team):
        try:
            card = QWidget()
            card.setObjectName("team_card")
            card.setFixedHeight(75)

            layout = QGridLayout()
            layout.addWidget(QLabel(" Team Name"), 0, 1)
            layout.addWidget(QLabel(" Team Number"), 0, 2)
            layout.addWidget(QLabel(" Round 1"), 0, 3)
            layout.addWidget(QLabel(" Round 2"), 0, 4)
            layout.addWidget(QLabel(" Round 3"), 0, 5)

            rank = QLabel(str(team.rank) if team.rank < 1E10 else "NP")
            rank.setMinimumWidth(28)
            rank.setStyleSheet("font-size: 24px")
            layout.addWidget(rank, 1, 0, 4, 1)
            layout.addWidget(QLineEdit(text=str(team.name), readOnly=True), 1, 1, 4, 1)
            number = QLineEdit(text=str(team.number), readOnly=True)
            number.setFixedWidth(100)
            layout.addWidget(number, 1, 2, 4, 1)

            for num in range(3):
                if team.scores[num] < 0:
                    roundWidget = QLineEdit(text="", readOnly=True)
                else:
                    roundWidget = QLineEdit(text=str(team.scores[num]), readOnly=True)
                    if team.highScoreIndex == num:
                        roundWidget.setStyleSheet("border: 4px solid #ED1C24")
                roundWidget.setFixedWidth(70)
                layout.addWidget(roundWidget, 1, num + 3, 4, 1)

            delete = QPushButton("Delete")
            delete.setFixedSize(60, 40)
            delete.pressed.connect(lambda number=team.number, card=card: self.deleteCheck(number, card))
            layout.addWidget(delete, 0, 6, 5, 1)
            card.setLayout(layout)

            return card
        except Exception as err:
            print(err)

    def rerank(self):
        self.clearTeamWidgets()

        # set rank field by high score
        self.teams.sort(key=lambda x: (x.highScore, x.secondHighest, x.thirdHighest, -x.number), reverse=True)
        for i, team in enumerate(self.teams):
            if sum(team.scores) == -3:
                team.rank = 1E10
            else:
                team.rank = i + 1

        self.loadAllTeams()
        self.audienceDisplay.rerank()

    def updateMatchNumber(self):
        # TODO Make this useful
        pass

    def deleteCheck(self, number, card):
        try:
            self.dlg = QDialog()
            message = QLabel("Are you sure you want to delete this team?")
            yes = QPushButton("Delete")
            yes.pressed.connect(lambda number=number, card=card: self.deleteTeam(number, card))
            cancel = QPushButton("Cancel")
            cancel.pressed.connect(self.dlg.close)

            main = QVBoxLayout()
            buttonWidget = QWidget()
            buttonLayout = QHBoxLayout()

            buttonLayout.addWidget(yes)
            buttonLayout.addWidget(cancel)

            buttonWidget.setLayout(buttonLayout)
            main.addWidget(message)
            main.addWidget(buttonWidget)

            self.dlg.setLayout(main)
            self.dlg.show()

        except Exception as err:
            print(err)

    def deleteTeam(self, number, card):
        try:
            self.dlg.close()
            card.deleteLater()
            self.teamGrid.removeWidget(card)
            for i, team in enumerate(self.teams):
                if team.number == number:
                    del self.teams[i]
            self.teamGrid.update()

            self.rerank()
        except Exception as err:
            print(err)

    def changeMode(self):
        self.audienceDisplay.changeMode()
        self.timerMode.setText(f"Change Audience to {'Rankings' if self.audienceDisplay.timerMode else 'Timer'}")
        self.menuBar().update()

    def startTimer(self):
        Substrate.writeLogEntry("match_start", f"{self.matchNum.value()}")
        self.audienceDisplay.timer.startTimer()

    def timerComplete(self):
        self.matchNum.setValue(self.matchNum.value() + 1)


if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Add font from local file
    fontId = QFontDatabase.addApplicationFont(os.path.join(os.path.dirname(__file__), "res/Roboto-Regular.ttf"))

    if fontId != -1:
        fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
        QApplication.setFont(QFont(fontFamily))

    window = MainWindow(app)
    window.setStyleSheet(sheet)
    window.show()
