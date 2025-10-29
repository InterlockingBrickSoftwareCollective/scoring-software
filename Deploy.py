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

import os
import shutil

import PyInstaller.__main__

shutil.rmtree('./dist/', ignore_errors=True)
shutil.rmtree('./build/', ignore_errors=True)

# Generate version file
os.mkdir("build")
with open(os.path.join("build", "Version.py"), "w") as verFile:
    try:
        import subprocess
        out = subprocess.check_output(
            ["git", "describe", "--tags", "--dirty"],
            stderr=subprocess.DEVNULL)
        appVersion = out.decode().strip()[1:] # strip off v from tag name
        verFile.write(f"version = \"{appVersion}\"")
    except:
        # can't determine version, don't bundle a potentially bad one!
        pass

PyInstaller.__main__.run([
    'Main.py',
    os.path.join("build", "Version.py"),
    '-y', # replace output directory
    '-F', # single-file distribution
    '-w', # no console window
    '-i', 'icon.png',
    '--add-data', 'icon.png:.',
    '--hidden-import', 'requests',
])
