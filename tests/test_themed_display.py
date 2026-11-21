import copy
import glob
import json
import os
import re
import xml.etree.ElementTree as ET

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QByteArray
from PyQt6.QtGui import QFontDatabase, QFontMetricsF, QFont
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QApplication

import faketheme
import ResourceManager
import ThemedDisplay
from datetime import datetime

from Team import Team, rank
from ThemedDisplay import RecentScore

SVG = "{http://www.w3.org/2000/svg}"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def theme(app, tmp_path):
    return ThemedDisplay.Theme(faketheme.write(str(tmp_path / "display")))


def parse(svg: bytes):
    root = ET.fromstring(svg)
    return root, {el.get("id"): el for el in root.iter() if el.get("id")}


def makeTeams(count, scored=None):
    teams = []
    for i in range(count):
        team = Team(f"Team {i + 1}", 100 + i, from_db=True)
        if scored is None or i < scored:
            team.setScore(1, 50 + i * 10, from_db=True)
        teams.append(team)
    rank(teams)
    return teams


# Loading

def test_no_theme_without_a_resource_pack(monkeypatch):
    monkeypatch.setattr(ResourceManager, "_temp_resource_dir", None)
    assert ThemedDisplay.Theme.fromResourcePack() is None


def test_no_theme_when_the_pack_has_no_display_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(ResourceManager, "_temp_resource_dir", str(tmp_path))
    assert ThemedDisplay.Theme.fromResourcePack() is None


def test_loads_the_packs_theme(app, monkeypatch, tmp_path):
    faketheme.write(str(tmp_path / "display"))
    monkeypatch.setattr(ResourceManager, "_temp_resource_dir", str(tmp_path))
    theme = ThemedDisplay.Theme.fromResourcePack()
    assert theme.name == "TESTGLOW"
    assert theme.hasScreen("standings") and not theme.hasScreen("thank_you")


def test_ignores_a_theme_from_a_newer_contract(app, monkeypatch, tmp_path):
    faketheme.write(str(tmp_path / "display"), dict(faketheme.THEME, themeVersion=2))
    monkeypatch.setattr(ResourceManager, "_temp_resource_dir", str(tmp_path))
    assert ThemedDisplay.Theme.fromResourcePack() is None


# Filling in templates

def test_fills_in_fields_and_their_copies(theme):
    root, ids = parse(theme.build("welcome", values={"event_name": "Fall Qualifier", "event_date": "Oct 3"}))
    assert ids["event_name"].text == "Fall Qualifier"
    assert ids["event_name__glow"].text == "Fall Qualifier"
    assert ids["event_date"].text == "Oct 3"
    assert ids["welcome_eyebrow"].text == "WELCOME TO THE"  # Not filled in, so unchanged


def test_escapes_text(theme):
    svg = theme.build("award_winner", values={"team_name": "Bots & <Bolts>"})
    assert b"Bots &amp; &lt;Bolts&gt;" in svg
    assert QSvgRenderer(QByteArray(svg)).isValid()


def test_leaves_the_template_unchanged(theme):
    theme.build("welcome", values={"event_name": "Changed"})
    _, ids = parse(theme.build("welcome"))
    assert ids["event_name"].text == "[EVENT NAME]"


def width(text, size, weight):
    font = QFont("Roboto")
    font.setPixelSize(100)
    font.setWeight(QFont.Weight(weight))
    return QFontMetricsF(font).horizontalAdvance(text) * size / 100


def test_short_text_keeps_its_size(theme):
    _, ids = parse(theme.build("welcome", values={"event_name": "Qualifier"}))
    assert float(ids["event_name"].get("font-size")) == 128


def test_long_text_shrinks_to_fit(theme):
    name = "Greater Springfield Regional"
    _, ids = parse(theme.build("welcome", values={"event_name": name}))
    size = float(ids["event_name"].get("font-size"))
    assert 80 <= size < 128
    assert width(name, size, 900) <= 1440
    assert ids["event_name__glow"].get("font-size") == ids["event_name"].get("font-size")


def test_text_too_long_for_one_line_wraps_and_makes_room(theme):
    name = "Greater Springfield Area FIRST LEGO League Challenge Championship"
    root, ids = parse(theme.build("welcome", values={"event_name": name}))
    first, second = ids["event_name"], ids["event_name__line2"]
    assert f"{first.text} {second.text}" == name
    size = float(first.get("font-size"))
    assert size >= 80
    assert float(first.get("y")) < 518 < float(second.get("y"))
    # The glow wraps the same way
    assert ids["event_name__glow__line2"].text == second.text
    # The lines above and below move out of the way
    assert ids["welcome_eyebrow"].get("transform").startswith("translate(0 -")
    assert ids["event_date"].get("transform").startswith("translate(0 ")
    assert QSvgRenderer(QByteArray(ET.tostring(root))).isValid()


def test_one_line_text_that_still_doesnt_fit_is_elided(theme):
    name = "The Extraordinarily Long-Named Robotics Team From Somewhere"
    _, ids = parse(theme.build("standings", values={"row1_name": name}))
    shown = ids["row1_name"].text
    assert shown.endswith("…") and len(shown) < len(name)
    assert float(ids["row1_name"].get("font-size")) == 22
    assert width(shown, 22, 300) <= 510 + 1


def test_copies_of_a_different_size_scale_alike(theme):
    name = "x" * 120
    _, ids = parse(theme.build("award_winner", values={"event_name": name}))
    footer = float(ids["event_name"].get("font-size"))
    header = float(ids["event_name__header"].get("font-size"))
    assert footer < 28
    assert header == pytest.approx(footer * 26 / 28, abs=0.02)


def test_hides_shows_and_sets_attributes(theme):
    _, ids = parse(theme.build("standings", hidden=["row8"], shown=["row1_top"],
                               attributes={"row1_rank": {"fill": "#ff0000"}}))
    assert ids["row8"].get("display") == "none"
    assert ids["row1_top"].get("display") is None
    assert ids["row1_rank"].get("fill") == "#ff0000"


# Standings

def test_standings_rows_follow_the_ranking():
    teams = makeTeams(3, scored=2)
    next(t for t in teams if t.number == 100).setScore(2, 300, from_db=True)
    rank(teams)
    rows = ThemedDisplay.standingsRows(teams)
    assert [(r["rank"], r["team"]) for r in rows] == [("1", "100"), ("2", "101"), ("NP", "102")]
    assert rows[0]["best"] == "300" and rows[0]["r1"] == "50" and rows[0]["r2"] == "300" and rows[0]["r3"] == "—"
    assert rows[2]["best"] == "—"


def test_standings_pages(theme):
    rows = ThemedDisplay.standingsRows(makeTeams(19))
    assert ThemedDisplay.standingsPageCount(len(rows), 8) == 3

    first = ThemedDisplay.standingsPage(theme, rows, 1)
    assert first["values"]["row1_rank"] == "1" and first["values"]["row8_rank"] == "8"
    assert "row1_top" in first["shown"] and "row1_bg" in first["hidden"]
    assert "row2_top" in first["hidden"] and "row2_bg" in first["shown"]
    assert first["attributes"]["row3_rank"]["fill"] == faketheme.ACCENT
    assert first["attributes"]["row4_rank"]["fill"] == faketheme.WHITE
    assert first["values"]["page_label"] == "PAGE 1 OF 3"

    last = ThemedDisplay.standingsPage(theme, rows, 3)
    assert last["values"]["row1_rank"] == "17" and last["values"]["row3_rank"] == "19"
    assert {"row4", "row5", "row6", "row7", "row8"} <= set(last["hidden"])
    assert last["attributes"]["row1_rank"]["fill"] == faketheme.WHITE
    assert last["dots"] == (3, 3)


def test_unranked_teams_are_never_highlighted(theme):
    page = ThemedDisplay.standingsPage(theme, ThemedDisplay.standingsRows(makeTeams(2, scored=0)), 1)
    assert page["values"]["row1_rank"] == "NP"
    assert page["attributes"]["row1_rank"]["fill"] == faketheme.WHITE
    assert "row1_top" in page["hidden"]


def test_one_page_has_no_page_label_or_dots(theme):
    page = ThemedDisplay.standingsPage(theme, ThemedDisplay.standingsRows(makeTeams(5)), 1)
    assert "page_label" in page["hidden"]
    _, ids = parse(theme.build("standings", **page))
    assert len(list(ids["page_dots"])) == 0


def test_page_dots_show_the_current_page(theme):
    page = ThemedDisplay.standingsPage(theme, ThemedDisplay.standingsRows(makeTeams(30)), 2)
    _, ids = parse(theme.build("standings", **page))
    dots = list(ids["page_dots"])
    assert [d.get("class") for d in dots] == ["done", "active", "todo", "todo"]
    assert dots[1].tag == SVG + "rect" and float(dots[1].get("width")) == 56
    # Centered on the screen
    left = float(dots[0].get("cx")) - 8
    right = float(dots[3].get("cx")) + 8
    assert (left + right) / 2 == pytest.approx(960)


# Timer

def test_format_time():
    assert [ThemedDisplay.formatTime(s) for s in (150, 28, 0, -3, 600)] == ["2:30", "0:28", "0:00", "0:00", "10:00"]


def test_timer_screen(theme):
    _, ids = parse(theme.build("timer", **ThemedDisplay.timerScreen(theme, "Match 12", 150, 150, False)))
    assert ids["timer_title"].text == "Match 12" and ids["timer_title__glow"].text == "Match 12"
    assert ids["timer_time"].text == "2:30"
    assert ids["timer_time"].get("fill") == faketheme.WHITE
    assert ids["timer_progress_fill"].get("fill") == faketheme.ACCENT
    assert float(ids["timer_progress_fill"].get("width")) == 1120


def test_timer_progress_empties_as_time_runs_out(theme):
    _, ids = parse(theme.build("timer", **ThemedDisplay.timerScreen(theme, "Match 12", 75, 150, False)))
    assert float(ids["timer_progress_fill"].get("width")) == 560
    _, ids = parse(theme.build("timer", **ThemedDisplay.timerScreen(theme, "Match 12", 1, 150, True)))
    assert float(ids["timer_progress_fill"].get("width")) == 18  # Never narrower than the bar is tall
    _, ids = parse(theme.build("timer", **ThemedDisplay.timerScreen(theme, "Match 12", 0, 150, True)))
    assert ids["timer_progress_fill"].get("display") == "none"


def test_timer_warning_look(theme):
    _, ids = parse(theme.build("timer", **ThemedDisplay.timerScreen(theme, "Practice timer", 28, 300, True)))
    assert ids["timer_time"].get("fill") == faketheme.WARNING
    assert ids["timer_time__glow"].get("fill") == faketheme.WARNING
    assert ids["timer_progress_fill"].get("fill") == faketheme.WARNING


def test_practice_timer_before_any_practice_has_no_progress(theme):
    _, ids = parse(theme.build("timer", **ThemedDisplay.timerScreen(theme, "Practice timer", 0, 0, False)))
    assert ids["timer_time"].text == "0:00"
    assert ids["timer_progress_fill"].get("display") == "none"


def test_hiding_a_field_hides_its_copies(theme):
    _, ids = parse(theme.build("timer", hidden=["timer_time"]))
    assert ids["timer_time"].get("display") == "none"
    assert ids["timer_time__glow"].get("display") == "none"


def test_timer_layer_has_only_the_time_and_progress(theme):
    root, ids = parse(theme.build("timer", only=ThemedDisplay.TIMER_LAYER))
    assert {"timer_time", "timer_time__glow", "timer_progress", "timer_progress_fill"} <= set(ids)
    assert "timer_title" not in ids
    assert root.find("{http://www.w3.org/2000/svg}defs") is not None  # Filters stay available


def test_timer_background_is_cached_while_the_title_stays(themed, monkeypatch):
    built = []
    original = themed.theme.build
    monkeypatch.setattr(themed.theme, "build", lambda screen, **kw: built.append(kw) or original(screen, **kw))
    themed.showTimer("Match 3", 150, 150, False)
    themed.showTimer("Match 3", 149, 150, False)
    assert sum(1 for kw in built if kw.get("only") is None) == 1  # One background, two time layers
    themed.showTimer("Match 4", 150, 150, False)
    assert sum(1 for kw in built if kw.get("only") is None) == 2


def test_show_timer_stops_the_rotation(themed):
    themed.start()
    themed.showTimer("Match 3", 150, 150, False)
    assert not themed.isRunning() and not themed._timer.isActive()
    themed.start()
    assert themed.currentScreen() == ("standings", 1) and themed._timer.isActive()


def test_expired_timer_turns_red(theme):
    _, ids = parse(theme.build("timer", **ThemedDisplay.timerScreen(theme, "Match 3", 0, 150, True, True)))
    assert ids["timer_time"].get("fill") == faketheme.EXPIRED
    assert ids["timer_time__glow"].get("fill") == faketheme.EXPIRED


def test_expired_timer_falls_back_to_the_warning_look(app, tmp_path):
    spec = json.loads(json.dumps(faketheme.THEME))
    del spec["screens"]["timer"]["states"]["expired"]
    old = ThemedDisplay.Theme(faketheme.write(str(tmp_path / "old"), spec))
    _, ids = parse(old.build("timer", **ThemedDisplay.timerScreen(old, "Match 3", 0, 150, False, True)))
    assert ids["timer_time"].get("fill") == faketheme.WARNING


# Clock

def test_clock_parts():
    assert ThemedDisplay.clockParts(datetime(2027, 1, 16, 10, 5)) == ("10", "05", "a")
    assert ThemedDisplay.clockParts(datetime(2027, 1, 16, 0, 30)) == ("12", "30", "a")
    assert ThemedDisplay.clockParts(datetime(2027, 1, 16, 12, 0)) == ("12", "00", "p")
    assert ThemedDisplay.clockParts(datetime(2027, 1, 16, 21, 7)) == ("9", "07", "p")
    assert ThemedDisplay.clockText(datetime(2027, 1, 16, 21, 7)) == "9:07 p"


def test_clock_colon_blinks(theme):
    _, ids = parse(theme.build("clock", **ThemedDisplay.clockScreen(theme, datetime(2027, 1, 16, 10, 5, 2))))
    assert ids["clock_hours"].text == "10" and ids["clock_minutes"].text == "05" and ids["clock_suffix"].text == "a"
    assert ids["clock_hours__glow"].text == "10"
    assert ids["clock_colon"].get("display") is None
    _, ids = parse(theme.build("clock", **ThemedDisplay.clockScreen(theme, datetime(2027, 1, 16, 10, 5, 3))))
    assert ids["clock_colon"].get("display") == "none"
    assert ids["clock_colon__glow"].get("display") == "none"


def test_clock_keeps_a_one_digit_hour_centered(theme):
    _, ids = parse(theme.build("clock", **ThemedDisplay.clockScreen(theme, datetime(2027, 1, 16, 10, 5))))
    assert ids["clock_time"].get("transform") is None
    _, ids = parse(theme.build("clock", **ThemedDisplay.clockScreen(theme, datetime(2027, 1, 16, 9, 5))))
    digit = width("0", 440, 900)
    shift = float(re.match(r"translate\((-?[0-9.]+) 0\)", ids["clock_time"].get("transform")).group(1))
    assert shift == pytest.approx(-digit / 2, abs=0.5)
    assert ids["clock_time__glow"].get("transform") == ids["clock_time"].get("transform")


def test_show_clock_caches_everything_but_the_time(themed, monkeypatch):
    built = []
    original = themed.theme.build
    monkeypatch.setattr(themed.theme, "build", lambda screen, **kw: built.append(kw) or original(screen, **kw))
    themed.start()
    themed.showClock(datetime(2027, 1, 16, 10, 5, 0))
    themed.showClock(datetime(2027, 1, 16, 10, 5, 1))
    clockBuilds = built[-3:]
    assert sum(1 for kw in clockBuilds if kw.get("only") is None) == 1
    assert not themed.isRunning()


# Latest scores

def test_ago():
    assert ThemedDisplay.ago(1000, 1030) == "just now"
    assert ThemedDisplay.ago(1000, 1000 + 5 * 60 + 10) == "5 min ago"
    assert ThemedDisplay.ago(1000, 1000 + 2 * 3600 + 60) == "2 hr ago"


def test_latest_scores_fill_from_the_bottom(theme):
    now = 10_000
    recent = [RecentScore(1259, 1, 281, now - 10), RecentScore(1333, 2, 259, now - 130), RecentScore(1222, 1, 258, now - 300)]
    latest = ThemedDisplay.recentScores(theme, recent, now)
    values = latest["values"]
    assert values["recent8_team"] == "#1259" and values["recent8_score"] == "281"
    assert values["recent8_detail"] == "Round 1 · just now"
    assert values["recent7_detail"] == "Round 2 · 2 min ago"
    assert values["recent6_team"] == "#1222"
    assert {"recent1", "recent2", "recent3", "recent4", "recent5"} <= set(latest["hidden"])
    assert "recent8_newest" in latest["shown"] and "recent7_newest" in latest["hidden"]
    assert "recent_empty" in latest["hidden"]


def test_latest_scores_show_as_many_as_fit(theme):
    recent = [RecentScore(100 + i, 1, i, 0) for i in range(12)]
    latest = ThemedDisplay.recentScores(theme, recent, 60)
    assert latest["values"]["recent1_team"] == "#107"  # The eighth newest, at the top
    assert not any(h.startswith("recent") and h[6:].isdigit() for h in latest["hidden"])


def test_no_latest_scores_yet(theme):
    latest = ThemedDisplay.recentScores(theme, [], 0)
    assert "recent_empty" in latest["shown"]


def test_standings_page_includes_latest_scores(theme):
    rows = ThemedDisplay.standingsRows(makeTeams(3))
    page = ThemedDisplay.standingsPage(theme, rows, 1, [RecentScore(100, 1, 50, 0)], now=0)
    _, ids = parse(theme.build("standings", **page))
    assert ids["recent8_team"].text == "#100"
    assert ids["recent1"].get("display") == "none"


def test_only_first_place_can_be_accented(theme, tmp_path):
    spec = json.loads(json.dumps(faketheme.THEME))
    spec["rankAccent"]["upTo"] = 1
    one = ThemedDisplay.Theme(faketheme.write(str(tmp_path / "one"), spec))
    page = ThemedDisplay.standingsPage(one, ThemedDisplay.standingsRows(makeTeams(3)), 1)
    assert page["attributes"]["row1_rank"]["fill"] == faketheme.ACCENT
    assert page["attributes"]["row2_rank"]["fill"] == faketheme.WHITE


# Standings header

def test_standings_header_shows_the_time_without_blinking(theme):
    header = ThemedDisplay.standingsHeader(theme, (12, "preparing"), datetime(2027, 1, 16, 14, 7, 31))
    assert header["values"]["standings_time"] == "2:07"
    assert header["values"]["standings_suffix"] == "pm"
    # The time sits just left of "pm", which is right-aligned on timeRight
    expected = 1385 - theme.textWidth("standings", "standings_suffix", "pm") - 10
    assert float(header["attributes"]["standings_time"]["x"]) == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("status, title, label, color", [
    ((12, "preparing"), "Match 12", "Setting up", faketheme.ACCENT),
    ((12, "scoring"), "Match 12", "Being scored", "#F0E973"),
    ((0, "opening_ceremonies"), "Opening", "Ceremonies", "#D59CD6"),
    ((0, "closing_ceremonies"), "Closing", "Ceremonies", "#D59CD6"),
])
def test_match_status_tile(theme, status, title, label, color):
    header = ThemedDisplay.standingsHeader(theme, status, datetime(2027, 1, 16, 9, 0))
    assert header["values"]["status_title"] == title and header["values"]["status_label"] == label
    assert header["attributes"]["status_dot"]["fill"] == color
    assert header["attributes"]["status_label"]["fill"] == color
    assert "status_single" in header["hidden"]


def test_match_status_tile_waits_without_a_status(theme):
    header = ThemedDisplay.standingsHeader(theme, None, datetime(2027, 1, 16, 9, 0))
    assert header["values"]["status_single"] == "Waiting"
    assert {"status_title", "status_label"} <= set(header["hidden"]) and "status_single" in header["shown"]
    assert header["attributes"]["status_dot"]["fill"] == "#7F92A5"


def test_standings_page_includes_the_header(theme):
    page = ThemedDisplay.standingsPage(theme, ThemedDisplay.standingsRows(makeTeams(3)), 1, status=(4, "scoring"),
                                       now=datetime(2027, 1, 16, 10, 5).timestamp())
    _, ids = parse(theme.build("standings", **page))
    assert ids["standings_time"].text == "10:05" and ids["standings_suffix"].text == "am"
    assert ids["status_title"].text == "Match 4" and ids["status_label"].text == "Being scored"


def test_standings_redraw_each_minute(themed):
    themed.start()
    assert themed._minuteTimer.isActive()
    assert themed._minuteTimer.remainingTime() <= 60_100
    themed.stop()
    assert not themed._minuteTimer.isActive()


# Advancing teams

def test_a_few_advancing_teams_make_one_centered_column(theme):
    args = ThemedDisplay.advancingList(theme, [(1259, "Fern Force"), (1333, "Root Rovers"), (1222, "Mossy Motors")])
    assert args["values"]["adv1_number"] == "1259" and args["values"]["adv3_name"] == "Mossy Motors"
    assert {"adv4", "adv5", "adv6", "advancing_right"} <= set(args["hidden"])
    assert args["attributes"]["advancing_left"] == {"transform": "translate(355 0)"}
    root, ids = parse(theme.build("advancing", **args))
    assert ids["advancing_right"].get("display") == "none"


def test_more_advancing_teams_balance_two_columns(theme):
    teams = [(1000 + i, f"Team {i}") for i in range(9)]
    args = ThemedDisplay.advancingList(theme, teams)
    # Five on the left, four on the right, in order down each column
    assert [args["values"][f"adv{n}_number"] for n in (1, 2, 3, 4, 5)] == ["1000", "1001", "1002", "1003", "1004"]
    assert [args["values"][f"adv{n}_number"] for n in (7, 8, 9, 10)] == ["1005", "1006", "1007", "1008"]
    assert {"adv6", "adv11", "adv12"} <= set(args["hidden"]) and "advancing_right" in args["shown"]
    assert "advancing_left" not in args["attributes"]


def test_advancing_teams_past_twelve_are_left_out(theme):
    args = ThemedDisplay.advancingList(theme, [(1000 + i, f"Team {i}") for i in range(14)])
    assert args["values"]["adv12_number"] == "1011" and "adv13_number" not in args["values"]


# Rotation

@pytest.fixture
def themed(theme):
    teams = makeTeams(10)
    audience = ThemedDisplay.ThemedAudience(theme, lambda: teams)
    audience.teams = teams
    yield audience
    audience.stop()


def test_rotation_pages_through_the_standings_only(themed):
    themed.setEventInfo("Fall Qualifier", "Oct 3")  # An event name doesn't add the welcome screen
    themed.start()
    seen = [themed.currentScreen()]
    for _ in range(2):
        themed.advance()
        seen.append(themed.currentScreen())
    assert seen == [("standings", 1), ("standings", 2), ("standings", 1)]
    assert themed._timer.isActive()
    assert themed._timer.interval() == ThemedDisplay.STANDINGS_PAGE_SECONDS * 1000


def test_welcome_loop_shows_the_welcome_screen_then_every_page(themed):
    themed.start(welcome=True)
    seen = [themed.currentScreen()]
    assert themed._timer.interval() == ThemedDisplay.WELCOME_SECONDS * 1000
    intervals = []
    for _ in range(3):
        themed.advance()
        seen.append(themed.currentScreen())
        intervals.append(themed._timer.interval())
    assert seen == [("welcome",), ("standings", 1), ("standings", 2), ("welcome",)]
    assert intervals == [ThemedDisplay.STANDINGS_PAGE_SECONDS * 1000] * 2 + [ThemedDisplay.WELCOME_SECONDS * 1000]


def test_rankings_never_show_the_welcome_screen(themed):
    themed.start()
    seen = [themed.currentScreen()]
    for _ in range(4):
        themed.advance()
        seen.append(themed.currentScreen())
    assert ("welcome",) not in seen


def test_switching_to_the_welcome_loop_starts_at_the_welcome_screen(themed):
    themed.start()
    themed.advance()
    assert themed.currentScreen() == ("standings", 2)
    themed.start(welcome=True)
    assert themed.currentScreen() == ("welcome",)
    themed.start()
    assert themed.currentScreen() == ("standings", 1)


def test_welcome_loop_with_one_page_still_rotates(theme):
    audience = ThemedDisplay.ThemedAudience(theme, lambda: makeTeams(3))
    audience.start(welcome=True)
    assert audience.currentScreen() == ("welcome",)
    assert audience._timer.isActive()
    audience.advance()
    assert audience.currentScreen() == ("standings", 1)


def test_welcome_screen_shows_new_event_info_straight_away(themed):
    themed.start(welcome=True)
    themed.setEventInfo("Spring Qualifier", "")
    assert themed.currentScreen() == ("welcome",)
    assert themed._timer.isActive()


# The results QR code

def qrMatrix(path: str, modules: int) -> list:
    grid = [[False] * modules for _ in range(modules)]
    for x, y, run in re.findall(r"M(\d+) (\d+)h(\d+)v1\.05h-\d+z", path):
        for col in range(int(x), int(x) + int(run)):
            grid[int(y)][col] = True
    return grid


def test_qr_path_draws_every_dark_module():
    url = "https://scores.example.org/events/fall-qual"
    path, modules = ThemedDisplay.qrPath(url)
    code = ThemedDisplay.segno.make(url, error="m", micro=False)
    assert modules == code.symbol_size(border=0)[0]
    assert qrMatrix(path, modules) == [[bool(m) for m in row] for row in code.matrix]


def test_welcome_screen_hides_the_results_card_without_a_results_page(theme):
    _, ids = parse(theme.build("welcome", values={"event_name": "Fall Qualifier"}))
    assert ids["results"].get("display") == "none"
    assert ids["welcome_text"].get("transform") is None
    assert len(ids["results_qr"]) == 0


def test_welcome_screen_shows_the_results_qr_code(theme):
    _, ids = parse(theme.build("welcome", results="https://scores.example.org/events/fall-qual"))
    assert ids["results"].get("display") is None
    assert ids["welcome_text"].get("transform") == "translate(0 -50)"
    path = list(ids["results_qr"])[0]
    modules = ThemedDisplay.qrPath("https://scores.example.org/events/fall-qual")[1]
    assert path.get("transform") == f"scale({ThemedDisplay._formatNumber(196 / modules)})"


def test_results_page_change_redraws_the_welcome_screen(themed, monkeypatch):
    built = []
    real = themed.theme.renderer
    monkeypatch.setattr(themed.theme, "renderer", lambda screen, **kw: built.append(kw) or real(screen, **kw))
    themed.start(welcome=True)
    themed.setResultsUrl("https://scores.example.org/events/fall-qual")
    themed.setResultsUrl(None)
    assert [kw.get("results") for kw in built] == [None, "https://scores.example.org/events/fall-qual", None]


def test_a_single_screen_does_not_rotate(theme):
    teams = makeTeams(3)
    audience = ThemedDisplay.ThemedAudience(theme, lambda: teams)
    audience.start()
    assert audience.currentScreen() == ("standings", 1)
    assert not audience._timer.isActive()
    # More teams make a second page, which starts the rotation
    teams.extend(makeTeams(8))
    audience.refresh()
    assert audience._timer.isActive()
    audience.stop()


def test_refresh_keeps_the_current_page(themed):
    themed.start()
    themed.advance()
    themed.refresh()
    assert themed.currentScreen() == ("standings", 2)


def test_stop_and_start(themed):
    themed.start()
    themed.stop()
    assert not themed.isRunning() and not themed._timer.isActive()
    themed.advance()  # A late timeout does nothing while stopped
    assert themed.currentScreen() == ("standings", 1)


def test_show_screen_holds_until_resumed(themed):
    themed.setEventInfo("Fall Qualifier", "")
    themed.start()
    themed.showScreen("award_winner", {"team_number": "1234", "team_name": "Bots"})
    assert themed.currentScreen() == ("held", "award_winner")
    assert not themed._timer.isActive()
    themed.advance()
    assert themed.currentScreen() == ("held", "award_winner")
    themed.resumeRotation()
    assert themed.currentScreen() == ("standings", 1)


def test_held_screen_gets_the_event_name(themed, monkeypatch):
    built = []
    original = themed.theme.build
    monkeypatch.setattr(themed.theme, "build", lambda screen, **kw: built.append((screen, kw)) or original(screen, **kw))
    themed.setEventInfo("Fall Qualifier", "")
    themed.start()
    themed.showScreen("award_winner", {"team_name": "Bots"})
    screen, kwargs = built[-1]
    assert screen == "award_winner"
    assert kwargs["values"] == {"event_name": "Fall Qualifier", "team_name": "Bots"}


def test_show_screen_rejects_unknown_screens(themed):
    with pytest.raises(KeyError):
        themed.showScreen("thank_you")


def test_view_letterboxes_to_the_themes_shape(themed):
    view = themed.view
    view.resize(1000, 1000)
    rect = view.targetRect()
    assert rect.width() == 1000 and rect.height() == pytest.approx(562.5)
    assert rect.top() == pytest.approx(218.75)
    themed.start()
    image = view.grab()
    assert not image.isNull()


# The real resource pack, when one is available (e.g. IBSS_RESOURCE_PACK=path/to/2026-bioglow_resources)

@pytest.mark.skipif(not os.environ.get("IBSS_RESOURCE_PACK"), reason="no resource pack to check")
def test_every_screen_in_the_resource_pack_renders(app):
    directory = os.environ["IBSS_RESOURCE_PACK"]
    for font in glob.glob(os.path.join(directory, "*.ttf")):
        QFontDatabase.addApplicationFont(font)
    theme = ThemedDisplay.Theme(os.path.join(directory, "display"))
    for screen, spec in theme.screens.items():
        values = {field: "Greater Springfield Area Championship Robotics" for field in spec["fields"]}
        assert QSvgRenderer(QByteArray(theme.build(screen, values=values))).isValid(), screen


def test_moved_elements_take_their_glow_along(theme):
    # When the award name wraps, the team number moves down to make room, and its glow with it
    theme.screens["award_winner"]["fields"]["award_name"] = {
        "maxWidth": 600, "minSize": 30, "maxLines": 2, "wrap": "center", "below": ["team_number"]}
    template = theme._templates["award_winner"].getroot()
    glow = copy.deepcopy(ThemedDisplay._index(template)["team_number"][0])
    glow.set("id", "team_number__glow")
    template.append(glow)
    _, ids = parse(theme.build("award_winner", values={"award_name": "Engineering Excellence Award Sponsored by Acme"}))
    assert ids["team_number"].get("transform", "").startswith("translate(0 ")
    assert ids["team_number__glow"].get("transform") == ids["team_number"].get("transform")
