"""
PitDisplay.py: Cloud pit display, shown on the audience display in place of the local rankings

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

import importlib.util
import os
import sys
from typing import Optional
from urllib.parse import quote, urlencode

from PyQt6.QtCore import *
from PyQt6.QtWidgets import *

import ResourceManager
import Sync

# Pit display settings: seconds per page, panel size, and scale (%). With all of them given,
# the page doesn't ask for them, which nobody could answer on the audience display.
DISPLAY_SETTINGS = {"dwell": 10, "panel": 25, "scale": 100}

# How long to wait before trying again when the pit page doesn't load (e.g. the network is down)
RETRY_SECONDS = 30

# The page has keyboard focus once clicked, so forward the audience display's fullscreen keys from it
_KEY_SCRIPT = """
document.addEventListener('keydown', function (e) {
    if (e.key === 'F11' || e.key === 'Escape') {
        e.preventDefault();
        window.chrome.webview.postMessage({name: 'audienceKey', params: [e.key], id: ''});
    }
}, true);
"""


def isAvailable() -> bool:
    """The cloud pit display uses Windows' WebView2 runtime, so it's only offered on Windows."""
    return sys.platform == "win32" and importlib.util.find_spec("qtwebview2") is not None


def pitDisplayUrl(config: Sync.SyncConfig) -> str:
    """The score reflector's pit display page for the event."""
    return f"{config.scoresSiteUrl}/events/{quote(config.eventCode, safe='')}/pit?{urlencode(DISPLAY_SETTINGS)}"


def _createWebView(**kwargs) -> QWidget:
    # qtwebview2 is written against QtPy, which has to be told which binding this app uses
    os.environ.setdefault("QT_API", "pyqt6")
    import qtwebview2
    from qtwebview2 import QtWebView2Widget, _dotnet_bridge

    if getattr(sys, "frozen", False):
        # qtwebview2 0.5.0's PyInstaller hook bundles its .NET assemblies in qtwebview2/lib, but when
        # frozen it looks for them in lib at the top of the bundle, so point it at where they really are
        packageDir = os.path.dirname(qtwebview2.__file__)
        _dotnet_bridge.get_absolute_path = lambda filename: os.path.join(packageDir, filename)

    class WebView(QtWebView2Widget):
        def _init_webview(self):
            # Loading .NET can fail before qtwebview2 reports it, and an exception escaping a Qt slot
            # aborts the app, so report every failure through initialization_done instead
            try:
                super()._init_webview()
            except Exception as err:
                self.bridge.initialization_done.emit(False, str(err))

    return WebView(**kwargs)


class PitView(QWidget):
    """Shows a web page in a WebView2 control, which is created the first time a page is set."""

    failed = pyqtSignal(str)       # WebView2 couldn't start; the reason is suitable for the operator
    keyPressed = pyqtSignal(str)   # F11 or Escape, pressed while the page had focus
    _navigated = pyqtSignal(bool, str)

    def __init__(self):
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._web = None
        self._url: Optional[str] = None
        self._retry = QTimer(self, singleShot=True, interval=RETRY_SECONDS * 1000)
        self._retry.timeout.connect(self._reload)
        self._navigated.connect(self._onNavigated)

    def setUrl(self, url: str):
        if url == self._url and self._web is not None:
            return
        self._url = url
        self._retry.stop()
        if self._web is None:
            self._web = _createWebView(
                url=url,
                fullscreen_support=False,  # The audience display handles fullscreen itself
                background_color="#ececec",
                user_data_folder=os.path.join(ResourceManager.getAppDataPath(), "WebView2"),
                js_apis={"audienceKey": self.keyPressed.emit},
                init_settings_hook=self._configure,
            )
            self._web.bridge.initialization_done.connect(self._onInitialized)
            self._layout.addWidget(self._web)
        else:
            self._web.load_url(url)

    def _configure(self, core):
        core.AddScriptToExecuteOnDocumentCreatedAsync(_KEY_SCRIPT)
        core.NavigationCompleted += lambda sender, args: self._navigated.emit(
            bool(args.IsSuccess), str(args.WebErrorStatus))

    def _onInitialized(self, success: bool, problem: str):
        if success:
            return
        print(f"Cloud pit display couldn't start: {problem}")
        # qtwebview2 deletes the widget when it fails, so start over next time
        self._web = None
        self._url = None
        self.failed.emit(problem)

    def _onNavigated(self, success: bool, status: str):
        # Navigating to a new page cancels the one loading, which isn't a problem
        if success or status == "OperationCanceled":
            return
        print(f"Cloud pit display didn't load ({status}), trying again in {RETRY_SECONDS} seconds")
        self._retry.start()

    def _reload(self):
        if self._web is not None and self._url is not None:
            self._web.load_url(self._url)

