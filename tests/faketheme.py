"""
A small made-up resource pack theme for tests, in the same shape as a real pack's
display/ directory (theme.json plus one SVG template per screen) but with no artwork.
"""

import json
import os

ACCENT = "#22D8C2"
WHITE = "#FFFFFF"

HEADER = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
          'width="1920" height="1080" viewBox="0 0 1920 1080">'
          '<defs><filter id="tg"><feGaussianBlur stdDeviation="16"/></filter></defs>'
          '<rect width="1920" height="1080" fill="#003947"/>')


def text(id, x, y, size, content, weight=400, anchor="middle", extra=""):
    return (f'<text id="{id}" x="{x}" y="{y}" font-family="Roboto" font-size="{size}" font-weight="{weight}" '
            f'fill="{WHITE}" text-anchor="{anchor}" {extra}>{content}</text>')


WELCOME = (HEADER
           + text("welcome_eyebrow", 960, 372, 40, "WELCOME TO THE", 700)
           + text("event_name__glow", 960, 518, 128, "[EVENT NAME]", 900, extra='filter="url(#tg)"')
           + text("event_name", 960, 518, 128, "[EVENT NAME]", 900)
           + text("event_date", 960, 607, 44, "[DATE]", 300)
           + "</svg>")

ROWS = 8
RECENT = 8
EXPIRED = "#FF5A4F"


def standingsSvg():
    rows = []
    for n in range(1, ROWS + 1):
        top = 312 + (n - 1) * 66
        y = top + 41
        rows.append(f'<g id="row{n}"><rect id="row{n}_bg" x="202" y="{top}" width="1518" height="60"/>'
                    f'<rect id="row{n}_top" x="202" y="{top}" width="1518" height="60" display="none"/>'
                    + text(f"row{n}_rank", 234, y, 32, str(n), 900, "start")
                    + text(f"row{n}_team", 344, y, 32, "[####]", 700, "start")
                    + text(f"row{n}_name", 534, y, 32, "[TEAM NAME]", 300, "start")
                    + text(f"row{n}_best", 1268, y, 38, "[SCORE]", 900, "end")
                    + "".join(text(f"row{n}_r{r}", 1268 + 140 * r, y, 32, "—", 300, "end") for r in (1, 2, 3))
                    + "</g>")
    recent = []
    for n in range(1, RECENT + 1):
        top = 244 + (n - 1) * 80
        recent.append(f'<g id="recent{n}"><rect id="recent{n}_newest" x="1408" y="{top}" width="424" height="80" display="none"/>'
                      + text(f"recent{n}_team", 1432, top + 40, 38, "#[####]", 700, "start")
                      + text(f"recent{n}_detail", 1432, top + 70, 22, "Round [N]", 400, "start")
                      + text(f"recent{n}_score", 1808, top + 54, 52, "[SCORE]", 900, "end")
                      + "</g>")
    return (HEADER + "".join(rows) + "".join(recent)
            + text("recent_empty", 1620, 550, 26, "No scores yet", 400, extra='display="none"')
            + '<g id="page_dots"/>'
            + text("page_label", 960, 1010, 24, "PAGE 1 OF 1", 700) + "</svg>")


AWARD_WINNER = (HEADER
                + text("award_name", 960, 268, 34, "Core Values Award", 700)
                + text("team_label", 960, 324, 30, "TEAM", 300)
                + text("team_number", 960, 577, 280, "[####]", 900)
                + text("team_name", 960, 705, 96, "[TEAM NAME]", 900)
                + text("team_location", 960, 775, 38, "[CITY]", 300)
                + text("event_name", 960, 996, 28, "[EVENT NAME]", 700)
                + text("event_name__header", 960, 124, 26, "[EVENT NAME]", 700)
                + "</svg>")

TIMER = (HEADER
         + text("timer_title__glow", 960, 175, 88, "Match [N]", 900, extra='filter="url(#tg)"')
         + text("timer_title", 960, 175, 88, "Match [N]", 900)
         + text("timer_time__glow", 960, 722, 540, "2:30", 900, extra='filter="url(#tg)"')
         + text("timer_time", 960, 722, 540, "2:30", 900)
         + '<g id="timer_progress"><rect x="400" y="810" width="1120" height="18" rx="9" fill="#ffffff" fill-opacity="0.12"/>'
         + f'<rect id="timer_progress_fill" x="400" y="810" width="1120" height="18" rx="9" fill="{ACCENT}"/></g>'
         + "</svg>")

WARNING = "#F0E973"


def clockPieces(suffix, extra=""):
    return (text(f"clock_hours{suffix}", 815.5, 696, 440, "10", 900, "end", extra)
            + text(f"clock_colon{suffix}", 881.6, 696, 440, ":", 900, "middle", extra)
            + text(f"clock_minutes{suffix}", 947.6, 696, 440, "05", 900, "start", extra)
            + text(f"clock_suffix{suffix}", 1497.6, 696, 220, "a", 900, "start", extra))


def advancingSvg():
    groups = []
    for column, group in enumerate(("advancing_left", "advancing_right")):
        x = 270 + column * 710
        rows = "".join(f'<g id="adv{column * 6 + r}"><rect x="{x}" y="{300 + (r - 1) * 80}" width="670" height="72"/>'
                       + text(f"adv{column * 6 + r}_number", x + 32, 350 + (r - 1) * 80, 44, "[####]", 900, "start")
                       + text(f"adv{column * 6 + r}_name", x + 194, 350 + (r - 1) * 80, 40, "[TEAM NAME]", 400, "start")
                       + "</g>" for r in range(1, 7))
        groups.append(f'<g id="{group}">{rows}</g>')
    return HEADER + text("title", 960, 175, 88, "Advancing to [NEXT EVENT]", 900) + "".join(groups) + "</svg>"


CLOCK = (HEADER
         + '<g id="clock_time__glow" filter="url(#tg)">' + clockPieces("__glow") + "</g>"
         + '<g id="clock_time">' + clockPieces("") + "</g>"
         + "</svg>")

THEME = {
    "themeVersion": 1,
    "name": "TESTGLOW",
    "season": 2026,
    "width": 1920,
    "height": 1080,
    "background": "#003947",
    "fontFamily": "Roboto",
    "rankAccent": {"fill": ACCENT, "upTo": 3, "otherFill": WHITE},
    "screens": {
        "welcome": {"file": "welcome.svg", "fields": {
            "event_name": {"maxWidth": 1440, "minSize": 80, "maxLines": 2, "lineHeight": 1.0, "wrap": "center",
                           "above": ["welcome_eyebrow"], "below": ["event_date"]},
            "event_date": {"maxWidth": 1440, "minSize": 28}}},
        "standings": {"file": "standings.svg", "rows": ROWS, "recent": RECENT,
                      "dots": {"centerX": 960, "centerY": 965, "size": 16, "activeWidth": 56, "gap": 14,
                               "activeFill": ACCENT, "doneFill": "#C6DE94", "doneOpacity": 0.6,
                               "todoStroke": "#C6DE94", "todoOpacity": 0.6, "todoStrokeWidth": 2, "max": 12},
                      "fields": {f"row{n}_name": {"maxWidth": 510, "minSize": 22} for n in range(1, ROWS + 1)}},
        "award_winner": {"file": "award_winner.svg", "fields": {
            "team_name": {"maxWidth": 1440, "minSize": 64, "maxLines": 2, "lineHeight": 1.0, "wrap": "center",
                          "above": ["award_name", "team_label", "team_number"], "below": ["team_location"]},
            "event_name": {"maxWidth": 1100, "minSize": 18}}},
        "timer": {"file": "timer.svg",
                  "fields": {"timer_title": {"maxWidth": 1400, "minSize": 48},
                             "timer_time": {"maxWidth": 1320, "minSize": 300}},
                  "progress": {"x": 400, "y": 810, "width": 1120, "height": 18},
                  "states": {
                      "normal": {"timer_time": {"fill": WHITE}, "timer_time__glow": {"fill": ACCENT},
                                 "timer_progress_fill": {"fill": ACCENT}},
                      "warning": {"timer_time": {"fill": WARNING}, "timer_time__glow": {"fill": WARNING},
                                  "timer_progress_fill": {"fill": WARNING}},
                      "expired": {"timer_time": {"fill": EXPIRED}, "timer_time__glow": {"fill": EXPIRED},
                                  "timer_progress_fill": {"fill": EXPIRED}}}},
        "advancing": {"file": "advancing.svg", "fields": {"title": {"maxWidth": 1600, "minSize": 48}},
                      "list": {"rows": 6, "columns": 2, "left": "advancing_left", "right": "advancing_right",
                               "singleColumnShift": 355}},
        "clock": {"file": "clock.svg", "fields": {},
                  "clock": {"group": "clock_time", "hours": "clock_hours", "colon": "clock_colon",
                            "minutes": "clock_minutes", "suffix": "clock_suffix", "centerX": 960}},
    },
}


def write(directory: str, theme: dict = None) -> str:
    """Write the theme into directory and return it."""
    os.makedirs(directory, exist_ok=True)
    files = {"welcome.svg": WELCOME, "standings.svg": standingsSvg(), "award_winner.svg": AWARD_WINNER,
             "timer.svg": TIMER, "clock.svg": CLOCK, "advancing.svg": advancingSvg()}
    for name, content in files.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
            f.write(content)
    with open(os.path.join(directory, "theme.json"), "w", encoding="utf-8") as f:
        json.dump(theme or THEME, f)
    return directory
