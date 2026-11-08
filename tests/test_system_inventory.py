import json
import os
import sqlite3
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import Substrate
import SystemInventory


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    yield app
    SystemInventory.stop()


def logEntries(tag):
    """Return the messages logged with tag, once every pending write has finished."""
    Substrate.getMeta("flush")     # Runs after every previously-submitted write
    dbFile = next(f for f in os.listdir(".") if f.endswith(".db"))
    with sqlite3.connect(dbFile) as db:
        return [row[0] for row in db.execute("SELECT message FROM log WHERE tag = ? ORDER BY timestamp", (tag,))]


def test_collect_describes_os_python_and_displays(app):
    inventory = SystemInventory.collect()

    assert inventory["os"]["system"]
    assert inventory["os"]["pretty_name"]
    assert inventory["python"]["version"] == ".".join(str(n) for n in sys.version_info[:3])
    assert inventory["python"]["frozen"] is False

    displays = inventory["displays"]
    assert len(displays) >= 1
    assert sum(d["primary"] for d in displays) == 1
    for display in displays:
        assert display["geometry"]["width"] > 0
        assert display["physical_resolution"]["width"] == round(display["geometry"]["width"] * display["device_pixel_ratio"])


def test_collect_reports_frozen_builds(app, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert SystemInventory.collect()["python"]["frozen"] is True


def test_summary_lists_each_display():
    inventory = {
        "os": {"system": "Windows", "release": "11", "version": "10.0.26200", "machine": "AMD64", "pretty_name": "Windows 11"},
        "python": {"version": "3.12.4", "frozen": True},
        "displays": [
            {"name": "A", "primary": True, "geometry": {}, "device_pixel_ratio": 1.5, "physical_resolution": {"width": 2560, "height": 1440}},
            {"name": "B", "primary": False, "geometry": {}, "device_pixel_ratio": 1.0, "physical_resolution": {"width": 1920, "height": 1080}},
        ],
    }
    assert SystemInventory.summarize(inventory) == (
        "Windows 11 (Windows 10.0.26200); Python 3.12.4 (frozen); 2 displays: 2560x1440@1.5 (primary), 1920x1080@1")


def test_start_logs_the_inventory(app, database, capsys):
    SystemInventory.start()

    [message] = logEntries("system_inventory")
    assert json.loads(message) == SystemInventory.collect()
    assert "System: " in capsys.readouterr().out


def test_display_changes_are_logged_without_the_removed_display(app, database):
    SystemInventory.start()
    screen = QApplication.primaryScreen()

    SystemInventory._onScreenRemoved(screen)

    [message] = logEntries("display_change")
    entry = json.loads(message)
    assert entry["change"] == "removed"
    assert entry["screen"] == screen.name()
    assert screen.name() not in [d["name"] for d in entry["displays"]]


def test_failures_are_logged_instead_of_raised(app, database, monkeypatch):
    def fail():
        raise RuntimeError("no screens")
    monkeypatch.setattr(SystemInventory, "collect", fail)

    SystemInventory.start()

    [message] = logEntries("system_inventory_error")
    assert "no screens" in message


def test_stop_disconnects_display_signals(app, database):
    SystemInventory.start()
    SystemInventory.stop()

    assert SystemInventory._watchedApp is None
    assert SystemInventory._watchedScreens == {}
