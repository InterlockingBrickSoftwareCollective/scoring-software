"""
ThemedDisplay.py: Themed audience display screens from the resource pack

This file is part of Interlocking Brick Scoring Software.

Interlocking Brick Scoring Software is free software: you can
redistribute it and/or modify it under the terms of version 3 of
the GNU General Public License as published by the Free Software
Foundation.

Interlocking Brick Scoring Software is distributed in the hope
that it will be useful, but WITHOUT ANY WARRANTY; without even the
implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE.  See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

# A resource pack may include themed screens for the audience display in its display/
# directory: one SVG template per screen and a theme.json that describes them. The
# templates come from the pack because they use licensed season artwork. Each piece of
# text that changes is an SVG <text> element whose id is a field in theme.json; this
# module fills those in, fits them to the space theme.json allows, and renders the
# result with Qt's SVG renderer. The contract is documented in the resource pack
# repository (2026-bioglow/display_src/README.md).

import copy
import glob
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Callable, Optional

from PyQt6.QtCore import QByteArray, QObject, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QWidget

import segno

import ResourceManager
from Team import UNRANKED

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

THEME_FILE = os.path.join("display", "theme.json")
SUPPORTED_THEME_VERSION = 1

# Every page (welcome screen or standings page) is shown this long
STANDINGS_PAGE_SECONDS = 8

NO_SCORE = "—"

# Font size used to measure text; widths at other sizes are scaled from it
_MEASURE_SIZE = 100


def registerFonts():
    """Make every font in the resource pack available, including the weights the themed screens use."""
    if not ResourceManager.isResourcePackInstalled():
        return
    for path in sorted(glob.glob(os.path.join(ResourceManager.getResourcePath(""), "*.ttf"))):
        if QFontDatabase.addApplicationFont(path) == -1:
            print(f"Couldn't load font {os.path.basename(path)}")


class Theme:
    """A resource pack's themed screens, as described by its display/theme.json."""

    def __init__(self, directory: str):
        """Load the theme in directory (which holds theme.json and the templates).
        Raises OSError or ValueError if it can't be used."""
        self.directory = directory
        with open(os.path.join(directory, "theme.json"), encoding="utf-8") as f:
            spec = json.load(f)
        if spec.get("themeVersion") != SUPPORTED_THEME_VERSION:
            raise ValueError(f"Unsupported theme version {spec.get('themeVersion')}")
        self.name: str = spec.get("name", "Themed")
        self.width: int = int(spec.get("width", 1920))
        self.height: int = int(spec.get("height", 1080))
        self.background = QColor(spec.get("background", "#000000"))
        self.fontFamily: str = spec.get("fontFamily", "Roboto")
        self.rankAccent: dict = spec.get("rankAccent", {})
        self.screens: dict = spec.get("screens", {})
        self._templates = {}
        for name, screen in self.screens.items():
            self._templates[name] = ET.parse(os.path.join(directory, screen["file"]))

    @classmethod
    def fromResourcePack(cls) -> Optional["Theme"]:
        """The installed resource pack's theme, or None if it doesn't have one."""
        if not ResourceManager.isResourcePackInstalled():
            return None
        path = ResourceManager.getResourcePath(THEME_FILE)
        if not os.path.exists(path):
            return None
        try:
            return cls(os.path.dirname(path))
        except (OSError, ValueError, KeyError, ET.ParseError) as err:
            print(f"Resource pack theme can't be used: {err}")
            return None

    def hasScreen(self, name: str) -> bool:
        return name in self.screens

    def build(self, screen: str, values: Optional[dict] = None, hidden=(), shown=(),
              attributes: Optional[dict] = None, dots: Optional[tuple] = None, only=None,
              results: Optional[str] = None) -> bytes:
        """Fill in a screen's template and return the SVG document.

        values: field id -> text. Elements with id "<field>__<suffix>" get the same text.
        hidden, shown: ids of elements to hide or show, with their "__" copies.
        attributes: element id -> {attribute: value} to set, e.g. a fill color.
        dots: (page, pages) to draw page dots in the screen's page_dots group.
        only: ids of top-level elements (and their "__" copies) to draw, leaving out everything
        else, so a layer that changes often can be drawn over a cached one.
        results: the event results page, to show its QR code card if the screen has one."""
        spec = self.screens[screen]
        root = copy.deepcopy(self._templates[screen].getroot())
        index = _index(root)

        for elementId, attrs in (attributes or {}).items():
            for element in index.get(elementId, []):
                for key, value in attrs.items():
                    element.set(key, str(value))

        # A field's "__" copies (e.g. its glow) are hidden and shown with it
        for elementId in hidden:
            for element in _fieldGroup(index, elementId):
                element.set("display", "none")
        for elementId in shown:
            for element in _fieldGroup(index, elementId):
                element.attrib.pop("display", None)

        fields = spec.get("fields", {})
        for field, value in (values or {}).items():
            group = _fieldGroup(index, field)
            if not group:
                continue
            fieldSpec = fields.get(field)
            if fieldSpec is None:
                for element in group:
                    _setText(element, value)
            else:
                self._fit(root, index, group, str(value), fieldSpec)

        if dots is not None and "dots" in spec:
            self._drawDots(index, spec["dots"], *dots)

        if results and "results" in spec:
            self._drawResults(index, spec["results"], results)

        if only is not None:
            keep = {id(element) for field in only for element in _fieldGroup(index, field)}
            for child in list(root):
                if child.tag in (f"{{{SVG_NS}}}defs", f"{{{SVG_NS}}}title"):
                    continue
                if id(child) not in keep and not any(id(el) in keep for el in child.iter()):
                    root.remove(child)

        return ET.tostring(root, encoding="utf-8")

    def textWidth(self, screen: str, elementId: str, text: str) -> float:
        """How wide text would be in a template element's font, in template pixels."""
        element = _index(self._templates[screen].getroot())[elementId][0]
        size = float(element.get("font-size", "16"))
        return _metrics(self.fontFamily, int(element.get("font-weight", "400"))).horizontalAdvance(text) * size / _MEASURE_SIZE

    def renderer(self, screen: str, **kwargs) -> QSvgRenderer:
        """A renderer for a filled-in screen; takes the same arguments as build()."""
        return QSvgRenderer(QByteArray(self.build(screen, **kwargs)))

    def _fit(self, root, index, group, text: str, spec: dict):
        """Set a field's text, shrinking, wrapping or eliding it to fit spec."""
        primary = group[0]
        size = float(primary.get("font-size", "16"))
        weight = int(primary.get("font-weight", "400"))
        maxWidth = float(spec.get("maxWidth", math.inf))
        minSize = float(spec.get("minSize", size))
        maxLines = int(spec.get("maxLines", 1))
        metrics = _metrics(self.fontFamily, weight)

        def width(s, at):
            return metrics.horizontalAdvance(s) * at / _MEASURE_SIZE

        lines = [text]
        if width(text, size) > maxWidth:
            fitted = _floorHalf(size * maxWidth / width(text, size))
            if fitted >= minSize:
                size = fitted
            elif maxLines >= 2 and " " in text.strip():
                lines = _splitInTwo(text, lambda s: width(s, 1))
                widest = max(width(line, 1) for line in lines)
                size = max(minSize, min(size, _floorHalf(maxWidth / widest)))
                lines = [lines[0], _elide(metrics, lines[1], maxWidth, size)]
                if width(lines[0], size) > maxWidth:
                    lines[0] = _elide(metrics, lines[0], maxWidth, size)
            else:
                size = minSize
                lines = [_elide(metrics, text, maxWidth, size)]

        # Copies may be a different size from the field (e.g. a header and a footer), so scale them alike
        scale = size / float(primary.get("font-size", "16"))
        for element in group:
            element.set("font-size", _formatNumber(float(element.get("font-size", "16")) * scale))
            _setText(element, lines[0])

        if len(lines) == 2:
            step = size * float(spec.get("lineHeight", 1.2))
            wrap = spec.get("wrap", "down")
            firstShift, secondShift = (-step / 2, step / 2) if wrap == "center" else (0, step)
            for element in group:
                y = float(element.get("y", "0"))
                second = copy.deepcopy(element)
                if element.get("id"):
                    second.set("id", element.get("id") + "__line2")
                _setText(second, lines[1])
                element.set("y", _formatNumber(y + firstShift))
                second.set("y", _formatNumber(y + secondShift))
                parent = _parent(root, element)
                parent.insert(list(parent).index(element) + 1, second)
            # Moved with their "__" copies, so a glow stays behind its text
            for elementId in spec.get("above", []):
                for element in _fieldGroup(index, elementId):
                    _translate(element, firstShift if wrap == "center" else 0)
            for elementId in spec.get("below", []):
                for element in _fieldGroup(index, elementId):
                    _translate(element, secondShift if wrap == "center" else step)

    def _drawDots(self, index, spec: dict, page: int, pages: int):
        groups = index.get("page_dots", [])
        if not groups or pages <= 1 or pages > int(spec.get("max", 12)):
            return
        group = groups[0]
        size = float(spec.get("size", 16))
        activeWidth = float(spec.get("activeWidth", size * 3.5))
        gap = float(spec.get("gap", size))
        total = activeWidth + (pages - 1) * (size + gap)
        x = float(spec.get("centerX", self.width / 2)) - total / 2
        cy = float(spec.get("centerY", 0))
        radius = size / 2
        for n in range(1, pages + 1):
            if n == page:
                attrs = {"x": x, "y": cy - radius, "width": activeWidth, "height": size, "rx": radius,
                         "fill": spec.get("activeFill", "#ffffff")}
                ET.SubElement(group, f"{{{SVG_NS}}}rect", _strings(attrs), id=f"dot{n}", **{"class": "active"})
                x += activeWidth + gap
                continue
            attrs = {"cx": x + radius, "cy": cy, "r": radius}
            if n < page:
                attrs.update({"fill": spec.get("doneFill", "#ffffff"), "fill-opacity": spec.get("doneOpacity", 1)})
                state = "done"
            else:
                width = float(spec.get("todoStrokeWidth", 2))
                attrs.update({"r": radius - width / 2, "fill": "none", "stroke": spec.get("todoStroke", "#ffffff"),
                              "stroke-opacity": spec.get("todoOpacity", 1), "stroke-width": width})
                state = "todo"
            ET.SubElement(group, f"{{{SVG_NS}}}circle", _strings(attrs), id=f"dot{n}", **{"class": state})
            x += size + gap


    def _drawResults(self, index, spec: dict, url: str):
        """Show the results card with the page's QR code, and make room for it."""
        for element in index.get(spec["group"], []):
            element.attrib.pop("display", None)
        shift = spec.get("shift")
        if shift:
            for element in index.get(shift["id"], []):
                _translate(element, float(shift["dy"]))
        for group in index.get(spec["qr"], []):
            path, modules = qrPath(url)
            scale = float(spec["size"]) / modules
            ET.SubElement(group, f"{{{SVG_NS}}}path", d=path, transform=f"scale({_formatNumber(scale)})")


def qrPath(text: str) -> tuple:
    """SVG path data for a QR code of text, one unit per module and no quiet zone (the template
    leaves room for it), and its width in modules. Each run of dark modules is one rectangle,
    a little taller than a module so rows don't show hairline gaps between them when drawn
    with antialiasing."""
    code = segno.make(text, error="m", micro=False)
    parts = []
    for y, row in enumerate(code.matrix):
        x = 0
        while x < len(row):
            if row[x]:
                start = x
                while x < len(row) and row[x]:
                    x += 1
                parts.append(f"M{start} {y}h{x - start}v1.05h{start - x}z")
            else:
                x += 1
    return "".join(parts), code.symbol_size(border=0)[0]


def _index(root) -> dict:
    index = {}
    for element in root.iter():
        elementId = element.get("id")
        if elementId:
            index.setdefault(elementId, []).append(element)
    return index


def _fieldGroup(index: dict, field: str) -> list:
    """The field's own element first, then its "<field>__<suffix>" copies."""
    group = list(index.get(field, []))
    prefix = field + "__"
    group += [element for elementId, elements in index.items() if elementId.startswith(prefix)
              for element in elements]
    return group


def _setText(element, text):
    for child in list(element):
        element.remove(child)
    element.text = str(text)


def _parent(root, child):
    for element in root.iter():
        if child in list(element):
            return element
    return root


def _translate(element, dy: float):
    if dy == 0:
        return
    existing = element.get("transform", "")
    element.set("transform", f"translate(0 {_formatNumber(dy)}) {existing}".strip())


def _floorHalf(value: float) -> float:
    return math.floor(value * 2) / 2


def _formatNumber(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _strings(attrs: dict) -> dict:
    return {key: _formatNumber(value) if isinstance(value, float) else str(value) for key, value in attrs.items()}


_metricsCache = {}


def _metrics(family: str, weight: int) -> QFontMetricsF:
    key = (family, weight)
    if key not in _metricsCache:
        font = QFont(family)
        font.setPixelSize(_MEASURE_SIZE)
        font.setWeight(QFont.Weight(max(100, min(900, weight))))
        _metricsCache[key] = QFontMetricsF(font)
    return _metricsCache[key]


def _elide(metrics: QFontMetricsF, text: str, maxWidth: float, size: float) -> str:
    return metrics.elidedText(text, Qt.TextElideMode.ElideRight, maxWidth * _MEASURE_SIZE / size)


def _splitInTwo(text: str, width: Callable[[str], float]) -> list:
    """Split text at the space that makes the wider of the two lines narrowest."""
    words = text.split()
    best = None
    for i in range(1, len(words)):
        first, second = " ".join(words[:i]), " ".join(words[i:])
        widest = max(width(first), width(second))
        if best is None or widest < best[0]:
            best = (widest, [first, second])
    return best[1]


# Standings ----------------------------------------------------------------------------

def standingsRows(teams: list) -> list:
    """One row of standings text per team, in ranking order (unranked teams last)."""
    rows = []
    for team in sorted(teams, key=lambda t: (t.rank, t.number)):
        played = [score for score in team.scores if score is not None]
        rows.append({
            "rank": "NP" if team.rank == UNRANKED else str(team.rank),
            "rankNumber": None if team.rank == UNRANKED else team.rank,
            "team": str(team.number),
            "name": str(team.name),
            "best": str(max(played)) if played else NO_SCORE,
            "r1": NO_SCORE if team.scores[0] is None else str(team.scores[0]),
            "r2": NO_SCORE if team.scores[1] is None else str(team.scores[1]),
            "r3": NO_SCORE if team.scores[2] is None else str(team.scores[2]),
        })
    return rows


class RecentScore:
    """A score entered for a team's round, and when (seconds since the epoch)."""

    def __init__(self, team: int, round: int, score: int, at: float):
        self.team = team
        self.round = round
        self.score = score
        self.at = at

    def __eq__(self, other):
        return isinstance(other, RecentScore) and vars(self) == vars(other)

    def __repr__(self):
        return f"RecentScore(team={self.team}, round={self.round}, score={self.score}, at={self.at})"


def ago(at: float, now: float) -> str:
    minutes = int((now - at) // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    return f"{minutes // 60} hr ago"


def recentScores(theme: Theme, recent: list, now: float) -> dict:
    """Values and visibility for the standings' latest scores: recent is newest first, and the
    newest goes in the last slot, highlighted, with older ones above it."""
    slots = int(theme.screens["standings"].get("recent", 0))
    values, hidden, shown = {}, [], []
    if not slots:
        return {"values": values, "hidden": hidden, "shown": shown}
    showing = recent[:slots]
    for i in range(slots):
        slot = slots - i
        prefix = f"recent{slot}"
        if i >= len(showing):
            hidden.append(prefix)
            continue
        item = showing[i]
        shown.append(prefix)
        values[f"{prefix}_team"] = f"#{item.team}"
        values[f"{prefix}_detail"] = f"Round {item.round} · {ago(item.at, now)}"
        values[f"{prefix}_score"] = str(item.score)
        (shown if i == 0 else hidden).append(f"{prefix}_newest")
    (hidden if showing else shown).append("recent_empty")
    return {"values": values, "hidden": hidden, "shown": shown}


# How the match status tile describes each status: (first line, second line)
STATUS_TEXT = {
    "preparing": ("Match {match}", "Setting up"),
    "running": ("Match {match}", "In progress"),
    "scoring": ("Match {match}", "Being scored"),
    "practice": ("Practice", "Practice matches"),
    "opening_ceremonies": ("Opening", "Ceremonies"),
    "closing_ceremonies": ("Closing", "Ceremonies"),
}


def standingsHeader(theme: Theme, status: Optional[tuple], now: datetime) -> dict:
    """Values and attributes for the standings header: the time of day (without a blinking colon)
    and the match status tile, for status (match, status) or None ("Waiting")."""
    spec = theme.screens["standings"].get("header")
    values, hidden, shown, attributes = {}, [], [], {}
    if not spec:
        return {"values": values, "hidden": hidden, "shown": shown, "attributes": attributes}

    hours, minutes, suffix = clockParts(now)
    suffix += "m"
    values["standings_time"] = f"{hours}:{minutes}"
    values["standings_suffix"] = suffix
    suffixWidth = theme.textWidth("standings", "standings_suffix", suffix)
    attributes["standings_time"] = {"x": _formatNumber(float(spec["timeRight"]) - suffixWidth - float(spec.get("suffixGap", 8)))}

    colors = spec.get("statusColors", {})
    if status is None or status[1] not in STATUS_TEXT:
        color = colors.get("waiting")
        values["status_single"] = "Waiting"
        hidden += ["status_title", "status_label"]
        shown.append("status_single")
    else:
        match, name = status
        first, second = STATUS_TEXT[name]
        color = colors.get(name)
        values["status_title"] = first.format(match=match)
        values["status_label"] = second
        shown += ["status_title", "status_label"]
        hidden.append("status_single")
        if color:
            attributes["status_label"] = {"fill": color}
    if color:
        attributes["status_dot"] = {"fill": color}
        attributes["status_dot__glow"] = {"fill": color}
    return {"values": values, "hidden": hidden, "shown": shown, "attributes": attributes}


def standingsPageCount(rowCount: int, rowsPerPage: int) -> int:
    return max(1, math.ceil(rowCount / rowsPerPage))


def standingsPage(theme: Theme, rows: list, page: int, recent=(), now: Optional[float] = None,
                  status: Optional[tuple] = None) -> dict:
    """build() arguments for one page (1-based) of the standings screen, with the latest
    scores (newest first) and the header's time of day and match status, if the theme shows them."""
    spec = theme.screens["standings"]
    perPage = int(spec.get("rows", 8))
    pages = standingsPageCount(len(rows), perPage)
    page = max(1, min(page, pages))
    pageRows = rows[(page - 1) * perPage:page * perPage]

    accent = theme.rankAccent
    values, hidden, shown, attributes = {}, [], [], {}
    for slot in range(1, perPage + 1):
        prefix = f"row{slot}"
        if slot > len(pageRows):
            hidden.append(prefix)
            continue
        row = pageRows[slot - 1]
        for key in ("rank", "team", "name", "best", "r1", "r2", "r3"):
            values[f"{prefix}_{key}"] = row[key]
        first = row["rankNumber"] == 1
        (shown if first else hidden).append(f"{prefix}_top")
        (hidden if first else shown).append(f"{prefix}_bg")
        if accent:
            highlighted = row["rankNumber"] is not None and row["rankNumber"] <= int(accent.get("upTo", 3))
            attributes[f"{prefix}_rank"] = {"fill": accent.get("fill") if highlighted else accent.get("otherFill")}

    if pages > 1:
        values["page_label"] = f"PAGE {page} OF {pages}"
    else:
        hidden.append("page_label")

    now = time.time() if now is None else now
    for extra in (recentScores(theme, list(recent), now), standingsHeader(theme, status, datetime.fromtimestamp(now))):
        values.update(extra["values"])
        hidden += extra["hidden"]
        shown += extra["shown"]
        attributes.update(extra.get("attributes", {}))
    return {"values": values, "hidden": hidden, "shown": shown, "attributes": attributes, "dots": (page, pages)}


# Advancing teams ----------------------------------------------------------------------

def advancingList(theme: Theme, teams: list) -> dict:
    """build() arguments for the advancing screen, for (number, name) pairs in the order to show
    them: one centered column if they fit, otherwise two balanced columns. Teams past the
    template's slots are left out."""
    spec = theme.screens["advancing"]["list"]
    rows, columns = int(spec["rows"]), int(spec["columns"])
    teams = list(teams)[:rows * columns]
    perColumn = len(teams) if len(teams) <= rows else -(-len(teams) // columns)
    values, hidden, shown, attributes = {}, [], [], {}
    placed = {}
    for i, team in enumerate(teams):
        column, row = divmod(i, perColumn) if perColumn else (0, 0)
        placed[column * rows + row + 1] = team
    for slot in range(1, rows * columns + 1):
        if slot in placed:
            number, name = placed[slot]
            values[f"adv{slot}_number"] = str(number)
            values[f"adv{slot}_name"] = str(name)
            shown.append(f"adv{slot}")
        else:
            hidden.append(f"adv{slot}")
    if len(teams) <= rows:
        hidden.append(spec["right"])
        attributes[spec["left"]] = {"transform": f"translate({_formatNumber(float(spec['singleColumnShift']))} 0)"}
    else:
        shown.append(spec["right"])
    return {"values": values, "hidden": hidden, "shown": shown, "attributes": attributes}


# Timer --------------------------------------------------------------------------------

def formatTime(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60:01d}:{seconds % 60:02d}"


# Drawn every second over a cached picture of the rest of the timer screen, because the
# rest has slow blur filters (the glowing spores and the card's shadow)
TIMER_LAYER = ["timer_time", "timer_progress"]


def timerScreen(theme: Theme, title: str, remaining: int, total: int, warning: bool, expired: bool = False) -> dict:
    """build() arguments for the timer screen: the time left, a progress bar showing the
    fraction of the countdown left, and the theme's warning look once the warning time passes
    and its expired look once time runs out (or the warning look, for themes without one)."""
    spec = theme.screens["timer"]
    states = spec.get("states", {})
    values = {"timer_title": title, "timer_time": formatTime(remaining)}
    if expired and "expired" in states:
        state = "expired"
    elif warning or expired:
        state = "warning"
    else:
        state = "normal"
    attributes = copy.deepcopy(states.get(state, {}))
    hidden, shown = [], []
    progress = spec.get("progress")
    if progress:
        fraction = max(0.0, min(1.0, remaining / total)) if total > 0 else 0.0
        if fraction <= 0:
            hidden.append("timer_progress_fill")
        else:
            shown.append("timer_progress_fill")
            # A rounded bar can't be narrower than it is tall
            width = max(float(progress["height"]), float(progress["width"]) * fraction)
            attributes.setdefault("timer_progress_fill", {})["width"] = _formatNumber(width)
    return {"values": values, "attributes": attributes, "hidden": hidden, "shown": shown}


# Clock --------------------------------------------------------------------------------

def clockParts(now: datetime) -> tuple:
    """("10", "05", "a") for 10:05 in the morning: 12-hour time without a leading zero."""
    return str(now.hour % 12 or 12), f"{now.minute:02d}", "a" if now.hour < 12 else "p"


def clockText(now: datetime) -> str:
    hours, minutes, suffix = clockParts(now)
    return f"{hours}:{minutes} {suffix}"


def clockScreen(theme: Theme, now: datetime) -> dict:
    """build() arguments for the clock screen. The colon shows on even seconds, so it blinks,
    and the time shifts so a one-digit hour stays centered like a two-digit one."""
    spec = theme.screens["clock"]["clock"]
    hours, minutes, suffix = clockParts(now)
    values = {spec["hours"]: hours, spec["minutes"]: minutes, spec["suffix"]: suffix}
    hidden, shown = ([], [spec["colon"]]) if now.second % 2 == 0 else ([spec["colon"]], [])
    shift = -(theme.textWidth("clock", spec["hours"], "00") - theme.textWidth("clock", spec["hours"], hours)) / 2
    transform = {"transform": f"translate({_formatNumber(shift)} 0)"} if shift else {}
    attributes = {spec["group"]: transform, spec["group"] + "__glow": transform} if transform else {}
    return {"values": values, "hidden": hidden, "shown": shown, "attributes": attributes}


# Display ------------------------------------------------------------------------------

class ThemedView(QWidget):
    """Shows a rendered screen, scaled to fit and letterboxed in the theme's background color."""

    def __init__(self, background: QColor, aspect: float):
        super().__init__()
        self.background = background
        self.aspect = aspect
        self._renderer: Optional[QSvgRenderer] = None
        self._pixmap: Optional[QPixmap] = None
        # An optional layer under the renderer's, rendered once and reused while its key stays the same
        self._background: Optional[QSvgRenderer] = None
        self._backgroundKey = None
        self._backgroundPixmap: Optional[QPixmap] = None
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)

    def setRenderer(self, renderer: Optional[QSvgRenderer], keepBackground=False):
        """Show renderer's screen, over the background layer if keepBackground."""
        if not keepBackground:
            self.setBackground(None, None)
        self._renderer = renderer
        self._pixmap = None
        self.update()

    def setBackground(self, renderer: Optional[QSvgRenderer], key):
        self._background = renderer
        self._backgroundKey = key
        self._backgroundPixmap = None
        self._pixmap = None

    def backgroundKey(self):
        return self._backgroundKey

    def targetRect(self) -> QRectF:
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return QRectF()
        if w / h > self.aspect:
            tw, th = h * self.aspect, h
        else:
            tw, th = w, w / self.aspect
        return QRectF((w - tw) / 2, (h - th) / 2, tw, th)

    def resizeEvent(self, event):
        self._pixmap = None
        self._backgroundPixmap = None
        super().resizeEvent(event)

    def paintEvent(self, event):
        # Filters make rendering slow, so render once per screen and size and reuse it
        if self._pixmap is None or self._pixmap.size() != self.size() * self.devicePixelRatioF():
            self._pixmap = self._render()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)
        painter.end()

    def _render(self) -> QPixmap:
        if self._background is not None:
            if self._backgroundPixmap is None or self._backgroundPixmap.size() != self.size() * self.devicePixelRatioF():
                self._backgroundPixmap = self._renderLayer(self._background, None)
            return self._renderLayer(self._renderer, self._backgroundPixmap)
        return self._renderLayer(self._renderer, None)

    def _renderLayer(self, renderer: Optional[QSvgRenderer], under: Optional[QPixmap]) -> QPixmap:
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(under) if under is not None else QPixmap(self.size() * ratio)
        pixmap.setDevicePixelRatio(ratio)
        if under is None:
            pixmap.fill(self.background)
        if renderer is not None and renderer.isValid():
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            renderer.render(painter, self.targetRect())
            painter.end()
        return pixmap


class ThemedAudience(QObject):
    """The themed audience display: rotates through the standings pages (after the welcome
    screen, in the welcome loop), or holds one screen shown with showScreen()."""

    def __init__(self, theme: Theme, teams: Callable[[], list], parent=None,
                 recent: Callable[[], list] = lambda: [], status: Callable[[], Optional[tuple]] = lambda: None):
        super().__init__(parent)
        self.theme = theme
        self._teams = teams
        self._recent = recent  # Latest scores, newest first
        self._status = status  # The match status, (match, status) or None
        self.eventName = ""
        self.eventDate = ""
        self.resultsUrl: Optional[str] = None  # The event results page, for the welcome screen's QR code
        self.view = ThemedView(theme.background, theme.width / theme.height)
        self._sequence: list = []
        self._position = 0
        self._held: Optional[tuple] = None  # (screen, build arguments) shown with showScreen()
        self._running = False
        self._welcome = False  # Whether the rotation starts with the welcome screen
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.advance)
        # Redraws the standings when the minute changes, for the time of day in their header
        self._minuteTimer = QTimer(self)
        self._minuteTimer.setSingleShot(True)
        self._minuteTimer.timeout.connect(self._onMinute)

    # Rotation

    def start(self, welcome: bool = False):
        """Start (or keep) showing the rotation, or the held screen. With welcome, the rotation
        is the welcome loop: the welcome screen, then every standings page."""
        if welcome != self._welcome:
            self._welcome = welcome
            self._timer.stop()
            self._position = 0
        self._running = True
        if self._held is None:
            if not self._timer.isActive():
                self._showCurrent()
        else:
            self._showHeld()

    def stop(self):
        """Stop changing screens, e.g. while a timer shows."""
        self._running = False
        self._timer.stop()
        self._minuteTimer.stop()

    def isRunning(self) -> bool:
        return self._running

    def refresh(self):
        """Show the latest standings and event details without restarting the rotation."""
        if not self._running:
            return
        if self._held is not None:
            self._showHeld()
            return
        current = self._sequence[self._position] if self._sequence else None
        self._sequence = self._buildSequence()
        if current in self._sequence:
            self._position = self._sequence.index(current)
        else:
            self._position = min(self._position, len(self._sequence) - 1)
        self._render(self._sequence[self._position])
        if len(self._sequence) > 1 and not self._timer.isActive():
            self._startTimer(self._sequence[self._position])

    def advance(self):
        """Move on to the next screen in the rotation."""
        if not self._running or self._held is not None:
            return
        self._sequence = self._buildSequence()
        self._position = (self._position + 1) % len(self._sequence)
        self._showCurrent(rebuild=False)

    def currentScreen(self) -> Optional[tuple]:
        """("welcome",), ("standings", page) or ("held", screen) for what the rotation shows."""
        if self._held is not None:
            return ("held", self._held[0])
        return self._sequence[self._position] if self._sequence else None

    def hasTimer(self) -> bool:
        return self.theme.hasScreen("timer")

    def hasClock(self) -> bool:
        return self.theme.hasScreen("clock") and "clock" in self.theme.screens["clock"]

    def hasWelcome(self) -> bool:
        return self.theme.hasScreen("welcome")

    def showClock(self, now: datetime):
        """Show the time of day in place of the rotation (until start() is called again).
        Call every second so the colon blinks."""
        self.stop()
        spec = self.theme.screens["clock"]["clock"]
        layer = [spec["group"]]
        if self.view.backgroundKey() != ("clock",):
            self.view.setBackground(self.theme.renderer("clock", hidden=layer), ("clock",))
        self.view.setRenderer(self.theme.renderer("clock", only=layer, **clockScreen(self.theme, now)),
                              keepBackground=True)

    def showTimer(self, title: str, remaining: int, total: int, warning: bool, expired: bool = False):
        """Show the timer screen in place of the rotation (until start() is called again)."""
        self.stop()
        args = timerScreen(self.theme, title, remaining, total, warning, expired)
        key = ("timer", title)
        if self.view.backgroundKey() != key:
            background = self.theme.renderer("timer", values={"timer_title": title}, hidden=TIMER_LAYER)
            self.view.setBackground(background, key)
        self.view.setRenderer(self.theme.renderer("timer", only=TIMER_LAYER, **args), keepBackground=True)

    def setEventInfo(self, name: str, date: str):
        self.eventName = name or ""
        self.eventDate = date or ""
        self.refresh()

    def setResultsUrl(self, url: Optional[str]):
        """The event results page, whose QR code the welcome screen shows, or None for none."""
        if url != self.resultsUrl:
            self.resultsUrl = url
            self.refresh()

    # Showing any screen (for the awards ceremony and announcements)

    def showScreen(self, screen: str, values: Optional[dict] = None, **kwargs):
        """Hold one of the theme's screens until resumeRotation(), filled with values
        (plus the event name and date). Takes the same keyword arguments as Theme.build()."""
        if not self.theme.hasScreen(screen):
            raise KeyError(f"The theme has no '{screen}' screen")
        self._timer.stop()
        self._held = (screen, dict(values or {}), kwargs)
        if self._running:
            self._showHeld()

    def resumeRotation(self):
        """Go back to rotating through the standings pages."""
        self._held = None
        if self._running:
            self._position = 0
            self._showCurrent()

    # Internals

    def _buildSequence(self) -> list:
        sequence = [("welcome",)] if self._welcome and self.hasWelcome() else []
        if self.theme.hasScreen("standings"):
            perPage = int(self.theme.screens["standings"].get("rows", 8))
            pages = standingsPageCount(len(self._teams()), perPage)
            sequence += [("standings", page) for page in range(1, pages + 1)]
        return sequence or [("blank",)]

    def _showCurrent(self, rebuild=True):
        if rebuild:
            self._sequence = self._buildSequence()
            self._position = min(self._position, len(self._sequence) - 1)
        item = self._sequence[self._position]
        self._render(item)
        if len(self._sequence) > 1:
            self._startTimer(item)

    def _startTimer(self, item: tuple):
        seconds = STANDINGS_PAGE_SECONDS
        self._timer.start(seconds * 1000)

    def _onMinute(self):
        if self._running and self._held is None:
            self._render(self._sequence[self._position])

    def _render(self, item: tuple):
        if item[0] == "standings":
            args = standingsPage(self.theme, standingsRows(self._teams()), item[1], self._recent(),
                                 status=self._status())
            if "header" in self.theme.screens["standings"]:
                now = datetime.now()
                self._minuteTimer.start((60 - now.second) * 1000 - now.microsecond // 1000 + 50)
            args["values"].update(self._eventValues("standings"))
            self.view.setRenderer(self.theme.renderer("standings", **args))
        elif item[0] == "welcome":
            self.view.setRenderer(self.theme.renderer("welcome", values=self._eventValues("welcome"),
                                                      results=self.resultsUrl))
        else:
            self.view.setRenderer(None)

    def _showHeld(self):
        screen, values, kwargs = self._held
        merged = self._eventValues(screen)
        merged.update(values)
        self.view.setRenderer(self.theme.renderer(screen, values=merged, **kwargs))

    def _eventValues(self, screen: str) -> dict:
        fields = self.theme.screens.get(screen, {}).get("fields", {})
        values = {}
        if "event_name" in fields:
            values["event_name"] = self.eventName
        if "event_date" in fields:
            values["event_date"] = self.eventDate
        return values
