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

import xml.etree.ElementTree as ET

from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QPainter, QPen, QPixmap
from PyQt6.QtWidgets import *

import EventHub


class ScoresheetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent

        # Load game metadata
        self.game = ET.parse("submerged.xml").getroot()

        # Initialize QRects and clicked status
        for element in self.game.iter():
            if element.tag == "option":
                x, y, w, h = int(element.attrib["x"]), int(element.attrib["y"]), int(element.attrib["width"]), int(element.attrib["height"])
                element.attrib["rect"] = QRect(x, y, w, h)
                element.attrib["clicked"] = False

        # Layout to hold image and submit button
        layout = QVBoxLayout(self)

        # Label to display the image
        self.image_label = QLabel(self)
        self.pixmap = QPixmap("scoresheet-75.png")
        self.original_pixmap = QPixmap("scoresheet-75.png")  # Original pixmap to preserve
        self.image_label.setPixmap(self.pixmap)
        self.image_label.setFixedSize(self.pixmap.size())
        layout.addWidget(self.image_label)

        # Team dropdown
        teamSelections = [""]
        teamSelections.extend(map(lambda x: str(x.number), sorted(parent.teams, key=lambda x: x.number, reverse=False)))
        self.team = QComboBox(self)
        self.team.addItems(teamSelections)
        self.team.setGeometry(348, 49, 60, 18)

        # Match dropdown
        self.match = QComboBox(self)
        self.match.addItems(["", "1", "2", "3"])
        self.match.setGeometry(410, 49, 59, 18)

        # Score label
        self.score_label = QLabel(self)
        self.score_label.setText("Score: uncalculated")
        layout.addWidget(self.score_label)

        # Calculate button
        self.calculate_button = QPushButton("Calculate", self)
        self.calculate_button.clicked.connect(self.on_calculate)
        layout.addWidget(self.calculate_button)

        # Submit button
        self.submit_button = QPushButton("Submit", self)
        self.submit_button.clicked.connect(self.on_submit)
        layout.addWidget(self.submit_button)

        self.setLayout(layout)

        self.tasks = {}
        self.score = None

    def mousePressEvent(self, event):
        # Capture the position of the mouse click
        click_pos = event.position().toPoint() - QPoint(12, 12)

        # Check if the click is inside any of the rectangles
        # Python XML parser doesn't have a "get siblings" or "get parent" method,
        # so get the task first then get its children in separate loops
        for task in filter(lambda x: x.tag == "task", self.game.iter()):
            for option in task:
                if option.attrib["rect"].contains(click_pos):
                    # Toggle clicked state
                    option.attrib['clicked'] = not option.attrib['clicked']

                    # Set all siblings to "unclicked"
                    for sibling in filter(lambda x: x is not option, task):
                        sibling.attrib['clicked'] = False

                    # Repaint
                    self.update_image()
                    break

    def update_image(self):
        # Create a copy of the original pixmap to draw on
        pixmap_copy = self.original_pixmap.copy()

        # Use QPainter to draw rectangles on the pixmap
        painter = QPainter(pixmap_copy)
        pen = QPen(Qt.PenStyle.SolidLine)
        for option in filter(lambda x: x.tag == "option", self.game.iter()):
            if option.attrib["clicked"]:
                pen.setColor(Qt.GlobalColor.red)  # Set pen color to red if clicked
                pen.setWidth(5)
            else:
                pen.setColor(Qt.GlobalColor.transparent)  # Transparent for unclicked
            painter.setPen(pen)
            painter.drawRect(option.attrib['rect'])
        painter.end()

        # Set the updated pixmap back to the QLabel
        self.image_label.setPixmap(pixmap_copy)

    def on_calculate(self):
        self.tasks = {}
        for mission in filter(lambda x: x.tag == "mission", self.game.iter()):
            for task in mission:
                json_key = task.attrib["eh_task_name"]
                json_value = None

                for opt in task:
                    if opt.attrib["clicked"] is True:
                        json_value = opt.attrib["value"]

                if json_value is None:
                    mission_str = mission.attrib.get('number', mission.attrib['name'])
                    QMessageBox.critical(self, "Error", f"Missing value in mission {mission_str}!")
                    return

                self.tasks[json_key] = json_value

        try:
            self.score = EventHub.get_score(self.tasks)
            QMessageBox.information(self, "Score", f"Calculated score is {self.score}")
            self.score_label.setText(f"Score: {self.score}")
        except:
            QMessageBox.warning(self, "Warning", "Could not contact EventHub for score!")

    def on_submit(self):
        if self.score == None:
            QMessageBox.critical(self, "Error", "Score has not yet been calculated!")
        elif self.team.currentText() == "":
            QMessageBox.critical(self, "Error", "No team selected!")
        elif self.match.currentText() == "":
            QMessageBox.critical(self, "Error", "No match selected!")
        else:
            print(f"Storing team {self.team.currentText()} match {self.match.currentText()} score {self.score}")
            team = self.parent.fetchTeam(int(self.team.currentText()))
            team.setScore(int(self.match.currentText()), self.score, str(self.tasks))

            self.parent.rerank()
            self.accept()