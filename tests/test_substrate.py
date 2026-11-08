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


def test_selected_match_survives_a_relaunch(database):
    assert Substrate.loadSelectedMatch() is None

    Events.publish(Events.MatchSelected(4))
    Events.publish(Events.MatchSelected(5))

    substrate = database()

    assert substrate.loadSelectedMatch() == 5


def test_match_starts_are_logged_at_the_time_the_timer_started(database):
    Events.publish(Events.MatchStarted(2, 1762005600.5))
    Events.publish(Events.MatchStarted(1, 1762005000.0))
    Events.publish(Events.MatchStarted(2, 1762006000.25))
    Events.publish(Events.MatchStarted(3))

    substrate = database()

    starts = substrate.retrieveMatchStartTimes()
    assert starts[:2] == [("1", 1762005000.0), ("2", 1762006000.25)]
    assert starts[2][0] == "3" and starts[2][1] > 1762006000


def test_new_database_has_current_schema_version(database, tmp_path):
    (dbFile,) = tmp_path.glob("*.db")
    with sqlite3.connect(dbFile) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == Substrate.SCHEMA_VERSION == 5


def test_awards_survive_a_relaunch(database):
    from Awards import Award
    assert Substrate.loadAwards() == []

    Events.publish(Events.AwardsChanged((Award("Core Values", 1, 42, [7, 9]), Award("Innovation Project", 2))))
    Events.publish(Events.AwardsChanged((Award("Robot Design", 1, 7), Award("Core Values", 2, 42, [9]))))

    substrate = database()

    assert substrate.loadAwards() == [Award("Robot Design", 1, 7, []), Award("Core Values", 2, 42, [9])]


def test_an_older_database_gets_the_awards_table(tmp_path, monkeypatch):
    import importlib
    from Awards import Award

    monkeypatch.chdir(tmp_path)
    with sqlite3.connect("TEST-29991231.db") as db:  # A precreated event database, from before awards
        db.executescript("""
            PRAGMA user_version = 4;
            CREATE TABLE teams(teamnumber type UNIQUE, name, pit);
            CREATE TABLE scores(slug type UNIQUE, teamnumber, round, score, comments);
            CREATE TABLE audit(timestamp, tag, data);
            CREATE TABLE log(timestamp, tag, message);
            CREATE TABLE scoresheets(slug type UNIQUE, teamnumber, round, scoresheet);
            CREATE TABLE meta(key type UNIQUE, value);
            INSERT INTO teams VALUES (42, 'Bricks', 3);
        """)
    db.close()
    importlib.reload(Substrate)
    Substrate.init()
    try:
        assert Substrate.loadAwards() == []
        Events.publish(Events.AwardsChanged((Award("Core Values", 1, 42),)))
        assert Substrate.loadAwards() == [Award("Core Values", 1, 42, [])]
        assert [t.teamnumber for t in Substrate.loadTeams()] == [42]
    finally:
        Substrate.deinit()
    with sqlite3.connect("TEST-29991231.db") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == Substrate.SCHEMA_VERSION
    db.close()


def test_advancement_survives_a_relaunch(database):
    from Awards import Advancement
    assert Substrate.loadAdvancement() == Advancement("", [])

    Events.publish(Events.AdvancementChanged("the State Championship", (42, 7, 9)))
    Events.publish(Events.AdvancementChanged("the State Championship", (9, 42)))

    substrate = database()

    assert substrate.loadAdvancement() == Advancement("the State Championship", [9, 42])


def test_a_version_5_database_without_the_advancement_table_gets_it(database, tmp_path):
    from Awards import Advancement
    (dbFile,) = tmp_path.glob("*.db")
    Substrate.loadAwards()  # Every write so far has finished
    with sqlite3.connect(dbFile) as db:  # Made before the advancement table was added to version 5
        db.execute("DROP TABLE advancement")
    db.close()
    substrate = database()
    Events.publish(Events.AdvancementChanged("", (7,)))
    assert substrate.loadAdvancement() == Advancement("", [7])
