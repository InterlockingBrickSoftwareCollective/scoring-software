"""
Deploy.py: Create EXE of scoring software using PyInstaller

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

import shutil

import PyInstaller.__main__

shutil.rmtree('./dist/', ignore_errors=True)
shutil.rmtree('./build/', ignore_errors=True)

PyInstaller.__main__.run([
    'Main.py',
    '-y', # replace output directory
    '-F', # single-file distribution
    '-w', # no console window
    '-i', 'icon.png',
    "--add-data", "res/Roboto-Regular.ttf:res",
    "--add-data", "res/start.wav:res",
    "--add-data", "res/endgame.wav:res",
    "--add-data", "res/end.wav:res",
    "--add-data", "res/bell.wav:res",
    "--add-data", "res/foghorn.wav:res",
])
