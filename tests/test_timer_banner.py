import importlib
import os

import pytest

# Run widgets without opening windows
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import Timer
from TimerBanner import TimerBanner


@pytest.fixture
def banner():
    app = QApplication.instance() or QApplication([])
    # Reload so the timer publishes on the fresh event bus each test gets
    importlib.reload(Timer)
    Timer.init()
    yield TimerBanner()
    Timer.abortMatch()
    Timer.stopPractice()


def tick(seconds: int):
    for _ in range(seconds):
        Timer._tick()


def test_hidden_until_a_timer_starts(banner):
    assert not banner.isVisibleTo(None)
    assert banner.title is None


def test_shows_the_running_match(banner):
    Timer.startMatch(3)
    assert banner.isVisibleTo(None)
    assert banner.text() == "Match 3  2:30"
    assert banner.stage == "running"

    tick(5)
    assert banner.text() == "Match 3  2:25"


def test_warns_at_endgame_then_expires(banner):
    Timer.startMatch(1)
    tick(Timer.MATCH_TIME - Timer.MATCH_WARNING)
    assert banner.text() == "Match 1  0:30"
    assert banner.stage == "warning"

    tick(Timer.MATCH_WARNING)
    assert banner.text() == "Match 1  0:00"
    assert banner.stage == "expired"


def test_hides_when_the_match_completes(banner):
    Timer.startMatch(1)
    tick(Timer.MATCH_TIME + Timer.HOLD_TIME + 1)
    assert not banner.isVisibleTo(None)
    assert banner.title is None


def test_hides_when_the_match_is_aborted(banner):
    Timer.startMatch(1)
    tick(10)
    Timer.abortMatch()
    assert not banner.isVisibleTo(None)


def test_shows_practice_and_switches_to_a_match(banner):
    Timer.startPractice(60, 10)
    assert banner.text() == "Practice session  1:00"

    tick(50)
    assert banner.stage == "warning"

    # Starting a match stops the practice session; the match starts out un-warned
    Timer.startMatch(2)
    assert banner.isVisibleTo(None)
    assert banner.text() == "Match 2  2:30"
    assert banner.stage == "running"


def test_hides_when_practice_is_stopped(banner):
    Timer.startPractice(60, 10)
    Timer.stopPractice()
    assert not banner.isVisibleTo(None)
