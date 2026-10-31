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
from ScoresheetModel import Game, IncompleteScoresheet, Task
from Team import Team

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
    """Scoresheet entry window. Opened for a particular team and match, it shows that round's
    scoresheet, if it has one, for review and correction, and the team and match can't be changed."""

    def __init__(self, main, team: Team | None = None, match: int | None = None):
        super().__init__()
        self.main = main

        root = ET.parse(ResourceManager.getResourcePath("scoresheet.xml")).getroot()
        self.game = Game.from_xml(root)

        # (team number, match) when opened for a particular round
        self.round: tuple[int, int] | None = None
        # Selections as of the last load or save, to tell whether there are changes to lose
        self.saved_selections: dict[str, str] = {}
        # Keyboard entry starts disabled, and is enabled by pressing Enter
        self.keyboard_mode_enabled = False
        self.current_task_index = 0
        self.time_elapsed = 0

        # Reviewing an existing scoresheet doesn't need the backend until the score is recalculated
        reviewing = team is not None and team.scoresheets[match - 1] is not None
        if not reviewing and not self.connectivity_check():
            QMessageBox.critical(
                self,
                "Connectivity Error",
                "Scoresheet connectivity check failed!\nCheck your Internet connection and try again,\nor use score calculator and add scores manually.",
            )
            self.close()
            return

        self.widget = QWidget()
        self.widget.setStyleSheet(sheet)

        # Parent layout, holds top bar and scoresheet image
        layout = QVBoxLayout(self.widget)

        # Top bar: Team and match selection, score display, Calculate button
        topbar_layout = QHBoxLayout()

        topbar_layout.addWidget(QLabel("Team:"))
        self.team_dropdown = QComboBox(self.widget)
        self.team_dropdown.currentIndexChanged.connect(self.on_team_select)
        topbar_layout.addWidget(self.team_dropdown)

        topbar_layout.addWidget(QLabel("Match:"))
        self.match_dropdown = QComboBox(self.widget)
        topbar_layout.addWidget(self.match_dropdown)

        self.score_label = QLabel(self.widget)
        self.score_label.setFixedWidth(150)
        topbar_layout.addWidget(self.score_label)

        # Calculate Score button (stretch to fill remaining space)
        calc_button = QPushButton("Calculate Score", self)
        calc_button.clicked.connect(self.on_calculate)
        topbar_layout.addWidget(calc_button, 1)

        # Label to display the image
        self.pixmap_label = QLabel(self.widget)
        self.pixmap_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.pixmap_label.setScaledContents(False)
        self.pixmap_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pixmap_label.setMinimumSize(100, 100)  # Allow shrinking below original size

        image = root.find("image")
        if image is None or not image.text:
            raise IOError("No graphic contained in scoresheet definition file!")
        self.original_pixmap = QPixmap()  # Original pixmap to preserve
        self.original_pixmap.loadFromData(base64.b64decode(image.text.strip()))
        if self.original_pixmap.isNull():
            raise IOError("Could not load scoresheet graphic!")

        # Track scale factor for coordinate transformation
        self.scale_factor = 1.0
        self.scaled_pixmap = self.original_pixmap.copy()

        layout.addLayout(topbar_layout)
        layout.addWidget(self.pixmap_label)
        self.setCentralWidget(self.widget)

        # Intercept keyboard events on child widgets
        self.team_dropdown.installEventFilter(self)
        self.match_dropdown.installEventFilter(self)
        calc_button.installEventFilter(self)

        if team is None:
            self.reset()
        else:
            self.show_round(team, match)

        # Move a little bit off the main window
        self.show()
        self.raise_()
        self.activateWindow()
        self.move(self.main.geometry().x() + 50, self.main.geometry().y() + 50)

        # Set initial window size to 95% of smallest screen dimension
        screen = self.screen().availableGeometry()
        target_size = int(0.95 * min(screen.width(), screen.height()))

        # Calculate window size maintaining image aspect ratio
        img_aspect_ratio = self.original_pixmap.width() / self.original_pixmap.height()
        if img_aspect_ratio > 1:  # Image is wider than tall
            # Add space for UI elements
            self.resize(target_size, int(target_size / img_aspect_ratio) + 50)
        else:  # Image is taller than wide
            self.resize(int(target_size * img_aspect_ratio), target_size)

        # Start elapsed timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.timer.start(1000)

    def open_for(self, team: Team, match: int):
        """Switch to a team's match, after confirming that unsaved selections can be discarded."""
        if self.has_unsaved_changes():
            confirm = QMessageBox.question(
                self,
                "Discard Changes",
                f"Discard the changes to the scoresheet being entered,\nand open team {team.number}'s match {match} instead?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm == QMessageBox.StandardButton.No:
                self.raise_()
                self.activateWindow()
                return

        self.show_round(team, match)
        self.raise_()
        self.activateWindow()

    def show_round(self, team: Team, match: int):
        """Show a team's match, with its scoresheet if it has one, and lock team and match selection."""
        self.round = (team.number, match)
        self.populate_teams()
        self.team_dropdown.setCurrentIndex(self.team_dropdown.findData(team.number))
        self.match_dropdown.setCurrentIndex(self.match_dropdown.findData(match))
        self.team_dropdown.setEnabled(False)
        self.match_dropdown.setEnabled(False)

        scoresheet = team.scoresheets[match - 1]
        self.game.load(scoresheet)
        self.saved_selections = self.game.selections()
        self.score_label.setText(f"Stored score: {team.scores[match - 1]}" if scoresheet is not None else "")
        self.restart_entry()

    def reset(self):
        """Reset to a blank scoresheet, with any team and match selectable."""
        self.round = None
        self.populate_teams()
        self.team_dropdown.setEnabled(True)
        self.game.clear()
        self.saved_selections = {}
        self.score_label.setText("")
        self.restart_entry()

    def populate_teams(self):
        # Rebuilt each time, so teams added since the window opened can be selected
        self.team_dropdown.clear()
        self.team_dropdown.addItem("", None)
        for team in sorted(self.main.teams):
            self.team_dropdown.addItem(f"{team.number}", team.number)

    def restart_entry(self):
        self.keyboard_mode_enabled = False
        self.current_task_index = 0
        self.time_elapsed = 0
        self.update_title()
        self.update_image()

    def has_unsaved_changes(self) -> bool:
        return self.game.selections() != self.saved_selections

    def mousePressEvent(self, event):
        """Toggle the option clicked, unselecting its task's other options."""
        if (hit := self.game.option_at(self.to_image_point(event.position().toPoint()))) is not None:
            task, option = hit
            task.toggle(option)
            self.update_image()

    def to_image_point(self, window_point: QPoint) -> QPoint:
        """Convert a point in window coordinates to original scoresheet graphic coordinates."""
        label_point = self.pixmap_label.mapFrom(self, window_point)

        # Account for the image being centered within the label
        x_offset = (self.pixmap_label.width() - int(self.original_pixmap.width() * self.scale_factor)) // 2
        y_offset = (self.pixmap_label.height() - int(self.original_pixmap.height() * self.scale_factor)) // 2

        return QPoint(int((label_point.x() - x_offset) / self.scale_factor),
                      int((label_point.y() - y_offset) / self.scale_factor))

    def keyPressEvent(self, event):
        """
        Qt handler for keyboard events.
        Enter enables keyboard mode, or calculates if already enabled.
        Numeric keys (0-9) select options in the current task when in keyboard mode.

        Also reached directly (not via eventFilter) when no child widget has
        focus, e.g. on macOS where combo boxes and buttons don't take focus.
        """
        match event.key():
            case Qt.Key.Key_Return | Qt.Key.Key_Enter:
                if not self.keyboard_mode_enabled:
                    self.keyboard_mode_enabled = True
                    self.update_image()  # Redraw to show current task indicator line
                else:
                    self.on_calculate()
            case key if self.keyboard_mode_enabled and Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
                if self.current_task_index < len(self.game.tasks):
                    task = self.game.tasks[self.current_task_index]
                    if (option := task.option_for_digit(key - Qt.Key.Key_0)) is not None:
                        task.selected = option
                        # Advance to the next task before repainting, so the indicator line moves
                        self.current_task_index += 1
                        self.update_image()
            case _:
                super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        """
        Event filter to intercept keyboard events before they reach child widgets.
        This allows numeric keys and Enter to be used for scoresheet entry even when
        combo boxes or buttons have focus.
        """
        if event.type() == event.Type.KeyPress:
            key = event.key()
            is_enter = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            is_digit = Qt.Key.Key_0 <= key <= Qt.Key.Key_9

            # Always intercept Enter; intercept numeric keys only in keyboard mode
            if is_enter or (self.keyboard_mode_enabled and is_digit):
                self.keyPressEvent(event)
                return True  # Event handled, don't pass to widget

        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        """Rescale the scoresheet image to fit the window, and repaint."""
        super().resizeEvent(event)

        # Skip if UI hasn't been fully initialized yet
        if not hasattr(self, "scaled_pixmap"):
            return

        self.scale_factor = min(self.pixmap_label.width() / self.original_pixmap.width(),
                               self.pixmap_label.height() / self.original_pixmap.height())
        self.scaled_pixmap = self.original_pixmap.scaled(
            self.original_pixmap.size() * self.scale_factor,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.update_image()

    def connectivity_check(self) -> bool:
        """Check whether the scoresheet backend currently has connectivity."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Connectivity Check")
        msg.setText("Checking scoresheet connectivity...")
        msg.setStandardButtons(QMessageBox.StandardButton.NoButton)
        # Native macOS alerts always have a button and can't be dismissed programmatically
        msg.setOption(QMessageBox.Option.DontUseNativeDialog)
        msg.setModal(True)
        msg.show()
        QApplication.processEvents()  # Force the dialog to appear immediately

        try:
            ScoresheetBackend.get_score(self.game.placeholder_scoresheet())
            result = True
        except Exception:
            # Any exception is a failed connectivity check
            result = False

        # Ensure the dialog is properly cleaned up. Use hide() rather than close():
        # QMessageBox ignores close() when it has no escape button, which left the
        # dialog up until deleteLater() ran after the scoresheet was shown, and
        # macOS then re-activated the main window over the scoresheet.
        msg.hide()
        msg.deleteLater()

        return result

    def update_timer(self):
        self.time_elapsed += 1
        self.update_title()

    def update_title(self):
        """Show what's being entered and how long it's taken, in m:ss format."""
        title = "Scoresheet Entry" if self.round is None else "Scoresheet: Team {}, Match {}".format(*self.round)
        minutes, seconds = divmod(self.time_elapsed, 60)
        self.setWindowTitle(f"{title} ({minutes:01d}:{seconds:02d})")

    def scaled(self, rect: QRect) -> QRect:
        return QRect(int(rect.x() * self.scale_factor), int(rect.y() * self.scale_factor),
                     int(rect.width() * self.scale_factor), int(rect.height() * self.scale_factor))

    def update_image(self):
        """Repaint scoresheet to reflect the current selections."""
        pixmap = self.scaled_pixmap.copy()
        painter = QPainter(pixmap)
        pen = QPen(Qt.GlobalColor.red)

        pen.setWidth(max(1, int(7 * self.scale_factor)))
        painter.setPen(pen)
        for option in self.game.selected_options():
            painter.drawRect(self.scaled(option.rect))

        # Draw current task indicator line (if keyboard mode is enabled)
        if self.keyboard_mode_enabled and self.current_task_index < len(self.game.tasks):
            if (line := self.game.tasks[self.current_task_index].line) is not None:
                x, y, width = (int(n * self.scale_factor) for n in line)
                pen.setWidth(max(2, int(4 * self.scale_factor)))  # Slightly thinner than option rectangles
                painter.setPen(pen)
                painter.drawLine(x, y, x + width, y)

        painter.end()
        self.pixmap_label.setPixmap(pixmap)

    def on_team_select(self):
        """On team selection, update the match dropdown"""
        self.match_dropdown.clear()
        team = self.main.fetchTeam(self.team_dropdown.currentData())

        if team is None:
            self.match_dropdown.setEnabled(False)
            return

        for match, score in enumerate(team.scores, start=1):
            self.match_dropdown.addItem(f"{match}" if score is None else f"{match} ({score})", match)

        # Default to the first match without a score
        first_unplayed = next((i for i, score in enumerate(team.scores) if score is None), None)
        if first_unplayed is not None:
            self.match_dropdown.setCurrentIndex(first_unplayed)

        self.match_dropdown.setEnabled(self.round is None)

    def on_calculate(self):
        """
        Calculate the score represented by the current state of the scoresheet,
        present a question to submit it, and if confirmed, submit the score.
        """
        team_num = self.team_dropdown.currentData()
        match = self.match_dropdown.currentData()
        if team_num is None:
            QMessageBox.critical(self, "Error", "No team selected!")
            return

        try:
            tasks = self.game.scoresheet()
        except IncompleteScoresheet as err:
            QMessageBox.critical(self, "Error", f"{err}!")
            return

        try:
            score = ScoresheetBackend.get_score(tasks)
        except Exception:
            QMessageBox.critical(self, "Error", "Could not calculate score! Check network connectivity.")
            return

        team = self.main.fetchTeam(team_num)
        if team is None:
            QMessageBox.critical(self, "Error", f"Team {team_num} no longer exists!")
            return

        if (previous := team.scores[match - 1]) is None:
            question = f"Calculated score is <b>{score}</b>.<br>Submit this score?"
            default = QMessageBox.StandardButton.Yes
        else:
            question = f"Calculated score is <b>{score}</b>.<br>Replace previous score of {previous}?"
            # Replacing is what a scoresheet opened for its round is for, but otherwise may be a mistake
            default = QMessageBox.StandardButton.Yes if self.round else QMessageBox.StandardButton.No

        confirm = QMessageBox.question(
            self, "Confirm Score", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, default)
        if confirm != QMessageBox.StandardButton.Yes:
            self.score_label.setText(f"Score: {score}")
            return

        print(f"Storing team {team_num} match {match} score {score}")
        team.setScore(match, score, tasks)
        self.main.rerank()

        if self.round is None:
            self.reset()
        else:
            self.saved_selections = self.game.selections()
            self.close()
