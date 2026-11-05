#!/usr/bin/env python3
"""Checks the car profiles against the JSON Schema and builds one pack per make (dist/<make>.json) and the index
LibreHU Apps and LibreHU service read (dist/index.json). No dependency but `jsonschema` (pip install jsonschema).

    python3 tools/build_packs.py           # check + build dist/
    python3 tools/build_packs.py --check   # check only (pull requests)

A pack's revision is the number of commits that touched its folder (brands/<make>/): it only moves when that make
changes, so fixing a Renault updates the Renault pack and nothing else. Its "engine" is the highest one its profiles
ask for (Semantic Versioning, see the "engine" field of each profile).
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRANDS = ROOT / "brands"
DIST = ROOT / "dist"
NAMES = {"renault": "Renault", "hyundai-kia": "Hyundai, Kia", "toyota": "Toyota", "honda": "Honda", "volkswagen": "Volkswagen group", "psa": "Peugeot, Citroën, DS"}


def version(req: str):
    m = re.match(r"^(?:>=|\^)?\s*(\d+)(?:\.(\d+))?(?:\.(\d+))?$", req.strip())
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def revision(folder: Path) -> int:
    try:
        out = subprocess.run(["git", "rev-list", "--count", "HEAD", "--", str(folder.relative_to(ROOT))], cwd=ROOT, capture_output=True, text=True, check=True)
        return int(out.stdout.strip() or 0)
    except Exception:
        return 0


def check(schema) -> list:
    import jsonschema

    v = jsonschema.Draft202012Validator(schema)
    errors, ids = [], {}
    for f in sorted(BRANDS.rglob("*.json")):
        rel = f.relative_to(ROOT)
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except ValueError as e:
            errors.append(f"{rel}: not JSON ({e})")
            continue
        for e in v.iter_errors(d):
            errors.append(f"{rel}: {'/'.join(map(str, e.path)) or '(top)'}: {e.message[:200]}")
        pid = d.get("id")
        if pid in ids:
            errors.append(f"{rel}: id {pid} also in {ids[pid]}")
        ids[pid] = rel
        if f.stem != pid:
            errors.append(f"{rel}: the file name must be its id ({pid}.json)")
        if not d.get("engine"):
            errors.append(f"{rel}: no \"engine\" (the engine version it needs, e.g. \">=2.0\")")
        if not d.get("examples"):
            errors.append(f"{rel}: no \"examples\" (at least one message and the values it gives)")
    return errors


def build() -> dict:
    DIST.mkdir(exist_ok=True)
    packs = []
    for folder in sorted(p for p in BRANDS.iterdir() if p.is_dir()):
        profiles = [json.loads(f.read_text(encoding="utf-8")) for f in sorted(folder.glob("*.json"))]
        if not profiles:
            continue
        engine = max((p.get("engine", ">=1.0") for p in profiles), key=version)
        makes = sorted({v["name"].split(" ")[0].rstrip(",") for p in profiles for v in p.get("variants", []) if v.get("name")})
        pack = {
            "format": "librehu-car-pack",
            "version": 1,
            "id": folder.name,
            "name": NAMES.get(folder.name, folder.name.title()),
            "revision": revision(folder),
            "engine": engine,
            "profiles": profiles,
        }
        text = json.dumps(pack, ensure_ascii=False, indent=1) + "\n"
        (DIST / f"{folder.name}.json").write_text(text, encoding="utf-8")
        data = text.encode("utf-8")
        packs.append(
            {
                "id": folder.name,
                "name": pack["name"],
                "revision": pack["revision"],
                "engine": engine,
                "makes": makes,
                "profiles": [p["id"] for p in profiles],
                "cars": sum(len(p.get("variants", [])) for p in profiles),
                "file": f"{folder.name}.json",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    index = {"format": "librehu-car-packs", "version": 1, "packs": packs}
    (DIST / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return index


def main() -> int:
    schema = json.loads((ROOT / "schema" / "can-vehicle.schema.json").read_text(encoding="utf-8"))
    errors = check(schema)
    for e in errors:
        print("FAIL", e)
    if errors:
        return 1
    print(f"{len(list(BRANDS.rglob('*.json')))} profiles match the schema")
    if "--check" not in sys.argv:
        index = build()
        for p in index["packs"]:
            print(f"pack {p['id']}: revision {p['revision']}, {p['cars']} cars, engine {p['engine']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
