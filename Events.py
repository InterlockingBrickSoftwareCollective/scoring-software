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

import time
import traceback

from dataclasses import dataclass, field
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
    """A team's score for a round was set. score is never negative."""
    teamNumber: int
    round: int
    score: int
    # Task key -> value, as recorded by scoresheet entry; None for scores entered without a scoresheet.
    # Subscribers must not modify it.
    scoresheet: Optional[dict] = None


@dataclass(frozen=True)
class ScoreCleared(Event):
    """A team's score for a round was removed, so the round is unplayed again."""
    teamNumber: int
    round: int


@dataclass(frozen=True)
class MatchSelected(Event):
    """The current match number changed, so that match is the next one to run."""
    match: int


@dataclass(frozen=True)
class AudienceThemeChanged(Event):
    """The operator turned the resource pack's themed audience display on or off."""
    enabled: bool


@dataclass(frozen=True)
class GlowEffectsChanged(Event):
    """The operator turned the themed audience display's glow effects on or off."""
    enabled: bool


@dataclass(frozen=True)
class EventInfoChanged(Event):
    """The operator set the event name and date shown on the themed audience display.
    An empty name means to use the score reflector's event name, if sync is set up."""
    name: str
    date: str


@dataclass(frozen=True)
class ClockAfterPracticeChanged(Event):
    """The operator chose whether the audience display shows the time of day after practice ends."""
    enabled: bool


@dataclass(frozen=True)
class AwardsChanged(Event):
    """The operator saved the awards (Awards.Award objects, in presentation order)."""
    awards: tuple


@dataclass(frozen=True)
class AdvancementChanged(Event):
    """The operator saved the teams advancing to the next event (team numbers in presentation
    order) and that event's name (empty if it isn't named)."""
    nextEvent: str
    teams: tuple


@dataclass(frozen=True)
class MatchStatusChanged(Event):
    """What's going on at the event changed (see MatchStatus): status is one of
    MatchStatus.MATCH_STATUSES for a match, one of MatchStatus.EVENT_STATUSES with match 0,
    or None when there's no status."""
    match: int
    status: Optional[str]


@dataclass(frozen=True)
class MatchStarted(Event):
    match: int
    # When the match's timer started, in seconds since the epoch
    at: float = field(default_factory=time.time)


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


def unsubscribe(eventType: type, handler: Callable[[Event], None]):
    """Stop calling a handler previously passed to subscribe() with the same eventType."""
    handlers = _subscribers.get(eventType, [])
    if handler in handlers:
        handlers.remove(handler)


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
