"""Update check and one-click self-update from GitHub releases.

- check(): asks the GitHub API for the latest release of this repository (one HTTPS request).
  Only the request itself is sent (User-Agent with the app version); no user data.
- apply(): downloads PoBLevelingCompanion.exe and its .sha256 from that release, verifies the hash,
  then starts a small hidden script that waits for this app to exit, swaps the exe and starts the
  new one. Only works in the packaged exe.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

REPO = "0z0zh/pob-leveling-companion"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
ASSET = "PoBLevelingCompanion.exe"

FROZEN = getattr(sys, "frozen", False)
_HERE = Path(__file__).resolve().parent
_RES = Path(getattr(sys, "_MEIPASS", _HERE))
_lock = threading.Lock()
_cache = None


def current_version():
    for p in (_RES / "VERSION", _HERE / "VERSION"):
        if p.is_file():
            return p.read_text(encoding="utf-8").strip()
    return "0.0.0"


def _parse(v):
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", str(v).strip())
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"PoBLevelingCompanion/{current_version()} (+https://github.com/{REPO})",
        "Accept": "application/vnd.github+json" if url == LATEST_API else "*/*",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def check(force=False):
    """Latest release info: {current, latest, hasUpdate, url, canApply, error?}."""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        cur = current_version()
        info = {"current": cur, "latest": None, "hasUpdate": False, "url": f"https://github.com/{REPO}/releases",
                "canApply": False}
        try:
            with _get(LATEST_API) as r:
                rel = json.loads(r.read().decode("utf-8"))
            assets = {a["name"]: a["browser_download_url"] for a in rel.get("assets", [])}
            info["latest"] = rel.get("tag_name", "").lstrip("v")
            info["url"] = rel.get("html_url") or info["url"]
            info["hasUpdate"] = _parse(info["latest"]) > _parse(cur)
            info["canApply"] = FROZEN and ASSET in assets and f"{ASSET}.sha256" in assets
            info["_assets"] = assets
        except Exception as e:  # noqa: BLE001  (offline, rate limited, ...: just no update info)
            info["error"] = str(e)
        _cache = info
        return info


def public(info):
    return {k: v for k, v in info.items() if not k.startswith("_")}


def apply():
    """Download + verify the new exe and schedule the swap. Returns {ok, error?}. Caller must then exit."""
    info = check()
    if not info.get("hasUpdate"):
        return {"ok": False, "error": "no update"}
    if not FROZEN:
        return {"ok": False, "error": "self-update only works in the exe"}
    assets = info.get("_assets", {})
    exe_url, sum_url = assets.get(ASSET), assets.get(f"{ASSET}.sha256")
    if not (exe_url and sum_url and exe_url.startswith(DOWNLOAD_PREFIX) and sum_url.startswith(DOWNLOAD_PREFIX)):
        return {"ok": False, "error": "release assets missing"}

    exe = Path(sys.executable).resolve()
    new = exe.with_name(exe.name + ".new")
    try:
        with _get(sum_url) as r:
            expected = r.read().decode("ascii", "replace").split()[0].lower()
        h = hashlib.sha256()
        with _get(exe_url, timeout=120) as r, open(new, "wb") as f:
            while chunk := r.read(1 << 16):
                h.update(chunk)
                f.write(chunk)
        if h.hexdigest() != expected:
            new.unlink(missing_ok=True)
            return {"ok": False, "error": "checksum mismatch"}
    except Exception as e:  # noqa: BLE001
        new.unlink(missing_ok=True)
        return {"ok": False, "error": str(e)}

    # PyInstaller onefile: the exe file is held by the bootloader (parent) process
    wait_pid = os.getppid()
    old = exe.with_name(exe.name + ".old")
    script = Path(tempfile.gettempdir()) / f"pblc_update_{os.getpid()}.cmd"
    script.write_text(f"""@echo off
rem PoB Leveling Companion updater: wait for the app to exit, swap the exe, start it again
for /l %%i in (1,1,60) do (
  tasklist /fi "PID eq {wait_pid}" 2>nul | find "{wait_pid}" >nul || goto swap
  ping -n 2 127.0.0.1 >nul
)
:swap
ping -n 2 127.0.0.1 >nul
move /y "{exe}" "{old}" >nul 2>&1 || goto fail
move /y "{new}" "{exe}" >nul 2>&1 || (move /y "{old}" "{exe}" >nul & goto fail)
start "" "{exe}"
ping -n 4 127.0.0.1 >nul
del "{old}" >nul 2>&1
:fail
del "%~f0" >nul 2>&1
""", encoding="mbcs" if os.name == "nt" else "utf-8")
    # The new exe must start as a fresh app: drop the PyInstaller variables this process inherited,
    # otherwise its bootloader treats it as our child and exits (PyInstaller "reset environment").
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI_", "_MEIPASS"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(["cmd", "/c", str(script)], creationflags=0x08000000,  # CREATE_NO_WINDOW
                     close_fds=True, cwd=str(exe.parent), env=env)
    return {"ok": True}
