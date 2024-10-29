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
