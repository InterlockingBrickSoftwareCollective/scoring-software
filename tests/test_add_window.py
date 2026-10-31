import pytest

from AddWindow import InvalidTeam, validateTeam
from Team import Team


def test_valid_team_is_trimmed():
    assert validateTeam(" 1234 ", "  Brick Builders ", []) == (1234, "Brick Builders")


@pytest.mark.parametrize("numberText", ["", "   "])
def test_blank_number_is_rejected(numberText):
    with pytest.raises(InvalidTeam) as err:
        validateTeam(numberText, "Brick Builders", [])
    assert err.value.field == "number"
    assert err.value.message == "Enter a team number."


@pytest.mark.parametrize("numberText", ["abc", "12a", "-5", "1.5", "0", "²"])
def test_invalid_number_is_rejected(numberText):
    with pytest.raises(InvalidTeam) as err:
        validateTeam(numberText, "Brick Builders", [])
    assert err.value.field == "number"
    assert f'"{numberText}" isn\'t a valid team number' in err.value.message


def test_duplicate_number_is_rejected_without_touching_the_existing_team(published):
    existing = Team("Original Name", 1234)
    published.clear()

    with pytest.raises(InvalidTeam) as err:
        validateTeam("1234", "New Name", [existing])

    assert err.value.field == "number"
    assert "Team 1234 (Original Name) has already been added" in err.value.message
    assert existing.name == "Original Name"
    assert published == []


@pytest.mark.parametrize("nameText", ["", "   "])
def test_blank_name_is_rejected(nameText):
    with pytest.raises(InvalidTeam) as err:
        validateTeam("1234", nameText, [])
    assert err.value.field == "name"
    assert err.value.message == "Enter a team name."
