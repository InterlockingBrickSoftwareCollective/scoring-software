"""
EventHub.py: Helper for submitting scoresheets to FIRST Event Hub

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

import requests

EVENT_HUB_URL = "https://o76fno8oxh.execute-api.eu-central-1.amazonaws.com/api/score_input/commands"

HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 IBSS/0.0.1"
}

def get_score(tasks: dict) -> int:
  eh_request = {"data": {"type": "generate_public_score", "attributes": tasks}}

  resp = requests.post(EVENT_HUB_URL, json=eh_request, headers=HEADERS)
  resp.raise_for_status()

  resp_data = resp.json()["data"]["attributes"]

  return resp_data["overall_score"]