import Events
from Team import Team, UNRANKED, rank


def test_team_without_scores_is_unranked():
    teams = [Team("Bricks", 42)]
    rank(teams)
    assert teams[0].rank == UNRANKED


def test_a_score_of_zero_ranks_above_an_unplayed_team():
    unplayed = Team("Unplayed", 1)
    zero = Team("Zero", 2)
    zero.setScore(1, 0)

    teams = [unplayed, zero]
    rank(teams)

    assert [t.number for t in teams] == [2, 1]
    assert zero.rank == 1
    assert unplayed.rank == UNRANKED


def test_ranking_uses_best_then_second_and_third_best_then_lower_team_number():
    a = Team("A", 10)
    for roundNum, score in [(1, 200), (2, 100), (3, 50)]:
        a.setScore(roundNum, score)
    b = Team("B", 20)
    for roundNum, score in [(1, 100), (2, 200), (3, 60)]:  # same best and second best, better third
        b.setScore(roundNum, score)
    c = Team("C", 30)
    c.setScore(2, 300)  # best single score
    d = Team("D", 5)
    for roundNum, score in [(1, 50), (2, 200), (3, 100)]:  # identical to A, lower number
        d.setScore(roundNum, score)

    teams = [a, b, c, d]
    rank(teams)

    assert [(t.number, t.rank) for t in teams] == [(30, 1), (20, 2), (5, 3), (10, 4)]


def test_high_score_is_the_best_played_round():
    team = Team("Bricks", 42)
    assert team.highScoreIndex is None
    team.setScore(1, 0)
    team.setScore(3, 150)
    assert team.highScoreIndex == 2


def test_clearing_the_only_score_makes_a_team_unranked_again(published):
    team = Team("Bricks", 42)
    team.setScore(2, 120)
    team.clearScore(2)

    teams = [team]
    rank(teams)

    assert team.scores == [None, None, None]
    assert team.rank == UNRANKED
    assert team.highScoreIndex is None
    assert published[-1] == Events.ScoreCleared(42, 2)


def test_clearing_an_unplayed_round_publishes_nothing(published):
    team = Team("Bricks", 42)
    published.clear()
    team.clearScore(1)
    assert published == []


def test_new_team_and_scores_are_published(published):
    team = Team("Bricks", "42", pit=3)
    team.setScore(1, 180, {"m01a": "true"})

    assert published == [
        Events.TeamAdded(42, "Bricks", 3),
        Events.ScoreUpdated(42, 1, 180, {"m01a": "true"}),
    ]


def test_teams_and_scores_restored_from_the_database_are_not_published(published):
    team = Team("Bricks", 42, from_db=True)
    team.setScore(1, 180, from_db=True)
    assert published == []


def test_scoresheets_are_kept_with_their_scores():
    team = Team("Bricks", 42, from_db=True)
    team.setScore(1, 180, {"m01a": "true"}, from_db=True)
    team.setScore(2, 90)
    assert team.scoresheets == [{"m01a": "true"}, None, None]


def test_a_score_entered_without_a_scoresheet_replaces_the_rounds_scoresheet():
    team = Team("Bricks", 42)
    team.setScore(1, 180, {"m01a": "true"})
    team.setScore(1, 200)
    assert team.scoresheets[0] is None


def test_clearing_a_score_forgets_its_scoresheet():
    team = Team("Bricks", 42)
    team.setScore(3, 180, {"m01a": "true"})
    team.clearScore(3)
    assert team.scoresheets == [None, None, None]
