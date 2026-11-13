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

import Events
import PitDisplay
import ResourceManager
import Timer
from CustomWidgets import CustomScroll, fitRankLabel
from Team import UNRANKED

# What the audience display shows when it isn't showing a timer
LOCAL = "local"  # The local rankings
PIT = "pit"      # The score reflector's pit display

# The audience display always uses light colors, even when the system is in dark mode,
# so every color is set here rather than coming from the system palette
sheet = """
QMainWindow, QAbstractScrollArea, QAbstractScrollArea > QWidget > QWidget {
    background-color: #ececec;
}

QLineEdit {
    font-size: 54px;
    background-color: white;
    color: black;
    border: 1px solid gray;
    border-radius: 4px;
    padding: 10px;
}

QLabel {
    font-size: 20px;
    color: black;
}

QWidget #team_card{
    background-color: #F8B4B6;
    border: 1px solid gray;
    padding: 6px;
    border-radius: 6px;
}
"""

def getMediaUrl(sound_name):
    """Get the QUrl for a sound file from the resource pack."""
    return QUrl.fromLocalFile(ResourceManager.getResourcePath(f"{sound_name}.wav"))

# Sound played when each timer event happens
SOUNDS = {
    Events.MatchStarted: "start",
    Events.MatchAborted: "foghorn",
    Events.PracticeStarted: "bell",
    Events.TimerWarning: "endgame",
    Events.TimerExpired: "end",
}


class AudienceWindow(QMainWindow):
    # Emitted whenever the window enters or leaves fullscreen, however that happened
    fullScreenChanged = pyqtSignal(bool)
    # The source or the pit display page changed
    sourceChanged = pyqtSignal()
    # The cloud pit display couldn't start, so the source is back to the local rankings;
    # the reason is suitable for the operator
    pitDisplayFailed = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__()

        self.dlg = None
        self.parent = parent
        self.mode = "ranks"
        self.source = LOCAL
        self.pitUrl = None  # The cloud pit display page, while there is one

        try:
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

            # Create clock faces after vbox initialization
            self.matchClock = ClockFace(self, Timer.MATCH_TIME)
            self.practiceClock = ClockFace(self, 0, banner="PRACTICE SESSION")
            Events.subscribe(Events.TimerUpdated, self.showTime)

            self.audioOutput = QAudioOutput()
            self.audioOutput.setVolume(100)
            self.mediaPlayer = QMediaPlayer()
            self.mediaPlayer.setAudioOutput(self.audioOutput)
            for eventType, sound in SOUNDS.items():
                Events.subscribe(eventType, lambda event, sound=sound: self.playSound(sound))

            self.loadWidgets()

            # Scroll Area Properties
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.scroll.setWidgetResizable(True)
            self.scroll.setWidget(self.widget)

            # Inhibit user scrolling
            self.scroll.verticalScrollBar().setEnabled(False)

            self.pitView = PitDisplay.PitView()
            self.pitView.failed.connect(self.onPitDisplayFailed)
            self.pitView.keyPressed.connect(self.handleFullScreenKey)

            self.stack = QStackedWidget()
            self.stack.addWidget(self.scroll)
            self.stack.addWidget(self.pitView)

            self.mainLayout = QGridLayout()
            self.mainLayout.addWidget(self.stack, 0, 0, 1, 7)

            self.mainWidget = QWidget()
            self.mainWidget.setLayout(self.mainLayout)

            self.setCentralWidget(self.mainWidget)
            self.setStyleSheet(sheet)

            # Set initial scroller state based on mode
            self.updateDisplayState()

        except Exception as err:
            print(err)

    def loadWidgets(self):
        try:
            if self.mode == "match_timer":
                self.vbox.insertWidget(0, self.matchClock)
            elif self.mode == "practice_timer":
                self.vbox.insertWidget(0, self.practiceClock)
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

            rank = QLabel(str(team.rank) if team.rank != UNRANKED else "NP")
            rank.setStyleSheet("font-size: 54px")
            fitRankLabel(rank, len(self.parent.teams), minimumWidth=80)

            number = QLineEdit(text=str(team.number), readOnly=True)
            number.setFixedWidth(200)

            layout.addWidget(rank, 1, 0, 4, 1)
            layout.addWidget(QLineEdit(text=str(team.name), readOnly=True), 1, 1, 4, 1)
            layout.addWidget(number, 1, 2, 4, 1)

            for num in range(3):
                if team.scores[num] is None:
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

    def setMode(self, mode: str):
        """Show the rankings ("ranks"), match timer ("match_timer"), or practice timer ("practice_timer")."""
        self.mode = mode
        self.clearTeamWidgets()
        self.loadWidgets()
        self.updateDisplayState()

    def setSource(self, source: str):
        """Show the local rankings (LOCAL) or the cloud pit display (PIT) when no timer is showing.
        The cloud pit display needs a page, set with setPitDisplayUrl(); without one, the local rankings show."""
        source = PIT if source == PIT else LOCAL
        if source == self.source:
            return
        self.source = source
        Events.publish(Events.AudienceSourceChanged(source))
        self.updateDisplayState()
        self.sourceChanged.emit()

    def setPitDisplayUrl(self, url):
        """Set the cloud pit display page, or None when there isn't one (e.g. sync isn't set up)."""
        if url == self.pitUrl:
            return
        self.pitUrl = url
        self.updateDisplayState()
        self.sourceChanged.emit()

    def isShowingPitDisplay(self) -> bool:
        return self.source == PIT and self.pitUrl is not None

    def onPitDisplayFailed(self, problem: str):
        self.setSource(LOCAL)
        self.pitDisplayFailed.emit(problem)

    def rerank(self):
        self.clearTeamWidgets()
        self.loadWidgets()

    def scrollToTop(self):
        self.scroll.verticalScrollBar().setValue(0)

    def updateDisplayState(self):
        """Show the cloud pit display or the local page, and control auto-scrolling, based on display mode"""
        if self.isShowingPitDisplay():
            # Keep the page loaded while a timer shows, so it's ready afterwards
            self.pitView.setUrl(self.pitUrl)
        showPit = self.mode == "ranks" and self.isShowingPitDisplay()
        self.stack.setCurrentWidget(self.pitView if showPit else self.scroll)

        if self.mode in ("match_timer", "practice_timer") or showPit:
            # Pause scrolling for timer displays and while the local rankings are hidden
            self.scroll.scroll.pause()
            # Reset scroll position to top
            self.scroll.verticalScrollBar().setValue(0)
        else:
            # Resume scrolling for rankings display
            self.scroll.scroll.resume()

    def setFullScreen(self, fullScreen: bool):
        """Fill the monitor the window is currently on, or restore the previous size and position."""
        if fullScreen == self.isFullScreen():
            return
        if fullScreen:
            self.showFullScreen()
        else:
            self.showNormal()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F11:
            self.handleFullScreenKey("F11")
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.handleFullScreenKey("Escape")
        else:
            super().keyPressEvent(event)

    def handleFullScreenKey(self, key: str):
        """F11 toggles fullscreen and Escape leaves it, whether pressed here or on the cloud pit display."""
        if key == "F11":
            self.setFullScreen(not self.isFullScreen())
        elif key == "Escape":
            self.setFullScreen(False)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.fullScreenChanged.emit(self.isFullScreen())

    def showTime(self, event):
        clock =self.practiceClock if event.practice else self.matchClock
        clock.showTime(event.remaining)

    def testSound(self):
        self.playSound("start")

    def playSound(self, sound: str):
        if ResourceManager.isResourcePackInstalled():
            self.mediaPlayer.setSource(getMediaUrl(sound))
            self.mediaPlayer.setPosition(0)
            self.mediaPlayer.play()


class AudienceSourceMenu(QMenu):
    """Toybox > Audience display: whether the audience display shows the local rankings or the
    score reflector's pit display. Only offered while there's a pit display page (sync is set up, on Windows)."""

    def __init__(self, audience: AudienceWindow, parent: QWidget):
        super().__init__("Audience display", parent)
        self._audience = audience
        self._window = parent
        group = QActionGroup(self)

        def add(label, source):
            action = self.addAction(label)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(lambda checked: audience.setSource(source))
            return action

        self._local = add("Local rankings", LOCAL)
        self._pit = add("Cloud pit display", PIT)

        audience.sourceChanged.connect(self._update)
        audience.pitDisplayFailed.connect(self._onFailed)
        self._update()

    def _update(self):
        self.menuAction().setVisible(self._audience.pitUrl is not None)
        (self._pit if self._audience.source == PIT else self._local).setChecked(True)

    def _onFailed(self, problem: str):
        QMessageBox.warning(
            self._window, "Cloud Pit Display",
            "The cloud pit display couldn't start, so the audience display is showing the local rankings.\n\n"
            "It needs the Microsoft Edge WebView2 Runtime, which comes with Windows 11.\n\n"
            f"Details: {problem}")


class ClockFace(QWidget):
    """Large mm:ss clock display, with an optional banner above it."""

    def __init__(self, audience_window, seconds, banner=None):
        super().__init__()

        self.audience_window = audience_window

        self.timerLayout = QVBoxLayout(self)

        self.bannerLabel = None
        if banner is not None:
            self.bannerLabel = QLabel(banner)
            self.bannerLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.bannerLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self.timerLayout.addWidget(self.bannerLabel)

        self.timerLabel = QLabel(self)
        self.timerLabel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.timerLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timerLayout.addWidget(self.timerLabel)

        # Initial update of the timer label and font sizes
        self.updateFontSize()
        self.showTime(seconds)
        self.setLayout(self.timerLayout)

    def updateFontSize(self):
        """Update font sizes based on audience window height"""
        windowHeight = self.audience_window.height()
        if windowHeight > 0:
            if self.bannerLabel is None:
                timerFontSize = int(windowHeight * 0.75)
            else:
                # Banner takes 10% of height, and the timer font is 60% of total height
                self.bannerLabel.setFixedHeight(int(windowHeight * 0.10))
                self.bannerLabel.setStyleSheet(f"background-color: #F74349; color: #ffffff; font-size: {int(windowHeight * 0.08)}px;")
                timerFontSize = int(windowHeight * 0.60)

            print(f"Height: {windowHeight}, timer font size: {timerFontSize}px ")
            self.timerLabel.setStyleSheet(f"font-size: {timerFontSize}px; padding: -20px;")

    def resizeEvent(self, event):
        """Recalculate font sizes when widget is resized"""
        super().resizeEvent(event)
        self.updateFontSize()

    def showTime(self, seconds: int):
        self.timerLabel.setText(f"{seconds // 60:01d}:{seconds % 60:02d}")
