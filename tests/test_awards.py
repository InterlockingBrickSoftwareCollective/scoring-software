import pytest

import Awards
from Awards import Advancement, Award, Step


def test_ordinals():
    assert [Awards.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 103, 111)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "103rd", "111th"]


def test_place_labels_only_with_runners_up():
    alone = Award("Core Values", 1, 42)
    assert Awards.placeLabel(alone, 1) is None
    contested = Award("Robot Performance", 2, 42, [7, 9])
    assert [Awards.placeLabel(contested, place) for place in (1, 2, 3)] == ["WINNER", "2ND PLACE", "3RD PLACE"]


def summary(steps):
    return [(s.kind, s.award.name if s.award else None, s.place, s.team, s.revealed) for s in steps]


def test_steps_go_from_last_place_up_to_the_winner_in_presentation_order():
    awards = [Award("Robot Performance", 2, 42, [7]), Award("Core Values", 1, 5)]
    assert summary(Awards.presentationSteps(awards)) == [
        ("welcome", None, 0, None, False),
        ("intro", "Core Values", 0, None, False),
        ("reveal", "Core Values", 1, 5, False),
        ("reveal", "Core Values", 1, 5, True),
        ("intro", "Robot Performance", 0, None, False),
        ("reveal", "Robot Performance", 2, 7, False),
        ("reveal", "Robot Performance", 2, 7, True),
        ("reveal", "Robot Performance", 1, 42, False),
        ("reveal", "Robot Performance", 1, 42, True),
        ("thanks", None, 0, None, False),
    ]


def test_an_award_without_a_winner_yet_has_only_its_intro():
    assert summary(Awards.presentationSteps([Award("Innovation Project", 1)])) == [
        ("welcome", None, 0, None, False), ("intro", "Innovation Project", 0, None, False),
        ("thanks", None, 0, None, False)]


def test_no_awards_is_just_the_welcome_screen():
    assert summary(Awards.presentationSteps([])) == [("welcome", None, 0, None, False), ("thanks", None, 0, None, False)]
    assert summary(Awards.presentationSteps([], thanksScreen=False)) == [("welcome", None, 0, None, False)]


def test_advancing_teams_come_after_the_awards_one_at_a_time():
    advancement = Advancement("the State Championship", [9, 42, 7])
    steps = Awards.presentationSteps([Award("Core Values", 1, 5)], advancement)
    assert [(s.kind, s.shown, s.team) for s in steps[4:]] == [
        ("advancing_title", 0, None),
        ("advancing", 0, None),
        ("advancing", 1, 9),
        ("advancing", 2, 42),
        ("advancing", 3, 7),
        ("thanks", 0, None),
    ]
    assert len({s.key() for s in steps}) == len(steps)


def test_no_advancing_steps_without_teams_or_the_screen():
    assert [s.kind for s in Awards.presentationSteps([], Advancement("State", []))] == ["welcome", "thanks"]
    assert [s.kind for s in Awards.presentationSteps([], Advancement("State", [9]), advancingScreen=False)] == \
        ["welcome", "thanks"]


def test_advancing_titles():
    assert Advancement("the State Championship").title() == "Advancing to the State Championship"
    assert Advancement("").title() == "Advancing from this event"


def test_advancing_descriptions():
    advancement = Advancement("State", [9, 42])
    assert Awards.describe(Step(Awards.ADVANCING_TITLE, advancement=advancement)) == "Advancing: title only"
    assert Awards.describe(Step(Awards.ADVANCING, advancement=advancement)).strip() == "Blank list (2 teams)"
    assert Awards.describe(Step(Awards.ADVANCING, team=42, advancement=advancement, shown=2), "Bricks").strip() == "2: 42 Bricks"
    assert Awards.describe(Step(Awards.THANKS)) == "Thank you screen"


def test_step_keys_survive_a_renamed_award():
    before = Awards.presentationSteps([Award("Core Valus", 1, 5)])
    after = Awards.presentationSteps([Award("Core Values", 1, 5)])
    assert [s.key() for s in before] == [s.key() for s in after]


def test_descriptions():
    award = Award("Robot Performance", 1, 42, [7])
    assert Awards.describe(Step(Awards.WELCOME)) == "Welcome screen"
    assert Awards.describe(Step(Awards.INTRO, award)) == "Robot Performance: intro"
    assert Awards.describe(Step(Awards.REVEAL, award, 2, 7)).strip() == "2nd place: blank display"
    assert Awards.describe(Step(Awards.REVEAL, award, 1, 42, True), "Bricks").strip() == "Winner: 42 Bricks"
