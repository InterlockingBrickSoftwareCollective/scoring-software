import json

import pytest

import PitDisplay
from Sync import SyncConfig
from test_sync import syncFile


@pytest.mark.parametrize("code, url", [
    ("fall-qual", "https://scores.example.org/events/fall-qual/pit?dwell=10&panel=25&scale=100"),
    ("fall qual/2", "https://scores.example.org/events/fall%20qual%2F2/pit?dwell=10&panel=25&scale=100"),
])
def test_pit_display_url_includes_the_display_settings_so_the_page_does_not_ask(code, url):
    config = SyncConfig.parse(json.dumps(syncFile(event={"code": code, "name": "Fall"})))
    assert PitDisplay.pitDisplayUrl(config) == url
