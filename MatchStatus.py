"""
MatchStatus.py: What's going on at the event, for the audience display

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

# The match status follows the same rules as the one sync reports to the score reflector
# (Sync.SyncEngine), but works whether or not sync is set up: a match is preparing until its
# timer starts, running until the timer completes, then scoring until the first score is
# entered, when the selected match is preparing. Selecting a match only shows while nothing
# else is going on: not during another match, nor an event-wide status or a cleared one the
# operator set. The operator sets event-wide statuses (practice, ceremonies) by hand.

from typing import Optional

import Events

MATCH_STATUSES = ("preparing", "running", "scoring")
EVENT_STATUSES = ("practice", "opening_ceremonies", "closing_ceremonies")

_status: Optional[tuple] = None  # (match, status), or None until there is one or it's cleared
_cleared = False  # The operator cleared it, so selecting a match doesn't bring it back
_selectedMatch: Optional[int] = None


def init():
    """Start following matches and score entry. Call once, before the first match is selected."""
    Events.subscribe(Events.MatchSelected, _onMatchSelected)
    Events.subscribe(Events.MatchStarted, lambda event: set(event.match, "running"))
    Events.subscribe(Events.MatchAborted, lambda event: set(event.match, "preparing"))  # It will run again
    Events.subscribe(Events.MatchCompleted, lambda event: set(event.match, "scoring"))
    Events.subscribe(Events.ScoreUpdated, _onScoreUpdated)


def current() -> Optional[tuple]:
    """The (match, status), or None if there is none. Event-wide statuses have match 0."""
    return _status


def set(match: int, status: str):
    """Set the status: one of MATCH_STATUSES for a match from 1, or one of EVENT_STATUSES (match is ignored)."""
    if status in MATCH_STATUSES:
        if int(match) < 1:
            raise ValueError(f"A {status} status needs a match number")
        _change((int(match), status))
    elif status in EVENT_STATUSES:
        _change((0, status))
    else:
        raise ValueError(f"Unknown match status {status!r}")


def clear():
    """Show no status until the operator sets one or a match starts."""
    global _cleared
    _cleared = True
    _change(None)


def _change(status: Optional[tuple]):
    global _status, _cleared
    if status is not None:
        _cleared = False
    if status == _status:
        return
    _status = status
    Events.publish(Events.MatchStatusChanged(*(status if status is not None else (0, None))))


def _onMatchSelected(event):
    global _selectedMatch
    _selectedMatch = int(event.match)
    if (_status is None and not _cleared) or (_status is not None and _status[1] == "preparing"):
        set(event.match, "preparing")


def _onScoreUpdated(event):
    # The first score entered after a match ends means the next one is being set up
    if _status is not None and _status[1] == "scoring":
        set(_selectedMatch if _selectedMatch is not None else _status[0] + 1, "preparing")
