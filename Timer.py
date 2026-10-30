"""
Timer.py: Match and practice countdown timer

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

from dataclasses import dataclass
from typing import Optional

from PyQt6.QtCore import Qt, QTimer

import Events

MATCH_TIME = 150
MATCH_WARNING = 30  # Endgame
HOLD_TIME = 3  # Keep showing "0:00" for a few seconds after time runs out


@dataclass
class _Countdown:
    match: Optional[int]  # None for a practice session
    duration: int
    warning: int
    remaining: int


# Only one countdown (match or practice) runs at a time
_current: Optional[_Countdown] = None
_ticker = None


def init():
    """Initialize the timer. Must be called after the QApplication is created."""
    global _ticker
    _ticker = QTimer()
    _ticker.setTimerType(Qt.TimerType.PreciseTimer)  # The default coarse timer drifts ~0.2s over a match
    _ticker.setInterval(1000)
    _ticker.timeout.connect(_tick)


def isMatchRunning() -> bool:
    return _current is not None and _current.match is not None


def isPracticeRunning() -> bool:
    return _current is not None and _current.match is None


def startMatch(match: int):
    """Start the match timer, stopping any practice session in progress."""
    stopPractice()
    _start(_Countdown(match, MATCH_TIME, MATCH_WARNING, MATCH_TIME), Events.MatchStarted(match))


def abortMatch():
    if isMatchRunning():
        _stop(Events.MatchAborted(_current.match))


def startPractice(duration: int, warning: int) -> bool:
    """Start a practice session, unless a countdown is already running. Returns whether it started."""
    if _current is not None:
        return False

    _start(_Countdown(None, duration, warning, duration), Events.PracticeStarted(duration))
    return True


def stopPractice():
    if isPracticeRunning():
        _stop(Events.PracticeEnded())


def _start(countdown: _Countdown, startEvent: Events.Event):
    """Start a countdown, announce startEvent, then show the starting time."""
    global _current
    _current = countdown
    _ticker.start()
    Events.publish(startEvent)
    Events.publish(Events.TimerUpdated(countdown.match is None, countdown.remaining))


def _stop(endEvent: Events.Event):
    """Stop the running countdown, announce endEvent, then reset the display to the full duration."""
    global _current
    countdown, _current = _current, None
    _ticker.stop()
    Events.publish(endEvent)
    Events.publish(Events.TimerUpdated(countdown.match is None, countdown.duration))


def _tick():
    _current.remaining -= 1

    if _current.remaining < -HOLD_TIME:
        if _current.match is not None:
            _stop(Events.MatchCompleted(_current.match))
        else:
            _stop(Events.PracticeEnded())
        return

    Events.publish(Events.TimerUpdated(_current.match is None, max(0, _current.remaining)))
    if _current.remaining == _current.warning:
        Events.publish(Events.TimerWarning())
    if _current.remaining == 0:
        Events.publish(Events.TimerExpired())
