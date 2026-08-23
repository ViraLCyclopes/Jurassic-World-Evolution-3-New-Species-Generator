"""Jurassic World Evolution 3 - Species Generator Entry Point

Modularized architecture re-exporting core generator, database, template, and logger functions.
"""

import sys
import os
import argparse
import json

# Add parent directory to path so core modules import seamlessly
BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# --- Re-export core constants and templates ---
from core.templates import (
    BASE_DIR, DEFAULT_SOURCE_FDB, DEFAULT_SOURCE_EXP_FDB, DEFAULT_OUT_ROOT,
    RESERVED_SPECIES_IDS, DEFAULT_ID_FLOOR,
    COSMETIC_TABLES, SPECIES_TABLES, EXPEDITION_TABLES,
    SCALE_TEMPLATE, SCALE_TEMPLATE_FALLBACK, SCALE_REQUIRE,
    PREFAB_LUA, COSMETIC_LUA, PREFABDATA_LUA, LUADATABASE_LUA,
    TECHTREE_LUA, REBIRTH_TECHTREE_LUA, INGEN_DATABASE_LUA,
    DINOSAUR_MODS_TECHTREE_LUA, INIT_DATABASE_LUA, ICON_MOUNT_LUA,
    MANIFEST_XML, DEFAULT_SPECIES_STATS, DEFAULT_GENOMES,
    DEFAULT_SPECIALISATION, DEFAULT_EXPEDITIONS, DEFAULT_BUILDING_UPGRADES
)


# --- Re-export core database operations ---
from core.database import (
    clone_fdb, clone_expeditions_fdb, ensure_table, read_table, write_table_rows,
    validate_cosmetics, add_digsite, list_generated_mods, scan_donor, allocate_species_ids
)




# --- Re-export core generator operations ---
from core.generator import (
    plan_species, serialize_lua_properties, _replace_lua_table,
    write_scale_module, audit_asset_packages, write_scaffold,
    generate_species
)

# --- Re-export core loggers & helpers ---
from core.logger import write_activity_log
from core.fdb_cloner import load_generated_mod_prefabs, scan_mod_assetpkgs, verify_asset_paths
from core.ppuipkg_manager import scan_mod_ppuipkg, save_mod_ppuipkg
from core.expeditions import load_digsites, add_digsite_to_fdb


def main():
    parser = argparse.ArgumentParser(
        description="Generate clean, update-safe JWE3 species mods."
    )
    parser.add_argument("--from-config", help="Path to JSON config file to generate from")
    args = parser.parse_args()

    if args.from_config:
        with open(args.from_config, "r", encoding="utf-8") as f:
            config = json.load(f)
        mod_name = config.get("mod_name", "CustomMod")
        species_configs = config.get("species", [])
        
        plans = []
        combined_report = {"warnings": [], "tables": {}, "exp_tables": {}}
        for sp_conf in species_configs:
            plan, rep = plan_species(sp_conf)
            plans.append({"config": sp_conf, **plan})
            if rep.get("warnings"):
                combined_report["warnings"].extend(rep["warnings"])

        res = generate_species(mod_name, plans, combined_report, config)
        print(f"Mod successfully generated at: {res['output_dir']}")


if __name__ == "__main__":
    main()
