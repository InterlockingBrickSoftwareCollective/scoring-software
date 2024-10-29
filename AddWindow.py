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

from PyQt6.QtWidgets import *

from Team import Team

sheet = """
QLabel {
    font-size: 18px;
}

QLineEdit {
    font-size: 16px;
}

QPushButton {
    background-color: #000000;
    color: #ffffff;
    border-radius: 3px;
    padding: 6px;
    font-size: 18px;
}
"""


class AddWindow(QMainWindow):
    def __init__(self, parent):
        try:
            super().__init__()

            self.parent = parent

            self.setWindowTitle("Add Team")
            self.setGeometry(100, 100, 700, 60)

            self.mainWidget = QWidget()
            self.mainWidget.setStyleSheet(sheet)

            self.mainLayout = QHBoxLayout()
            self.mainLayout.addWidget(QLabel("Team Name:"))
            self.name = QLineEdit()
            self.mainLayout.addWidget(self.name)
            self.mainLayout.addWidget(QLabel("Team Number:"))
            self.number = QLineEdit()
            self.number.returnPressed.connect(self.addTeam)
            self.mainLayout.addWidget(self.number)
            self.add = QPushButton("Add Team")
            self.add.pressed.connect(self.addTeam)
            self.mainLayout.addWidget(self.add)

            self.mainWidget.setLayout(self.mainLayout)

            self.setCentralWidget(self.mainWidget)

            self.show()
        except Exception as err:
            print(err)

    def addTeam(self):
        try:
            if len(self.name.text()) == 0 or len(self.number.text()) == 0:
                return
            team = Team(self.name.text(), int(self.number.text()))
            self.name.setText("")
            self.number.setText("")
            self.parent.addSingleTeam(team)
        except Exception as err:
            print(err)
