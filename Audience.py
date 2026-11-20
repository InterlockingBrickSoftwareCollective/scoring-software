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
import time
from datetime import datetime

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtWidgets import *

import Events
import ResourceManager
import ThemedDisplay
import Timer
from CustomWidgets import CustomScroll, fitRankLabel
from Team import UNRANKED

# What the audience display shows (its mode)
RANKS = "ranks"                    # The rankings: local or themed standings
WELCOME = "welcome"                # The themed welcome screen (only with a theme)
CLOCK = "clock"                    # The time of day
MATCH_TIMER = "match_timer"
PRACTICE_TIMER = "practice_timer"
TIMER_MODES = (MATCH_TIMER, PRACTICE_TIMER)

# How many of the latest scores to remember for the themed standings
RECENT_SCORES = 20

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
    # The themed display was turned on or off
    themeChanged = pyqtSignal(bool)
    # What the display shows changed (RANKS, WELCOME, CLOCK, MATCH_TIMER or PRACTICE_TIMER)
    modeChanged = pyqtSignal(str)

    def __init__(self, parent):
        super().__init__()

        self.dlg = None
        self.parent = parent
        self.mode = RANKS
        # The resource pack's themed screens, shown in place of the local rankings while enabled
        self.theme = ThemedDisplay.Theme.fromResourcePack()
        self.themed = None
        self.themeEnabled = False
        # What the themed timer shows, kept up to date from timer events
        self.matchNumber = None
        self.timers = {
            False: TimerState(Timer.MATCH_TIME, Timer.MATCH_TIME),  # The match timer
            True: TimerState(0, 0),  # The practice timer
        }
        self.runningPractice = None  # Whether the running countdown is a practice session; None when idle
        # The latest scores entered since the program started, newest first, for the themed standings
        self.recentScores = []

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
            self.timeOfDay = ClockFace(self, 0, fontScale=0.42)
            # Updates the time of day while it shows, every second so the themed colon blinks
            self.clockTicker = QTimer(self)
            self.clockTicker.setInterval(1000)
            self.clockTicker.timeout.connect(self.showTimeOfDay)
            Events.subscribe(Events.TimerUpdated, self.showTime)
            Events.subscribe(Events.MatchSelected, lambda event: self.setMatchNumber(event.match))
            Events.subscribe(Events.MatchStarted, self.onMatchStarted)
            Events.subscribe(Events.PracticeStarted, self.onPracticeStarted)
            Events.subscribe(Events.TimerWarning, self.onTimerWarning)
            Events.subscribe(Events.TimerExpired, self.onTimerExpired)
            for endType in (Events.MatchAborted, Events.MatchCompleted, Events.PracticeEnded):
                Events.subscribe(endType, self.onTimerEnded)
            Events.subscribe(Events.ScoreUpdated, self.onScoreUpdated)
            Events.subscribe(Events.ScoreCleared, lambda event: self.forgetRecentScores(event.teamNumber, event.round))
            Events.subscribe(Events.TeamDeleted, lambda event: self.forgetRecentScores(event.number))

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

            self.stack = QStackedWidget()
            self.stack.addWidget(self.scroll)

            if self.theme is not None:
                self.themed = ThemedDisplay.ThemedAudience(self.theme, lambda: self.parent.teams, self,
                                                           recent=lambda: self.recentScores)
                self.stack.addWidget(self.themed.view)

            self.mainLayout = QGridLayout()
            self.mainLayout.addWidget(self.stack, 0, 0, 1, 7)
            self.defaultMargins = self.mainLayout.contentsMargins()

            self.mainWidget = QWidget()
            self.mainWidget.setLayout(self.mainLayout)

            self.setCentralWidget(self.mainWidget)
            self.setStyleSheet(sheet)

            # Set initial scroller state based on mode
            self.updateScrollerState()

        except Exception as err:
            print(err)

    def loadWidgets(self):
        try:
            if self.mode == MATCH_TIMER:
                self.vbox.insertWidget(0, self.matchClock)
            elif self.mode == PRACTICE_TIMER:
                self.vbox.insertWidget(0, self.practiceClock)
            elif self.mode == CLOCK:
                self.timeOfDay.showText(ThemedDisplay.clockText(datetime.now()))
                self.vbox.insertWidget(0, self.timeOfDay)
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

    def canShowWelcome(self) -> bool:
        """The welcome screen is only themed, so it's only available while the theme is on."""
        return self.themeEnabled and self.themed is not None and self.themed.hasWelcome()

    def setMode(self, mode: str):
        """Show the rankings (RANKS), the welcome screen (WELCOME), the time of day (CLOCK),
        the match timer (MATCH_TIMER), or the practice timer (PRACTICE_TIMER)."""
        if mode == WELCOME and not self.canShowWelcome():
            mode = RANKS
        changed = mode != self.mode
        self.mode = mode
        self.clearTeamWidgets()
        self.loadWidgets()
        self.updateDisplayState()
        if changed:
            self.modeChanged.emit(mode)

    def hasTheme(self) -> bool:
        """Whether the resource pack has themed screens."""
        return self.themed is not None

    def setThemeEnabled(self, enabled: bool):
        """Show the resource pack's themed screens in place of the local rankings, or the
        standard rankings. Has no effect without a theme."""
        enabled = bool(enabled) and self.hasTheme()
        if enabled == self.themeEnabled:
            return
        self.themeEnabled = enabled
        Events.publish(Events.AudienceThemeChanged(enabled))
        if self.mode == WELCOME and not enabled:
            self.setMode(RANKS)
        self.updateDisplayState()
        self.themeChanged.emit(enabled)

    def isShowingTheme(self) -> bool:
        """Whether the themed standings rotation shows."""
        return self.mode == RANKS and self.themeEnabled

    def isShowingThemedTimer(self) -> bool:
        return (self.mode in TIMER_MODES and self.themeEnabled
                and self.themed is not None and self.themed.hasTimer())

    def isShowingThemedClock(self) -> bool:
        return self.mode == CLOCK and self.themeEnabled and self.themed is not None and self.themed.hasClock()

    def showTimeOfDay(self):
        now = datetime.now()
        if self.isShowingThemedClock():
            self.themed.showClock(now)
        elif self.mode == CLOCK:
            self.timeOfDay.showText(ThemedDisplay.clockText(now))

    # Latest scores

    def onScoreUpdated(self, event):
        self.forgetRecentScores(event.teamNumber, event.round)
        self.recentScores.insert(0, ThemedDisplay.RecentScore(event.teamNumber, event.round, event.score, time.time()))
        del self.recentScores[RECENT_SCORES:]

    def forgetRecentScores(self, team: int, round: int = None):
        """Drop a team's latest score for a round (or every round) that was cleared or deleted."""
        self.recentScores = [s for s in self.recentScores
                             if not (s.team == team and (round is None or s.round == round))]

    def setMatchNumber(self, match: int):
        """The match the themed match timer is titled with, until a match starts."""
        self.matchNumber = match
        self.refreshThemedTimer()

    def onTimerExpired(self, event):
        if self.runningPractice is not None:
            self.timers[self.runningPractice].expired = True
            self.refreshThemedTimer()

    def onMatchStarted(self, event):
        self.matchNumber = event.match
        self.runningPractice = False
        self.timers[False] = TimerState(Timer.MATCH_TIME, Timer.MATCH_TIME)

    def onPracticeStarted(self, event):
        self.runningPractice = True
        self.timers[True] = TimerState(event.duration, event.duration)

    def onTimerWarning(self, event):
        if self.runningPractice is not None:
            self.timers[self.runningPractice].warning = True
            self.refreshThemedTimer()

    def onTimerEnded(self, event):
        practice = isinstance(event, Events.PracticeEnded)
        self.timers[practice].warning = False
        self.timers[practice].expired = False
        self.runningPractice = None

    def refreshThemedTimer(self):
        if not self.isShowingThemedTimer():
            return
        practice = self.mode == PRACTICE_TIMER
        state = self.timers[practice]
        if practice:
            title = "Practice timer"
        else:
            title = f"Match {self.matchNumber}" if self.matchNumber is not None else "Match"
        self.themed.showTimer(title, state.remaining, state.total, state.warning, state.expired)

    def setEventInfo(self, name: str, date: str):
        """The event name and date the themed screens show."""
        if self.themed is not None:
            self.themed.setEventInfo(name, date)

    def showThemedScreen(self, screen: str, values: dict = None, **kwargs):
        """Hold one of the theme's screens (e.g. "award_winner") in place of the rotation
        until resumeThemedRotation(). See ThemedDisplay.ThemedAudience.showScreen()."""
        if self.themed is None:
            raise RuntimeError("The resource pack has no themed screens")
        self.themed.showScreen(screen, values, **kwargs)

    def resumeThemedRotation(self):
        if self.themed is not None:
            self.themed.resumeRotation()

    def rerank(self):
        self.clearTeamWidgets()
        self.loadWidgets()
        if self.themed is not None:
            self.themed.refresh()

    def scrollToTop(self):
        self.scroll.verticalScrollBar().setValue(0)

    def updateDisplayState(self):
        """Show the themed or standard page, and control auto-scrolling, based on display mode"""
        showTheme = self.isShowingTheme()
        showThemedTimer = self.isShowingThemedTimer()
        showThemedClock = self.isShowingThemedClock()
        showWelcome = self.mode == WELCOME and self.canShowWelcome()
        # The themed screens fill the window edge to edge, letterboxed in the theme's own color
        themed = showTheme or showThemedTimer or showThemedClock or showWelcome
        self.mainLayout.setContentsMargins(QMargins(0, 0, 0, 0) if themed else self.defaultMargins)
        if themed:
            self.stack.setCurrentWidget(self.themed.view)
        else:
            self.stack.setCurrentWidget(self.scroll)
        if showThemedTimer:
            self.refreshThemedTimer()
        elif showThemedClock:
            self.themed.showClock(datetime.now())
        elif showWelcome:
            self.themed.showWelcome()
        elif showTheme:
            self.themed.start()
        elif self.themed is not None:
            self.themed.stop()

        if self.mode == CLOCK:
            self.clockTicker.start()
        else:
            self.clockTicker.stop()

        if self.mode != RANKS or showTheme:
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
            self.setFullScreen(not self.isFullScreen())
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.setFullScreen(False)
        else:
            super().keyPressEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.fullScreenChanged.emit(self.isFullScreen())

    def showTime(self, event):
        clock =self.practiceClock if event.practice else self.matchClock
        clock.showTime(event.remaining)
        self.timers[event.practice].remaining = event.remaining
        if self.isShowingThemedTimer() and event.practice == (self.mode == PRACTICE_TIMER):
            self.refreshThemedTimer()

    def testSound(self):
        self.playSound("start")

    def playSound(self, sound: str):
        if ResourceManager.isResourcePackInstalled():
            self.mediaPlayer.setSource(getMediaUrl(sound))
            self.mediaPlayer.setPosition(0)
            self.mediaPlayer.play()


class TimerState:
    """What a themed timer shows: seconds left, the countdown's length, and whether its warning time passed."""

    def __init__(self, remaining: int, total: int):
        self.remaining = remaining
        self.total = total
        self.warning = False
        self.expired = False  # Time ran out


class ClockFace(QWidget):
    """Large mm:ss clock display, with an optional banner above it."""

    def __init__(self, audience_window, seconds, banner=None, fontScale=0.75):
        super().__init__()

        self.audience_window = audience_window
        self.fontScale = fontScale  # Font size as a fraction of the window height, without a banner

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
                timerFontSize = int(windowHeight * self.fontScale)
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

    def showText(self, text: str):
        self.timerLabel.setText(text)
