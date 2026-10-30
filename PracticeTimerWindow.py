"""
PracticeTimerWindow.py: Practice timer controls.

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

from PyQt6.QtWidgets import *
from PyQt6.QtCore import QTime

import Events
import Timer

class PracticeTimerWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Practice Timer Control")

        self.mainWidget = QWidget()
        self.mainLayout = QVBoxLayout()

        self.practiceTimeLayout = QHBoxLayout()
        self.practiceTimeLayout.addWidget(QLabel("Start time:"))
        self.practiceTimeWidget = QTimeEdit()
        self.practiceTimeWidget.setTime(QTime(0, 20, 0))
        self.practiceTimeWidget.setDisplayFormat("mm:ss")
        self.practiceTimeWidget.setFixedWidth(70)
        self.practiceTimeLayout.addWidget(self.practiceTimeWidget)

        self.warningTimeLayout = QHBoxLayout()
        self.warningTimeLayout.addWidget(QLabel("Warning time:"))
        self.warningTimeWidget = QTimeEdit()
        self.warningTimeWidget.setTime(QTime(0, 2, 0)) # default 2 minutes
        self.warningTimeWidget.setDisplayFormat("mm:ss")
        self.warningTimeWidget.setFixedWidth(70)
        self.warningTimeLayout.addWidget(self.warningTimeWidget)

        self.startStopBtn = QPushButton("Start Practice Timer")
        self.startStopBtn.pressed.connect(self.handleStartStop)

        self.mainLayout.addLayout(self.practiceTimeLayout)
        self.mainLayout.addLayout(self.warningTimeLayout)
        self.mainLayout.addWidget(self.startStopBtn)
        self.mainWidget.setLayout(self.mainLayout)
        self.setCentralWidget(self.mainWidget)

        Events.subscribe(Events.PracticeStarted, lambda event: self.startStopBtn.setText("Stop Practice Timer"))
        Events.subscribe(Events.PracticeEnded, lambda event: self.startStopBtn.setText("Start Practice Timer"))

    def handleStartStop(self):
        if Timer.isPracticeRunning():
            Timer.stopPractice()
        else:
            practice_time = self.practiceTimeWidget.time().minute() * 60 + self.practiceTimeWidget.time().second()
            warning_time = self.warningTimeWidget.time().minute() * 60 + self.warningTimeWidget.time().second()
            if not Timer.startPractice(practice_time, warning_time):
                QMessageBox.warning(self, "Match in Progress", "The practice timer can't be started while a match is running.")