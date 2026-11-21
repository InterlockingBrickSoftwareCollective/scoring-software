import importlib

import pytest

import Events
import MatchStatus


@pytest.fixture
def status(eventBus):
    importlib.reload(MatchStatus)
    MatchStatus.init()
    return MatchStatus


def changes(published):
    return [(e.match, e.status) for e in published if isinstance(e, Events.MatchStatusChanged)]


def test_nothing_until_a_match_is_selected(status):
    assert status.current() is None


def test_follows_a_match_through(status, published):
    Events.publish(Events.MatchSelected(4))
    assert status.current() == (4, "preparing")
    Events.publish(Events.MatchStarted(4))
    assert status.current() == (4, "running")
    Events.publish(Events.MatchSelected(5))  # Advanced while the match runs
    assert status.current() == (4, "running")
    Events.publish(Events.MatchCompleted(4))
    assert status.current() == (4, "scoring")
    Events.publish(Events.ScoreUpdated(100, 1, 50))  # The first score means the next match is setting up
    assert status.current() == (5, "preparing")
    assert changes(published) == [(4, "preparing"), (4, "running"), (4, "scoring"), (5, "preparing")]


def test_an_aborted_match_is_set_up_again(status):
    Events.publish(Events.MatchStarted(3))
    Events.publish(Events.MatchAborted(3))
    assert status.current() == (3, "preparing")


def test_without_a_selected_match_the_next_one_is_assumed(status):
    Events.publish(Events.MatchStarted(3))
    Events.publish(Events.MatchCompleted(3))
    Events.publish(Events.ScoreUpdated(100, 1, 50))
    assert status.current() == (4, "preparing")


def test_event_wide_statuses_hold_until_a_match_starts(status):
    Events.publish(Events.MatchSelected(4))
    status.set(7, "opening_ceremonies")
    assert status.current() == (0, "opening_ceremonies")
    Events.publish(Events.MatchSelected(5))  # Doesn't replace the ceremony
    assert status.current() == (0, "opening_ceremonies")
    Events.publish(Events.MatchStarted(5))
    assert status.current() == (5, "running")


def test_clearing_keeps_it_clear_until_a_match_starts(status, published):
    status.set(0, "practice")
    status.clear()
    assert status.current() is None
    assert changes(published)[-1] == (0, None)
    Events.publish(Events.MatchSelected(5))
    assert status.current() is None
    Events.publish(Events.MatchStarted(5))
    assert status.current() == (5, "running")


@pytest.mark.parametrize("match, value", [(0, "preparing"), (3, "dancing")])
def test_invalid_statuses_are_refused(status, match, value):
    with pytest.raises(ValueError):
        status.set(match, value)


def test_event_status_menu_works_without_sync(status):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QWidget
    from SyncControl import EventStatusMenu

    app = QApplication.instance() or QApplication([])

    class NoSync:
        """A sync controller with sync not set up"""
        matchStatus = None
        told = []

        def setMatchStatus(self, match, value):
            self.told.append((match, value))

        def clearMatchStatus(self):
            self.told.append(None)

    parent = QWidget()
    controller = NoSync()
    menu = EventStatusMenu(controller, lambda: 3, parent)
    choose = {a.text(): a for a in menu.actions()}
    choose["Closing ceremonies"].trigger()
    assert status.current() == (0, "closing_ceremonies")
    choose["Matches"].trigger()
    assert status.current() == (3, "preparing")
    choose["None"].trigger()
    assert status.current() is None
    # Sync hears the same choices, for when it's set up
    assert controller.told == [(0, "closing_ceremonies"), (3, "preparing"), None]
    parent.deleteLater()
