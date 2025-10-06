"""
About.py: About screen

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

import os

from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PyQt6.QtWidgets import *

import ResourceManager

licenseText = """
<p style="margin-bottom: 1em">Copyright © 2024-2025 Interlocking Brick Software Collective.</p>
<p style="margin-bottom: 1em">Interlocking Brick Scoring Software is free software: you can redistribute it and/or modify it under the terms of version 3 of the GNU General Public License as published by the Free Software Foundation.</p>
<p style="margin-bottom: 1em">Interlocking Brick Scoring Software is distributed in the hope that it will be useful, but <b>WITHOUT ANY WARRANTY</b>; without even the <b>implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE</b>. See the <a href="https://www.gnu.org/licenses/gpl-3.0.txt">GNU General Public License</a> for more details.</p>

"""

ossText = """
Interlocking Brick Scoring Software includes the following open-source software:
* [PyQt6](https://pypi.org/project/PyQt6/), copyright © Riverbank Computing Limited, licensed under GPLv3
* [requests](https://pypi.org/project/requests/), copyright © Kenneth Reitz, licensed under Apache 2.0
"""

_version = None

def getVersion() -> str:
    global _version

    if _version != None:
        return _version

    try:
        # assume production version, where Deploy script will
        # generate and package a Version.py
        from Version import version
        appVersion = version  # slice off "v" from tag name
    except:
        # running development version, try to get it from git
        try:
            import subprocess
            out = subprocess.check_output(
                ["git", "describe", "--tags", "--dirty"],
                stderr=subprocess.DEVNULL)
            appVersion = "git " + out.decode().strip()
        except:
            # all our attempts to get a version failed
            appVersion = "unknown"

    _version = appVersion
    return _version

def show(parent):
    """Show the About dialog."""
    try:
        aboutDialog = QDialog(parent)
        aboutDialog.setWindowTitle("About")
        aboutDialog.setFixedSize(500, 200)

        mainLayout = QVBoxLayout()

        # Top section: Icon and version information side by side
        topLayout = QHBoxLayout()

        iconLabel = QLabel()
        pixmap = QPixmap(os.path.join(os.path.dirname(__file__), "icon.png"))
        scaledPixmap = pixmap.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        iconLabel.setPixmap(scaledPixmap)
        iconLabel.setFixedSize(96, 96)

        # Right side: Text information in a vertical layout
        textLayout = QVBoxLayout()

        # Application name
        appNameLabel = QLabel("Interlocking Brick Scoring Software")
        appNameLabel.setStyleSheet("font-size: 18px; font-weight: bold;")
        textLayout.addWidget(appNameLabel)

        # Application version
        appVersionLabel = QLabel(f"Version: {getVersion()}")
        appVersionLabel.setStyleSheet("font-size: 14px;")
        textLayout.addWidget(appVersionLabel)

        # Resource pack version
        if ResourceManager.isResourcePackInstalled():
            packVersion = ResourceManager.getResourcePackVersion()
            versionText = packVersion if packVersion else "unknown"
        else:
            versionText = "not installed"
        packVersionLabel = QLabel(f"Resource Pack: {versionText}")
        packVersionLabel.setStyleSheet("font-size: 14px;")
        textLayout.addWidget(packVersionLabel)

        # Add stretch to push text to the top
        textLayout.addStretch()

        topLayout.addWidget(iconLabel)
        topLayout.addLayout(textLayout)

        # Add top section to main layout
        mainLayout.addLayout(topLayout)

        # Separate version - license
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        mainLayout.addWidget(separator)

        # License
        licenseLabel = QLabel()
        licenseLabel.setTextFormat(Qt.TextFormat.RichText)
        licenseLabel.setWordWrap(True)
        licenseLabel.setStyleSheet("font-size: 12px")
        licenseLabel.setText(licenseText)
        mainLayout.addWidget(licenseLabel)

        # Separate license - OSS text
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.Shape.HLine)
        separator2.setFrameShadow(QFrame.Shadow.Sunken)
        mainLayout.addWidget(separator2)

        # Open-source software acknowledgements
        ossLabel = QLabel()
        ossLabel.setTextFormat(Qt.TextFormat.MarkdownText)
        ossLabel.setWordWrap(True)
        ossLabel.setStyleSheet("font-size: 12px")
        ossLabel.setText(ossText)
        mainLayout.addWidget(ossLabel)

        aboutDialog.setLayout(mainLayout)
        aboutDialog.exec()

    except Exception as err:
        print(err)