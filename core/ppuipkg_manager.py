import os
import json

from core.ppuipkg import (
    normalise_mod_asset_package, read_package, write_package,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def scan_mod_ppuipkg(mod_name):
    try:
        if not mod_name:
            return json.dumps({"success": False, "error": "No mod name provided"})
        ui_root = os.path.join(BASE_DIR, "Generated", mod_name, "UI")
        if not os.path.isdir(ui_root):
            return json.dumps({"success": True, "icons": []})

        icons = []
        seen_ids = set()
        for root_dir, _, files in os.walk(ui_root):
            for f in files:
                if f.lower().endswith(".ppuipkg"):
                    pkg_path = os.path.join(root_dir, f)
                    try:
                        _basic, _files, package_icons = read_package(pkg_path)
                        for img_path, pkg_name in package_icons:
                            icon_id = (os.path.splitext(os.path.basename(img_path))[0]
                                       if img_path else "Icon")
                            if icon_id and icon_id not in seen_ids:
                                seen_ids.add(icon_id)
                                icons.append({
                                    "id": icon_id,
                                    "path": img_path,
                                    "assetPackage": pkg_name,
                                })
                    except Exception:
                        pass
        return json.dumps({"success": True, "icons": icons})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def save_mod_ppuipkg(mod_name, icons_json):
    try:
        icons = json.loads(icons_json) if isinstance(icons_json, str) else icons_json
        mod_root = os.path.join(BASE_DIR, "Generated", mod_name)
        pkg_ui_dir = os.path.join(mod_root, "UI", mod_name)
        os.makedirs(pkg_ui_dir, exist_ok=True)
        pkg_path = os.path.join(
            pkg_ui_dir, f"userinterfaceimages{mod_name.lower()}.ppuipkg")

        icon_refs = []
        seen = set()
        for icon in icons:
            img_path = icon.get("path") or icon.get("image_name") or ""
            if not img_path or img_path in seen:
                continue
            seen.add(img_path)
            pkg_name = normalise_mod_asset_package(
                mod_name,
                icon.get("assetPackage")
                or icon.get("asset_package")
                or mod_name)
            icon_refs.append((img_path, pkg_name))

            norm_img_path = img_path.replace("/", os.sep).replace("\\", os.sep)
            dir_name = os.path.dirname(norm_img_path)
            if dir_name:
                os.makedirs(os.path.join(pkg_ui_dir, dir_name), exist_ok=True)

        # The editor owns only <types>. Preserve every embedded file (notably
        # author SVGs) byte-for-byte when saving icon references.
        existing_files = []
        if os.path.isfile(pkg_path):
            _basic, existing_files, _existing_icons = read_package(pkg_path)
        write_package(pkg_path, f"{mod_name}/UI",
                      files=existing_files, icons=icon_refs)

        return json.dumps({"success": True, "path": pkg_path,
                           "count": len(icon_refs)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def verify_ppuipkg_paths(mod_name, icons_json_str):
    try:
        icons = json.loads(icons_json_str) if isinstance(icons_json_str, str) else (icons_json_str or [])
        mod_dir = os.path.join(BASE_DIR, "Generated", mod_name)
        results = {}
        # The package lives at UI/<mod>/userinterfaceimages<mod>.ppuipkg - ONE
        # per mod, named for the MOD.
        #
        # It is NOT named for the icon's asset_package. That field is an
        # internal OVS stream name (Cobblestone: overlay `CobblestoneBlock`,
        # asset package `images_cobblestoneblock_decoration`), and treating it
        # as a folder made every icon whose package was not literally the mod
        # name report a false "PPUIPKG Missing" - e.g. `Capiraptor_Dinosaur_Small`
        # was looked up at UI/Capiraptor_Dinosaur_Small/, which never exists.
        pkg_ui_dir = os.path.join(mod_dir, "UI", mod_name)
        ppuipkg_file = os.path.join(
            pkg_ui_dir, f"userinterfaceimages{mod_name.lower()}.ppuipkg")
        file_exists = os.path.isfile(ppuipkg_file)

        listed = set()
        if file_exists:
            try:
                from core.ppuipkg import read_package
                _basic, _files, pkg_icons = read_package(ppuipkg_file)
                listed = {img for img, _p in pkg_icons}
            except Exception:
                listed = set()

        for icon in icons:
            icon_id = icon.get("id") or icon.get("name") or "icon"
            img_path = icon.get("path") or icon.get("image_name") or ""

            norm_img_path = img_path.replace("/", os.sep).replace("\\", os.sep)
            dir_name = os.path.dirname(norm_img_path)
            image_folder = os.path.join(pkg_ui_dir, dir_name) if dir_name else pkg_ui_dir
            folder_exists = os.path.isdir(image_folder)

            # cobra-tools ships a texture as the pair <name>.png.png + .png.tex,
            # so check for the actual art rather than just its directory.
            base = os.path.join(pkg_ui_dir, norm_img_path)
            image_exists = (os.path.isfile(base + ".png")
                            or os.path.isfile(base + ".tex")
                            or os.path.isfile(base))

            in_package = img_path in listed

            exists = file_exists and folder_exists and in_package and image_exists
            results[icon_id] = {
                "exists": exists,
                "file_exists": file_exists,
                "folder_exists": folder_exists,
                "in_package": in_package,
                "image_exists": image_exists,
                "ppuipkg_file": ppuipkg_file,
                "image_folder": image_folder
            }
        return json.dumps({"success": True, "results": results})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
