"""This file is part of Interlocking Brick Scoring Software.

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

INITIAL_TIME = 150


class AudienceWindow(QMainWindow):
    def __init__(self, parent):
        self.dlg = None
        self.parent = parent
        self.timerMode = False
        self.timer = TimerWidget()

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
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
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

            self.show()
        except Exception as err:
            print(err)

    def loadWidgets(self):
        try:
            if self.timerMode:
                self.vbox.insertWidget(0, self.timer)
                self.timer.showLogo()
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
        self.timerMode = not self.timerMode
        self.timer.resetTimer()
        self.clearTeamWidgets()
        self.loadWidgets()

    def rerank(self):
        self.clearTeamWidgets()
        self.loadWidgets()

    def scrollToTop(self):
        self.scroll.verticalScrollBar().setValue(0)

    def testSound(self):
        if not self.timerMode:
            self.parent.changeMode()

        self.timer.startTimer()
        self.timer.remainingTime = 0


class TimerWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.remainingTime = INITIAL_TIME
        self.timerRunning = False

        # Create buzzer sound media player
        audioPath = os.path.join(os.path.dirname(__file__), "res\\end.wav")

        media = QUrl.fromLocalFile(audioPath)
        self.mediaPlayer = QMediaPlayer()
        self.mediaPlayer.setSource(media)

        self.audioOutput = QAudioOutput()
        self.audioOutput.setVolume(100)

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
        self.updateTimer()
        self.setLayout(self.timerLayout)

        # Make end "splash screen"
        self.logo = QPixmap(os.path.join(os.path.dirname(__file__), "res\\logo.png"))
        self.logo = self.logo.scaledToWidth(int(screen.width() * 0.8), Qt.TransformationMode.SmoothTransformation)

    def startTimer(self):
        # Reset timer if it is already done
        if self.remainingTime <= 0:
            self.resetTimer()

        self.timerLabel.setText("2:30")

        # Start the timer
        if not self.timerRunning:
            self.timerRunning = True
            self.timer.start(1000)

    def resetTimer(self):
        self.timer.stop()  # Stop the timer
        self.timerRunning = False
        self.remainingTime = INITIAL_TIME
        self.updateTimer()

    def updateTimer(self):
        # Convert remaining time to mm:ss format
        showTime = max(0, self.remainingTime)
        minutes = showTime // 60
        seconds = showTime % 60
        timeStr = f"{minutes:01d}:{seconds:02d}"

        # Update the timer label
        self.timerLabel.setText(timeStr)

        # Decrement remaining time
        if self.remainingTime >= -3:
            # Show 0 for 3 seconds after the timer runs out
            if self.remainingTime == 0:
                self.mediaPlayer.setPosition(0)
                self.mediaPlayer.play()

            self.remainingTime -= 1
        else:
            self.timer.stop()
            self.showLogo()

    def showLogo(self):
        self.timerLabel.setPixmap(self.logo)
