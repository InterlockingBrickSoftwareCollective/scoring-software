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
    font-size: 16px;
}

QPushButton {
    background-color: #000000;
    color: white;
    border-radius: 4px;
    padding: 6px;
}
"""


class ScoresheetDialog(QMainWindow):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent

        # Load game metadata
        metadataPath = ResourceManager.getResourcePath("scoresheet.xml")
        self.game = ET.parse(metadataPath).getroot()
        self.tasks = {}

        # Perform connectivity check
        if not self.connectivity_check():
            QMessageBox.critical(
                self,
                "Connectivity Error",
                "Scoresheet connectivity check failed!\nCheck your Internet connection and try again,\nor use score calculator and add scores manually.",
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

        # Build ordered list of tasks for keyboard navigation
        self.ordered_tasks = []
        for mission in filter(lambda x: x.tag == "mission", self.game.iter()):
            for task in mission:
                self.ordered_tasks.append(task)

        # Track current task index for keyboard input
        self.current_task_index = 0

        # Set up keyboard event filter flag (starts disabled, enabled by pressing Enter)
        self.keyboard_mode_enabled = False

        # Window setup
        self.setWindowTitle("Scoresheet Entry")
        self.widget = QWidget()
        self.widget.setStyleSheet(sheet)

        # Parent layout, holds top bar and scoresheet image
        layout = QVBoxLayout(self.widget)

        # Top bar: Team and match selection, score display, Calculate button
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
        self.score_label.setText("")
        topbar_layout.addWidget(self.score_label)

        # Calculate Score button (stretch to fill remaining space)
        calc_button = QPushButton("Calculate Score", self)
        calc_button.clicked.connect(self.on_calculate)
        topbar_layout.addWidget(calc_button, 1)

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

        # Install event filter on widgets to intercept keyboard events
        self.team_dropdown.installEventFilter(self)
        self.match_dropdown.installEventFilter(self)
        calc_button.installEventFilter(self)

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

                    # Repaint
                    self.update_image()
                    break

    def keyPressEvent(self, event):
        """
        Qt handler for keyboard events.
        Numeric keys (0-9) select options in the current task.
        + key calls calculate.
        """
        key = event.key()

        # Handle + key to calculate
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self.on_calculate()
            return

        # Handle numeric keys 0-9
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            # Convert key to index
            digit = key - Qt.Key.Key_0

            # Check if we're within bounds of task list
            if self.current_task_index >= len(self.ordered_tasks):
                return  # Already processed all tasks

            current_task = self.ordered_tasks[self.current_task_index]
            options = list(current_task)

            # For tasks with 2 options (false/true), map 0→false, 1→true
            if len(options) == 2:
                # Find which option has value="false" and which has value="true"
                false_idx = None
                true_idx = None
                for idx, opt in enumerate(options):
                    if opt.attrib["value"] == "false":
                        false_idx = idx
                    elif opt.attrib["value"] == "true":
                        true_idx = idx

                if digit == 0 and false_idx is not None:
                    self.select_option_by_index(current_task, false_idx)
                elif digit == 1 and true_idx is not None:
                    self.select_option_by_index(current_task, true_idx)
            else:
                # For tasks with multiple numeric options, select by index
                # Find the option with value matching the digit
                for idx, opt in enumerate(options):
                    if opt.attrib["value"] == str(digit):
                        self.select_option_by_index(current_task, idx)
                        break

            return

        # Pass other keys to parent handler
        super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """
        Event filter to intercept keyboard events before they reach child widgets.
        This allows numeric keys and + to be used for scoresheet entry even when
        combo boxes or buttons have focus.
        """
        if event.type() == event.Type.KeyPress:
            key = event.key()

            if self.keyboard_mode_enabled:
                # When keyboard mode is enabled, intercept numeric keys and Enter key
                if (Qt.Key.Key_0 <= key <= Qt.Key.Key_9) or key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                    # Process the event ourselves
                    self.keyPressEvent(event)
                    return True  # Event handled, don't pass to widget
            else:
                # When not in keyboard mode, Enter key enables keyboard mode
                if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
                    self.keyboard_mode_enabled = True
                    self.update_image()  # Redraw to show current task indicator line
                    return True  # Event handled, don't pass to widget

        # Pass all other events to the widget
        return super().eventFilter(obj, event)

    def select_option_by_index(self, task, option_index):
        """
        Select an option in a task by its index.
        Used for keyboard input.
        """
        options = list(task)
        if option_index < 0 or option_index >= len(options):
            return  # Invalid index, do nothing

        selected_option = options[option_index]

        # Set the selected option as clicked
        selected_option.attrib["clicked"] = True

        # Unclick all siblings
        for sibling in filter(lambda x: x is not selected_option, task):
            sibling.attrib["clicked"] = False

        # Advance to next task BEFORE repainting
        # This ensures the indicator line moves to the next task
        self.current_task_index += 1

        # Repaint (line will now appear at the new current_task_index)
        self.update_image()

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

        # Draw current task indicator line (if keyboard mode is enabled)
        if self.keyboard_mode_enabled and self.current_task_index < len(self.ordered_tasks):
            current_task = self.ordered_tasks[self.current_task_index]

            # Check if task has x, y, width attributes (backwards compatibility)
            if "x" in current_task.attrib and "y" in current_task.attrib and "width" in current_task.attrib:
                # Get task line coordinates
                task_x = int(current_task.attrib["x"])
                task_y = int(current_task.attrib["y"])
                task_width = int(current_task.attrib["width"])

                # Scale coordinates
                scaled_x = int(task_x * self.scale_factor)
                scaled_y = int(task_y * self.scale_factor)
                scaled_width = int(task_width * self.scale_factor)

                # Draw red line for current task
                pen.setColor(Qt.GlobalColor.red)
                pen.setWidth(max(2, int(4 * self.scale_factor)))  # Slightly thinner than option rectangles
                painter.setPen(pen)
                painter.drawLine(scaled_x, scaled_y, scaled_x + scaled_width, scaled_y)

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

    def on_calculate(self):
        """
        Calculate the score represented by the current state of the scoresheet,
        present a question to submit it, and if confirmed, submit the score.
        """
        if self.team_dropdown.currentData() is None:
            QMessageBox.critical(self, "Error", "No team selected!")
            return

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
            score = ScoresheetBackend.get_score(self.tasks)
        except:
            QMessageBox.critical(
                self, "Error", "Could not calculate score! Check network connectivity."
            )
            return

        confirm = QMessageBox.question(
            self,
            "Confirm Score",
            f"Calculated score is <b>{score}</b>. Submit this score?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm == QMessageBox.StandardButton.Yes:
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

            print(f"Storing team {team_num} match {match_num} score {score}")
            team.setScore(match_num, score, str(self.tasks))

            self.parent.rerank()
            self.reset()
        else:
            self.score_label.setText(f"Score: {score}")

    def reset(self):
        """Reset scoresheet to initial state"""
        # Clear clicked state
        for option in filter(lambda x: x.tag == "option", self.game.iter()):
            option.attrib["clicked"] = False

        self.update_image()
        self.tasks = {}
        self.team_dropdown.setCurrentIndex(0)
        self.match_dropdown.setCurrentIndex(0)
        self.match_dropdown.setEnabled(False)
        self.score_label.setText("")
        self.time_elapsed = 0
        self.current_task_index = 0
        self.keyboard_mode_enabled = False
