from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QApplication
from PyQt6.QtCore import Qt
from datetime import datetime
import Substrate


class CycleTimeReportDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Cycle Time Report")
        self.setFixedSize(600, 500)

        # Main layout
        mainLayout = QVBoxLayout()

        # Create table widget
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Match #", "Start Time", "Cycle Time"])

        # Set column widths
        self.table.setColumnWidth(0, 100)
        self.table.setColumnWidth(1, 200)
        self.table.setColumnWidth(2, 200)

        # Make table read-only
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        # Populate table with data
        self.populateTable()

        # Add table to layout
        mainLayout.addWidget(self.table)

        # Create button layout
        buttonLayout = QHBoxLayout()

        # Copy button
        copyButton = QPushButton("Copy to Clipboard")
        copyButton.clicked.connect(self.copyToClipboard)
        copyButton.setFixedWidth(150)

        # Close button
        closeButton = QPushButton("Close")
        closeButton.clicked.connect(self.close)
        closeButton.setFixedWidth(100)

        buttonLayout.addStretch()
        buttonLayout.addWidget(copyButton)
        buttonLayout.addWidget(closeButton)

        mainLayout.addLayout(buttonLayout)

        self.setLayout(mainLayout)

    def populateTable(self):
        """Query database and populate table with cycle time data"""
        try:
            # Query for all match_start entries, getting the latest timestamp for each match
            Substrate._cur.execute('''
                SELECT message, MAX(timestamp) as latest_timestamp
                FROM log
                WHERE tag = 'match_start'
                GROUP BY message
                ORDER BY CAST(message AS INTEGER)
            ''')

            matches = Substrate._cur.fetchall()

            # Set row count
            self.table.setRowCount(len(matches))

            previous_timestamp = None

            for row, (match_num, timestamp) in enumerate(matches):
                # Match number
                matchItem = QTableWidgetItem(str(match_num))
                matchItem.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 0, matchItem)

                # Start time (HH:MM am/pm format)
                dt = datetime.fromtimestamp(timestamp)
                start_time_str = dt.strftime("%I:%M %p").lstrip('0')  # Remove leading zero from hour
                startTimeItem = QTableWidgetItem(start_time_str)
                startTimeItem.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 1, startTimeItem)

                # Cycle time
                if previous_timestamp is None:
                    # First match has no cycle time
                    cycleTimeItem = QTableWidgetItem("N/A")
                else:
                    # Calculate cycle time in seconds
                    cycle_seconds = int(timestamp - previous_timestamp)
                    minutes = cycle_seconds // 60
                    seconds = cycle_seconds % 60
                    cycle_time_str = f"{minutes}m{seconds:02d}s"
                    cycleTimeItem = QTableWidgetItem(cycle_time_str)

                cycleTimeItem.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, 2, cycleTimeItem)

                previous_timestamp = timestamp

        except Exception as e:
            print(f"Error populating cycle time report: {e}")

    def copyToClipboard(self):
        """Copy the cycle time report as plaintext to clipboard"""
        try:
            # Build plaintext report
            lines = []
            lines.append("Cycle Time Report")
            lines.append("=" * 60)
            lines.append(f"{'Match':<10}{'Start Time':<20}{'Cycle Time':<20}")
            lines.append("-" * 60)

            # Query data again for plaintext export
            Substrate._cur.execute('''
                SELECT message, MAX(timestamp) as latest_timestamp
                FROM log
                WHERE tag = 'match_start'
                GROUP BY message
                ORDER BY CAST(message AS INTEGER)
            ''')

            matches = Substrate._cur.fetchall()
            previous_timestamp = None

            for match_num, timestamp in matches:
                # Format start time
                dt = datetime.fromtimestamp(timestamp)
                start_time_str = dt.strftime("%I:%M %p").lstrip('0')

                # Calculate cycle time
                if previous_timestamp is None:
                    cycle_time_str = "N/A"
                else:
                    cycle_seconds = int(timestamp - previous_timestamp)
                    minutes = cycle_seconds // 60
                    seconds = cycle_seconds % 60
                    cycle_time_str = f"{minutes}m{seconds:02d}s"

                lines.append(f"{match_num:<10}{start_time_str:<20}{cycle_time_str:<20}")
                previous_timestamp = timestamp

            lines.append("=" * 60)

            # Copy to clipboard
            report_text = "\n".join(lines)
            QApplication.clipboard().setText(report_text)

            # Update button text temporarily to show success
            sender = self.sender()
            if sender:
                original_text = sender.text()
                sender.setText("Copied!")
                sender.setEnabled(False)

                # Reset after 1 second
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(1000, lambda: (sender.setText(original_text), sender.setEnabled(True)))

        except Exception as e:
            print(f"Error copying to clipboard: {e}")


def show(parent):
    """Show the cycle time report dialog"""
    dialog = CycleTimeReportDialog(parent)
    dialog.exec()
