"""
Scoresheet.py: Scoresheet entry logic

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

import base64
import importlib.util
import os
import sys
import xml.etree.ElementTree as ET

from PyQt6.QtCore import QPoint, QRect, Qt, QTimer
from PyQt6.QtGui import QPainter, QPen, QPixmap
from PyQt6.QtWidgets import *

import ResourceManager

# Load ScoresheetBackend from resource pack
scoresheet_backend_path = ResourceManager.getResourcePath("ScoresheetBackend.py")
if not os.path.exists(scoresheet_backend_path):
    raise FileNotFoundError(
        f"ScoresheetBackend module not found in resource pack at {scoresheet_backend_path}"
    )

spec = importlib.util.spec_from_file_location(
    "ScoresheetBackend", scoresheet_backend_path
)
if spec is None or spec.loader is None:
    raise ImportError(
        f"Failed to load ScoresheetBackend module from {scoresheet_backend_path}"
    )

ScoresheetBackend = importlib.util.module_from_spec(spec)
sys.modules["ScoresheetBackend"] = ScoresheetBackend
spec.loader.exec_module(ScoresheetBackend)

sheet = """
QComboBox {
    font-size: 12px;
}
"""


class ScoresheetDialog(QMainWindow):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent

        # Load game metadata
        metadataPath = ResourceManager.getResourcePath("scoresheet.xml")
        self.game = ET.parse(metadataPath).getroot()
        self.tasks = {}
        self.score = None

        # Perform connectivity check
        if not self.connectivity_check():
            QMessageBox.critical(
                self, "Connectivity Error", "Scoresheet connectivity check failed!\nCheck your Internet connection and try again,\nor use score calculator and add scores manually."
            )
            self.close()
            return

        # Initialize QRects and clicked status
        for element in self.game.iter():
            if element.tag == "option":
                x, y, w, h = (
                    int(element.attrib["x"]),
                    int(element.attrib["y"]),
                    int(element.attrib["width"]),
                    int(element.attrib["height"]),
                )
                element.attrib["rect"] = QRect(x, y, w, h)
                element.attrib["clicked"] = False

        # Window setup
        self.setWindowTitle("Scoresheet Entry")
        self.widget = QWidget()
        self.widget.setStyleSheet(sheet)

        # Parent layout, holds top bar and submit button
        layout = QVBoxLayout(self.widget)

        # Top bar: Team and match selection, score display, Calculate/Submit button
        topbar_layout = QHBoxLayout()

        # Team selection
        topbar_layout.addWidget(QLabel("Team:"))
        self.team_dropdown = QComboBox(self.widget)
        self.team_dropdown.addItem("", None)
        for team in sorted(parent.teams):
            self.team_dropdown.addItem(f"{team.number}", team.number)
        self.team_dropdown.currentIndexChanged.connect(self.on_team_select)
        topbar_layout.addWidget(self.team_dropdown)

        # Match selection
        topbar_layout.addWidget(QLabel("Match:"))
        self.match_dropdown = QComboBox(self.widget)
        self.match_dropdown.setEnabled(False)
        topbar_layout.addWidget(self.match_dropdown)

        # Score label
        self.score_label = QLabel(self.widget)
        self.score_label.setFixedWidth(150)
        self.score_label.setText("Score: uncalculated")
        topbar_layout.addWidget(self.score_label)

        # Calculate/Submit button (stretch to fill remaining space)
        self.calc_submit_button = QPushButton("Calculate", self)
        self.calc_submit_button.clicked.connect(self.on_calc_submit)
        topbar_layout.addWidget(self.calc_submit_button, 1)  # stretch factor of 1

        # Label to display the image
        self.pixmap_label = QLabel(self.widget)
        self.pixmap_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.pixmap_label.setScaledContents(False)

        # Load image data from element
        graphic_base64_element = self.game.find("image")
        if graphic_base64_element is None or not graphic_base64_element.text:
            raise IOError("No graphic contained in scoresheet definition file!")

        graphic_data = base64.b64decode(graphic_base64_element.text.strip())
        self.original_pixmap = QPixmap()
        self.original_pixmap.loadFromData(graphic_data)  # Original pixmap to preserve
        if self.original_pixmap.isNull():
            raise IOError("Could not load scoresheet graphic!")

        self.pixmap_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pixmap_label.setMinimumSize(
            100, 100
        )  # Allow shrinking below original size

        # Free up memory and reduce size of game XML object
        graphic_base64_element.clear()
        del graphic_base64_element
        del graphic_data

        # Track scale factor for coordinate transformation
        self.scale_factor = 1.0
        self.scaled_pixmap = self.original_pixmap.copy()
        self.resizing = False  # Flag to prevent recursive resize events

        # Assemble together
        layout.addLayout(topbar_layout)
        layout.addWidget(self.pixmap_label)
        self.widget.setLayout(layout)
        self.setCentralWidget(self.widget)

        # Move a little bit off the parent window
        self.show()
        self.move(self.parent.geometry().x() + 50, self.parent.geometry().y() + 50)

        # # Set initial window size to 95% of smallest screen dimension
        screen = self.screen().availableGeometry()
        target_size = int(0.95 * min(screen.width(), screen.height()))

        # Calculate window size maintaining image aspect ratio
        img_aspect_ratio = self.original_pixmap.width() / self.original_pixmap.height()

        if img_aspect_ratio > 1:  # Image is wider than tall
            initial_width = target_size
            # Add space for UI elements
            initial_height = int(target_size / img_aspect_ratio) + 50
        else:  # Image is taller than wide
            initial_height = target_size
            initial_width = int(target_size * img_aspect_ratio)

        self.resize(initial_width, initial_height)

        # Start elapsed timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.time_elapsed = 0
        self.timer.start(1000)

    def mousePressEvent(self, event):
        """
        Qt handler for mouse press events.
        Check if an option within a mission task is clicked; if so, unclick its siblings, then repaint scoresheet.
        """
        # Capture the position of the mouse click relative to the image label
        click_pos = self.pixmap_label.mapFrom(self, event.position().toPoint())

        # Account for the centered image within the label
        label_width = self.pixmap_label.width()
        label_height = self.pixmap_label.height()
        scaled_img_width = int(self.original_pixmap.width() * self.scale_factor)
        scaled_img_height = int(self.original_pixmap.height() * self.scale_factor)

        # Calculate the offset due to centering
        x_offset = (label_width - scaled_img_width) // 2
        y_offset = (label_height - scaled_img_height) // 2

        # Adjust click position to image coordinates
        image_x = click_pos.x() - x_offset
        image_y = click_pos.y() - y_offset

        # Convert to original image coordinates by dividing by scale factor
        original_x = int(image_x / self.scale_factor)
        original_y = int(image_y / self.scale_factor)
        original_click_pos = QPoint(original_x, original_y)

        # Check if the click is inside any of the rectangles
        # Python XML parser doesn't have a "get siblings" or "get parent" method,
        # so get the task first then get its children in separate loops
        for task in filter(lambda x: x.tag == "task", self.game.iter()):
            for option in task:
                if option.attrib["rect"].contains(original_click_pos):
                    # Toggle clicked state
                    option.attrib["clicked"] = not option.attrib["clicked"]

                    # Set all siblings to "unclicked"
                    for sibling in filter(lambda x: x is not option, task):
                        sibling.attrib["clicked"] = False

                    # Reset score, in case someone hit Calculate and then edited
                    if self.score is not None:
                        self.score = None
                        self.calc_submit_button.setText("Calculate")

                    # Repaint
                    self.update_image()
                    break

    def resizeEvent(self, event):
        """
        Qt handler for window resize events.
        Recalculate scoresheet image size and repaint.
        """
        super().resizeEvent(event)

        # Skip if UI hasn't been fully initialized yet
        if not hasattr(self, "pixmap_label") or not hasattr(self, "original_pixmap"):
            return

        # Get the actual size of the image label widget
        label_width = self.pixmap_label.width()
        label_height = self.pixmap_label.height()

        # Calculate scale factor while maintaining aspect ratio
        width_scale = label_width / self.original_pixmap.width()
        height_scale = label_height / self.original_pixmap.height()
        self.scale_factor = min(width_scale, height_scale)

        # Scale the pixmap
        scaled_size = self.original_pixmap.size() * self.scale_factor
        self.scaled_pixmap = self.original_pixmap.scaled(
            scaled_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        # Update the image with current selections
        self.update_image()

    def connectivity_check(self):
        """Check whether the scoresheet backend currently has connectivity."""
        # Construct blank scoresheet for backend to check
        tasks = {}
        for mission in filter(lambda x: x.tag == "mission", self.game.iter()):
            for task in mission:
                # Always get the first option just to provide something valid to the backend
                json_key = task.attrib["eh_task_name"]
                json_value = task[0].attrib["value"]
                tasks[json_key] = json_value

        msg = QMessageBox(self)
        msg.setWindowTitle("Connectivity Check")
        msg.setText("Checking scoresheet connectivity...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        msg.setModal(True)
        msg.show()
        QApplication.processEvents()  # Force the dialog to appear immediately

        # Submit blank scoresheet
        result = False
        try:
            ScoresheetBackend.get_score(tasks)
            result = True
        except:
            # Any exception is a failed connectivity check
            pass

        # Ensure the dialog is properly cleaned up
        msg.close()
        msg.deleteLater()

        return result

    def update_timer(self):
        """Update elapsed time for current scoresheet."""
        self.time_elapsed += 1
        # Convert remaining time to m:ss format
        minutes = self.time_elapsed // 60
        seconds = self.time_elapsed % 60
        timeStr = f"{minutes:01d}:{seconds:02d}"
        self.setWindowTitle(f"Scoresheet Entry ({timeStr})")

    def update_image(self):
        """Repaint scoresheet to reflect current mission states."""
        # Create a copy of the scaled pixmap to draw on
        pixmap_copy = self.scaled_pixmap.copy()

        # Use QPainter to draw rectangles on the pixmap
        painter = QPainter(pixmap_copy)
        pen = QPen(Qt.PenStyle.SolidLine)
        for option in filter(lambda x: x.tag == "option", self.game.iter()):
            if option.attrib["clicked"]:
                pen.setColor(Qt.GlobalColor.red)  # Set pen color to red if clicked
                pen.setWidth(max(1, int(7 * self.scale_factor)))  # Scale pen width
            else:
                pen.setColor(Qt.GlobalColor.transparent)  # Transparent for unclicked
            painter.setPen(pen)

            # Scale the rectangle coordinates
            original_rect = option.attrib["rect"]
            scaled_rect = QRect(
                int(original_rect.x() * self.scale_factor),
                int(original_rect.y() * self.scale_factor),
                int(original_rect.width() * self.scale_factor),
                int(original_rect.height() * self.scale_factor),
            )
            painter.drawRect(scaled_rect)
        painter.end()

        # Set the updated pixmap back to the QLabel
        self.pixmap_label.setPixmap(pixmap_copy)

    def on_team_select(self):
        """On team selection, update the match dropdown"""
        self.match_dropdown.clear()
        team_num = self.team_dropdown.currentData()
        team = self.parent.fetchTeam(team_num)

        if team is None:
            self.match_dropdown.setEnabled(False)
            return

        first_nonempty_score_idx = 1e3
        for idx, score in enumerate(team.scores):
            match_num = idx + 1
            if score == -1:
                self.match_dropdown.addItem(f"{match_num}", match_num)
                first_nonempty_score_idx = min(first_nonempty_score_idx, idx)
            else:
                self.match_dropdown.addItem(f"{match_num} ({score})", match_num)

        if first_nonempty_score_idx != 1e3:
            self.match_dropdown.setCurrentIndex(first_nonempty_score_idx)

        self.match_dropdown.setEnabled(True)

    def on_calc_submit(self):
        """Handle clicks on the combined Calculate/Submit button."""
        if self.score is None:
            self.calculate()
            # After calculation, should have a score, otherwise something failed
            if self.score is not None:
                self.calc_submit_button.setText("Submit")
        else:
            self.submit()

    def calculate(self):
        """Calculate the score represented by the current state of the scoresheet."""
        self.tasks = {}
        for mission in filter(lambda x: x.tag == "mission", self.game.iter()):
            for task in mission:
                json_key = task.attrib["eh_task_name"]
                json_value = None

                for opt in task:
                    if opt.attrib["clicked"] is True:
                        json_value = opt.attrib["value"]

                if json_value is None:
                    mission_str = mission.attrib.get("number", mission.attrib["name"])
                    QMessageBox.critical(
                        self, "Error", f"Missing value in mission {mission_str}!"
                    )
                    return

                self.tasks[json_key] = json_value

        try:
            self.score = ScoresheetBackend.get_score(self.tasks)
            QMessageBox.information(self, "Score", f"Calculated score is {self.score}")
            self.score_label.setText(f"Score: {self.score}")
        except:
            QMessageBox.critical(
                self, "Error", "Could not contact ScoresheetBackend for score!"
            )

    def submit(self):
        """Submit a calculated scoresheet."""
        if self.score is None:
            QMessageBox.critical(self, "Error", "Score has not yet been calculated!")
        elif self.team_dropdown.currentData() is None:
            QMessageBox.critical(self, "Error", "No team selected!")
        else:
            team_num = self.team_dropdown.currentData()
            match_num = self.match_dropdown.currentData()

            team = self.parent.fetchTeam(team_num)

            if team.scores[match_num - 1] != -1:
                confirm = QMessageBox.question(
                    self,
                    "Confirmation",
                    f"Team {team_num} already has a score for match {match_num};\nare you sure you want to overwrite it?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if confirm == QMessageBox.StandardButton.No:
                    return

            print(f"Storing team {team_num} match {match_num} score {self.score}")
            team.setScore(match_num, self.score, str(self.tasks))

            self.parent.rerank()
            self.reset()

    def reset(self):
        """Reset scoresheet to initial state"""
        # Clear clicked state
        for option in filter(lambda x: x.tag == "option", self.game.iter()):
            option.attrib["clicked"] = False

        self.update_image()
        self.score = None
        self.tasks = {}
        self.team_dropdown.setCurrentIndex(0)
        self.match_dropdown.setCurrentIndex(0)
        self.match_dropdown.setEnabled(False)
        self.score_label.setText("Score: uncalculated")
        self.calc_submit_button.setText("Calculate")
        self.time_elapsed = 0
