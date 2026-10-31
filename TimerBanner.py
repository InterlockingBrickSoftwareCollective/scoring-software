"""
TimerBanner.py: Running timer readout for the scoring display

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

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy

import Events

# Banner colors for each stage of the countdown; these read the same in light and dark mode
_STYLES = {
    "running": "background-color: #000000; color: white;",
    "warning": "background-color: #f5b041; color: black;",
    "expired": "background-color: #ED1C24; color: white;",
}


class TimerBanner(QLabel):
    """Shows the match or practice timer while one is running, so the scorekeeper can keep an eye on
    it without looking at the audience display. Hidden the rest of the time."""

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setVisible(False)

        # What's running ("Match 3" or "Practice session"), or None when no timer is running
        self.title: Optional[str] = None
        self.stage = "running"

        Events.subscribe(Events.MatchStarted, lambda event: self._start(f"Match {event.match}"))
        Events.subscribe(Events.PracticeStarted, lambda event: self._start("Practice session"))
        Events.subscribe(Events.TimerWarning, lambda event: self._setStage("warning"))
        Events.subscribe(Events.TimerExpired, lambda event: self._setStage("expired"))
        Events.subscribe(Events.TimerUpdated, self._showTime)
        for endEvent in (Events.MatchCompleted, Events.MatchAborted, Events.PracticeEnded):
            Events.subscribe(endEvent, lambda event: self._stop())

    def _start(self, title: str):
        self.title = title
        self._setStage("running")
        # The timer follows up with the starting time, which shows the banner

    def _stop(self):
        # The timer follows up with a reset to the full duration, which _showTime ignores
        self.title = None
        self.setVisible(False)

    def _setStage(self, stage: str):
        self.stage = stage
        self.setStyleSheet(f"{_STYLES[stage]} font-size: 24px; font-weight: bold; padding: 6px; border-radius: 4px;")

    def _showTime(self, event):
        if self.title is None:
            return
        self.setText(f"{self.title}  {event.remaining // 60:01d}:{event.remaining % 60:02d}")
        self.setVisible(True)
