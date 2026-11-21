import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QMessageBox

import Audience
import Awards
import Events
import faketheme
import ThemedDisplay
from Awards import Advancement, Award
from AwardsEntryWindow import AwardsEntryWindow
from AwardsWindow import AwardsWindow
from Team import Team

app = QApplication.instance() or QApplication([])


class Scoring:
    def __init__(self, teams=()):
        self.teams = list(teams)


@pytest.fixture
def theme(tmp_path):
    return ThemedDisplay.Theme(faketheme.write(str(tmp_path / "display")))


@pytest.fixture
def audience(monkeypatch, theme):
    monkeypatch.setattr(ThemedDisplay.Theme, "fromResourcePack", classmethod(lambda cls: theme))
    window = Audience.AudienceWindow(Scoring([Team("Bricks", 42, from_db=True), Team("Bots", 7, from_db=True),
                                              Team("Gears", 9, from_db=True)]))
    window.setThemeEnabled(True)
    yield window
    window.deleteLater()


@pytest.fixture
def saved():
    """The awards as saved, which AwardsChanged events replace."""
    awards = [Award("Core Values", 1, 42), Award("Robot Performance", 2, 42, [7, 9])]
    Events.subscribe(Events.AwardsChanged, lambda event: awards.__setitem__(slice(None), list(event.awards)))
    return awards


@pytest.fixture
def advancing():
    """The advancing teams as saved, which AdvancementChanged events replace."""
    advancement = Advancement("the State Championship", [9, 42])
    Events.subscribe(Events.AdvancementChanged, lambda event: advancement.__init__(event.nextEvent, list(event.teams)))
    return advancement


@pytest.fixture
def control(audience, saved, advancing):
    window = AwardsWindow(audience, lambda: list(saved), lambda: Advancement(advancing.nextEvent, list(advancing.teams)),
                          lambda: audience.setMode(Audience.AWARDS))
    yield window
    window.deleteLater()


def built(audience, monkeypatch):
    """Every themed screen built from now on, as (screen, build arguments)."""
    screens = []
    original = audience.theme.build
    monkeypatch.setattr(audience.theme, "build",
                        lambda screen, **kw: screens.append((screen, kw)) or original(screen, **kw))
    return screens


# The audience display's awards mode

def test_awards_mode_starts_on_the_welcome_screen(audience):
    audience.setMode(Audience.AWARDS)
    assert audience.mode == Audience.AWARDS
    assert audience.stack.currentWidget() is audience.themed.view
    assert audience.themed.currentScreen() == ("still", "welcome")
    assert not audience.themed.isRunning()  # No standings rotation


def test_awards_mode_needs_the_theme(audience):
    audience.setThemeEnabled(False)
    audience.setMode(Audience.AWARDS)
    assert audience.mode == Audience.RANKS and not audience.canShowAwards()


def test_turning_the_theme_off_leaves_awards_mode(audience):
    audience.setMode(Audience.AWARDS)
    audience.setThemeEnabled(False)
    assert audience.mode == Audience.RANKS


def test_award_steps_reach_the_display(audience, monkeypatch):
    screens = built(audience, monkeypatch)
    audience.setEventInfo("Fall Qualifier", "")
    audience.setMode(Audience.AWARDS)
    award = Award("Robot Performance", 1, 42, [7])

    audience.showAwardStep(Awards.Step(Awards.INTRO, award))
    assert screens[-1] == ("award_intro", {"values": {"event_name": "Fall Qualifier", "award_name": "Robot Performance"}})

    audience.showAwardStep(Awards.Step(Awards.REVEAL, award, 2, 7, revealed=False))
    screen, args = screens[-1]
    assert screen == "award_winner" and args["values"]["place"] == "2ND PLACE"
    assert "team_number" in args["hidden"] and "team_name" not in args["values"]

    audience.showAwardStep(Awards.Step(Awards.REVEAL, award, 1, 42, revealed=True))
    screen, args = screens[-1]
    assert args["values"]["place"] == "WINNER"
    assert args["values"]["team_number"] == "42" and args["values"]["team_name"] == "Bricks"


def test_award_steps_wait_for_awards_mode(audience):
    audience.showAwardStep(Awards.Step(Awards.INTRO, Award("Core Values", 1, 42)))
    assert audience.mode == Audience.RANKS and audience.themed.currentScreen() == ("standings", 1)
    audience.setMode(Audience.AWARDS)
    assert audience.themed.currentScreen() == ("still", "award_intro")


def test_leaving_awards_mode_brings_back_the_standings(audience):
    audience.setMode(Audience.AWARDS)
    audience.setMode(Audience.RANKS)
    assert audience.themed.isRunning() and audience.themed.currentScreen() == ("standings", 1)


# Presentation control

def test_control_lists_every_step(control):
    assert [control.list.item(row).text().strip() for row in range(control.list.count())] == [
        "Welcome screen",
        "Core Values: intro", "Winner: blank display", "Winner: 42 Bricks",
        "Robot Performance: intro", "3rd place: blank display", "3rd place: 9 Gears", "2nd place: blank display", "2nd place: 7 Bots",
        "Winner: blank display", "Winner: 42 Bricks",
        "Advancing: title only", "Blank list (2 teams)", "1: 9 Gears", "2: 42 Bricks",
        "Thank you screen",
    ]
    assert control.currentStep().kind == Awards.WELCOME
    assert not control.backButton.isEnabled() and control.nextButton.isEnabled()


def test_space_and_clicker_keys_step_through(control, audience):
    QTest.keyClick(control, Qt.Key.Key_Space)
    assert control.currentStep().kind == Awards.INTRO and audience.mode == Audience.AWARDS
    assert audience.themed.currentScreen() == ("still", "award_intro")
    QTest.keyClick(control, Qt.Key.Key_PageDown)
    QTest.keyClick(control, Qt.Key.Key_Right)
    step = control.currentStep()
    assert (step.kind, step.team, step.revealed) == (Awards.REVEAL, 42, True)
    QTest.keyClick(control, Qt.Key.Key_PageUp)
    assert not control.currentStep().revealed
    QTest.keyClick(control, Qt.Key.Key_Left)
    assert control.currentStep().kind == Awards.INTRO


def test_next_stops_at_the_last_step(control):
    last = control.list.count() - 1
    control.goTo(last)
    control.next()
    assert control.currentRow() == last and not control.nextButton.isEnabled()


def test_clicking_a_step_shows_it(control, audience):
    control.list.setCurrentRow(5)
    assert audience.awardStep == control.steps[5] and audience.mode == Audience.AWARDS


def test_show_welcome_goes_back_to_the_start(control, audience):
    control.goTo(4)
    control.welcomeButton.click()
    assert control.currentRow() == 0 and audience.themed.currentScreen() == ("still", "welcome")


def test_corrections_keep_the_place_and_reach_the_screen(control, audience, saved):
    control.goTo(4)  # Robot Performance: intro
    Events.publish(Events.AwardsChanged((Award("Core Values", 1, 42), Award("Robot Game", 2, 42, [7, 9]))))
    assert control.currentRow() == 4 and audience.awardStep.award.name == "Robot Game"
    assert control.list.item(4).text() == "Robot Game: intro"


def test_renamed_teams_are_relabelled(control, audience):
    audience.parent.teams[0].name = "Brickworks"
    Events.publish(Events.TeamUpdated(42, "Brickworks", 0))
    assert control.list.item(3).text().strip() == "Winner: 42 Brickworks"


def test_no_awards_says_how_to_enter_them(audience):
    window = AwardsWindow(audience, lambda: [], lambda: Advancement(), lambda: None)
    assert window.list.count() == 2 and not window.emptyLabel.isHidden()  # Welcome and thank-you screens
    window.deleteLater()


# Entering awards

@pytest.fixture
def entry(audience):
    awards = [Award("Robot Performance", 2, 42, [7]), Award("Core Values", 1, 9)]
    window = AwardsEntryWindow(lambda: awards, lambda: Advancement("the State Championship", [7]),
                               lambda: audience.parent.teams)
    window.show()
    yield window
    window.closeWithoutSaving()
    window.deleteLater()


def test_entry_lists_awards_in_order(entry):
    assert [entry.list.item(row).text() for row in range(entry.list.count())] == ["Core Values", "Robot Performance"]
    assert entry.nameEdit.text() == "Core Values" and entry.winnerPicker.team() == 9


def test_entry_edits_and_reorders(entry):
    entry.list.setCurrentRow(1)
    assert entry.runnersUpSpin.value() == 1 and entry.runnerUpPickers[0].team() == 7
    entry.runnersUpSpin.setValue(2)
    entry.runnerUpPickers[1].setTeam(9)
    entry.moveAward(-1)
    entry.addAward()
    QTest.keyClicks(entry.nameEdit, "Innovation Project")
    assert entry.list.item(2).text() == "Innovation Project"
    assert entry.problems() == []
    assert entry.enteredAwards() == [Award("Robot Performance", 1, 42, [7, 9]), Award("Core Values", 2, 9, []),
                                      Award("Innovation Project", 3, None, [])]


def test_entry_finds_problems(entry):
    entry.addAward()  # No name
    entry.list.setCurrentRow(1)
    entry.runnersUpSpin.setValue(2)  # 3rd place not chosen
    entry.list.setCurrentRow(0)
    entry.winnerPicker.setTeam(None)
    entry.runnersUpSpin.setValue(1)
    entry.runnerUpPickers[0].setTeam(42)  # A runner-up without a winner
    problems = entry.problems()
    assert "Every award needs a name." in problems
    assert "Robot Performance: choose a team for every runner-up place, or have fewer runners-up." in problems
    assert "Core Values: choose the winner as well as the runners-up." in problems


def test_entry_rejects_a_team_in_two_places(entry):
    entry.list.setCurrentRow(1)
    entry.runnerUpPickers[0].setTeam(42)
    assert entry.problems() == ["Robot Performance: a team can only have one place."]


def test_entry_keeps_a_deleted_team(audience):
    window = AwardsEntryWindow(lambda: [Award("Core Values", 1, 1234)], lambda: Advancement(), lambda: audience.parent.teams)
    assert window.winnerPicker.team() == 1234 and "not in the team list" in window.winnerPicker.currentText()
    window.deleteLater()


def test_saving_publishes_the_awards_and_closes(entry, published):
    entry.list.setCurrentRow(1)
    entry.winnerPicker.setTeam(7)
    entry.runnerUpPickers[0].setTeam(42)
    entry.save()
    assert published[-2:] == [Events.AwardsChanged((Award("Core Values", 1, 9, []), Award("Robot Performance", 2, 7, [42]))),
                              Events.AdvancementChanged("the State Championship", (7,))]
    assert not entry.isVisible() and not entry.changed


def test_problems_keep_the_window_open(entry, published, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    entry.addAward()
    assert not entry.save()
    assert warnings == ["Every award needs a name."] and entry.isVisible()
    assert not any(isinstance(event, Events.AwardsChanged) for event in published)


@pytest.mark.parametrize("answer, closes, saves", [
    (QMessageBox.StandardButton.Cancel, False, False),
    (QMessageBox.StandardButton.Discard, True, False),
    (QMessageBox.StandardButton.Save, True, True),
])
def test_closing_with_unsaved_changes_asks(entry, published, monkeypatch, answer, closes, saves):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: answer)
    entry.close()  # Nothing changed, so nothing to ask
    assert not entry.isVisible()
    entry.show()
    QTest.keyClicks(entry.nameEdit, "!")
    entry.close()
    assert entry.isVisible() != closes
    assert any(isinstance(event, Events.AwardsChanged) for event in published) == saves


def test_reloading_starts_from_whats_saved(entry):
    QTest.keyClicks(entry.nameEdit, " Award")
    entry.load()
    assert entry.nameEdit.text() == "Core Values" and not entry.changed


def test_teams_added_while_open_can_be_chosen(entry, audience):
    entry.winnerPicker.setTeam(9)
    newcomer = Team("Newcomers", 55)  # Publishes TeamAdded before it joins the team list
    audience.parent.teams.append(newcomer)
    QTest.qWait(10)
    assert entry.winnerPicker.findData(55) >= 0 and entry.winnerPicker.team() == 9


def test_saved_winners_are_shown_as_teams(entry):
    # The winner picker is made before the teams are loaded, so it has to be given them too
    assert entry.winnerPicker.currentText() == "9  Gears"
    entry.list.setCurrentRow(1)
    assert entry.winnerPicker.currentText() == "42  Bricks"
    assert entry.runnerUpPickers[0].currentText() == "7  Bots"


# Advancement

def test_advancing_steps_reach_the_display(audience, monkeypatch):
    screens = built(audience, monkeypatch)
    audience.setMode(Audience.AWARDS)
    advancement = Advancement("the State Championship", [9, 42])

    audience.showAwardStep(Awards.Step(Awards.ADVANCING_TITLE, advancement=advancement))
    screen, args = screens[-1]
    assert screen == "advancing" and args["values"]["title"] == "Advancing to the State Championship"
    assert "adv1" in args["hidden"]

    audience.showAwardStep(Awards.Step(Awards.ADVANCING, team=9, advancement=advancement, shown=1))
    screen, args = screens[-1]
    assert args["values"]["adv1_number"] == "9" and args["values"]["adv1_name"] == "Gears"
    assert "adv2_number" in args["hidden"] and "adv2" in args["shown"]

    audience.showAwardStep(Awards.Step(Awards.THANKS))
    assert screens[-1][0] == "thank_you"


def test_control_steps_into_the_advancing_teams(control, audience):
    control.goTo(11)  # Advancing: title only
    assert control.nowLabel.text() == "Advancing to the State Championship"
    assert control.nowDetail.text() == "Title only"
    assert control.nextLabel.text() == "Next: Blank list: 2 teams"
    QTest.keyClick(control, Qt.Key.Key_Space)
    QTest.keyClick(control, Qt.Key.Key_Space)
    assert control.nowDetail.text() == "Team 1 of 2: 9 Gears"
    assert audience.themed.currentScreen() == ("still", "advancing")
    control.goTo(control.list.count() - 1)
    assert audience.themed.currentScreen() == ("still", "thank_you") and not control.nextButton.isEnabled()


def test_control_follows_advancement_changes(control, audience):
    control.goTo(13)  # The first team revealed
    Events.publish(Events.AdvancementChanged("", (7, 9, 42)))
    assert control.currentRow() == 13 and control.nowLabel.text() == "Advancing from this event"
    assert control.nowDetail.text() == "Team 1 of 3: 7 Bots"


def test_entry_has_an_advancement_tab(entry):
    assert [entry.tabs.tabText(i) for i in range(entry.tabs.count())] == ["Awards", "Advancement"]
    assert entry.nextEventEdit.text() == "the State Championship"
    assert [entry.advList.item(row).text() for row in range(entry.advList.count())] == ["7  Bots"]
    assert entry.titlePreview.text() == 'Shown as "Advancing to the State Championship"'


def offered(picker):
    return [picker.itemData(i) for i in range(picker.count())]


def test_entry_offers_only_teams_not_yet_advancing(entry):
    assert offered(entry.advPicker) == [None, 9, 42]  # 7 is already advancing
    entry.advPicker.setTeam(42)
    entry.advAddButton.click()
    assert offered(entry.advPicker) == [None, 9] and entry.advPicker.team() is None
    entry.advList.setCurrentRow(0)
    entry.removeAdvancing()  # Team 7
    assert offered(entry.advPicker) == [None, 7, 9]


def test_entry_adds_and_orders_advancing_teams(entry):
    entry.advPicker.setTeam(42)
    entry.advAddButton.click()
    entry.advPicker.setTeam(9)
    entry.advAddButton.click()
    entry.moveAdvancing(-1)
    assert entry.advancing == [7, 9, 42] and entry.changed
    entry.advList.setCurrentRow(0)
    entry.removeAdvancing()
    assert entry.advancing == [9, 42]
    entry.nextEventEdit.clear()
    entry.onNextEventEdited("")
    assert entry.titlePreview.text() == 'Shown as "Advancing from this event"'
    assert entry.enteredAdvancement() == Advancement("", [9, 42])


def test_entry_limits_advancing_teams(entry, monkeypatch):
    teams = [Team(f"Team {n}", 500 + n, from_db=True) for n in range(13)]
    entry.getTeams = lambda: teams
    entry.refreshTeams()
    entry.advancing = []
    for team in teams:
        entry.advPicker.setTeam(team.number)
        entry.addAdvancing()
    assert len(entry.advancing) == Awards.MAX_ADVANCING == 12
    assert not entry.advAddButton.isEnabled() and entry.advCount.text() == "12 of 12 teams"


# The blank screen

def test_blank_screen_hides_the_award_text(audience, monkeypatch):
    screens = built(audience, monkeypatch)
    audience.setEventInfo("Fall Qualifier", "")
    audience.setMode(Audience.AWARDS)
    audience.showAwardStep(Awards.Step(Awards.BLANK))
    screen, args = screens[-1]
    assert screen == "award_winner" and args["values"] == {"event_name": "Fall Qualifier"}
    assert set(args["hidden"]) == {"award_name", "place_badge", "team_number", "team_name"}


def test_show_blank_then_back_returns_to_the_step(control, audience):
    control.goTo(4)  # Robot Performance: intro
    control.blankButton.click()
    assert control.blank and audience.awardStep.kind == Awards.BLANK
    assert control.currentRow() == 4 and control.nowLabel.text() == "Blank screen"
    assert control.nowDetail.text() == "Back returns to: Robot Performance, Intro"
    assert not control.blankButton.isEnabled()
    QTest.keyClick(control, Qt.Key.Key_Left)
    assert not control.blank and control.currentRow() == 4 and audience.awardStep == control.steps[4]


def test_next_after_blank_carries_on(control, audience):
    control.goTo(4)
    control.showBlank()
    QTest.keyClick(control, Qt.Key.Key_Space)
    assert not control.blank and control.currentRow() == 5 and audience.awardStep == control.steps[5]


def test_clicker_blank_key_toggles(control, audience):
    control.goTo(2)
    QTest.keyClick(control, Qt.Key.Key_B)
    assert control.blank and audience.themed.currentScreen() == ("still", "award_winner")
    QTest.keyClick(control, Qt.Key.Key_Period)
    assert not control.blank and audience.awardStep == control.steps[2]


def test_blank_from_the_welcome_screen_can_go_back(control):
    control.showBlank()
    assert control.backButton.isEnabled()
    control.back()
    assert not control.blank and control.currentRow() == 0


def test_edits_while_blank_keep_the_screen_blank(control, audience):
    control.goTo(4)
    control.showBlank()
    Events.publish(Events.AwardsChanged((Award("Core Values", 1, 42), Award("Robot Game", 2, 42, [7, 9]))))
    assert control.blank and audience.awardStep.kind == Awards.BLANK
    assert control.nowDetail.text() == "Back returns to: Robot Game, Intro"
