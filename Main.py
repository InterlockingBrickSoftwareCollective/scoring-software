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
import json
import math
import sys
import threading

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *

import About
import ResourceManager
import Substrate
import Sync
from AddWindow import AddWindow
from Audience import AudienceWindow
from Insert import Insert
from PracticeTimerWindow import PracticeTimerWindow
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

            self.insert = QAction("Add Score Manually")
            self.insert.triggered.connect(self.openInsertPane)

            # Scoresheet functionality is optional and only available if both
            # a resource pack is installed and the resource pack contains a
            # scoresheet backend module.
            self.scoresheet = None
            try:
                global Scoresheet
                import Scoresheet
                self.scoresheet = QAction("Add Scoresheet")
                self.scoresheet.triggered.connect(self.openScoresheetPane)
            except:
                print(f"Scoresheet entry unavailable (missing backend)")

            self.export = QAction("Export Scores")
            self.export.triggered.connect(self.exportCsv)

            # Audience menu options
            self.audienceMenu = QMenu("Audience Display Options")
            practiceTimer = QAction("Practice Timer...")
            practiceTimer.triggered.connect(self.practiceTimerControl)
            self.rankingsTop = QAction("Scroll to Top of Rankings")
            self.rankingsTop.triggered.connect(self.audienceDisplay.scrollToTop)
            self.testAudio = QAction("Test Sound")
            self.testAudio.triggered.connect(self.audienceDisplay.testSound)
            self.audienceMenu.addActions([practiceTimer, self.rankingsTop, self.testAudio])

            self.forceSync = QAction("Force Sync")
            self.forceSync.triggered.connect(self.doForceSync)

            # Timer control buttons
            self.timerMode = QAction("Show Timer")
            self.timerMode.triggered.connect(self.changeMode)
            self.timerCtl = QAction("Start Timer")
            self.timerCtl.triggered.connect(self.handleTimerCtl)
            self.timerCtl.setDisabled(True) # Audience display starts on rank display

            self.menuBar().addAction(self.insert)
            if self.scoresheet:
                self.menuBar().addAction(self.scoresheet)
            self.menuBar().addAction(self.export)
            self.menuBar().addMenu(self.audienceMenu)
            self.menuBar().addActions([self.forceSync, self.timerMode, self.timerCtl])

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

            # Create Toybox menu and button
            self.toyboxMenu = QMenu("Toybox", self)
            installResPack = QAction("Install resource pack")
            installResPack.triggered.connect(self.installResPack)
            aboutAction = QAction("About...")
            aboutAction.triggered.connect(self.showAboutDialog)
            self.toyboxMenu.addActions([aboutAction, installResPack])
            self.toyboxButton = QPushButton("Toybox")
            self.toyboxButton.setMenu(self.toyboxMenu)
            self.toyboxButton.setFixedWidth(100)

            self.configLayout.addWidget(self.matchNumLabel, 0, 0)
            self.configLayout.addWidget(self.matchNum, 0, 1)
            self.configLayout.addWidget(QLabel(" " * 6), 0, 2)
            self.configLayout.addWidget(self.scoresEnteredLabel, 0, 3)
            self.configLayout.addWidget(QLabel(" " * 6), 0, 4)
            self.configLayout.addWidget(self.sortNum, 0, 5)
            self.configLayout.addWidget(self.sortRank, 0, 6)
            self.configLayout.setColumnStretch(7, 1)  # Add stretch to push Toybox to the right
            self.configLayout.addWidget(self.toyboxButton, 0, 8)
            self.configLayout.setContentsMargins(0, 0, 0, 0)

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
            self.mainLayout.addWidget(self.configWidget, 0, 0, 1, 7)
            self.mainWidget.setLayout(self.mainLayout)
            self.setCentralWidget(self.mainWidget)
            self.setStyleSheet(sheet)

            # Restore any teams and scores in the database
            self.addTeams([Team(team.name, team.teamnumber, team.pit, from_db=True) for team in Substrate.loadTeams()])

            for score in Substrate.loadScores():
                team = self.fetchTeam(score.teamnumber)
                team.setScore(score.round, score.score, from_db=True)

            self.rerank()
            self.show()

            # Start sync thread
            self.syncThread = threading.Thread(target=Sync.request_thread, daemon=True)
            self.syncThread.start()

            # Load sync credentials
            with open("sync.json", "r") as syncCreds:
                syncSettings = json.loads(syncCreds.read())
                Sync.setup_sync(syncSettings)

            # Render audience window, then bring focus back to main scoring window
            self.audienceDisplay.show()
            self.raise_()
            self.activateWindow()

            application.exec()
        except Exception as err:
            print(err)

    def showAboutDialog(self):
        About.show(self)

    def installResPack(self):
        """Install a resource pack from a ZIP file."""
        try:
            # Open file dialog filtered for ZIP files
            dialog = QFileDialog()
            filename, _ = dialog.getOpenFileName(
                self,
                "Select Resource Pack",
                "",
                "ZIP Files (*.zip)"
            )

            # User cancelled the dialog
            if not filename:
                return

            ResourceManager.installResourcePack(filename)

            # Show success message
            QMessageBox.information(
                self,
                "Success",
                "Resource pack installed!\nRestart application to complete installation."
            )

        except Exception as err:
            # Show error message for any failure
            QMessageBox.critical(
                self,
                "Installation Failed",
                "Resource pack installation failed."
            )
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

            sort = sorted(self.teams, key=lambda x: x.pit if x.pit != 0 else x.number, reverse=False)
            with open(filename, "w") as f:
                f.write("Pit #,Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score\n")
                for team in sort:
                    f.write(f"{team.pit},{team.name},{team.number},{team.scores[0]},{team.scores[1]},{team.scores[2]}\n")

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
        # Do nothing if no teams loaded yet
        if len(self.teams) == 0:
            QMessageBox.critical(self, "Error", "No teams loaded!")
            return

        try:
            self.insertWindow = Insert(self)
        except Exception as err:
            print(err)

    def openScoresheetPane(self):
        # Do nothing if no teams loaded yet
        if len(self.teams) == 0:
            QMessageBox.critical(self, "Error", "No teams loaded!")
        else:
            try:
                if self.insertWindow is None or not self.insertWindow.isVisible():
                    self.insertWindow = Scoresheet.ScoresheetDialog(self)
            except Exception as e:
                QMessageBox.critical(self, "Error", "Problem using scoresheet entry!\nUse score calculator and add scores manually.")
                self.scoresheet.setEnabled(False)

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
            Sync.post_teams(self.teams)
        except Exception as err:
            print(err)

    def addTeams(self, teams):
        try:
            self.teams.extend(teams)
            self.rerank()
            Sync.post_teams(self.teams)
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

            rename = QPushButton("Rename")
            rename.setFixedSize(70, 25)
            rename.pressed.connect(lambda number=team.number, card=card: self.renameCheck(number, card))
            layout.addWidget(rename, 0, 6, 1, 1)
            card.setLayout(layout)

            delete = QPushButton("Delete")
            delete.setFixedSize(70, 25)
            delete.pressed.connect(lambda number=team.number, card=card: self.deleteCheck(number, card))
            layout.addWidget(delete, 2, 6, 1, 1)
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

    def renameCheck(self, number, card):
        self.dlg = QDialog()
        message = QLabel(f"Renaming team #{number}:")
        new_name = QLineEdit()
        new_name.setObjectName("new_name")
        new_name.returnPressed.connect(lambda n = number: self.renameTeam(n))
        rename = QPushButton("Rename")
        rename.pressed.connect(lambda n = number: self.renameTeam(n))

        main = QHBoxLayout()

        main.addWidget(message)
        main.addWidget(new_name)
        main.addWidget(rename)

        self.dlg.setLayout(main)
        self.dlg.show()

    def renameTeam(self, number: int):
        team = self.fetchTeam(number)
        team.name = self.dlg.findChild(QLineEdit).text()
        Substrate.saveTeam(int(number), team.name, team.pit)
        Sync.post_teams(self.teams)

        self.rerank()
        self.dlg.close()

    def deleteCheck(self, number, card):
        try:
            self.dlg = QDialog()
            message = QLabel(f"Are you sure you want to delete team #{number}?")
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
        self.timerMode.setText(f"Show {'Rankings' if self.audienceDisplay.mode != 'ranks' else 'Timer'}")
        self.timerCtl.setDisabled(False if self.audienceDisplay.mode != "ranks" else True)
        self.menuBar().update()

    def handleTimerCtl(self):
        matchNum = int(self.matchNum.value())
        if not self.audienceDisplay.timer.timerRunning:
            # Timer isn't running -- start timer and lock out mode control
            Substrate.writeLogEntry("match_start", f"{matchNum}")
            Sync.post_match_status(matchNum, "running")
            self.audienceDisplay.timer.startTimer()
            self.timerCtl.setText("Reset Timer")
            self.timerMode.setDisabled(True)
        else:
            # Timer was running -- reset timer and unlock mode control
            Sync.post_match_status(matchNum, "aborted")
            self.audienceDisplay.timer.resetTimer()
            self.timerCtl.setText("Start Timer")
            self.timerMode.setDisabled(False)

    def timerComplete(self):
        Sync.post_match_status(int(self.matchNum.value() + 1), "queueing")
        self.matchNum.setValue(self.matchNum.value() + 1)
        self.changeMode()
        self.timerCtl.setText("Start Timer")
        self.timerMode.setDisabled(False)

    def practiceTimerControl(self):
        self.practiceTimerCtl = PracticeTimerWindow(self)

    def practiceTimerComplete(self):
        if self.practiceTimerCtl is not None:
            self.practiceTimerCtl.handleTimerComplete()

    def doForceSync(self):
        Sync.sync_event(self.matchNum.value(), "queueing", self.teams)

if __name__ == "__main__":
    app = QApplication(sys.argv)

    print(f"Interlocking Brick Scoring Software version {About.getVersion()}")

    if ResourceManager.isResourcePackInstalled():
        packVersion = ResourceManager.getResourcePackVersion()
        print(f"Using resource pack version {packVersion if packVersion else 'unknown'}")

        # Add font from resource pack if available
        fontId = QFontDatabase.addApplicationFont(ResourceManager.getResourcePath("Roboto-Regular.ttf"))

        if fontId != -1:
            fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
            QApplication.setFont(QFont(fontFamily))

    window = MainWindow(app)
    window.setStyleSheet(sheet)
    window.show()
