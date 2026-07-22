import os
import json
import sqlite3
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_generated_mod_prefabs(mod_name):
    try:
        main_dir = os.path.join(BASE_DIR, "Generated", mod_name, "Main")
        if not os.path.isdir(main_dir):
            return json.dumps({"success": False, "error": f"Generated Main directory for '{mod_name}' not found."})

        family = []
        for fname in sorted(os.listdir(main_dir)):
            if not fname.endswith(".lua"):
                continue
            if (re.search(r"_\d{2}\.lua$", fname) or 
                fname.startswith("database.") or 
                fname.startswith("managers.") or 
                fname.startswith("techtrees.") or 
                fname.endswith("dinosaurs.fdb") or 
                fname.endswith("expeditions.fdb")):
                continue

            full_path = os.path.join(main_dir, fname)
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            prefab_match = re.search(r"Prefab\s*=\s*['\"]([^'\"]+)['\"]", content)
            parent_prefab = prefab_match.group(1) if prefab_match else ""

            props = {}
            root_props_match = re.search(r"return\s*\{.*?\bProperties\s*=\s*\{(.*?)\}\s*,\s*\}", content, re.DOTALL)
            if root_props_match:
                block = root_props_match.group(1)
                prop_matches = re.findall(r"^\s*([A-Za-z0-9_]+)\s*=\s*\{\s*Default\s*=\s*(['\"].*?['\"]|\{.*?\}|true|false|[\w\d_\-\.]+)", block, re.MULTILINE | re.DOTALL)
                for prop_name, default_val in prop_matches:
                    if prop_name.endswith("Component") or "Audio" in prop_name or "Brain" in prop_name:
                        continue
                    default_val = default_val.strip()
                    if default_val.startswith("{") and default_val.endswith("}"):
                        items = re.findall(r"['\"]([^'\"]+)['\"]", default_val)
                        props[prop_name] = items
                    else:
                        clean_val = default_val.strip("'\"")
                        if clean_val == "true": clean_val = True
                        elif clean_val == "false": clean_val = False
                        props[prop_name] = clean_val

            member_name = os.path.splitext(fname)[0]
            family.append({
                "Name": member_name,
                "Prefab": parent_prefab or member_name,
                "Props": props
            })

        return json.dumps({"success": True, "family": family})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def scan_mod_assetpkgs(mod_name):
    try:
        if not mod_name:
            return json.dumps({"success": False, "error": "No mod name provided"})
        mod_dir = os.path.join(BASE_DIR, "Generated", mod_name)
        init_dir = os.path.join(mod_dir, "Init")
        if not os.path.exists(init_dir):
            return json.dumps({"success": True, "packages": {}})

        pkgs = {}
        for fname in os.listdir(init_dir):
            if fname.lower().endswith(".assetpkg"):
                pkg_name = fname[:-9]
                fp = os.path.join(init_dir, fname)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                        m = re.search(r"<asset_path>(.*?)</asset_path>", content, re.DOTALL)
                        asset_path = m.group(1).strip() if m else ""
                        pkgs[pkg_name] = asset_path
                except Exception:
                    pass
        return json.dumps({"success": True, "packages": pkgs})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def verify_asset_paths(mod_name, packages_json_str):
    try:
        packages = json.loads(packages_json_str) if isinstance(packages_json_str, str) else (packages_json_str or {})
        mod_dir = os.path.join(BASE_DIR, "Generated", mod_name)
        results = {}
        for name, path in packages.items():
            parts = [p for p in path.replace("/", "\\").split("\\") if p]
            lowered_parts = [p.lower() for p in parts]
            target_folder = ""
            if "ovldata" in lowered_parts:
                idx = lowered_parts.index("ovldata")
                if idx + 2 < len(parts):
                    rel_sub = os.path.join(*parts[idx + 2:])
                    target_folder = os.path.join(mod_dir, rel_sub)
                elif idx + 1 < len(parts):
                    rel_sub = os.path.join(*parts[idx + 1:])
                    target_folder = os.path.join(mod_dir, rel_sub)
            elif parts:
                target_folder = os.path.join(mod_dir, *parts)

            exists = os.path.isdir(target_folder) if target_folder else False
            results[name] = {"exists": exists, "target_folder": target_folder}
        return json.dumps({"success": True, "results": results})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
