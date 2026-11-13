"""PoB Leveling Companion - desktop app entry point.

Runs the local server in the background and shows the UI in its own window
(Edge WebView2 via pywebview) instead of a browser tab.
Build the exe with build_exe.bat.
"""
import ctypes
import os
import threading
from ctypes import wintypes

import webbrowser

import webview

import server
import updater

TITLE = "PoB Leveling Companion"
DEFAULT_WINDOW = {"width": 1400, "height": 850, "x": None, "y": None, "onTop": False}

_user32 = ctypes.windll.user32
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
_user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_uint]


def _find_own_window():
    """Handle of this process's top-level window titled TITLE (or None)."""
    found = []
    pid = os.getpid()
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _user32.IsWindowVisible(hwnd):
            buf = ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, buf, 256)
            if buf.value == TITLE:
                found.append(hwnd)
                return False
        return True

    _user32.EnumWindows(proc(cb), 0)
    return found[0] if found else None


def _set_topmost(on):
    # SetWindowPos is safe to call from any thread. pywebview's own `window.on_top = ...`
    # touches the WinForms window from the JS-bridge thread, which can deadlock the UI.
    hwnd = _find_own_window()
    if hwnd:
        _user32.SetWindowPos(hwnd, HWND_TOPMOST if on else HWND_NOTOPMOST, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    return bool(hwnd)


class Api:
    """Functions callable from the page as window.pywebview.api.*
    (attributes starting with "_" are not exposed to the page)."""

    def __init__(self, on_top):
        self._on_top = on_top
        self._window = None  # set after the window is created (underscore: not exposed to the page)

    def get_on_top(self):
        return self._on_top

    def open_url(self, url):
        # links open in the normal browser, not inside the app window
        if str(url).startswith("https://github.com/"):
            webbrowser.open(url)

    def apply_update(self):
        result = updater.apply()
        if result.get("ok"):
            # the update script swaps the exe once this process has exited
            threading.Timer(0.8, self._window.destroy).start()
        return result

    def toggle_on_top(self):
        if _set_topmost(not self._on_top):
            self._on_top = not self._on_top
            server.CONFIG.setdefault("window", dict(DEFAULT_WINDOW))["onTop"] = self._on_top
            server.save_config(server.CONFIG)
        return self._on_top


def main():
    url = server.start_server(port=0)  # free port, so it never clashes with another running copy
    win_cfg = {**DEFAULT_WINDOW, **server.CONFIG.get("window", {})}
    api = Api(bool(win_cfg["onTop"]))
    window = webview.create_window(
        TITLE, url, js_api=api,
        width=win_cfg["width"], height=win_cfg["height"], x=win_cfg["x"], y=win_cfg["y"],
        on_top=api._on_top, min_size=(800, 500), background_color="#0e0f12",
    )

    def on_closing():
        # remember size / position for next launch
        try:
            server.CONFIG["window"] = {"width": window.width, "height": window.height,
                                       "x": window.x, "y": window.y, "onTop": api._on_top}
            server.save_config(server.CONFIG)
        except Exception:  # noqa: BLE001
            pass

    api._window = window
    window.events.closing += on_closing
    webview.start()


if __name__ == "__main__":
    main()
