"""
EventInfoDialog.py: Event name and date shown on the themed audience display

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

from typing import Optional

from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout


def effectiveEventName(enteredName: str, syncName: Optional[str]) -> str:
    """The name to show: the one the operator entered, or else the score reflector's."""
    return enteredName.strip() or (syncName or "").strip()


class EventInfoDialog(QDialog):
    """Asks for the event name and date. When sync is set up, the name can be left blank
    to use the score reflector's event name."""

    def __init__(self, parent, name: str, date: str, syncName: Optional[str]):
        super().__init__(parent)
        self.setWindowTitle("Event Name and Date")

        self.nameEdit = QLineEdit(name)
        self.dateEdit = QLineEdit(date)
        self.dateEdit.setPlaceholderText("e.g. Saturday, January 16, 2027")
        if syncName:
            self.nameEdit.setPlaceholderText(syncName)
            hint = QLabel(f"Leave the name blank to use the score reflector's name, \"{syncName}\".")
        else:
            hint = QLabel("Shown on the themed audience display.")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Event name", self.nameEdit)
        form.addRow("Date", self.dateEdit)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setMinimumWidth(480)

    def name(self) -> str:
        return self.nameEdit.text().strip()

    def date(self) -> str:
        return self.dateEdit.text().strip()
