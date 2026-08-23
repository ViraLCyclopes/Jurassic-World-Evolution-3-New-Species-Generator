"""Jurassic World Evolution 3 - Localization Module

Generates automatic dinosaur localization text files across all 14 official language subfolders.
"""

import os
import shutil
from core.templates import BASE_DIR

LOC_LANGUAGES = [
    ("English", "UnitedKingdom"),
    ("English", "UnitedStates"),
    ("French", "France"),
    ("German", "Germany"),
    ("Italian", "Italy"),
    ("Japanese", "Japan"),
    ("Korean", "Korea"),
    ("Polish", "Poland"),
    ("Portuguese", "Brazil"),
    ("Russian", "Russia"),
    ("SimpleChinese", "China"),
    ("Spanish", "Mexico"),
    ("Spanish", "Spain"),
    ("TraditionalChinese", "Taiwan")
]

BASE_LOCS_DIR = os.path.join(BASE_DIR, "Base Dinosaur Locs")


def generate_species_localizations(out_dir, species_name, report=None):
    """Generate species loc text files across all 14 language subfolders using Base Dinosaur Locs templates."""
    if not os.path.exists(BASE_LOCS_DIR):
        if report is not None and isinstance(report, dict):
            report.setdefault("warnings", []).append(f"Base Dinosaur Locs directory not found: {BASE_LOCS_DIR}")
        return []

    sp_lower = species_name.lower()
    written = []

    # Get all .txt template files directly in BASE_LOCS_DIR
    template_files = [
        f for f in os.listdir(BASE_LOCS_DIR)
        if os.path.isfile(os.path.join(BASE_LOCS_DIR, f)) and f.endswith(".txt")
    ]

    localised_root = os.path.join(out_dir, "Localised")

    for lang, country in LOC_LANGUAGES:
        target_dir = os.path.join(localised_root, lang, country)
        os.makedirs(target_dir, exist_ok=True)

        if lang == "English" and country == "UnitedStates":
            loc_dir = os.path.join(target_dir, "Loc")
            os.makedirs(loc_dir, exist_ok=True)

            for template_name in template_files:
                target_filename = template_name.replace("titanosaurusviral", sp_lower)
                src_path = os.path.join(BASE_LOCS_DIR, template_name)
                dst_path = os.path.join(loc_dir, target_filename)

                with open(src_path, "r", encoding="utf-8", errors="ignore") as f_in:
                    raw_content = f_in.read()

                with open(dst_path, "w", encoding="utf-8") as f_out:
                    f_out.write(raw_content)

                written.append(os.path.relpath(dst_path, out_dir))


    # Copy helper batch script into Localised/
    bat_src = os.path.join(BASE_DIR, "copy_us_locs.bat")
    if os.path.isfile(bat_src):
        bat_dst = os.path.join(localised_root, "copy_us_locs.bat")
        shutil.copy2(bat_src, bat_dst)
        written.append(os.path.relpath(bat_dst, out_dir))

    if report is not None and isinstance(report, dict):
        report.setdefault("warnings", []).append(
            f"Reminder for '{species_name}': Localization template files have been created under Localised/. "
            "It is up to you to edit your localization text files before building Loc.ovl! "
            "Use Localised\\copy_us_locs.bat to quickly copy your US Loc .ovl or Loc/ folder to all 13 other language folders."
        )


    return written
