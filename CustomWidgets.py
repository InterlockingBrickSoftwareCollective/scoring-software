"""
CustomWidgets.py: Custom widgets shared across application

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
from PyQt6.QtWidgets import *

from Scroller import Scroller


class CustomScroll(QScrollArea):
    def __init__(self):
        super().__init__()
        self.scroll = Scroller(self)
        self.autoScroll()
        self.verticalScrollBar().setVisible(False)

    def autoScroll(self):
        self.scroll.start()


def fitRankLabel(label: QLabel, teamCount: int, minimumWidth: int = 0):
    """Make a rank label wide enough for "NP" or any rank up to teamCount, so the rank column
    lines up across team cards. Set the label's font size before calling this."""
    label.ensurePolished()
    metrics = label.fontMetrics()
    textWidth = max(metrics.boundingRect(text).width() for text in ("NP", str(teamCount)))
    label.setMinimumWidth(max(minimumWidth, textWidth + 2 * label.margin() + 4))
