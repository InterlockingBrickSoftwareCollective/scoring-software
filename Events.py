"""
Events.py: Application event bus

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

import traceback

from dataclasses import dataclass
from typing import Callable, Optional


# Event definitions
#
# Events describe something that has already happened (past tense) and are
# immutable, so a single instance can safely be handed to every subscriber.

@dataclass(frozen=True)
class Event:
    """Base class for all events. Subscribing to Event receives every event."""


@dataclass(frozen=True)
class TeamAdded(Event):
    number: int
    name: str
    pit: int


@dataclass(frozen=True)
class TeamUpdated(Event):
    number: int
    name: str
    pit: int


@dataclass(frozen=True)
class TeamDeleted(Event):
    number: int


@dataclass(frozen=True)
class ScoreUpdated(Event):
    teamNumber: int
    round: int
    score: int
    scoresheet: Optional[str] = None


@dataclass(frozen=True)
class MatchSelected(Event):
    """The current match number changed, so that match is now queueing."""
    match: int


@dataclass(frozen=True)
class MatchStarted(Event):
    match: int


@dataclass(frozen=True)
class MatchAborted(Event):
    match: int


@dataclass(frozen=True)
class MatchCompleted(Event):
    match: int


@dataclass(frozen=True)
class PracticeStarted(Event):
    duration: int


@dataclass(frozen=True)
class PracticeEnded(Event):
    """The practice session was stopped or ran out."""


@dataclass(frozen=True)
class TimerUpdated(Event):
    """The match or practice timer display should now read `remaining` seconds."""
    practice: bool
    remaining: int


@dataclass(frozen=True)
class TimerWarning(Event):
    """The running timer reached its warning time (e.g., endgame)."""


@dataclass(frozen=True)
class TimerExpired(Event):
    """The running timer reached 0:00."""


# Event bus
#
# Delivery is synchronous: publish() calls each subscriber in turn, on the
# publishing thread, before returning. Events are published from the Qt main
# thread, so subscribers must return quickly and hand any slow work (e.g.,
# network requests) off to their own thread.

_subscribers = {}


def subscribe(eventType: type, handler: Callable[[Event], None]):
    """Call handler with every published event of eventType (including its subclasses)."""
    _subscribers.setdefault(eventType, []).append(handler)


def publish(event: Event):
    """Deliver an event to all of its subscribers."""
    for eventType in type(event).__mro__:
        # Copy the handler list so handlers may subscribe while being called
        for handler in list(_subscribers.get(eventType, [])):
            # A failing subscriber must not break the code that published the event
            try:
                handler(event)
            except Exception:
                print(f"Error handling {event}:")
                traceback.print_exc()
