"""
Audience.py: Audience display window

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

import os

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtWidgets import *

from CustomWidgets import CustomScroll

sheet = """
QLineEdit {
    font-size: 54px;
    background-color: white;
    border: 1px solid gray;
    border-radius: 4px;
    padding: 10px;
}

QLabel {
    font-size: 20px
}

QWidget #team_card{
    background-color: #F8B4B6;
    border: 1px solid gray;
    padding: 6px;
    border-radius: 6px;
}
"""

media = {
    "bell": QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "res", "bell.wav")),
    "end": QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "res", "end.wav")),
    "endgame": QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "res", "endgame.wav")),
    "foghorn": QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "res", "foghorn.wav")),
    "start": QUrl.fromLocalFile(os.path.join(os.path.dirname(__file__), "res", "start.wav")),
}

INITIAL_TIME = 150


class AudienceWindow(QMainWindow):
    def __init__(self, parent):
        self.dlg = None
        self.parent = parent
        self.mode = "ranks"
        self.timer = TimerWidget(parent)
        self.practice = PracticeTimerWidget(parent)

        try:
            super().__init__()
            self.setWindowTitle("Audience Display")

            # Block off window controls
            self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, False)

            # Find size of monitor and launch app
            screen = QGuiApplication.primaryScreen().geometry()
            self.setGeometry(10, 30, screen.width() - 40, screen.height() - 60)

            self.scroll = CustomScroll()
            self.widget = QWidget()
            self.vbox = QVBoxLayout()
            self.vbox.addStretch()
            self.widget.setLayout(self.vbox)
            self.loadWidgets()

            # Scroll Area Properties
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setWidgetResizable(True)
            self.scroll.setWidget(self.widget)

            # Inhibit user scrolling
            self.scroll.verticalScrollBar().setEnabled(False)

            self.mainLayout = QGridLayout()
            self.mainLayout.addWidget(self.scroll, 0, 0, 1, 7)

            self.mainWidget = QWidget()
            self.mainWidget.setLayout(self.mainLayout)

            self.setCentralWidget(self.mainWidget)
            self.setStyleSheet(sheet)

        except Exception as err:
            print(err)

    def loadWidgets(self):
        try:
            if self.mode == "match_timer":
                self.vbox.insertWidget(0, self.timer)
                self.timer.paintTimer()
            elif self.mode == "practice_timer":
                self.vbox.insertWidget(0, self.practice)
                self.practice.paintTimer()
            else:
                for team in self.parent.teams[::-1]:
                    widget = self.makeTeamWidget(team)
                    self.vbox.insertWidget(0, widget)
        except Exception as err:
            print(err)

    def clearTeamWidgets(self):
        try:
            for i in reversed(range(self.vbox.count() - 1)):
                self.vbox.itemAt(i).widget().setParent(None)
        except Exception as err:
            print(err)

    def makeTeamWidget(self, team):
        try:
            card = QWidget()
            card.setObjectName("team_card")
            card.setFixedHeight(160)
            layout = QGridLayout()

            layout.setHorizontalSpacing(10)
            layout.setVerticalSpacing(2)
            layout.addWidget(QLabel(" Team Name"), 0, 1)
            layout.addWidget(QLabel(" Team Number"), 0, 2)
            layout.addWidget(QLabel(" Round 1"), 0, 3)
            layout.addWidget(QLabel(" Round 2"), 0, 4)
            layout.addWidget(QLabel(" Round 3"), 0, 5)

            rank = QLabel(str(team.rank) if team.rank < 1E10 else "NP")
            rank.setMinimumWidth(80)
            rank.setStyleSheet("font-size: 54px")

            number = QLineEdit(text=str(team.number), readOnly=True)
            number.setFixedWidth(200)

            layout.addWidget(rank, 1, 0, 4, 1)
            layout.addWidget(QLineEdit(text=str(team.name), readOnly=True), 1, 1, 4, 1)
            layout.addWidget(number, 1, 2, 4, 1)

            for num in range(3):
                if team.scores[num] < 0:
                    roundWidget = QLineEdit(text="", readOnly=True)
                else:
                    roundWidget = QLineEdit(text=str(team.scores[num]), readOnly=True)
                    if team.highScoreIndex == num:
                        roundWidget.setStyleSheet("border: 8px solid #ED1C24; font-weight: bold;")
                roundWidget.setFixedWidth(140)
                layout.addWidget(roundWidget, 1, num + 3, 4, 1)

            card.setLayout(layout)

            return card
        except Exception as err:
            print(err)

    def changeMode(self):
        self.mode = "ranks" if self.mode in ("practice_timer", "match_timer") else "match_timer"
        self.timer.resetTimer()
        self.clearTeamWidgets()
        self.loadWidgets()

    def rerank(self):
        self.clearTeamWidgets()
        self.loadWidgets()

    def scrollToTop(self):
        self.scroll.verticalScrollBar().setValue(0)

    def testSound(self):
        self.timer.playSound("start")

    def startPracticeTimer(self, practice_time: int, warning_time: int):
        self.mode = "practice_timer"
        self.practice.practiceTime = practice_time
        self.practice.warningTime = warning_time
        self.clearTeamWidgets()
        self.loadWidgets()
        self.practice.startTimer()

    def stopPracticeTimer(self):
        self.practice.resetTimer()


class TimerWidget(QWidget):
    def __init__(self, main):
        super().__init__()

        self.main = main

        self.remainingTime = INITIAL_TIME
        self.timerRunning = False

        self.audioOutput = QAudioOutput()
        self.audioOutput.setVolume(100)
        self.mediaPlayer = QMediaPlayer()
        self.mediaPlayer.setAudioOutput(self.audioOutput)

        self.timerLayout = QVBoxLayout(self)
        self.timerLabel = QLabel(self)

        # Make text very large
        screen = QGuiApplication.primaryScreen().geometry()
        self.timerLabel.setStyleSheet(f"font-size: {int(screen.height() * 0.75)}px; padding: -20px;")
        self.timerLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.timerLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timerLayout.addWidget(self.timerLabel)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateTimer)

        # Initial update of the timer label
        self.paintTimer()
        self.setLayout(self.timerLayout)

    def paintTimer(self):
        # Convert remaining time to mm:ss format
        showTime = max(0, self.remainingTime)
        minutes = showTime // 60
        seconds = showTime % 60
        timeStr = f"{minutes:01d}:{seconds:02d}"

        # Update the timer label
        self.timerLabel.setText(timeStr)

    def startTimer(self):
        # Reset timer if it is already done
        if self.remainingTime <= 0:
            self.resetTimer()

        # Start the timer
        if not self.timerRunning:
            self.playSound("start")

            self.timerRunning = True
            self.timer.start(1000)

    def resetTimer(self):
        if self.timerRunning:
            self.playSound("foghorn")

        self.timer.stop()  # Stop the timer
        self.timerRunning = False
        self.remainingTime = INITIAL_TIME
        self.paintTimer()

    def updateTimer(self):
        # Timer tick and repaint
        self.remainingTime -= 1
        self.paintTimer()

        if self.remainingTime >= -3: # Show "0:00" for 3 seconds after the timer runs out
            # Endgame at 30 seconds
            if self.remainingTime == 30:
                self.playSound("endgame")

            # End of match at 0 seconds
            if self.remainingTime == 0:
                self.playSound("end")
        else:
            self.timerRunning = False
            self.main.timerComplete()

    def playSound(self, sound: str):
        self.mediaPlayer.setSource(media[sound])
        self.mediaPlayer.setPosition(0)
        self.mediaPlayer.play()

class PracticeTimerWidget(QWidget):
    def __init__(self, main):
        super().__init__()

        self.main = main

        self.practiceTime = 0
        self.remainingTime = 0
        self.warningTime = 0
        self.timerRunning = False

        self.audioOutput = QAudioOutput()
        self.audioOutput.setVolume(100)
        self.mediaPlayer = QMediaPlayer()
        self.mediaPlayer.setAudioOutput(self.audioOutput)

        screen = QGuiApplication.primaryScreen().geometry()

        self.timerLayout = QVBoxLayout(self)

        practiceLabel = QLabel("PRACTICE SESSION")
        practiceLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        practiceLabel.setStyleSheet(f"background-color: #F74349; color: #ffffff; font-size: {int(screen.height() * 0.08)}px;")
        practiceLabel.setFixedHeight(int(screen.height() * 0.10))
        practiceLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.timerLayout.addWidget(practiceLabel)

        # Make text very large
        self.timerLabel = QLabel(self)
        self.timerLabel.setStyleSheet(f"font-size: {int(screen.height() * 0.60)}px; padding: -20px;")
        self.timerLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.timerLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timerLayout.addWidget(self.timerLabel)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.updateTimer)

        # Initial update of the timer label
        self.paintTimer()
        self.setLayout(self.timerLayout)

    def paintTimer(self):
        # Convert remaining time to mm:ss format
        showTime = max(0, self.remainingTime)
        minutes = showTime // 60
        seconds = showTime % 60
        timeStr = f"{minutes:01d}:{seconds:02d}"

        # Update the timer label
        self.timerLabel.setText(timeStr)

    def startTimer(self):
        if not self.timerRunning:
            self.playSound("bell")

            self.timer.start(1000)
            self.timerRunning = True
            self.remainingTime = self.practiceTime
            self.paintTimer()

    def resetTimer(self):
        self.timer.stop()  # Stop tick
        self.timerRunning = False
        self.remainingTime = self.practiceTime
        self.paintTimer()

    def updateTimer(self):
        # Timer tick and repaint
        self.remainingTime -= 1
        self.paintTimer()

        if self.timerRunning and self.remainingTime >= -3: # Show "0:00" for 3 seconds after the timer runs out
            # Practice warning time
            if self.remainingTime == self.warningTime:
                self.playSound("endgame")

            # End of practice at 0 seconds
            if self.remainingTime == 0:
                self.playSound("end")
        else:
            self.main.practiceTimerComplete()
            # Reset timer after main callback to prevent a "flash" of the newly-reset timer
            self.resetTimer()

    def playSound(self, sound: str):
        self.mediaPlayer.setSource(media[sound])
        self.mediaPlayer.setPosition(0)
        self.mediaPlayer.play()
