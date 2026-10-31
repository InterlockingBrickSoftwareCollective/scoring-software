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
import sys
from string import Template

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *

import About
import CycleTimeReport
import Events
import ResourceManager
import Substrate
import Timer

from AddWindow import AddWindow
from Audience import AudienceWindow
from CustomWidgets import fitRankLabel
from Insert import Insert
from PracticeTimerWindow import PracticeTimerWindow
from SyncControl import EventStatusMenu, FinalizeEventButton, SyncController, SyncStatusButton
from Team import Team, UNRANKED, rank as rankTeams
from TimerBanner import TimerBanner

# Colors for the light and dark color schemes, filled into the style sheets below
LIGHT_COLORS = {
    "field": "white",
    "field_text": "black",
    "field_border": "gray",
    "spin_border": "black",
    "accent": "#F8B4B6",
    "accent_text": "black",
    "inactive": "#aaaaaa",
    "inactive_text": "black",
}

DARK_COLORS = {
    "field": "#2b2b2b",
    "field_text": "#f0f0f0",
    "field_border": "#6e6e6e",
    "spin_border": "#8a8a8a",
    "accent": "#5c3437",
    "accent_text": "#f0f0f0",
    "inactive": "#4a4a4a",
    "inactive_text": "#b0b0b0",
}

sheet = Template("""
QLineEdit{
    font-size: 20px;
    background-color: $field;
    color: $field_text;
    border: 1px solid $field_border;
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
    background-color: $accent;
    color: $accent_text;
    border: 1px solid gray;
    padding: 12px;
    font-size: 18px;
}

QAction {
    font-size: 16px;
    margin: 8px;
}

QWidget #team_card {
    background-color: $accent;
    border: 1px solid gray;
    padding: 1px;
    border-radius: 4px;
}

QWidget #team_card QLabel {
    color: $accent_text;
}

QPushButton {
    background-color: #000000;
    color: white;
    border-radius: 4px;
    padding: 6px;
}

QSpinBox {
    font-size: 20px;
    background-color: $field;
    color: $field_text;
    border: 2px solid $spin_border;
    border-radius: 4px;
    padding: 2px;
}
""")

sortButtonSheet = Template("background-color: $accent; color: $accent_text")
inactiveSortButtonSheet = Template("background-color: $inactive; color: $inactive_text")


def themeColors():
    """Colors for the system's current light or dark color scheme."""
    if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return DARK_COLORS
    return LIGHT_COLORS


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
            self.practiceTimerCtl = None

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

            # Timer control buttons
            self.timerMode = QAction("Show Timer")
            self.timerMode.triggered.connect(self.changeMode)
            self.timerCtl = QAction("Start Timer")
            self.timerCtl.triggered.connect(self.handleTimerCtl)
            self.timerCtl.setDisabled(True) # Audience display starts on rank display

            Timer.init()
            Events.subscribe(Events.MatchStarted, lambda event: self.setAudienceMode("match_timer"))
            Events.subscribe(Events.MatchAborted, lambda event: self.updateTimerControls())
            Events.subscribe(Events.MatchCompleted, self.onMatchCompleted)
            Events.subscribe(Events.PracticeStarted, lambda event: self.setAudienceMode("practice_timer"))

            self.menuBar().addAction(self.insert)
            if self.scoresheet:
                self.menuBar().addAction(self.scoresheet)
            self.menuBar().addAction(self.export)
            self.menuBar().addMenu(self.audienceMenu)
            self.menuBar().addActions([self.timerMode, self.timerCtl])

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
            self.scoresEnteredLabel = QLabel("Scores Entered: 0 / 0")
            self.scoresEnteredLabel.setStyleSheet("font-size: 20px")
            self.scoresEnteredLabel.setFixedWidth(260)

            # Sort type
            self.sortNum = QPushButton("Sort by Team Number")
            self.sortNum.setFixedWidth(180)
            self.sortNum.pressed.connect(self.sortTeamsByNumber)

            self.sortRank = QPushButton("Sort by Team Rank")
            self.sortRank.setFixedWidth(180)
            self.sortRank.pressed.connect(self.sortTeamsByRank)
            self.sortRank.setEnabled(False)

            # Create Toybox menu and button
            self.toyboxMenu = QMenu("Toybox", self)
            installResPack = QAction("Install resource pack")
            installResPack.triggered.connect(self.installResPack)
            cycleTimeAction = QAction("Cycle time report")
            cycleTimeAction.triggered.connect(self.showCycleTimeReport)
            aboutAction = QAction("About...")
            aboutAction.triggered.connect(self.showAboutDialog)
            self.toyboxMenu.addActions([aboutAction, cycleTimeAction, installResPack])

            # Sync to score reflector
            self.sync = SyncController(self)
            self.toyboxMenu.addSeparator()
            setUpSyncAction = QAction("Set up sync...", self)
            setUpSyncAction.triggered.connect(self.sync.setUp)
            self.syncNowAction = QAction("Sync now", self)
            self.syncNowAction.triggered.connect(self.sync.syncNow)
            self.removeSyncAction = QAction("Remove sync...", self)
            self.removeSyncAction.triggered.connect(self.sync.remove)
            self.eventStatusMenu = EventStatusMenu(self.sync, self.matchNum.value, self)
            self.toyboxMenu.addActions([setUpSyncAction, self.syncNowAction, self.eventStatusMenu.menuAction(),
                                        self.removeSyncAction])
            self.sync.statusChanged.connect(self.updateSyncActions)
            self.syncStatusButton = SyncStatusButton(self.sync)
            self.finalizeButton = FinalizeEventButton(self.sync)

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
            self.configLayout.setColumnStretch(7, 1)  # Add stretch to push sync controls and Toybox to the right
            self.configLayout.addWidget(self.finalizeButton, 0, 7, alignment=Qt.AlignmentFlag.AlignRight)
            self.configLayout.addWidget(self.syncStatusButton, 0, 8)
            self.configLayout.addWidget(self.toyboxButton, 0, 9)
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

            # Running timer readout, in its own row below the team list so it never covers the list or
            # gets in the way of scrolling it
            self.timerBanner = TimerBanner()

            self.mainLayout.addWidget(self.scroll, 1, 0, 1, 7)
            self.mainLayout.addWidget(self.configWidget, 0, 0, 1, 7)
            self.mainLayout.addWidget(self.timerBanner, 2, 0, 1, 7)
            self.mainLayout.setRowStretch(1, 1)
            self.mainWidget.setLayout(self.mainLayout)
            self.setCentralWidget(self.mainWidget)
            self.applyTheme()
            QGuiApplication.styleHints().colorSchemeChanged.connect(self.applyTheme)

            # Restore any teams and scores in the database
            self.addTeams([Team(team.name, team.teamnumber, team.pit, from_db=True) for team in Substrate.loadTeams()])

            for score in Substrate.loadScores():
                team = self.fetchTeam(score.teamnumber)
                team.setScore(score.round, score.score, score.scoresheet, from_db=True)

            self.rerank()
            self.show()

            self.sync.startFromSavedConfig()

            # Render audience window, then bring focus back to main scoring window
            self.audienceDisplay.show()
            self.raise_()
            self.activateWindow()

            application.exec()
        except Exception as err:
            print(err)

    def showAboutDialog(self):
        About.show(self)

    def updateSyncActions(self, status):
        configured = status is not None
        self.syncNowAction.setVisible(configured)
        self.removeSyncAction.setVisible(configured)
        self.eventStatusMenu.menuAction().setVisible(configured)

    def showCycleTimeReport(self):
        CycleTimeReport.show(self)

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
                                    score = int(row[f"Round {i} Score"])
                                except ValueError:  # probably blank entry, haven't played round
                                    continue
                                # unexpected exceptions get rethrown and caught below

                                # Older exports wrote -1 for rounds that hadn't been played
                                if score >= 0:
                                    team.setScore(i, score)

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
                    scores = ",".join("" if score is None else str(score) for score in team.scores)
                    f.write(f"{team.pit},{team.name},{team.number},{scores}\n")

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
                self.sync.shutdown()
                Substrate.deinit()

                if self.insertWindow is not None:
                    self.insertWindow.close()
                if self.addWindow is not None:
                    self.addWindow.close()

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
        # Errors are left to the caller, which shows them to the operator
        self.teams.append(team)
        self.rerank()

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

                self.scoresEntered += sum([1 for score in team.scores if score is not None])

            # Every team plays three rounds
            expected = len(teamList) * 3
            self.scoresEnteredLabel.setText(f"Scores Entered: {self.scoresEntered} / {expected}")
            self.finalizeButton.setScoresComplete(expected > 0 and self.scoresEntered >= expected)
        except Exception as err:
            print(err)

    def clearTeamWidgets(self):
        try:
            # Unlike the audience display's list, the grid holds nothing but team cards
            for i in reversed(range(self.teamGrid.count())):
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

        self.styleSortButtons()

    def styleSortButtons(self):
        # Highlight the button that switches to the other sort order
        colors = themeColors()
        active = sortButtonSheet.substitute(colors)
        inactive = inactiveSortButtonSheet.substitute(colors)
        self.sortNum.setStyleSheet(active if self.sortByRank else inactive)
        self.sortRank.setStyleSheet(inactive if self.sortByRank else active)

    def applyTheme(self):
        """Style the window for the system's current light or dark color scheme."""
        self.setStyleSheet(sheet.substitute(themeColors()))
        self.styleSortButtons()

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

            rank = QLabel(str(team.rank) if team.rank != UNRANKED else "NP")
            rank.setStyleSheet("font-size: 24px")
            fitRankLabel(rank, len(self.teams))
            layout.addWidget(rank, 1, 0, 4, 1)
            layout.addWidget(QLineEdit(text=str(team.name), readOnly=True), 1, 1, 4, 1)
            number = QLineEdit(text=str(team.number), readOnly=True)
            number.setFixedWidth(100)
            layout.addWidget(number, 1, 2, 4, 1)

            for num in range(3):
                if team.scores[num] is None:
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

        rankTeams(self.teams)

        self.loadAllTeams()
        self.audienceDisplay.rerank()

    def updateMatchNumber(self):
        Events.publish(Events.MatchSelected(self.matchNum.value()))

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
        Events.publish(Events.TeamUpdated(int(number), team.name, team.pit))

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
            Events.publish(Events.TeamDeleted(number))

            self.rerank()
        except Exception as err:
            print(err)

    def changeMode(self):
        self.setAudienceMode("match_timer" if self.audienceDisplay.mode == "ranks" else "ranks")

    def setAudienceMode(self, mode: str):
        self.audienceDisplay.setMode(mode)
        self.updateTimerControls()

    def updateTimerControls(self):
        # Lock out mode control while a match is running; timer control is only available when showing a timer
        matchRunning = Timer.isMatchRunning()
        self.timerMode.setText(f"Show {'Rankings' if self.audienceDisplay.mode != 'ranks' else 'Timer'}")
        self.timerMode.setDisabled(matchRunning)
        self.timerCtl.setText("Reset Timer" if matchRunning else "Start Timer")
        self.timerCtl.setDisabled(self.audienceDisplay.mode == "ranks")
        self.menuBar().update()

    def handleTimerCtl(self):
        if Timer.isMatchRunning():
            Timer.abortMatch()
        else:
            Timer.startMatch(self.matchNum.value())

    def onMatchCompleted(self, event):
        self.matchNum.setValue(self.matchNum.value() + 1)
        self.setAudienceMode("ranks")

    def practiceTimerControl(self):
        # Reuse the same window so it keeps showing the state of a running practice session
        if self.practiceTimerCtl is None:
            self.practiceTimerCtl = PracticeTimerWindow()
        self.practiceTimerCtl.show()
        self.practiceTimerCtl.raise_()
        self.practiceTimerCtl.activateWindow()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    # Qt 6.7+ defaults to the "windows11" style on Windows 11, which doesn't respect the stylesheets'
    # menu bar font sizes and draws spin box buttons over the text, so use the previous default style
    if app.style().name() == "windows11":
        app.setStyle("windowsvista")

    print(f"Interlocking Brick Scoring Software version {About.getVersion()}")

    try:
        ResourceManager.initializeResources()

        packVersion = ResourceManager.getResourcePackVersion()
        print(f"Using resource pack version {packVersion if packVersion else 'unknown'}")

        # Add font from resource pack if available
        fontId = QFontDatabase.addApplicationFont(ResourceManager.getResourcePath("Roboto-Regular.ttf"))
        if fontId != -1:
            fontFamily = QFontDatabase.applicationFontFamilies(fontId)[0]
            QApplication.setFont(QFont(fontFamily))
    except FileNotFoundError:
        print("No resource pack installed")
    except Exception as e:
        print(f"Failed to load resource pack: {e}")

    window = MainWindow(app)
    window.show()
