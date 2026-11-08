import pytest

import TeamCsv
from Team import Team
from TeamCsv import NO_PIT, TeamRecord, parseTeams, readTeams, writeTeams


def write(tmp_path, text, encoding="utf-8"):
    path = tmp_path / "teams.csv"
    path.write_bytes(text.encode(encoding))
    return str(path)


# --- Reading the current format -------------------------------------------------------

def test_reads_pit_numbers_from_the_current_format():
    teams = parseTeams([
        "Pit #,Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score",
        "3,Bricks,42,180,,95",
        "1,Gears,7,,,",
    ])
    assert teams == [
        TeamRecord("Bricks", 42, 3, [180, None, 95]),
        TeamRecord("Gears", 7, 1, [None, None, None]),
    ]


def test_blank_pit_in_the_current_format_means_no_pit():
    teams = parseTeams(["Pit #,Team Name,Team Number", ",Bricks,42"])
    assert teams[0].pit == NO_PIT


@pytest.mark.parametrize("header", ["Pit #", "Pit", "pit number", " PIT  # "])
def test_pit_column_header_is_matched_loosely(header):
    teams = parseTeams([f"{header},Team Name,Team Number", "5,Bricks,42"])
    assert teams[0].pit == 5


# --- Reading the older format ---------------------------------------------------------

def test_reads_the_older_format_without_a_pit_column():
    teams = parseTeams([
        "Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score",
        "Bricks,42,180,200,-1",
    ])
    # -1 was how older exports marked unplayed rounds
    assert teams == [TeamRecord("Bricks", 42, NO_PIT, [180, 200, None])]


def test_reads_a_plain_team_list_without_score_columns():
    teams = parseTeams(["Team Name,Team Number", "Bricks,42", "Gears,7"])
    assert teams == [TeamRecord("Bricks", 42), TeamRecord("Gears", 7)]


def test_columns_are_found_by_name_not_position():
    teams = parseTeams(["Team Number,Round 2 Score,Team Name,Pit #", "42,150,Bricks,9"])
    assert teams == [TeamRecord("Bricks", 42, 9, [None, 150, None])]


# --- Robustness -----------------------------------------------------------------------

def test_blank_and_unparseable_scores_are_unplayed_rounds():
    teams = parseTeams(["Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score",
                        "Bricks,42, ,n/a,0"])
    assert teams[0].scores == [None, None, 0]


def test_short_rows_are_padded_with_unplayed_rounds():
    teams = parseTeams(["Pit #,Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score",
                        "2,Bricks,42,100"])
    assert teams[0].scores == [100, None, None]


def test_blank_rows_are_skipped():
    teams = parseTeams(["Team Name,Team Number", "Bricks,42", "", ",,", "Gears,7"])
    assert [t.number for t in teams] == [42, 7]


def test_names_with_commas_and_quotes_are_read():
    teams = parseTeams(['Team Name,Team Number', '"Bricks, Inc. ""The Best""",42'])
    assert teams[0].name == 'Bricks, Inc. "The Best"'


def test_empty_file_has_no_teams():
    assert parseTeams([]) == []


def test_missing_required_columns_is_an_error():
    with pytest.raises(ValueError, match="Team Number"):
        parseTeams(["Pit #,Team Name", "1,Bricks"])


def test_invalid_team_number_is_an_error_naming_the_line():
    with pytest.raises(ValueError, match="Line 3"):
        parseTeams(["Team Name,Team Number", "Bricks,42", "Gears,seven"])


# --- Files and encodings --------------------------------------------------------------

def test_reads_a_file_with_an_excel_byte_order_mark(tmp_path):
    path = write(tmp_path, "﻿Pit #,Team Name,Team Number\r\n4,Bricks,42\r\n")
    assert readTeams(path) == [TeamRecord("Bricks", 42, 4)]


def test_reads_a_file_in_a_legacy_encoding(tmp_path, monkeypatch):
    path = write(tmp_path, "Team Name,Team Number\nRobótica,42\n", encoding="cp1252")
    # The fallback uses the system's default encoding; pin it so the test doesn't depend on the OS
    realOpen = open
    monkeypatch.setattr("builtins.open", lambda *a, **kw: realOpen(*a, **{"encoding": "cp1252", **kw}))
    assert readTeams(path)[0].name == "Robótica"


# --- Writing --------------------------------------------------------------------------

def makeTeam(name, number, pit=NO_PIT, scores=(None, None, None)):
    team = Team(name, number, pit, from_db=True)
    for roundNum, score in enumerate(scores, start=1):
        if score is not None:
            team.setScore(roundNum, score, from_db=True)
    return team


def test_writes_the_current_format_sorted_by_pit(tmp_path):
    path = tmp_path / "out.csv"
    writeTeams(str(path), [
        makeTeam("Gears", 7, pit=2, scores=(100, None, 0)),
        makeTeam("Bricks", 42, pit=1, scores=(180, 200, 95)),
    ])
    assert path.read_text(encoding="utf-8-sig").splitlines() == [
        "Pit #,Team Name,Team Number,Round 1 Score,Round 2 Score,Round 3 Score",
        "1,Bricks,42,180,200,95",
        "2,Gears,7,100,,0",
    ]


def test_teams_without_a_pit_are_ordered_by_team_number():
    rows = TeamCsv.formatTeams([makeTeam("B", 30), makeTeam("A", 10), makeTeam("P", 99, pit=20)])
    assert [row[2] for row in rows[1:]] == ["10", "99", "30"]


def test_round_trip_keeps_names_pits_and_scores(tmp_path):
    original = [
        makeTeam("Bricks, Inc.", 42, pit=3, scores=(180, None, 95)),
        makeTeam('The "Gears"', 7, pit=1),
        makeTeam("Robótica", 1234, pit=2, scores=(0, 0, 0)),
    ]
    path = str(tmp_path / "out.csv")
    writeTeams(path, original)

    assert readTeams(path) == [
        TeamRecord('The "Gears"', 7, 1, [None, None, None]),
        TeamRecord("Robótica", 1234, 2, [0, 0, 0]),
        TeamRecord("Bricks, Inc.", 42, 3, [180, None, 95]),
    ]
