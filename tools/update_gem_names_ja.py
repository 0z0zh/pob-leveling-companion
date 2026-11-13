"""Regenerate data/gem_names_ja.json (English gem name -> Japanese gem name).

Source: the gem lists of Grinding Gear Games' official trade site, in English and Japanese:
  https://www.pathofexile.com/api/trade/data/items
  https://jp.pathofexile.com/api/trade/data/items
Both lists contain the same gems in the same order, so entry N of one is entry N of the other.

This is a developer script, run by hand after a league update (2 requests). The app never fetches
these names itself; it only reads the generated JSON. The names are Grinding Gear Games' content.
Run:  python tools/update_gem_names_ja.py
"""
import json
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "gem_names_ja.json"
URLS = {"en": "https://www.pathofexile.com/api/trade/data/items",
        "ja": "https://jp.pathofexile.com/api/trade/data/items"}
HEADERS = {"User-Agent": "PoBLevelingCompanion-data-script/1.0"}


def gem_entries(lang):
    req = urllib.request.Request(URLS[lang], headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    return next(c for c in data["result"] if c["id"] == "gem")["entries"]


def main():
    en, ja = gem_entries("en"), gem_entries("ja")
    if len(en) != len(ja):
        raise SystemExit(f"gem lists differ in length (en {len(en)}, ja {len(ja)}); not writing anything")
    names = {}
    for e, j in zip(en, ja):
        # same position must be the same kind of entry, otherwise the lists are not aligned
        if (e.get("flags"), e.get("discriminator")) != (j.get("flags"), j.get("discriminator")):
            raise SystemExit(f"gem lists are not aligned at {e.get('type')!r}; not writing anything")
        key = e["type"].strip().lower()
        if j["type"] and j["type"] != e["type"]:
            names.setdefault(key, j["type"])
    OUT.write_text(json.dumps(dict(sorted(names.items())), ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(names)} gem names)")


if __name__ == "__main__":
    main()
