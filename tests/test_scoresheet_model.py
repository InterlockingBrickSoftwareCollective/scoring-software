import xml.etree.ElementTree as ET

import pytest
from PyQt6.QtCore import QPoint

from ScoresheetModel import Game, IncompleteScoresheet

DEFINITION = """
<game name="test" year="2026">
  <image>aGVsbG8=</image>
  <mission name="Equipment inspection">
    <task eh_task_name="m00" x="55" y="579" width="808">
      <option x="876" y="523" width="58" height="38" value="false" />
      <option x="975" y="523" width="58" height="38" value="true" />
    </task>
  </mission>
  <mission number="1" name="Drone Survey">
    <task eh_task_name="m01a">
      <option x="877" y="760" width="58" height="38" value="false" />
      <option x="976" y="760" width="58" height="38" value="true" />
    </task>
    <task eh_task_name="m01b" x="57" y="964" width="439">
      <option x="881" y="934" width="33" height="38" value="0" />
      <option x="921" y="934" width="33" height="38" value="1" />
      <option x="962" y="934" width="33" height="38" value="2" />
    </task>
  </mission>
</game>
"""


@pytest.fixture
def game():
    return Game.from_xml(ET.fromstring(DEFINITION))


def test_definition_is_read_in_scoresheet_order(game):
    assert [mission.label for mission in game.missions] == ["Equipment inspection", "1"]
    assert [task.key for task in game.tasks] == ["m00", "m01a", "m01b"]
    assert [option.value for option in game.tasks[2].options] == ["0", "1", "2"]
    assert game.tasks[0].line == (55, 579, 808)
    assert game.tasks[1].line is None  # Older definitions have no keyboard entry line


def test_clicking_an_option_box_toggles_it_and_unselects_its_siblings(game):
    task, option = game.option_at(QPoint(880, 530))
    assert (task.key, option.value) == ("m00", "false")

    task.toggle(option)
    assert game.selections() == {"m00": "false"}
    task.toggle(task.options[1])
    assert game.selections() == {"m00": "true"}
    task.toggle(task.options[1])
    assert game.selections() == {}

    assert game.option_at(QPoint(0, 0)) is None


def test_digits_pick_yes_no_answers_or_values(game):
    yes_no, count = game.tasks[1], game.tasks[2]
    assert yes_no.option_for_digit(1).value == "true"
    assert yes_no.option_for_digit(0).value == "false"
    assert yes_no.option_for_digit(2) is None
    assert count.option_for_digit(2).value == "2"
    assert count.option_for_digit(3) is None


def test_a_loaded_scoresheet_round_trips(game):
    scoresheet = {"m00": "true", "m01a": "false", "m01b": "2"}
    game.load(scoresheet)
    assert game.scoresheet() == scoresheet


def test_loading_replaces_selections_and_leaves_unrecognized_values_unselected(game):
    game.load({"m00": "true", "m01a": "true", "m01b": "1"})
    game.load({"m00": "false", "m01a": "maybe", "retired_task": "true"})

    assert game.selections() == {"m00": "false"}
    with pytest.raises(IncompleteScoresheet) as err:
        game.scoresheet()
    assert err.value.mission.label == "1"


def test_clearing_unselects_everything(game):
    game.load({"m00": "true", "m01a": "false", "m01b": "2"})
    game.clear()
    assert game.selected_options() == []


def test_placeholder_scoresheet_answers_every_task(game):
    assert game.placeholder_scoresheet() == {"m00": "false", "m01a": "false", "m01b": "0"}
