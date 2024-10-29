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
