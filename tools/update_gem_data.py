"""Regenerate data/gem_sources.json from exile-leveling's public data.

Source: https://github.com/HeartofPhos/exile-leveling (common/data/json)
Run:  python tools/update_gem_data.py
"""
import json
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/HeartofPhos/exile-leveling/main/common/data/json/"
OUT = Path(__file__).resolve().parent.parent / "data" / "gem_sources.json"
ALL = ["Marauder", "Duelist", "Ranger", "Shadow", "Witch", "Templar", "Scion"]


def fetch(name):
    with urllib.request.urlopen(BASE + name, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    quests = fetch("quests.json")
    gems = fetch("gems.json")
    chars = fetch("characters.json")
    sources = {}

    def add(gem_id, entry):
        sources.setdefault(gem_id, []).append(entry)

    # starting gems / first chest
    for cls, c in chars.items():
        add(c["start_gem_id"], {"act": 1, "kind": "start", "quest": "startGem", "npc": "", "classes": [cls], "order": 0})
        add(c["chest_gem_id"], {"act": 1, "kind": "start", "quest": "chestGem", "npc": "", "classes": [cls], "order": 0})

    for order, q in enumerate(quests.values(), 1):
        act = int(q["act"])
        for offer in q["reward_offers"].values():
            for gem_id, x in offer.get("quest", {}).items():
                add(gem_id, {"act": act, "kind": "quest", "quest": q["name"], "npc": offer.get("quest_npc", ""),
                             "classes": x.get("classes") or ALL, "order": order})
            for gem_id, x in offer.get("vendor", {}).items():
                add(gem_id, {"act": act, "kind": "vendor", "quest": q["name"], "npc": x.get("npc", ""),
                             "classes": x.get("classes") or ALL, "order": order})

    out = {
        "gems": {gid: {"name": gems.get(gid, {}).get("name", gid.rsplit("/", 1)[-1]), "sources": sorted(src, key=lambda e: (e["act"], e["order"]))}
                 for gid, src in sources.items()},
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} ({len(out['gems'])} gems)")


if __name__ == "__main__":
    main()
