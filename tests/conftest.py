import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import Events


@pytest.fixture(autouse=True)
def eventBus():
    """Give every test an event bus with no subscribers."""
    importlib.reload(Events)
    yield Events


@pytest.fixture
def published(eventBus):
    """Every event published during the test, in order."""
    events = []
    eventBus.subscribe(eventBus.Event, events.append)
    return events


@pytest.fixture
def database(tmp_path, monkeypatch):
    """Run the database layer against an empty working directory. Returns a function that
    closes the database and opens it again, as relaunching the application would."""
    import Substrate

    monkeypatch.chdir(tmp_path)
    importlib.reload(Substrate)
    Substrate.init()

    def reopen():
        Substrate.deinit()
        importlib.reload(Events)
        importlib.reload(Substrate)
        Substrate.init()
        return Substrate

    yield reopen
    Substrate.deinit()
