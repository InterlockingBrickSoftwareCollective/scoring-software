"""
Scroller.py: Scroller widget for audience display

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

from PyQt6.QtCore import *


class Scroller(QObject):
    """Auto-scrolls a QScrollArea from the GUI thread (widgets must not be touched from other threads)."""

    inc = 1
    interval = 1000 // 60
    holdTime = 5000  # ms to linger at the bottom, and then at the top, before scrolling again

    def __init__(self, scroll):
        super().__init__(scroll)
        self.scroll = scroll
        self.paused = False
        self.atBottom = False

        self.tickTimer = QTimer(self)
        self.tickTimer.setTimerType(Qt.TimerType.PreciseTimer)
        self.tickTimer.setInterval(self.interval)
        self.tickTimer.timeout.connect(self.tick)

        self.holdTimer = QTimer(self)
        self.holdTimer.setSingleShot(True)
        self.holdTimer.setInterval(self.holdTime)
        self.holdTimer.timeout.connect(self.endHold)

    def start(self):
        """Start auto-scrolling"""
        self.paused = False
        self.atBottom = False
        self.holdTimer.stop()
        self.tickTimer.start()

    def pause(self):
        """Pause auto-scrolling (for timer displays)"""
        self.paused = True
        self.tickTimer.stop()
        self.holdTimer.stop()

    def resume(self):
        """Resume auto-scrolling (for rankings display)"""
        if self.paused:
            self.start()

    def tick(self):
        bar = self.scroll.verticalScrollBar()
        val = bar.value() + self.inc

        if val > bar.maximum():
            # Reached the bottom: hold here, then jump to the top and hold again
            self.tickTimer.stop()
            self.atBottom = True
            self.holdTimer.start()
        else:
            bar.setValue(val)

    def endHold(self):
        if self.atBottom:
            self.atBottom = False
            self.scroll.verticalScrollBar().setValue(0)
            self.holdTimer.start()
        else:
            self.tickTimer.start()
