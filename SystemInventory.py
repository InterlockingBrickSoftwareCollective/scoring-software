"""
SystemInventory.py: Records the system the software is running on, to help diagnose problems after an event

Copyright (C) 2026 Interlocking Brick Software Collective

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

import json
import platform
import sys
import traceback

from PyQt6.QtCore import QSysInfo
from PyQt6.QtGui import QGuiApplication, QScreen

import Substrate


def collect() -> dict:
    """Return a description of the operating system, Python runtime, and displays.
    A QGuiApplication must exist."""
    return {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            # Python on Windows 11 may report release "10", so also record Qt's name for the OS
            "pretty_name": QSysInfo.prettyProductName(),
        },
        "python": {
            "version": platform.python_version(),
            "frozen": bool(getattr(sys, "frozen", False)),
        },
        "displays": collectDisplays(),
    }


def collectDisplays(exclude: QScreen = None) -> list:
    """Return a description of each connected display, leaving out exclude."""
    primary = QGuiApplication.primaryScreen()
    return [_describeScreen(screen, screen is primary) for screen in QGuiApplication.screens() if screen is not exclude]


def _describeScreen(screen: QScreen, isPrimary: bool) -> dict:
    geometry = screen.geometry()
    ratio = screen.devicePixelRatio()
    return {
        "name": screen.name(),
        "primary": isPrimary,
        # Logical pixels, as used for window positions
        "geometry": {"x": geometry.x(), "y": geometry.y(), "width": geometry.width(), "height": geometry.height()},
        "device_pixel_ratio": ratio,
        "physical_resolution": {"width": round(geometry.width() * ratio), "height": round(geometry.height() * ratio)},
    }


def summarize(inventory: dict) -> str:
    """Return a one-line, human-readable summary of an inventory from collect()."""
    os = inventory["os"]
    python = inventory["python"]
    displays = inventory["displays"]
    displayText = ", ".join(_summarizeDisplay(d) for d in displays)
    return (f"{os['pretty_name']} ({os['system']} {os['version']}); "
            f"Python {python['version']}{' (frozen)' if python['frozen'] else ''}; "
            f"{len(displays)} display{'' if len(displays) == 1 else 's'}: {displayText}")


def _summarizeDisplay(display: dict) -> str:
    resolution = display["physical_resolution"]
    text = f"{resolution['width']}x{resolution['height']}@{display['device_pixel_ratio']:g}"
    return text + " (primary)" if display["primary"] else text


_watchedApp = None
_watchedScreens = {}   # QScreen -> its geometryChanged slot


def start():
    """Log the system inventory, print a summary, and log display changes until stop() is called.
    Substrate must be initialized. Failures are logged rather than raised, so they can't stop startup."""
    try:
        inventory = collect()
        print(f"System: {summarize(inventory)}")
        Substrate.writeLogEntry("system_inventory", json.dumps(inventory))
    except Exception:
        _logError()

    try:
        _watch(QGuiApplication.instance())
    except Exception:
        _logError()


def stop():
    """Stop logging display changes. Call before deinitializing Substrate."""
    global _watchedApp
    if _watchedApp is not None:
        _watchedApp.screenAdded.disconnect(_onScreenAdded)
        _watchedApp.screenRemoved.disconnect(_onScreenRemoved)
        _watchedApp.primaryScreenChanged.disconnect(_onPrimaryScreenChanged)
        _watchedApp = None
    for screen, slot in _watchedScreens.items():
        try:
            screen.geometryChanged.disconnect(slot)
        except (TypeError, RuntimeError):
            pass    # The screen has already been removed
    _watchedScreens.clear()


def _watch(app):
    global _watchedApp
    app.screenAdded.connect(_onScreenAdded)
    app.screenRemoved.connect(_onScreenRemoved)
    app.primaryScreenChanged.connect(_onPrimaryScreenChanged)
    _watchedApp = app
    for screen in QGuiApplication.screens():
        _watchScreen(screen)


def _watchScreen(screen: QScreen):
    # Changes to resolution or scaling both change the logical geometry
    slot = lambda _geometry: _logDisplayChange("geometry_changed", screen)
    screen.geometryChanged.connect(slot)
    _watchedScreens[screen] = slot


def _onScreenAdded(screen: QScreen):
    _watchScreen(screen)
    _logDisplayChange("added", screen)


def _onScreenRemoved(screen: QScreen):
    _watchedScreens.pop(screen, None)
    # The removed screen may still be listed while this signal is emitted
    _logDisplayChange("removed", screen, exclude=screen)


def _onPrimaryScreenChanged(screen: QScreen):
    _logDisplayChange("primary_changed", screen)


def _logDisplayChange(change: str, screen, exclude: QScreen = None):
    try:
        entry = {
            "change": change,
            "screen": screen.name() if screen is not None else None,
            "displays": collectDisplays(exclude),
        }
        Substrate.writeLogEntry("display_change", json.dumps(entry))
    except Exception:
        _logError()


def _logError():
    message = traceback.format_exc()
    print(f"Failed to record system inventory:\n{message}")
    try:
        Substrate.writeLogEntry("system_inventory_error", message)
    except Exception:
        pass
