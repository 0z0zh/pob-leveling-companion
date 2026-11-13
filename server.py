"""PoB Leveling Companion - local server.

Reads Path of Building build files / export codes, PoB passive tree data and the
PoE Client.txt log, and serves a single-page UI that shows the passive tree
and skill gems side by side, switching sets automatically on level-up.

Started by the desktop app (app.py / PoBLevelingCompanion.exe) via start_server().
"""
import base64
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# When packaged with PyInstaller: bundled read-only files live in sys._MEIPASS,
# while config/cache must sit next to the exe so they survive restarts.
FROZEN = getattr(sys, "frozen", False)
RES_DIR = Path(getattr(sys, "_MEIPASS", HERE))
APP_DIR = Path(sys.executable).resolve().parent if FROZEN else HERE
CONFIG_PATH = APP_DIR / "config.json"
CACHE_DIR = APP_DIR / "cache"
STATIC_DIR = RES_DIR / "static"
DATA_DIR = RES_DIR / "data"

def documents_dir():
    """The user's Documents folder (handles OneDrive / relocated folders on Windows)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0:  # CSIDL_PERSONAL
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    return Path.home() / "Documents"


def _steam_libraries():
    """Steam library folders from the registry + libraryfolders.vdf."""
    roots = []
    if os.name == "nt":
        try:
            import winreg
            for hive, key, name in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
                try:
                    with winreg.OpenKey(hive, key) as k:
                        roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                except OSError:
                    pass
        except ImportError:
            pass
    libs = []
    for root in roots:
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="replace")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
        except OSError:
            pass
    return libs


def detect_client_log():
    """Find PoE's Client.txt (Steam, standalone or Epic install). Returns '' when not found."""
    cands = [lib / "steamapps" / "common" / "Path of Exile" / "logs" / "Client.txt" for lib in _steam_libraries()]
    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            cands.append(Path(base) / "Grinding Gear Games" / "Path of Exile" / "logs" / "Client.txt")
            cands.append(Path(base) / "Epic Games" / "PathOfExile" / "logs" / "Client.txt")
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\GrindingGearGames\Path of Exile") as k:
                cands.append(Path(winreg.QueryValueEx(k, "InstallLocation")[0]) / "logs" / "Client.txt")
        except OSError:
            pass
    found = [p for p in cands if p.is_file()]
    # several installs: use the one the game wrote to most recently
    return str(max(found, key=lambda p: p.stat().st_mtime)) if found else ""


DEFAULT_CONFIG = {
    "port": 8765,
    "pobDir": os.path.join(os.environ.get("APPDATA", ""), "Path of Building Community"),
    "buildsDir": str(documents_dir() / "Path of Building" / "Builds"),
    "clientLog": "",  # auto-detected on start when empty or missing
    "characterName": "",  # empty = follow any character's level-up
    "lastBuild": "",
    "lang": "",  # "" = follow the system language
    "timerAutoStart": False,  # start the run timer automatically on a new character
    "gemNameLang": "",  # language of gem names: "" = follow the system language, "en" or "ja"
    "updateCheck": True,  # check GitHub for a newer release at start-up
    "timerStart": None,  # wall-clock time of the manual timer start
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print("config.json read error:", e)
    cfg.pop("gemLang", None)  # replaced by gemNameLang (old default was always English)
    if not cfg.get("clientLog") or not Path(cfg["clientLog"]).is_file():
        found = detect_client_log()
        if found:
            cfg["clientLog"] = found
    return cfg


def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")


CONFIG = load_config()
if not CONFIG_PATH.exists():
    save_config(CONFIG)


# ---------------------------------------------------------------- Lua parsing
class LuaParser:
    """Minimal parser for PoB's data files (a `return { ... }` table literal)."""

    _ws = re.compile(r"(?:\s+|--\[\[.*?\]\]|--[^\n]*)+", re.S)
    _num = re.compile(r"-?(?:0x[0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)")
    _ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

    def __init__(self, text):
        self.s = text
        self.i = 0

    def ws(self):
        m = self._ws.match(self.s, self.i)
        if m:
            self.i = m.end()

    def parse(self):
        self.ws()
        if self.s.startswith("return", self.i):
            self.i += 6
        return self.value()

    def value(self):
        self.ws()
        c = self.s[self.i]
        if c == "{":
            return self.table()
        if c in "\"'":
            return self.string()
        if self.s.startswith("true", self.i):
            self.i += 4
            return True
        if self.s.startswith("false", self.i):
            self.i += 5
            return False
        if self.s.startswith("nil", self.i):
            self.i += 3
            return None
        m = self._num.match(self.s, self.i)
        if m:
            self.i = m.end()
            t = m.group(0)
            if t.lower().startswith(("0x", "-0x")):
                return int(t, 16)
            f = float(t)
            return int(f) if f.is_integer() and "." not in t and "e" not in t.lower() else f
        raise ValueError(f"unexpected {self.s[self.i:self.i+30]!r} at {self.i}")

    def string(self):
        q = self.s[self.i]
        self.i += 1
        out = []
        while True:
            c = self.s[self.i]
            if c == "\\":
                n = self.s[self.i + 1]
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(n, n))
                self.i += 2
            elif c == q:
                self.i += 1
                return "".join(out)
            else:
                out.append(c)
                self.i += 1

    def table(self):
        self.i += 1
        arr, obj = [], {}
        while True:
            self.ws()
            c = self.s[self.i]
            if c == "}":
                self.i += 1
                break
            if c == "[":
                self.i += 1
                key = self.value()
                self.ws()
                self.i += 1  # ]
                self.ws()
                self.i += 1  # =
                obj[str(key)] = self.value()
            else:
                m = self._ident.match(self.s, self.i)
                if m and m.group(0) not in ("true", "false", "nil"):
                    j = m.end()
                    k = self._ws.match(self.s, j)
                    j2 = k.end() if k else j
                    if self.s[j2] == "=" and self.s[j2 + 1] != "=":
                        self.i = j2 + 1
                        obj[m.group(0)] = self.value()
                        self._sep()
                        continue
                arr.append(self.value())
            self._sep()
        if obj and arr:
            for n, v in enumerate(arr, 1):
                obj[str(n)] = v
            return obj
        return obj if obj else arr

    def _sep(self):
        self.ws()
        if self.i < len(self.s) and self.s[self.i] in ",;":
            self.i += 1


# ---------------------------------------------------------------- tree data
_tree_cache = {}
_tree_lock = threading.Lock()
KEEP_NODE_KEYS = (
    "name", "stats", "group", "orbit", "orbitIndex", "out", "in", "isNotable",
    "isKeystone", "isMastery", "isJewelSocket", "ascendancyName", "isAscendancyStart",
    "classStartIndex", "masteryEffects", "isMultipleChoiceOption", "isBloodline", "isProxy", "expansionJewel",
)


def tree_dir_for(version):
    base = Path(CONFIG["pobDir"]) / "TreeData"
    if (base / version / "tree.lua").exists():
        return base / version
    versions = sorted(
        (d.name for d in base.iterdir() if d.is_dir() and re.fullmatch(r"3_\d+", d.name)),
        key=lambda v: int(v.split("_")[1]),
    )
    return base / versions[-1]


def get_tree(version):
    with _tree_lock:
        d = tree_dir_for(version or "")
        ver = d.name
        if ver in _tree_cache:
            return _tree_cache[ver]
        CACHE_DIR.mkdir(exist_ok=True)
        cache = CACHE_DIR / f"tree_{ver}.json"
        src = d / "tree.lua"
        if cache.exists() and cache.stat().st_mtime >= src.stat().st_mtime:
            data = json.loads(cache.read_text(encoding="utf-8"))
        else:
            print(f"Parsing tree data {ver} (first time only)...")
            raw = LuaParser(src.read_text(encoding="utf-8")).parse()
            data = compute_tree(raw, ver)
            cache.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
        _tree_cache[ver] = data
        return data


def orbit_angles(n):
    import math
    if n == 16:
        deg = [0, 30, 45, 60, 90, 120, 135, 150, 180, 210, 225, 240, 270, 300, 315, 330]
    elif n == 40:
        deg = [0, 10, 20, 30, 40, 45, 50, 60, 70, 80, 90, 100, 110, 120, 130, 135, 140, 150, 160,
               170, 180, 190, 200, 210, 220, 225, 230, 240, 250, 260, 270, 280, 290, 300, 310, 315,
               320, 330, 340, 350]
    else:
        deg = [360 * i / n for i in range(n)]
    return [math.radians(d) for d in deg]


def compute_tree(raw, ver):
    import math
    consts = raw["constants"]
    radii = consts["orbitRadii"]
    per_orbit = consts["skillsPerOrbit"]
    angles = [orbit_angles(n) for n in per_orbit]
    groups = raw["groups"]
    nodes = {}
    for nid, n in raw["nodes"].items():
        if nid == "root" or not isinstance(n, dict):
            continue
        g = groups.get(str(n.get("group"))) if isinstance(groups, dict) else None
        if g is None or n.get("isProxy") or n.get("expansionJewel") and n.get("group") is None:
            continue
        orbit = n.get("orbit", 0)
        a = angles[orbit][n.get("orbitIndex", 0)]
        r = radii[orbit]
        out = {k: n[k] for k in KEEP_NODE_KEYS if k in n}
        out["x"] = round(g["x"] + math.sin(a) * r, 1)
        out["y"] = round(g["y"] - math.cos(a) * r, 1)
        out["gx"], out["gy"] = g["x"], g["y"]
        if "classStartIndex" not in n and isinstance(n.get("spc"), list) and n["spc"]:
            out["classStartIndex"] = n["spc"][0]
        nodes[nid] = out
    classes = []
    for c in raw["classes"]:
        classes.append({"name": c["name"], "ascendancies": [a["id"] for a in c.get("ascendancies", [])]})
    alternates = [{"id": a["id"], "name": a.get("name", a["id"])} for a in raw.get("alternate_ascendancies", [])]
    return {"version": ver, "nodes": nodes, "classes": classes, "alternates": alternates,
            "bounds": [raw.get("min_x"), raw.get("min_y"), raw.get("max_x"), raw.get("max_y")]}


# ---------------------------------------------------------------- gem data
_gems = None


def get_gems():
    """Map variantId / skillId -> {name, color, support}."""
    global _gems
    if _gems is not None:
        return _gems
    _gems = {}
    path = Path(CONFIG["pobDir"]) / "Data" / "Gems.lua"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return _gems
    for block in re.split(r'\n\t\["Metadata/', text)[1:]:
        def f(key):
            m = re.search(r"\n\t\t" + key + r' = "?([^",\n]*)', block)
            return m.group(1) if m else ""
        req = {c: int(f("req" + c) or 0) for c in ("Str", "Dex", "Int")}
        best = max(req, key=req.get)
        color = {"Str": "r", "Dex": "g", "Int": "b"}[best] if req[best] > 0 else "w"
        info = {"name": f("name"), "color": color, "support": "\t\t\tsupport = true" in block}
        for k in (f("variantId"), f("grantedEffectId")):
            if k:
                _gems.setdefault(k, info)
    return _gems


# ---------------------------------------------------------------- build parsing
def decode_export_code(code):
    code = re.sub(r"\s+", "", code.strip())
    if code.startswith("http"):
        raise ValueError("ERR_URL_NOT_SUPPORTED")  # translated in the UI
    b = base64.urlsafe_b64decode(code.replace("+", "-").replace("/", "_") + "=" * (-len(code) % 4))
    return zlib.decompress(b).decode("utf-8")


def parse_build(xml_text):
    root = ET.fromstring(xml_text)
    b = root.find("Build")
    gems_db = get_gems()
    build = {
        "className": b.get("className") if b is not None else "",
        "ascendClassName": b.get("ascendClassName") if b is not None else "",
        "level": int(b.get("level", 1)) if b is not None else 1,
        "trees": [], "skillSets": [], "activeSpec": 0, "activeSkillSet": 0,
    }
    tree = root.find("Tree")
    if tree is not None:
        build["activeSpec"] = int(tree.get("activeSpec", 1)) - 1
        for i, spec in enumerate(tree.findall("Spec")):
            nodes = [n for n in (spec.get("nodes") or "").split(",") if n]
            masteries = re.findall(r"\{(\d+),(\d+)\}", spec.get("masteryEffects") or "")
            build["trees"].append({
                "index": i,
                "title": spec.get("title") or f"Tree {i + 1}",
                "treeVersion": spec.get("treeVersion") or "",
                "classId": spec.get("classId"),
                "ascendClassId": spec.get("ascendClassId"),
                "secondaryAscendClassId": spec.get("secondaryAscendClassId"),
                "nodes": nodes,
                "masteries": {m: e for m, e in masteries},
            })
    skills = root.find("Skills")
    if skills is not None:
        build["activeSkillSet"] = int(skills.get("activeSkillSet", 1))
        sets = skills.findall("SkillSet")
        if not sets:  # very old format: skills directly under <Skills>
            sets = [skills]
        for i, ss in enumerate(sets):
            groups = []
            for sk in ss.findall("Skill"):
                gems = []
                for g in sk.findall("Gem"):
                    info = gems_db.get(g.get("variantId") or "") or gems_db.get(g.get("skillId") or "") or {}
                    name = g.get("nameSpec") or info.get("name") or g.get("skillId") or "?"
                    support = info.get("support", False) or "Support" in (g.get("gemId") or "")
                    gems.append({
                        "name": name + (" Support" if support and not name.endswith("Support") else ""),
                        "gemId": g.get("gemId") or "",
                        "level": g.get("level"), "quality": g.get("quality"),
                        "enabled": g.get("enabled") != "false",
                        "color": info.get("color", "w"), "support": support,
                    })
                if not gems:
                    continue
                groups.append({
                    "label": sk.get("label") or "", "slot": sk.get("slot") or "",
                    "enabled": sk.get("enabled") != "false",
                    "fromItem": bool(sk.get("source")), "gems": gems,
                })
            ss_id = int(ss.get("id", i + 1)) if ss.get("id") else i + 1
            build["skillSets"].append({"index": i, "id": ss_id, "title": ss.get("title") or f"Skill set {i + 1}", "groups": groups})
    notes = root.find("Notes")
    build["notes"] = (notes.text or "").strip() if notes is not None else ""
    return build


# ---------------------------------------------------------------- log watcher
# Level-up system message. The text is localised by the game client:
#   EN: "] : Name (Duelist) is now level 12"
#   JA: "] : Name (デュエリスト)はレベル12になりました"
# The last pattern is a loose fallback for other client languages ("] : Name (Class)<text><number><text>").
LEVEL_RES = [
    re.compile(r"\] : (\S+) \(([^)]+)\) is now level (\d+)"),
    re.compile(r"\] : (\S+) \(([^)]+)\)はレベル(\d+)になりました"),
    re.compile(r"\] : (\S+) \(([^)]+)\)[^\d()]{1,40}?(\d+)[^\d()]{0,20}$"),
]
# Localised class / ascendancy names -> English (anything else is passed through unchanged).
CLASS_ALIASES = {
    "マローダー": "Marauder", "デュエリスト": "Duelist", "レンジャー": "Ranger", "シャドウ": "Shadow",
    "ウィッチ": "Witch", "テンプラー": "Templar", "サイオン": "Scion",
    "ジャガーノート": "Juggernaut", "バーサーカー": "Berserker", "チーフテン": "Chieftain",
    "スレイヤー": "Slayer", "グラディエーター": "Gladiator", "チャンピオン": "Champion",
    "デッドアイ": "Deadeye", "パスファインダー": "Pathfinder", "ウォーデン": "Warden",
    "アサシン": "Assassin", "サボター": "Saboteur", "トリックスター": "Trickster",
    "ネクロマンサー": "Necromancer", "エレメンタリスト": "Elementalist", "オカルティスト": "Occultist",
    "インクイジター": "Inquisitor", "ハイロファント": "Hierophant", "ガーディアン": "Guardian",
    "アセンダント": "Ascendant", "レリクアリアン": "Reliquarian", "ルミナリー": "Luminary",
}
ENGLISH_CLASSES = set(CLASS_ALIASES.values()) | {"Raider"}
# e.g. Generating level 40 area "1_4_town" -> act 4 ; "2_6_town" -> act 6 ; "2_11_endgame_town" -> 11 (not localised).
# The act number is the second field for both parts (part 2 = acts 6-10, 11 = epilogue / endgame).
AREA_RE = re.compile(r'Generating level \d+ area "(([12])_(\d+)_[^"]*)"')
TS_RE = re.compile(r"^(\d{4})/(\d\d)/(\d\d) (\d\d):(\d\d):(\d\d) ")
PID_RE = re.compile(r"\[[A-Z]+ Client (\d+)\]")
STRAND_AREA = "1_1_1"  # The Twilight Strand (first area of a new character)


def game_running():
    """True when a Path of Exile client process exists (any of PathOfExile*.exe)."""
    if os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                        ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

        k32 = ctypes.windll.kernel32
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if snap in (None, wintypes.HANDLE(-1).value):
            return True
        try:
            e = PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = k32.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                if e.szExeFile.lower().startswith("pathofexile"):
                    return True
                ok = k32.Process32NextW(snap, ctypes.byref(e))
        finally:
            k32.CloseHandle(snap)
        return False
    except Exception:  # noqa: BLE001
        return True


class RunTimer:
    """Leveling run timer rebuilt from Client.txt timestamps.

    - start: manual by default ("Start" button; the wall-clock time is saved in config.json as
      timerStart so the run survives restarts). With the timerAutoStart setting, a run starts
      automatically when a new character entered The Twilight Strand (detected on its first level-up
      to Lv2; the start time is the "You have entered ..." message right after the strand loaded).
    - an act split is taken the first time an area of a later act is generated
    - stops when the epilogue / endgame town (act 11) is reached
    - time while the game was closed is excluded: a new client process id means the game was
      restarted, and the gap since the previous process's last line is not counted
    """

    def __init__(self):
        self.paused = 0.0       # total excluded seconds so far
        self.last_ts = None
        self.last_pid = None
        self.act = None
        self._await_enter = False
        self.strand_enter_ts = None  # wall time the strand was entered (auto start candidate)
        self.manual_start = CONFIG.get("timerStart")       # wall time of the manual start, or None
        self.reset_at = CONFIG.get("timerResetAt") or 0.0  # auto starts before this are ignored
        self.run = None

    def eff(self, ts):
        return ts - self.paused

    def _new_run(self, start_eff):
        self.run = {"start": start_eff, "splits": {self.act or 1: start_eff}, "end": None}

    def _maybe_manual(self, ts):
        if self.manual_start is not None and self.run is None and ts >= self.manual_start:
            self._new_run(self.eff(self.manual_start))

    def feed(self, line):
        """Updates clock/pause bookkeeping; returns the line's timestamp (or None)."""
        m = TS_RE.match(line)
        if not m:
            return None
        ts = time.mktime((*map(int, m.groups()), 0, 0, -1))
        self._maybe_manual(ts)
        p = PID_RE.search(line)
        if not p:
            # e.g. "***** LOG FILE OPENING *****" written when the game starts: it has no client id,
            # so it must not advance the clock of the previous session (that would hide the gap)
            return ts
        pid = p.group(1)
        if self.last_pid and pid != self.last_pid and self.last_ts is not None and ts > self.last_ts:
            self.paused += ts - self.last_ts  # game was closed in between
        self.last_ts, self.last_pid = ts, pid
        return ts

    def on_area(self, ts, area_id, act):
        self.act = act
        if area_id == STRAND_AREA:
            self._await_enter = True
            self.strand_enter_ts = ts
        r = self.run
        # Acts are played in order, so only the next act counts as a split. A bigger jump
        # (e.g. Act 4 -> endgame town) means another character was played and is ignored.
        if r and r["end"] is None and act == max(r["splits"]) + 1:
            r["splits"][act] = self.eff(ts)
            if act >= 11:
                r["end"] = self.eff(ts)

    def on_system_message(self, ts):
        if self._await_enter:  # "You have entered ..." right after loading the strand
            self._await_enter = False
            self.strand_enter_ts = ts

    def on_level(self, name, lvl):
        if (lvl == 2 and CONFIG.get("timerAutoStart") and self.manual_start is None
                and self.strand_enter_ts is not None and self.strand_enter_ts > self.reset_at):
            self.act = 1
            self._new_run(self.eff(self.strand_enter_ts))
            self.strand_enter_ts = None

    # ---- button actions (called from the HTTP thread)
    def start_now(self):
        now = time.time()
        self.manual_start = now
        self.run = None
        self._new_run(self.eff(now))
        CONFIG["timerStart"] = now
        save_config(CONFIG)

    def reset(self):
        self.manual_start = None
        self.run = None
        self.strand_enter_ts = None
        self.reset_at = time.time()
        CONFIG["timerStart"] = None
        CONFIG["timerResetAt"] = self.reset_at
        save_config(CONFIG)

    def snapshot(self):
        r = self.run
        if not r:
            return {"active": False}
        running = r["end"] is None and game_running()
        if r["end"] is not None:
            now = r["end"]
        elif running:
            now = self.eff(max(time.time(), self.last_ts or 0))
        else:
            now = max(self.eff(self.last_ts), r["start"]) if self.last_ts is not None else r["start"]
        acts = sorted(r["splits"])
        splits = []
        for i, a in enumerate(acts):
            if a >= 11:
                break
            begin = r["splits"][a]
            end = r["splits"][acts[i + 1]] if i + 1 < len(acts) else now
            splits.append({"act": a, "start": begin - r["start"], "duration": max(0.0, end - begin),
                           "current": i + 1 == len(acts) and r["end"] is None})
        return {"active": True, "total": max(0.0, now - r["start"]), "ticking": running,
                "finished": r["end"] is not None, "splits": splits}


class LogWatcher(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.level = None
        self.character = None
        self.char_class = None
        self.act = None
        self._known_class = {}  # character name -> English class seen earlier
        self.timer = RunTimer()
        self.updated = 0.0
        self.error = None
        self._path = None
        self._pos = 0

    def _on_line(self, line):
        ts = self.timer.feed(line)
        a = AREA_RE.search(line)
        if a:
            act = min(int(a.group(3)), 11)  # 11 = epilogue / endgame town
            self.act = act
            if ts is not None:
                self.timer.on_area(ts, a.group(1), act)
            return
        if "] : " not in line:
            return
        if ts is not None:
            self.timer.on_system_message(ts)
        if "(" not in line:
            return
        m = next((m for r in LEVEL_RES if (m := r.search(line))), None)
        if not m:
            return
        name, cls, lvl = m.group(1), m.group(2).strip(), int(m.group(3))
        if not 1 <= lvl <= 100:
            return
        want = CONFIG.get("characterName") or ""
        if want and want != name:
            return
        cls = CLASS_ALIASES.get(cls, cls)
        if cls in ENGLISH_CLASSES:
            self._known_class[name] = cls
        else:
            # unknown (e.g. untranslated ascendancy name): keep what we knew for this character
            cls = self._known_class.get(name, cls)
        self.character, self.char_class, self.level = name, cls, lvl
        self.updated = time.time()
        self.timer.on_level(name, lvl)

    def _initial_scan(self, path):
        size = path.stat().st_size
        # read the tail (enough to find the latest level-up), not the whole file
        with open(path, "rb") as f:
            chunk = 8 * 1024 * 1024
            start = max(0, size - chunk)
            f.seek(start)
            data = f.read().decode("utf-8", "replace")
        for line in data.splitlines():
            self._on_line(line)
        self._pos = size

    def run(self):
        while True:
            try:
                raw = CONFIG.get("clientLog") or ""
                path = Path(raw)
                if raw != self._path:
                    self._path = raw
                    self._pos = 0
                    self.level = self.character = self.act = None
                    self.timer = RunTimer()
                    if raw and path.is_file():
                        self._initial_scan(path)
                if not raw:
                    self.error = "ERR_LOG_NOT_SET"  # translated in the UI
                elif path.is_file():
                    size = path.stat().st_size
                    if size < self._pos:  # log was truncated/rotated
                        self._pos = 0
                    if size > self._pos:
                        with open(path, "rb") as f:
                            f.seek(self._pos)
                            data = f.read()
                        nl = data.rfind(b"\n")
                        if nl >= 0:
                            self._pos += nl + 1
                            for line in data[: nl + 1].decode("utf-8", "replace").splitlines():
                                self._on_line(line)
                    self.error = None
                else:
                    self.error = f"ERR_LOG_NOT_FOUND|{path}"  # translated in the UI
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
            time.sleep(2)

    def rescan(self):
        self._path = None


WATCHER = LogWatcher()


# ---------------------------------------------------------------- HTTP
def list_builds():
    base = Path(CONFIG["buildsDir"])
    out = []
    if base.exists():
        for p in base.rglob("*.xml"):
            out.append({"path": str(p.relative_to(base)).replace("\\", "/"), "mtime": p.stat().st_mtime})
    out.sort(key=lambda b: -b["mtime"])
    return out


def build_path(rel):
    base = Path(CONFIG["buildsDir"]).resolve()
    p = (base / rel).resolve()
    if base not in p.parents:
        raise ValueError("invalid path")
    return p


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        try:
            if u.path in ("/", "/index.html"):
                return self._send(200, (STATIC_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/state":
                return self._send(200, {
                    "level": WATCHER.level, "character": WATCHER.character, "charClass": WATCHER.char_class,
                    "updated": WATCHER.updated, "logError": WATCHER.error, "act": WATCHER.act, "timer": WATCHER.timer.snapshot(),
                })
            if u.path == "/api/config":
                return self._send(200, CONFIG)
            if u.path == "/api/update":
                import updater
                return self._send(200, updater.public(updater.check(force=q.get("force") == "1")))
            if u.path == "/api/gem_names_ja":
                return self._send(200, (DATA_DIR / "gem_names_ja.json").read_bytes())
            if u.path == "/api/gem_sources":
                return self._send(200, (DATA_DIR / "gem_sources.json").read_bytes())
            if u.path == "/api/builds":
                return self._send(200, list_builds())
            if u.path == "/api/build":
                p = build_path(q["path"])
                build = parse_build(p.read_text(encoding="utf-8"))
                build["mtime"] = p.stat().st_mtime
                if CONFIG.get("lastBuild") != q["path"]:
                    CONFIG["lastBuild"] = q["path"]
                    save_config(CONFIG)
                return self._send(200, build)
            if u.path == "/api/build_mtime":
                return self._send(200, {"mtime": build_path(q["path"]).stat().st_mtime})
            if u.path == "/api/tree":
                return self._send(200, get_tree(q.get("version", "")))
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        try:
            if u.path == "/api/timer":
                action = body.get("action")
                if action == "start":
                    WATCHER.timer.start_now()
                elif action == "reset":
                    WATCHER.timer.reset()
                return self._send(200, WATCHER.timer.snapshot())
            if u.path == "/api/import":
                return self._send(200, parse_build(decode_export_code(body["code"])))
            if u.path == "/api/config":
                for k in ("buildsDir", "clientLog", "characterName", "pobDir", "lang", "timerAutoStart", "gemNameLang", "updateCheck"):
                    if k in body:
                        CONFIG[k] = body[k]
                save_config(CONFIG)
                global _gems
                _gems = None
                WATCHER.rescan()
                return self._send(200, CONFIG)
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": str(e)})


def start_server(port=None):
    """Start the log watcher and HTTP server in background threads; returns the URL.
    port=0 lets the OS pick a free port (used by the desktop app)."""
    if not WATCHER.is_alive():
        WATCHER.start()
    srv = ThreadingHTTPServer(("127.0.0.1", int(CONFIG.get("port", 8765)) if port is None else port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}/"
