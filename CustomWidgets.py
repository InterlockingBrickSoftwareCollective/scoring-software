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
        self.threadpool = QThreadPool()
        self.autoScroll()
        self.verticalScrollBar().setVisible(False)

    def autoScroll(self):
        self.threadpool.start(self.scroll)
