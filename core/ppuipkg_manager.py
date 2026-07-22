import os
import json
import xml.etree.ElementTree as ET

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
                        tree = ET.parse(pkg_path)
                        root = tree.getroot()
                        nodes = root.findall(".//userinterfaceicondata")
                        for node in nodes:
                            name_elem = node.find("name")
                            img_elem = node.find("image_name")
                            pkg_elem = node.find("asset_package")

                            img_path = img_elem.text if img_elem is not None and img_elem.text else ""
                            pkg_name = pkg_elem.text if pkg_elem is not None and pkg_elem.text else os.path.basename(root_dir)

                            if name_elem is not None and name_elem.text:
                                icon_id = name_elem.text.strip()
                            else:
                                icon_id = os.path.splitext(os.path.basename(img_path))[0] if img_path else "Icon"

                            if icon_id and icon_id not in seen_ids:
                                seen_ids.add(icon_id)
                                icons.append({
                                    "id": icon_id,
                                    "path": img_path,
                                    "assetPackage": pkg_name
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
        init_dir = os.path.join(mod_root, "Init")
        os.makedirs(init_dir, exist_ok=True)

        icons_by_pkg = {}
        for icon in icons:
            pkg_name = icon.get("assetPackage") or icon.get("asset_package") or mod_name
            icons_by_pkg.setdefault(pkg_name, []).append(icon)

        if not icons_by_pkg:
            icons_by_pkg[mod_name] = []

        last_path = ""
        for pkg_name, pkg_icons in icons_by_pkg.items():
            pkg_ui_dir = os.path.join(mod_root, "UI", pkg_name)
            os.makedirs(pkg_ui_dir, exist_ok=True)
            pkg_path = os.path.join(pkg_ui_dir, f"userinterfaceimages{pkg_name.lower()}.ppuipkg")

            lines = [
                '<PPUIPKGRoot file_count="0" icondata_count="{}" game="Jurassic World Evolution 3">'.format(len(pkg_icons)),
                '\t<types>'
            ]
            for icon in pkg_icons:
                icon_id = icon.get("id") or icon.get("name") or "Icon"
                img_path = icon.get("path") or icon.get("image_name") or ""
                lines.append('\t\t<userinterfaceicondata>')
                lines.append('\t\t\t<name>{}</name>'.format(icon_id))
                lines.append('\t\t\t<image_name>{}</image_name>'.format(img_path))
                lines.append('\t\t\t<asset_package>{}</asset_package>'.format(pkg_name))
                lines.append('\t\t</userinterfaceicondata>')

                norm_img_path = img_path.replace("/", os.sep).replace("\\", os.sep)
                dir_name = os.path.dirname(norm_img_path)
                if dir_name:
                    icon_folder = os.path.join(pkg_ui_dir, dir_name)
                    os.makedirs(icon_folder, exist_ok=True)

            lines.append('\t</types>')
            lines.append('</PPUIPKGRoot>')
            with open(pkg_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            last_path = pkg_path

        return json.dumps({"success": True, "path": last_path, "count": len(icons)})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def verify_ppuipkg_paths(mod_name, icons_json_str):
    try:
        icons = json.loads(icons_json_str) if isinstance(icons_json_str, str) else (icons_json_str or [])
        mod_dir = os.path.join(BASE_DIR, "Generated", mod_name)
        results = {}
        for icon in icons:
            icon_id = icon.get("id") or icon.get("name") or "icon"
            pkg_name = icon.get("assetPackage") or icon.get("asset_package") or mod_name
            img_path = icon.get("path") or icon.get("image_name") or ""

            pkg_ui_dir = os.path.join(mod_dir, "UI", pkg_name)
            ppuipkg_file = os.path.join(pkg_ui_dir, f"userinterfaceimages{pkg_name.lower()}.ppuipkg")

            norm_img_path = img_path.replace("/", os.sep).replace("\\", os.sep)
            dir_name = os.path.dirname(norm_img_path)
            image_folder = os.path.join(pkg_ui_dir, dir_name) if dir_name else pkg_ui_dir

            file_exists = os.path.isfile(ppuipkg_file)
            folder_exists = os.path.isdir(image_folder)

            exists = file_exists and folder_exists
            results[icon_id] = {
                "exists": exists,
                "file_exists": file_exists,
                "folder_exists": folder_exists,
                "ppuipkg_file": ppuipkg_file,
                "image_folder": image_folder
            }
        return json.dumps({"success": True, "results": results})
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
