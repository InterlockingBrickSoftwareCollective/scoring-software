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

import atexit
import json
import os
import platform
import shutil
import tempfile
import zipfile

# Global variable to store the temporary directory path
_temp_resource_dir: str | None = None
_pack_version: str | None = None


def getResourcePackVersion() -> str | None:
    """
    Return the resource pack version as read at initialization.
    """
    return _pack_version


def getResourcePath(filename: str) -> str:
    """
    Get the full path to a resource file in the extracted temporary directory.

    Args:
        filename: The name of the resource file (e.g., "bell.wav", "Roboto-Regular.ttf")

    Returns:
        The full path to the resource file in the temporary directory
    """
    if _temp_resource_dir is None:
        raise RuntimeError(
            "Resources not initialized. Call initializeResources() first."
        )
    return os.path.join(_temp_resource_dir, filename)


def isResourcePackInstalled() -> bool:
    """
    Check if a resource pack is installed by verifying the ZIP file exists.

    Returns:
        True if resource pack ZIP is installed, False otherwise
    """
    return _temp_resource_dir is not None


def installResourcePack(zipPath: str):
    """
    Install the specified resource pack by copying the ZIP to the resource pack directory.

    Args:
        zipPath: The path to the resource pack ZIP file
    """
    resource_path = _getResourcePackPath()
    dest_zip = os.path.join(resource_path, "resources.zip")

    # Create the resource pack directory if it doesn't exist
    os.makedirs(resource_path, exist_ok=True)

    # Copy the ZIP file (overwriting if it exists)
    shutil.copy2(zipPath, dest_zip)


def initializeResources():
    """
    Extract the resource pack ZIP to a temporary directory at program startup.
    This should be called once when the application starts.

    Raises:
        FileNotFoundError: If the resource pack ZIP is not installed
    """
    global _temp_resource_dir
    global _pack_version

    if _temp_resource_dir is not None:
        # Already initialized
        return

    resource_zip = os.path.join(_getResourcePackPath(), "resources.zip")

    if not os.path.exists(resource_zip):
        raise FileNotFoundError(f"Resource pack not installed at {resource_zip}")

    # Create a temporary directory
    _temp_resource_dir = tempfile.mkdtemp(prefix="ibss_resources_")

    # Extract the ZIP file to the temporary directory
    with zipfile.ZipFile(resource_zip, "r") as zip_ref:
        zip_ref.extractall(_temp_resource_dir)

    # Check manifest for pack version
    manifest_path = os.path.join(_temp_resource_dir, "manifest.json")

    try:
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
            _pack_version = manifest.get("packVersion")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        print("Resource pack manifest not found or invalid")
        _temp_resource_dir = None
        return

    # Register cleanup function to run at exit
    atexit.register(_cleanupResources)


def _cleanupResources():
    """
    Internal function to clean up the temporary resource directory on exit.
    """
    global _temp_resource_dir

    if _temp_resource_dir is not None and os.path.exists(_temp_resource_dir):
        try:
            shutil.rmtree(_temp_resource_dir)
        except Exception as e:
            print(f"Failed to clean up resources: {e}")
        finally:
            _temp_resource_dir = None


def _getResourcePackPath() -> str:
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
