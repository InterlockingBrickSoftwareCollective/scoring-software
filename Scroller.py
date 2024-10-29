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

import time

from PyQt6.QtCore import *


class Scroller(QRunnable):
    inc = 1

    def __init__(self, scroll):
        super().__init__()
        self.scroll = scroll
        self.go = True

    @pyqtSlot()
    def run(self):
        while self.go:
            time.sleep(1 / 60)
            val = self.scroll.verticalScrollBar().value() + self.inc

            if val > self.scroll.verticalScrollBar().maximum():
                for _ in range(int(5 * 10)):
                    if self.go:
                        time.sleep(0.1)
                    else:
                        return

                val = 0
                self.scroll.verticalScrollBar().setValue(0)

                for _ in range(int(5 * 10)):
                    if self.go:
                        time.sleep(0.1)
                    else:
                        return

            self.scroll.verticalScrollBar().setValue(val)
