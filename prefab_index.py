"""Build a compact, queryable index of JWE3_Prefabs.lua.

WHY AN INDEX RATHER THAN SHIPPING THE DUMP
------------------------------------------
The prefab dump is enormous and is a flat Lua table, so anything that wants to
ask "what can I inherit from?" or "what properties does X set?" would otherwise
re-scan hundreds of megabytes per question. This produces one JSON file the UI
(and species_gen.py) can load instantly.

DUMP FORMAT - the traps that make hand-grepping unreliable
----------------------------------------------------------
* Top-level entries sit at COLUMN 0:            triceratopsjwe = {
* Top-level keys are LOWERCASED by the dumper, but the values inside keep their
  real casing ('TriceratopsJWE'). Searching with the original capitalisation
  finds nothing - always match case-insensitively.
* A name that appears ONLY as an inner `Prefab = 'X'` reference and never as a
  column-0 entry is ENGINE-SIDE. Inheriting it yields a prefab that compiles and
  spawns but inherits nothing - no renderer, invisible, and no error anywhere.
  The index records both sets so callers can tell them apart.

OUTPUT  (prefab_index.json)
---------------------------
{
  "entries": {
     "<lowercase name>": {
        "name":   "<lowercase name as it appears at column 0>",
        "parent": "Dimetrodon_Female" | null,   # its `Prefab =` value
        "props":  {"ModelName": "Deinodoot_Female", ...},   # simple Default= only
        "line":   930650,
        "is_variant": true            # _01 / _02 style cosmetic variant
     }, ...
  },
  "referenced_only": ["livebaitbase", ...]   # named as parents but never defined
}

Usage:
    python prefab_index.py                 # writes prefab_index.json next to the dump
    python prefab_index.py --stats
"""
import argparse
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(BASE, "JWE3_Prefabs.lua")
if not os.path.isfile(DUMP):
    parent_dump = os.path.join(os.path.dirname(BASE), "JWE3_Prefabs.lua")
    if os.path.isfile(parent_dump):
        DUMP = parent_dump

OUT = os.path.join(BASE, "prefab_index.json")


ENTRY_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*\{")
PARENT_RE = re.compile(r"""^\s*Prefab\s*=\s*['"]([^'"]+)['"]""")
# a property block:   ModelName = {   ...   Default = 'X'
PROPKEY_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*)\s*=\s*\{\s*$")
DEFAULT_RE = re.compile(r"""^\s*Default\s*=\s*['"]([^'"]+)['"]""")
VARIANT_RE = re.compile(r"_\d{2}$")

# Properties worth surfacing in a prefab builder UI. Everything else is still
# captured, this is only the suggested ordering/allow-list for the front end.
COMMON_PROPS = [
    "ModelName", "MaterialLayersName", "MaterialEffectsName",
    "MaterialPatternsName", "MaterialVariantsName", "MaterialPatternIndex",
    "MotionGraphName", "AssetPackages",
]


def build(dump_path=DUMP):
    entries = {}
    parents_seen = set()

    cur = None          # current entry dict
    children_depth = None
    pending_prop = None  # property key whose Default= we are waiting for

    with open(dump_path, "r", encoding="utf-8", errors="ignore") as f:
        for lineno, line in enumerate(f, 1):
            if line[:1] not in (" ", "\t", "\r", "\n", ""):
                m = ENTRY_RE.match(line)
                if m:
                    name = m.group(1).lower()
                    cur = {"name": name, "parent": None, "props": {},
                           "line": lineno,
                           "is_variant": bool(VARIANT_RE.search(name))}
                    entries[name] = cur
                    depth = line.count("{") - line.count("}")
                    children_depth = None
                    pending_prop = None
                    continue

            if cur is None:
                continue

            depth += line.count("{") - line.count("}")
            if depth <= 0:
                cur = None
                children_depth = None
                pending_prop = None
                continue

            if "Children = {" in line and children_depth is None:
                children_depth = depth

            if children_depth is not None and depth < children_depth:
                children_depth = None

            if children_depth is not None:
                continue

            m = PARENT_RE.match(line)
            if m and cur["parent"] is None:
                cur["parent"] = m.group(1)
                parents_seen.add(m.group(1).lower())
                continue

            m = PROPKEY_RE.match(line)
            if m:
                prop = m.group(1)
                if prop not in cur["props"]:
                    pending_prop = prop
                continue

            if pending_prop:
                m = DEFAULT_RE.match(line)
                if m:
                    cur["props"][pending_prop] = m.group(1)
                    pending_prop = None




    referenced_only = sorted(p for p in parents_seen if p not in entries)
    return {"entries": entries, "referenced_only": referenced_only}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", default=DUMP)
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    if not os.path.isfile(args.dump):
        print(f"ERROR: dump not found: {args.dump}")
        return 1

    print(f"indexing {args.dump} ...")
    idx = build(args.dump)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(idx, f, indent=2)


    e = idx["entries"]
    print(f"  {len(e)} top-level entries")
    print(f"  {len(idx['referenced_only'])} names referenced as a parent but NEVER "
          f"defined (engine-side - do NOT inherit these)")
    print(f"  {sum(1 for v in e.values() if v['is_variant'])} _NN cosmetic variants")
    print(f"  {sum(1 for v in e.values() if v['parent'])} entries declare a parent")
    print(f"wrote {args.out} ({os.path.getsize(args.out)/1e6:.1f} MB)")

    if args.stats:
        from collections import Counter
        c = Counter(k for v in e.values() for k in v["props"])
        print("\nmost common properties:")
        for k, n in c.most_common(15):
            print(f"  {k:28s} {n}")
        print("\nsample engine-side (referenced but undefined):")
        for n in idx["referenced_only"][:15]:
            print("  ", n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
