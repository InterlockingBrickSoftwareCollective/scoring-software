import sqlite3

import Events
import Substrate


def scores(substrate):
    return {(s.teamnumber, s.round): (s.score, s.scoresheet) for s in substrate.loadScores()}


def test_teams_scores_and_scoresheets_survive_a_relaunch(database):
    Events.publish(Events.TeamAdded(42, "Bricks", 3))
    Events.publish(Events.ScoreUpdated(42, 1, 180, {"m01a": "true", "m02b": "2"}))
    Events.publish(Events.ScoreUpdated(42, 2, 0))

    substrate = database()

    assert [(t.teamnumber, t.name, t.pit) for t in substrate.loadTeams()] == [(42, "Bricks", 3)]
    assert scores(substrate) == {
        (42, 1): (180, {"m01a": "true", "m02b": "2"}),
        (42, 2): (0, None),
    }


def test_team_updates_replace_the_team(database):
    Events.publish(Events.TeamAdded(42, "Bricks", 3))
    Events.publish(Events.TeamUpdated(42, "Blocks", 4))
    assert [(t.teamnumber, t.name, t.pit) for t in Substrate.loadTeams()] == [(42, "Blocks", 4)]


def test_cleared_score_and_its_scoresheet_are_gone_after_a_relaunch(database):
    Events.publish(Events.TeamAdded(42, "Bricks", 3))
    Events.publish(Events.ScoreUpdated(42, 1, 180, {"m01a": "true"}))
    Events.publish(Events.ScoreUpdated(42, 2, 90))
    Events.publish(Events.ScoreCleared(42, 1))

    substrate = database()

    assert scores(substrate) == {(42, 2): (90, None)}

    # Scoring the round again must not bring back the old scoresheet
    Events.publish(Events.ScoreUpdated(42, 1, 100))
    assert scores(substrate)[(42, 1)] == (100, None)


def test_score_entered_without_a_scoresheet_replaces_the_previous_scoresheet(database):
    Events.publish(Events.TeamAdded(42, "Bricks", 3))
    Events.publish(Events.ScoreUpdated(42, 1, 180, {"m01a": "true"}))
    Events.publish(Events.ScoreUpdated(42, 1, 150))
    assert scores(Substrate) == {(42, 1): (150, None)}


def test_deleting_a_team_deletes_its_scores(database):
    Events.publish(Events.TeamAdded(42, "Bricks", 3))
    Events.publish(Events.TeamAdded(7, "Studs", 1))
    Events.publish(Events.ScoreUpdated(42, 1, 180, {"m01a": "true"}))
    Events.publish(Events.ScoreUpdated(7, 1, 60))
    Events.publish(Events.TeamDeleted(42))

    substrate = database()

    assert [t.teamnumber for t in substrate.loadTeams()] == [7]
    assert scores(substrate) == {(7, 1): (60, None)}


def test_new_database_has_current_schema_version(database, tmp_path):
    (dbFile,) = tmp_path.glob("*.db")
    with sqlite3.connect(dbFile) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
