"""
ResourceManager.py: Resource pack path management

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
import platform
import shutil
import zipfile


def getResourcePackPath() -> str:
    """Get the platform-specific path for the resource pack directory."""
    system = platform.system()

    if system == "Windows":
        # Use %LOCALAPPDATA%\Interlocking Brick Software\Scoring
        base_path = os.path.expandvars("%LOCALAPPDATA%")
        return os.path.join(base_path, "Interlocking Brick Software", "Scoring")
    else:
        # Linux/Unix: Use $XDG_DATA_HOME or fallback to ~/.local/share
        xdg_data_home = os.environ.get("XDG_DATA_HOME")
        if xdg_data_home:
            base_path = xdg_data_home
        else:
            base_path = os.path.expanduser("~/.local/share")
        return os.path.join(base_path, "interlocking-brick-scoring")


def getResourcePath(filename: str) -> str:
    """
    Get the full path to a resource file in the resource pack directory.

    Args:
        filename: The name of the resource file (e.g., "bell.wav", "Roboto-Regular.ttf")

    Returns:
        The full path to the resource file
    """
    return os.path.join(getResourcePackPath(), filename)


def isResourcePackInstalled() -> bool:
    """
    Check if a resource pack is installed by verifying the directory exists and has files.

    Returns:
        True if resource pack is installed, False otherwise
    """
    resource_path = getResourcePackPath()

    if not os.path.exists(resource_path):
        return False

    # Check if directory has at least one file (recursively)
    for root, dirs, files in os.walk(resource_path):
        if files:
            return True

    return False

def installResourcePack(zipPath: str):
    """
    Install the specified resource pack to the resource pack directory.

    Args:
        zipPath: The path to the resource pack ZIP file
    """
    resource_path = getResourcePackPath()

    # Delete existing resource pack directory if it exists
    if os.path.exists(resource_path):
        shutil.rmtree(resource_path)

    # Create the resource pack directory
    os.makedirs(resource_path, exist_ok=True)

    # Extract the ZIP file
    with zipfile.ZipFile(zipPath, 'r') as zip_ref:
        zip_ref.extractall(resource_path)