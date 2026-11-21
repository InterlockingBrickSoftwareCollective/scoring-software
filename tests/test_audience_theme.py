import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

import Audience
import Events
import faketheme
import ThemedDisplay
from EventInfoDialog import effectiveEventName
from datetime import datetime

from Team import Team, rank
from ThemedDisplay import RecentScore

# Keep a reference, or the application is deleted as soon as it's made
app = QApplication.instance() or QApplication([])


class Scoring:
    def __init__(self, teams=()):
        self.teams = list(teams)


def makeAudience(monkeypatch, theme, teams=()):
    monkeypatch.setattr(ThemedDisplay.Theme, "fromResourcePack", classmethod(lambda cls: theme))
    window = Audience.AudienceWindow(Scoring(teams))
    return window


@pytest.fixture
def theme(tmp_path):
    return ThemedDisplay.Theme(faketheme.write(str(tmp_path / "display")))


@pytest.fixture
def audience(monkeypatch, theme):
    teams = [Team(f"Team {i}", 100 + i, from_db=True) for i in range(12)]
    for team in teams:
        team.setScore(1, team.number, from_db=True)
    rank(teams)
    window = makeAudience(monkeypatch, theme, teams)
    yield window
    window.deleteLater()


@pytest.fixture
def plain(monkeypatch):
    window = makeAudience(monkeypatch, None)
    yield window
    window.deleteLater()


def showing(window):
    current = window.stack.currentWidget()
    if window.themed is not None and current is window.themed.view:
        return "theme"
    return "local"


def test_without_a_theme_nothing_changes(plain, published):
    assert not plain.hasTheme()
    plain.setThemeEnabled(True)
    assert not plain.themeEnabled
    assert showing(plain) == "local"
    assert not any(isinstance(e, Events.AudienceThemeChanged) for e in published)
    plain.setEventInfo("Fall Qualifier", "")  # Harmless without a theme
    with pytest.raises(RuntimeError):
        plain.showThemedScreen("welcome")


def test_theme_is_off_until_enabled(audience):
    assert audience.hasTheme()
    assert showing(audience) == "local"


def test_enabled_theme_replaces_the_local_rankings(audience, published):
    changes = []
    audience.themeChanged.connect(changes.append)
    audience.setThemeEnabled(True)
    assert showing(audience) == "theme"
    assert audience.themed.isRunning()
    assert audience.scroll.scroll.paused
    assert [e.enabled for e in published if isinstance(e, Events.AudienceThemeChanged)] == [True]
    assert changes == [True]
    # Margins go so the screen fills the window
    assert audience.mainLayout.contentsMargins().left() == 0


def test_disabling_the_theme_brings_back_the_rankings(audience):
    audience.setThemeEnabled(True)
    audience.setThemeEnabled(False)
    assert showing(audience) == "local"
    assert not audience.themed.isRunning()
    assert not audience.scroll.scroll.paused
    assert audience.mainLayout.contentsMargins() == audience.defaultMargins


def test_rerank_updates_the_themed_standings(audience):
    audience.setThemeEnabled(True)
    assert audience.themed.currentScreen() == ("standings", 1)
    audience.themed.advance()
    audience.rerank()
    assert audience.themed.currentScreen() == ("standings", 2)


def test_event_info_reaches_the_themed_display(audience):
    audience.setThemeEnabled(True)
    audience.setEventInfo("Fall Qualifier", "Oct 3")
    assert audience.themed.eventName == "Fall Qualifier"


def test_show_and_resume_themed_screens(audience):
    audience.setThemeEnabled(True)
    audience.showThemedScreen("award_winner", {"team_name": "Bots"})
    assert audience.themed.currentScreen() == ("held", "award_winner")
    audience.resumeThemedRotation()
    assert audience.themed.currentScreen() == ("standings", 1)


def test_effective_event_name():
    assert effectiveEventName("Fall Qualifier", "FLL-FQ-2026") == "Fall Qualifier"
    assert effectiveEventName("  ", "Score Reflector Name") == "Score Reflector Name"
    assert effectiveEventName("", None) == ""


# Saving the choices

def test_theme_choice_is_saved(database):
    import Substrate
    assert Substrate.loadAudienceTheme() is None
    Events.publish(Events.AudienceThemeChanged(False))
    assert database().loadAudienceTheme() is False
    Events.publish(Events.AudienceThemeChanged(True))
    assert database().loadAudienceTheme() is True


def test_event_info_is_saved(database):
    import Substrate
    assert Substrate.loadEventInfo() == ("", "")
    Events.publish(Events.EventInfoChanged("Fall Qualifier", "Oct 3"))
    assert database().loadEventInfo() == ("Fall Qualifier", "Oct 3")


# Themed timers

@pytest.fixture
def timers(audience, monkeypatch):
    """Every themed timer the audience display draws, as (title, remaining, total, warning)."""
    drawn = []
    original = audience.themed.showTimer
    def record(*args):
        drawn.append(args)
        original(*args)
    monkeypatch.setattr(audience.themed, "showTimer", record)
    audience.setThemeEnabled(True)
    return drawn


def test_match_timer_is_themed(audience, timers):
    audience.setMatchNumber(12)
    audience.setMode("match_timer")
    assert showing(audience) == "theme"
    assert not audience.themed.isRunning()  # The rotation stops while the timer shows
    assert timers[-1] == ("Match 12", 150, 150, False, False)


def test_match_timer_counts_down_and_turns_to_endgame(audience, timers):
    audience.setMode("match_timer")
    Events.publish(Events.MatchStarted(7))
    Events.publish(Events.TimerUpdated(False, 150))
    Events.publish(Events.TimerUpdated(False, 31))
    assert timers[-1] == ("Match 7", 31, 150, False, False)
    Events.publish(Events.TimerUpdated(False, 30))
    Events.publish(Events.TimerWarning())
    assert timers[-1] == ("Match 7", 30, 150, True, False)
    Events.publish(Events.TimerUpdated(False, 0))
    Events.publish(Events.TimerExpired())
    assert timers[-1] == ("Match 7", 0, 150, True, True)


def test_the_next_match_starts_without_the_warning(audience, timers):
    audience.setMode("match_timer")
    Events.publish(Events.MatchStarted(7))
    Events.publish(Events.TimerWarning())
    Events.publish(Events.MatchCompleted(7))
    Events.publish(Events.TimerUpdated(False, 150))
    assert timers[-1][3] is False
    Events.publish(Events.MatchStarted(8))
    Events.publish(Events.TimerUpdated(False, 150))
    assert timers[-1] == ("Match 8", 150, 150, False, False)


def test_practice_timer_is_themed_and_turns_yellow(audience, timers):
    audience.setMode("practice_timer")
    Events.publish(Events.PracticeStarted(300))
    Events.publish(Events.TimerUpdated(True, 300))
    assert timers[-1] == ("Practice timer", 300, 300, False, False)
    Events.publish(Events.TimerUpdated(True, 120))
    Events.publish(Events.TimerWarning())
    assert timers[-1] == ("Practice timer", 120, 300, True, False)
    Events.publish(Events.PracticeEnded())
    Events.publish(Events.TimerUpdated(True, 300))
    assert timers[-1] == ("Practice timer", 300, 300, False, False)


def test_match_ticks_dont_redraw_the_practice_timer(audience, timers):
    audience.setMode("practice_timer")
    count = len(timers)
    Events.publish(Events.TimerUpdated(False, 100))
    assert len(timers) == count


def test_back_to_the_rotation_after_a_match(audience, timers):
    audience.setMode("match_timer")
    audience.setMode("ranks")
    assert showing(audience) == "theme"
    assert audience.themed.isRunning()


def test_timers_keep_the_usual_look_with_the_theme_off(audience):
    audience.setMode("match_timer")
    assert showing(audience) == "local"


def test_timers_keep_the_usual_look_when_the_theme_has_no_timer(monkeypatch, tmp_path):
    spec = dict(faketheme.THEME)
    spec["screens"] = {k: v for k, v in spec["screens"].items() if k != "timer"}
    theme = ThemedDisplay.Theme(faketheme.write(str(tmp_path / "old"), spec))
    window = makeAudience(monkeypatch, theme)
    window.setThemeEnabled(True)
    window.setMode("match_timer")
    assert showing(window) == "local"
    window.setMode("ranks")
    assert showing(window) == "theme"
    window.deleteLater()


def test_the_next_match_starts_without_the_red(audience, timers):
    audience.setMode("match_timer")
    Events.publish(Events.MatchStarted(7))
    Events.publish(Events.TimerExpired())
    Events.publish(Events.MatchCompleted(7))
    Events.publish(Events.MatchStarted(8))
    Events.publish(Events.TimerUpdated(False, 150))
    assert timers[-1] == ("Match 8", 150, 150, False, False)


# Welcome and the time of day

def test_welcome_screen_shows_when_chosen(audience):
    modes = []
    audience.modeChanged.connect(modes.append)
    audience.setThemeEnabled(True)
    audience.setMode(Audience.WELCOME)
    assert audience.mode == Audience.WELCOME and showing(audience) == "theme"
    assert audience.themed.isRunning() and audience.themed.currentScreen() == ("welcome",)
    assert modes == [Audience.WELCOME]
    audience.setMode(Audience.RANKS)
    assert audience.themed.isRunning() and audience.themed.currentScreen() == ("standings", 1)


def test_results_page_reaches_the_welcome_screen(audience):
    audience.setResultsUrl("https://scores.example.org/events/fall-qual")
    assert audience.themed.resultsUrl == "https://scores.example.org/events/fall-qual"


def test_welcome_screen_needs_the_theme(audience, plain):
    audience.setMode(Audience.WELCOME)  # Theme off
    assert audience.mode == Audience.RANKS
    plain.setMode(Audience.WELCOME)
    assert plain.mode == Audience.RANKS and not plain.canShowWelcome()


def test_turning_the_theme_off_leaves_the_welcome_screen(audience):
    modes = []
    audience.modeChanged.connect(modes.append)
    audience.setThemeEnabled(True)
    audience.setMode(Audience.WELCOME)
    audience.setThemeEnabled(False)
    assert audience.mode == Audience.RANKS and showing(audience) == "local"
    assert modes == [Audience.WELCOME, Audience.RANKS]


def test_themed_clock(audience, monkeypatch):
    shown = []
    original = audience.themed.showClock
    monkeypatch.setattr(audience.themed, "showClock", lambda now: shown.append(now) or original(now))
    audience.setThemeEnabled(True)
    audience.setMode(Audience.CLOCK)
    assert showing(audience) == "theme"
    assert audience.clockTicker.isActive()
    audience.showTimeOfDay()  # What each tick does
    assert len(shown) == 2
    audience.setMode(Audience.RANKS)
    assert not audience.clockTicker.isActive()


def test_plain_clock_without_the_theme(plain):
    plain.setMode(Audience.CLOCK)
    assert showing(plain) == "local"
    assert plain.vbox.itemAt(0).widget() is plain.timeOfDay
    assert re.fullmatch(r"\d{1,2}:\d\d [ap]", plain.timeOfDay.timerLabel.text())
    assert plain.clockTicker.isActive()


# Latest scores

def test_latest_scores_follow_score_changes(audience):
    assert audience.recentScores == []  # Nothing carries over from before the program started
    Events.publish(Events.ScoreUpdated(100, 1, 50))
    Events.publish(Events.ScoreUpdated(101, 1, 70))
    Events.publish(Events.ScoreUpdated(100, 1, 55))  # A correction replaces the earlier entry
    assert [(s.team, s.round, s.score) for s in audience.recentScores] == [(100, 1, 55), (101, 1, 70)]
    Events.publish(Events.ScoreCleared(100, 1))
    assert [(s.team, s.round) for s in audience.recentScores] == [(101, 1)]
    Events.publish(Events.TeamDeleted(101))
    assert audience.recentScores == []


def test_latest_scores_reach_the_standings(audience, monkeypatch):
    audience.setThemeEnabled(True)
    built = []
    original = audience.theme.build
    monkeypatch.setattr(audience.theme, "build", lambda screen, **kw: built.append(kw) or original(screen, **kw))
    Events.publish(Events.ScoreUpdated(105, 2, 99))
    audience.rerank()
    assert built[-1]["values"]["recent8_team"] == "#105"


def test_clock_after_practice_setting_is_saved(database):
    import Substrate
    assert Substrate.loadClockAfterPractice() is True
    Events.publish(Events.ClockAfterPracticeChanged(False))
    assert database().loadClockAfterPractice() is False


# Match status

def test_match_status_reaches_the_standings(audience, monkeypatch):
    audience.setThemeEnabled(True)
    built = []
    original = audience.theme.build
    monkeypatch.setattr(audience.theme, "build", lambda screen, **kw: built.append(kw) or original(screen, **kw))
    Events.publish(Events.MatchStatusChanged(9, "preparing"))
    assert audience.matchStatus == (9, "preparing")
    assert built[-1]["values"]["status_title"] == "Match 9"
    Events.publish(Events.MatchStatusChanged(0, None))
    assert audience.matchStatus is None
    assert built[-1]["values"]["status_single"] == "Waiting"


# Glow effects

def test_glow_effects_can_be_turned_off(audience, monkeypatch):
    audience.setThemeEnabled(True)
    published, changed = [], []
    monkeypatch.setattr(Events, "publish", published.append)
    audience.glowChanged.connect(changed.append)
    assert audience.glowEnabled()
    audience.setGlowEnabled(False)
    assert not audience.theme.glow
    assert [e.enabled for e in published if isinstance(e, Events.GlowEffectsChanged)] == [False]
    assert changed == [False]
    audience.setGlowEnabled(False)  # No change, no event
    assert changed == [False]


def test_glow_choice_redraws_the_timer_background(audience):
    audience.setThemeEnabled(True)
    audience.setMode(Audience.MATCH_TIMER)
    assert audience.themed.view.backgroundKey() is not None
    audience.setGlowEnabled(False)
    assert audience.themed.view.backgroundKey() is not None  # Drawn again, without glow


def test_glow_choice_is_saved(database):
    import Substrate
    assert Substrate.loadGlowEffects() is True
    Events.publish(Events.GlowEffectsChanged(False))
    assert database().loadGlowEffects() is False
