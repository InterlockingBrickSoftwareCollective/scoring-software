import os

import pytest

# Run widgets without opening windows
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QMessageBox, QWidget

import Audience
import Events
from Audience import LOCAL, PIT

PIT_URL = "https://scores.example.org/events/fall-qual/pit?dwell=10&panel=25&scale=100"


@pytest.fixture
def audience(monkeypatch):
    app = QApplication.instance() or QApplication([])

    class Scoring:
        teams = []

    window = Audience.AudienceWindow(Scoring())
    # Don't start WebView2; remember which page it would show
    window.pitView.loaded = None
    monkeypatch.setattr(window.pitView, "setUrl", lambda url: setattr(window.pitView, "loaded", url))
    yield window
    window.deleteLater()


@pytest.fixture
def menu(audience):
    parent = QWidget()
    menu = Audience.AudienceSourceMenu(audience, parent)
    yield menu
    parent.deleteLater()


def showing(audience):
    return "pit" if audience.stack.currentWidget() is audience.pitView else "local"


def sourcesPublished(published):
    return [e.source for e in published if isinstance(e, Events.AudienceSourceChanged)]


def choose(menu, label):
    next(a for a in menu.actions() if a.text() == label).trigger()


def checked(menu):
    return next(a.text() for a in menu.actions() if a.isChecked())


# The audience window

def test_shows_local_rankings_by_default(audience, published):
    audience.setPitDisplayUrl(PIT_URL)
    assert showing(audience) == "local"
    assert audience.pitView.loaded is None
    assert sourcesPublished(published) == []


def test_shows_the_pit_display_when_chosen_and_there_is_a_page(audience, published):
    audience.setSource(PIT)
    assert showing(audience) == "local"  # No page yet

    audience.setPitDisplayUrl(PIT_URL)
    assert showing(audience) == "pit"
    assert audience.pitView.loaded == PIT_URL

    audience.setPitDisplayUrl(None)
    assert showing(audience) == "local"
    assert audience.source == PIT  # Still chosen, for when there's a page again
    assert sourcesPublished(published) == [PIT]


def test_timers_take_over_from_the_pit_display(audience):
    audience.setSource(PIT)
    audience.setPitDisplayUrl(PIT_URL)
    audience.setMode("match_timer")
    assert showing(audience) == "local"
    audience.setMode("ranks")
    assert showing(audience) == "pit"


def test_publishes_only_changes_of_source(audience, published):
    audience.setSource(PIT)
    audience.setSource(PIT)
    audience.setSource("something else")
    assert sourcesPublished(published) == [PIT, LOCAL]


def test_a_pit_display_that_cannot_start_goes_back_to_local_rankings(audience, published):
    failures = []
    audience.pitDisplayFailed.connect(failures.append)
    audience.setSource(PIT)
    audience.setPitDisplayUrl(PIT_URL)

    audience.pitView.failed.emit("WebView2 Runtime not found")
    assert showing(audience) == "local"
    # Published, so it isn't tried again on the next launch either
    assert sourcesPublished(published) == [PIT, LOCAL]
    assert failures == ["WebView2 Runtime not found"]


# Toybox > Audience display

def test_only_offered_while_there_is_a_pit_display_page(menu, audience):
    assert not menu.menuAction().isVisible()
    audience.setPitDisplayUrl(PIT_URL)
    assert menu.menuAction().isVisible()
    audience.setPitDisplayUrl(None)
    assert not menu.menuAction().isVisible()


def test_choosing_sets_the_source(menu, audience):
    audience.setPitDisplayUrl(PIT_URL)
    assert checked(menu) == "Local rankings"
    choose(menu, "Cloud pit display")
    assert audience.source == PIT
    choose(menu, "Local rankings")
    assert audience.source == LOCAL


def test_follows_the_source_however_it_changes(menu, audience):
    audience.setPitDisplayUrl(PIT_URL)
    audience.setSource(PIT)  # As when restored at startup
    assert checked(menu) == "Cloud pit display"
    audience.setSource(LOCAL)  # As when sync is removed
    assert checked(menu) == "Local rankings"


def test_the_operator_is_told_when_the_pit_display_cannot_start(menu, audience, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    audience.setPitDisplayUrl(PIT_URL)
    choose(menu, "Cloud pit display")

    audience.pitView.failed.emit("WebView2 Runtime not found")
    assert checked(menu) == "Local rankings"
    assert "WebView2 Runtime not found" in warnings[0][2]
