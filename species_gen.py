"""JWE3 new-species generator - clone an existing species into a new one.

WHAT THIS DOES
--------------
Reads c0dinosaurs.fdb (plain SQLite), finds every row belonging to a source
species across all ~50 species-referencing tables, and writes a MOD FDB
containing copies of those rows under a brand new SpeciesID / GeneticSpeciesID
and Name. The result is a data-complete new species that behaves exactly like
its donor until you tune it.

WHAT IT DOES NOT DO
-------------------
It cannot invent art. The clone points at the donor's Prefab/model/textures, so
out of the box it IS the donor under a new name. Swapping the model, textures,
icons and loca strings is the manual part - see SPECIES_GEN_HANDOFF.md.

WHY THE PAIR TABLES WORK GENERICALLY
-------------------------------------
Identity is expressed by ANY column whose name contains "SpeciesID":
SpeciesID, GeneticSpeciesID, SpeciesIDPredator, PreySpeciesID,
InstigatorSpeciesID, OtherSpeciesID, SpeciesIDOverride, ...
So rather than hardcoding each relationship table, every such column is treated
as a reference. A row is cloned if ANY of its identity columns names the source,
and in the copy EVERY identity column that named the source is repointed at the
new species. That automatically gives the new species the donor's predator
relationships, prey relationships, cohabitation entries and social entries, in
both directions, with no per-table special cases.

Columns are split into two id spaces by name: anything containing "Genetic" uses
the GeneticSpecies id space, everything else uses the Species id space.

USAGE
-----
    # simplest: clone Triceratops as Torosaurus
    python species_gen.py --source Triceratops --name Torosaurus

    # pick ids yourself, point at a different prefab, and tune stats
    python species_gen.py --source Deinosuchus --name Sarcosuchus \
        --species-id 900 --genetic-id 900 \
        --prefab Sarcosuchus \
        --set SpeciesStats.MaxHealth=2500 \
        --set Species.READONLY_BioGroup=Reptile

    # see what would happen without writing anything
    python species_gen.py --source Ceratosaurus --name Foo --dry-run

    # restrict to a subset of tables while experimenting
    python species_gen.py --source X --name Y --only Species,SpeciesStats,UIData

    # use a previously saved config
    python species_gen.py --from-config species_config.json

Every run also writes a report listing exactly which tables and rows were
produced, and flags anything that needs a human decision.
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SOURCE_FDB = os.path.join(BASE, "extracted_fdbs", "c0dinosaurs.fdb")
DEFAULT_SOURCE_EXP_FDB = os.path.join(BASE, "extracted_fdbs", "c0expeditions.fdb")
DEFAULT_OUT_ROOT = os.path.join(BASE, "Generated")

# Species.SpeciesID carries an explicit CHECK constraint banning these.
RESERVED_SPECIES_IDS = {59, 61, 63, 64, 65, 323}

# Start well above vanilla so a game update adding species cannot collide.
DEFAULT_ID_FLOOR = 900

IDENT_RE = re.compile(r"SpeciesID", re.IGNORECASE)


# ---------------------------------------------------------------- schema utils

def table_names(con):
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def columns(con, table):
    """[(name, declared_type, is_pk), ...]"""
    return [(r[1], (r[2] or "").upper(), bool(r[5]))
            for r in con.execute(f'PRAGMA table_info("{table}")')]


def identity_columns(con, table):
    """Columns that reference a species, split by id space.

    Only INTEGER-typed columns count: names like SpeciesNameReadOnly and
    GeneticSpeciesNameReference contain the word but hold text, and
    IsSpeciesOverride / IsPrimarySpecies are flags.
    """
    out = []
    for name, decl, _pk in columns(con, table):
        if not IDENT_RE.search(name):
            continue
        if decl and "INT" not in decl:
            continue
        space = "genetic" if "genetic" in name.lower() else "species"
        out.append((name, space))
    return out




def species_tables(con):
    """{table: [(col, space), ...]} for every table referencing a species."""
    out = {}
    for t in table_names(con):
        ident = identity_columns(con, t)
        if ident:
            out[t] = ident
    return out


# ---------------------------------------------------------------- id handling

def lookup_species(con, name):
    row = con.execute(
        "SELECT SpeciesID, GeneticSpeciesID, Name FROM Species "
        "WHERE Name = ? COLLATE NOCASE", (name,)).fetchone()
    return row


def species_family(con, genetic_id):
    """All Species rows sharing a GeneticSpeciesID.

    A "species" is NOT one row. Triceratops is three:
        9   Triceratops           Adult/Female   prefab TriceratopsJWE
        67  Triceratops_Juvenile  Juvenile       prefab Triceratops_Juvenile
        109 Triceratops_Male      Adult/Male     prefab Triceratops_Male
    all with GeneticSpeciesID 7. Each needs its OWN new SpeciesID and its own
    unique Name, so the clone maps the whole family rather than a single id.
    """
    return con.execute(
        "SELECT SpeciesID, Name FROM Species WHERE GeneticSpeciesID = ? "
        "ORDER BY SpeciesID", (genetic_id,)).fetchall()


def build_family_maps(con, src_name, new_name, genetic_id, base_new_id,
                      explicit_base=None):
    """-> ({old_species_id: new_species_id}, {old_species_id: new_name})

    Names keep their variant suffix: Triceratops_Juvenile -> Torosaurus_Juvenile.
    The base row (exact name match) takes the requested/auto id so that the
    headline SpeciesID is predictable; the rest follow on.
    """
    fam = species_family(con, genetic_id)
    used = {r[0] for r in con.execute("SELECT SpeciesID FROM Species")}

    id_map, name_map = {}, {}
    next_id = base_new_id
    # base row first so it gets base_new_id
    fam_sorted = sorted(fam, key=lambda r: (r[1].lower() != src_name.lower(), r[0]))
    for old_id, old_name in fam_sorted:
        if explicit_base is not None and old_name.lower() == src_name.lower():
            nid = explicit_base
        else:
            while next_id in used or next_id in RESERVED_SPECIES_IDS:
                next_id += 1
            nid = next_id
            next_id += 1
        used.add(nid)
        id_map[old_id] = nid
        # preserve the variant suffix (_Juvenile, _Male, ...)
        suffix = old_name[len(src_name):] if old_name.lower().startswith(src_name.lower()) else ""
        name_map[old_id] = new_name + suffix
    return id_map, name_map


def pick_free_id(con, table, col, floor, banned=()):
    used = {r[0] for r in con.execute(f'SELECT "{col}" FROM "{table}"')}
    n = max(floor, 0)
    while n in used or n in banned:
        n += 1
    return n


# ---------------------------------------------------------------- cloning

# TEXT columns whose value names a game ASSET or DATA FILE, not the species.
# The donor's value must be KEPT: a renamed one points at a file that was never
# authored, and the game silently gets nothing.
#
#   SpeciesCosmeticInheritance.CosmeticInheritanceFile
#       an unreversed file format - we cannot produce a replacement at all, so
#       the clone MUST keep inheriting the donor's cosmetic file
#   SpeciesCosmeticSets.PackageName / AnimationPackageNameOverride
#       OVL asset/animation package names shipped with the base game
#   Breeding.SettingsFile            a data file reference
#   SpeciesAnimation.HatcheryMusicName   audio asset
#   SpeciesCosmeticSets.WorldSpaceMotionSpeciesNameOverride   motion reference
#
# Deliberately NOT preserved (these SHOULD follow the new species):
#   Species.Name / GeneticSpecies.Name        identity
#   Species.Prefab / SpeciesCosmeticSets.Prefab   point at the mod's own prefabs,
#                                                 including the generated _01s
#   UIData.LabelTextSymbol                    the mod supplies its own loca key
#   *.SpeciesNameReadOnly, *NameReference, READONLY names   mirrors of identity
PRESERVE_DONOR_TEXT = {
    ("SpeciesCosmeticInheritance", "CosmeticInheritanceFile"),
    ("SpeciesCosmeticSets", "PackageName"),
    ("SpeciesCosmeticSets", "AnimationPackageNameOverride"),
    ("SpeciesCosmeticSets", "WorldSpaceMotionSpeciesNameOverride"),
    ("Breeding", "SettingsFile"),
    ("SpeciesAnimation", "HatcheryMusicName"),
}


def clone_rows(con, table, idents, id_map, name_map, src_genetic, new_genetic,
               prefab_map=None, src_name=None, new_name=None, preserved=None):
    """Return (column_names, [row, ...]) of cloned rows for one table.

    id_map covers the WHOLE species family (adult/juvenile/male), so a row is
    matched and repointed if any species-space column names any family member.
    """
    cols = [c[0] for c in columns(con, table)]

    clauses, params = [], []
    for col, space in idents:
        if space == "species":
            marks = ",".join("?" * len(id_map))
            clauses.append(f'"{col}" IN ({marks})')
            params.extend(id_map.keys())
        else:
            clauses.append(f'"{col}" = ?')
            params.append(src_genetic)
    sql = f'SELECT * FROM "{table}" WHERE ' + " OR ".join(clauses)

    out = []
    for row in con.execute(sql, params).fetchall():
        row = list(row)
        old_base = None          # which family member this row belonged to
        for col, space in idents:
            i = cols.index(col)
            if space == "species":
                if row[i] in id_map:
                    if old_base is None:
                        old_base = row[i]
                    row[i] = id_map[row[i]]
            elif row[i] == src_genetic:
                row[i] = new_genetic

        # Name columns must stay UNIQUE per family member, so they are derived
        # from the family name map rather than blanket-set to the new name.
        if table == "Species" and old_base is not None and "Name" in cols:
            row[cols.index("Name")] = name_map[old_base]
            # Point at the mod's OWN prefab (which inherits the donor's), so
            # there is somewhere to override the model later. Without the
            # scaffold this stays the donor's prefab, which also works but
            # leaves no hook for custom art.
            if prefab_map and "Prefab" in cols and old_base in prefab_map:
                row[cols.index("Prefab")] = prefab_map[old_base]

        # FilmVariant / film skin cosmetic sets (e.g. Atrociraptor Tiger/Ghost/Panthera/Red,
        # Velociraptor Blue/Delta) are 1-variant film skins tied to base-game textures.
        # Custom modded species should only clone standard cosmetic sets (SetDefault == 'Standard').
        if table == "SpeciesCosmeticSets" and "SetDefault" in cols:
            if row[cols.index("SetDefault")] == "FilmVariant":
                continue

        # Auto-replace donor names in string columns (like UiLabel, Name, etc.)
        #
        # ...EXCEPT columns that name a game ASSET or DATA FILE rather than the
        # species itself. Renaming those points the new species at a file that
        # does not exist, and for several of them the format is not something we
        # can author yet (CosmeticInheritanceFile in particular is an unreversed
        # format). Keeping the DONOR's value means the clone reuses the donor's
        # asset, which exists and works. See PRESERVE_DONOR_TEXT.
        if src_name and new_name:
            for i, val in enumerate(row):
                if not isinstance(val, str) or src_name not in val:
                    continue
                if (table, cols[i]) in PRESERVE_DONOR_TEXT:
                    if preserved is not None:
                        preserved.add(f"{table}.{cols[i]} = {val!r}")
                    continue
                row[i] = val.replace(src_name, new_name)

        out.append(row)
    return cols, out

def apply_overrides(table, cols, rows, overrides, report):
    """--set Table.Column=value, applied to every cloned row of that table."""
    for (t, col), raw in overrides.items():
        if t.lower() != table.lower():
            continue
        if col not in cols:
            report.setdefault("warnings", []).append(
                f"--set {t}.{col}: no such column in {table}, ignored")
            continue
        i = cols.index(col)
        val = coerce(raw)
        for row in rows:
            row[i] = val
        report.setdefault("overrides_applied", []).append(
            f"{table}.{col} = {val!r} ({len(rows)} row(s))")


def coerce(s):
    if s.lower() in ("null", "none"):
        return None
    if s.lower() == "true":
        return 1
    if s.lower() == "false":
        return 0
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


# ---------------------------------------------------------------- output

def create_mod_fdb(src_con, path, wanted):
    """Fresh SQLite holding ONLY the touched tables, schema copied verbatim.

    Mods ship a partial FDB and the game merges the rows in (the Red Deer
    Feeder's dinosaurs FDB is 7 tables with one row each), so there is no need
    to reproduce the whole 200-table database.
    """
    if os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass

    out = sqlite3.connect(path)
    for t in wanted:
        ddl = src_con.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (t,)).fetchone()
        if ddl and ddl[0]:
            sql_stmt = ddl[0].replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
            out.execute(sql_stmt)

    out.commit()
    return out


# ------------------------------------------------------- prefab dump checking

PREFAB_DUMP = os.path.join(BASE, "JWE3_Prefabs.lua")
# Top-level dump entries sit at COLUMN 0 and are lowercased by the dumper:
#     triceratopsjwe = {
# Anything that appears only as an inner `Prefab = 'X'` reference is engine-side
# and cannot be inherited by a Lua prefab - it compiles and spawns but inherits
# nothing, so the entity ends up with no renderer. Two mods have been bitten by
# this (BLDG_BaseGameplay_NoSupply, LiveBaitBase), which is why this check runs.
ENTRY_RE = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*\{")


PREFAB_INDEX = os.path.join(BASE, "JWE 3 Luas", "prefab_index.json")


def load_prefab_index():
    """prefab_index.json if it exists (see prefab_index.py), else None.

    Preferred over re-scanning the dump: ~1000x smaller and instant, and it also
    carries `referenced_only`, the engine-side names that must never be
    inherited. Rebuild with `python prefab_index.py`.
    """
    if not os.path.isfile(PREFAB_INDEX):
        return None
    try:
        with open(PREFAB_INDEX) as f:
            return json.load(f)
    except Exception:
        return None


def donor_cosmetics(idx, donor_prefab):
    """The donor's _NN cosmetic variants: [(suffix, props), ...] sorted.

    These are the colour/pattern morphs - they inherit the sex/age prefab and
    carry MaterialPatternsName / MaterialVariantsName and nothing else.
    """
    if not idx or not donor_prefab:
        return []
    out = []
    dl = donor_prefab.lower()
    for name, v in idx["entries"].items():
        if not v.get("is_variant"):
            continue
        if (v.get("parent") or "").lower() != dl:
            continue
        m = re.search(r"_(\d{2})$", name)
        if m:
            out.append((m.group(1), v.get("props", {})))
    return sorted(out)


def load_prefab_entries(path=PREFAB_DUMP):
    """Set of lowercase top-level prefab names, or None if the dump is absent."""
    if not os.path.isfile(path):
        return None
    names = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not line or line[0] in " \t\r\n":
                continue          # cheap reject: entries are at column 0
            m = ENTRY_RE.match(line)
            if m:
                names.add(m.group(1).lower())
    return names


def check_donor_prefabs(members, report):
    """Warn for any donor prefab that is not a real dump ENTRY."""
    entries = load_prefab_entries()
    if entries is None:
        report["warnings"].append(
            f"prefab dump not found at {PREFAB_DUMP} - donor prefabs unverified")
        return
    for prefab_name, donor in members:
        if not donor:
            continue
        if donor.lower() not in entries:
            report["warnings"].append(
                f"{prefab_name}: donor prefab {donor!r} is NOT a top-level entry "
                f"in JWE3_Prefabs.lua. If it only appears as a `Prefab =` "
                f"reference it is ENGINE-SIDE and inheriting it yields an entity "
                f"with no renderer (invisible). Pick a real entry instead.")
    report["prefab_dump_entries"] = len(entries)


# ---------------------------------------------------------------- scaffolding

PREFAB_LUA = '''local global = _G
local api = global.api
local require = global.require

local {mod} = module(...)

-- Inherits the donor prefab {donor!r}, which is a real registered prefab, so
-- this species renders correctly from the first load. Point ModelName and
-- AssetPackages at your own art when you have it.
--
-- RULE: only ever inherit a prefab that is a real ENTRY in the prefab dump.
-- A parent that appears only as a `Prefab =` reference is engine-side and
-- inherits NOTHING - it still compiles and spawns, just with no renderer.
-- Grep the dump CASE-INSENSITIVELY before changing this.
{mod}.GetRoot = function()
    return {{
        Prefab = {donor!r},
{properties}
    }}
end

{mod}.GetFlattenedRoot = function()
    api.entity.CompilePrefab({mod}.GetRoot(), {name!r})
    return api.entity.FindPrefab({name!r})
end

return {mod}
'''

COSMETIC_LUA = '''local global = _G
local api = global.api
local require = global.require

local {mod} = module(...)

{mod}.GetRoot = function()
    return {{
        Properties = {{
            MaterialPatternsName = {{
                Default = {patterns!r}
            }},
            MaterialVariantsName = {{
                Default = {variants!r}
            }},
            AssetPackages = {{
                Default = {{
                    __inheritance = 'Append'
                }}
            }}
        }},
        Prefab = {parent!r}
    }}
end

{mod}.GetFlattenedRoot = function()
    api.entity.CompilePrefab({mod}.GetRoot(), {name!r})
    return api.entity.FindPrefab({name!r})
end

return {mod}
'''

PREFABDATA_LUA = '''local global = _G
local api = global.api
local ipairs = global.ipairs
local require = global.require

local {mod_name}PrefabData = module(...)

-- ORDER MATTERS. A prefab must be registered BEFORE anything that names it,
-- otherwise the lookup silently finds nothing - no compile error, and the
-- reference is never retried. Base first, variants after.
{mod_name}PrefabData.AddLuaPrefabs = function(_fnAdd)
    local tPrefabFilenames = {{
{prefab_list}
    }}
    for _, sPrefabName in ipairs(tPrefabFilenames) do
        _fnAdd(sPrefabName, require(sPrefabName).GetRoot())
    end
end
'''

LUADATABASE_LUA = '''local global = _G
local api = global.api
local table = global.table
local require = global.require

local {mod_name}Database = module(...)

{mod_name}Database.AddContentToCall = function(_tContentToCall)
    -- Guard: without ACSE none of this can register.
    if not api.acse then
        return
    end

    table.insert(_tContentToCall, require("Database.{mod_name}PrefabData"))
    table.insert(_tContentToCall, require("Database.{mod_name}TechTreeData"))
    table.insert(_tContentToCall, require("Database.{mod_name}RebirthHiddenSpeciesTechTree"))
    table.insert(_tContentToCall, require("Database.{mod_name}InGenDatabaseData")){scale_require}{icon_require}
end
'''


SCALE_REQUIRE = ('\n    table.insert(_tContentToCall, '
                 'require("Database.{mod_name}ScaleData"))')

TECHTREE_LUA = '''-----------------------------------------------------------------------
--/  @file   Database.{mod_name}TechTreeData.lua
--/  @brief  Adds {mod_name} species to the Dinosaur Mods research category and
--/          injects this category into the sandbox tech tree.
--/
--/  @note   DO NOT MANUALLY EDIT the injection section at the bottom.
--/
--/  @see    https://github.com/OpenNaja/ACSE
-----------------------------------------------------------------------

local global = _G
local api = global.api
local pairs = global.pairs
local table = global.table
local require = global.require
local TechTreeDatabase = require("Database.MainTechTreeData")
local {mod_name}TechTreeData = module(...)

-- Define new species research reward.
{mod_name}TechTreeData.tUiRewards = {{
{ui_rewards}
}}

-- Define new species research node.
{mod_name}TechTreeData.tNodes = {{
{nodes}
}}

-----------------------------------------------------------------------
-- Note: DO NOT ALTER THE CONTENT OF THE FILE BELOW THIS LINE. This
-- code is responsible for injecting the Dinosaur modded species
-- research tree into the game.
--

-- Define default mods category
{mod_name}TechTreeData.tUiCategories = {{
    DinosaurMods = {{
        group   = "dinosaurGenomes",
        icon    = "categoryGeneMods",
        sort    = 7
    }}
}}

-- Define what techtrees we need to inject new species research category
-- and nodes.
local techTrees = {{
    sandboxtechtreeset   = require("TechTrees.Sets.SandboxTechTreeSet"),
}}

-- Define the Dinosaur Mods tech tree
local techtree_key  = "TechTrees.Trees.DinosaurModsTechTree"
local DinosaurModsTechTree = require(techtree_key)

-- Game hook to modify tech tree data.
{mod_name}TechTreeData.AddTechTreeData = function(
    _fnAddAvailableSets,
    _fnAddAvailablePatches,
    _fnAddConditionPresets,
    _fnAddResearchPresets,
    _fnAddRewardGroups,
    _fnAddUiCategories,
    _fnAddUiRewards)

    -- Do not add the category if it exists
    if not TechTreeDatabase.UiCategories['DinosaurMods'] then
        _fnAddUiCategories({mod_name}TechTreeData.tUiCategories)
    end
    _fnAddUiRewards({mod_name}TechTreeData.tUiRewards)

    -- Custom local function to check a key inside a table.
    local has_key = function(tTable, val) for _,k in global.ipairs(tTable) do if k == val then return true end end return false end

    -- Add mod category techtree to the selected set.
    for k, v in global.pairs(techTrees) do
        cTechTrees = v.TechTrees
        if not has_key(cTechTrees, techtree_key) then table.insert(cTechTrees, techtree_key) end
        v.TechTrees = cTechTrees
    end

    -- Add our current new species to the Dinosaur Mods tree, regardless of what mod created the category
    for k, v in global.pairs({mod_name}TechTreeData.tNodes) do
        DinosaurModsTechTree.TechTree.nodes[k] = v
    end
end
'''

REBIRTH_TECHTREE_LUA = '''local global = _G
local api = global.api
local {mod_name}RebirthHiddenSpeciesTechTree = module(...)
{mod_name}RebirthHiddenSpeciesTechTree.TechTree = {{
    name = "{mod_name}RebirthHiddenSpeciesTechTree",
    nodes = {{
        Mutadon = {{
            assignments = {{
                {{preset = "AssignmentComplete", AssignmentID = "Getting_Out_Of_Hand"}}
            }},
            BaseGameSpecies = {{
                rewards = {{
{rebirth_rewards}
                }}
            }}
        }}
    }}
}}
'''

INGEN_DATABASE_LUA = '''local global = _G
local pairs = pairs
local ipairs = ipairs
local Vector3 = require("Vector3")
local Main = require("Database.Main")
local GameDatabase = require("Database.GameDatabase")
local {mod_name}InGenDatabaseData = module(...)

{mod_name}InGenDatabaseData.tInGenDatabaseData = {{
    DinosaurFilmData = {{
{ingen_data}
    }}
}}
{mod_name}InGenDatabaseData.AddInGenDatabaseData = function(_fnAddDinosaurFilmData)
    local tData = {mod_name}InGenDatabaseData.tInGenDatabaseData
    for sID, tDinosaurFilmData in pairs(tData.DinosaurFilmData) do
        _fnAddDinosaurFilmData(sID, tDinosaurFilmData)
    end
end

{mod_name}InGenDatabaseData.tDefaultUnlockedEntries = {{
    TechTreeRewardIDs = {{
{ingen_techtree}
    }},
    GenomeIDs = {{
{ingen_genomes}
    }}
}}

{mod_name}InGenDatabaseData.AddDefaultUnlocks = function(
    _fnAddDefaultTechTreeUnlock,
    _fnAddDefaultGenomeUnlock,
    _fnAddDefaultInjuryUnlock)

    local tData = {mod_name}InGenDatabaseData.tDefaultUnlockedEntries

    for _, sTechTreeRewardID in pairs(tData.TechTreeRewardIDs) do
        _fnAddDefaultTechTreeUnlock(sTechTreeRewardID)
    end

    for _, sGenomeID in pairs(tData.GenomeIDs) do
        _fnAddDefaultGenomeUnlock(sGenomeID)
    end
end
'''

# This file is shared across all species mods - DO NOT ALTER.
DINOSAUR_MODS_TECHTREE_LUA = '''-----------------------------------------------------------------------
--/  @file   TechTrees.Trees.DinosaurModsTechTree.lua
--/  @author Inaki
--/
--/  @brief  Creates a prototype for adding a modded species research
--/          category for JWE3.
--/
--/  @note   DO NOT ALTER THIS FILE. Other modded species might include
--/          a copy of this file and your changes might interfere with
--/          those mods.
--/
--/  @see    https://github.com/OpenNaja/ACSE
-----------------------------------------------------------------------

--
-- Modded Dinosaurs research category
--
local DinosaurModsTechTree = module(...)
DinosaurModsTechTree.TechTree = {
    name = "DinosaurMods",
    uiCategory = "DinosaurMods",
    nodes = {}
}
'''

INIT_DATABASE_LUA = '''-----------------------------------------------------------------------
--/  @file    Databases.{mod_name}.lua
--/  @brief   FDB merge configuration for {mod_name}. Tells ACSE to load
--/           and merge the mod's dinosaurs and expeditions databases.
--/
--/  @see    https://github.com/OpenNaja/ACSE
-----------------------------------------------------------------------
local global = _G

local {mod_name}DatabaseConfig = module(...)

{mod_name}DatabaseConfig.tConfig = {{

    tLoad = {{
        {mod_name}Dinosaurs = {{
            sSymbol = "{mod_name}Dinosaurs"
        }},
        {mod_name}Expeditions = {{
            sSymbol = "{mod_name}Expeditions"
        }},
    }},

    tCreateAndMerge = {{
        Dinosaurs = {{
            tChildrenToMerge = {{"{mod_name}Dinosaurs"}}
        }},
        Expeditions = {{
            tChildrenToMerge = {{"{mod_name}Expeditions"}}
        }}
    }}

}}

{mod_name}DatabaseConfig.GetDatabaseConfig = function()
    if global.api.acse and global.api.acse.versionNumber > 0.641 then
        return {mod_name}DatabaseConfig.tConfig
    else
        return {{}}
    end
end
'''

MANIFEST_XML = '''<?xml version="1.0" encoding="utf-8"?>
<ContentPack version="1">
  <Name>{name}</Name>
  <ID>{uuid}</ID>
  <Version>1</Version>
  <Type>Game</Type>
</ContentPack>
'''

BUILD_PY = '''"""Build and install the {name} species mod.

Same shape as build_and_install_deerfeeder.py. KEEP BOTH SAFETY RAILS:
  - the luacheck gate, because ovl_tool SILENTLY DROPS any .lua that fails a
    syntax check and still prints SUCCESS;
  - the post-pack contents listing, which is how such a drop gets noticed.
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from lua_syntax_gate import check_lua_dirs

MOD = os.path.join(BASE, "SpeciesGenerator", "Generated", "{name}")
OVL_TOOL = os.path.join(BASE, "cobra-tools-master", "ovl_tool_cmd.py")
TARGET = r"{target}"
GAME = "Jurassic World Evolution 3"



def pack(src, dst, label):
    print(f"packing {{label}}: {{src}} -> {{dst}}")
    if not os.path.isdir(src):
        print("  SKIP - no such directory")
        return True
    r = subprocess.run(["python", OVL_TOOL, "new", "-g", GAME,
                        "-i", src, "-o", dst, "-f"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("  ERROR:", r.stderr[-2000:])
        return False
    return True


def contents(ovl_path):
    import logging, contextlib, io
    sys.path.insert(0, os.path.join(BASE, "cobra-tools-master"))
    logging.success = logging.info
    logging.getLogger().setLevel(logging.ERROR)
    from generated.formats.ovl import OvlFile
    o = OvlFile()
    o.game = GAME
    with contextlib.redirect_stdout(io.StringIO()):
        o.load(ovl_path)
    return sorted(o.loaders)


def main():
    os.makedirs(TARGET, exist_ok=True)

    print("checking lua syntax")
    if not check_lua_dirs([os.path.join(MOD, "Main"), os.path.join(MOD, "Init")]):
        print("\\nFAILED - nothing installed")
        return 1

    ok = pack(os.path.join(MOD, "Main"), os.path.join(TARGET, "Main.ovl"), "Main.ovl")
    ok &= pack(os.path.join(MOD, "Init"), os.path.join(TARGET, "Init.ovl"), "Init.ovl")
    if not ok:
        print("\\nFAILED - nothing installed")
        return 1

    man = os.path.join(MOD, "Manifest.xml")
    if os.path.isfile(man):
        import shutil
        shutil.copy(man, os.path.join(TARGET, "Manifest.xml"))

    print("\\nMain.ovl now contains:")
    try:
        got = contents(os.path.join(TARGET, "Main.ovl"))
        for n in got:
            print("   ", n)
        expected = {{n for n in os.listdir(os.path.join(MOD, "Main"))
                    if n.endswith((".lua", ".fdb"))}}
        missing = sorted(expected - set(got))
        if missing:
            print("\\n  WARNING - expected but NOT packed:", ", ".join(missing))
    except Exception as e:
        print("    (could not verify:", e, ")")

    print("\\nInit.ovl now contains:")
    try:
        got = contents(os.path.join(TARGET, "Init.ovl"))
        for n in got:
            print("   ", n)
    except Exception as e:
        print("    (could not verify:", e, ")")

    print("\\nSUCCESS - restart the game to pick it up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''


# ================================================ PUBLIC LIBRARY API
# These functions are the stable interface for both the CLI and the GUI.
# They separate scanning, planning, and generating into distinct phases
# so the GUI can show intermediate results (family preview, table list,
# warnings) without writing any files.

def scan_donor(fdb_path, source_name):
    """Scan the FDB for a species and return its family + available tables.

    Returns dict:
        source: {name, SpeciesID, GeneticSpeciesID}
        family: [{SpeciesID, Name, Prefab}, ...]
        tables: {table_name: {row_count, ident_columns: [...]}}
        species_list: [{Name, SpeciesID, GeneticSpeciesID}, ...]  (all species)
    Or raises ValueError on error.
    """
    if not os.path.isfile(fdb_path):
        raise ValueError(f"source fdb not found: {fdb_path}")

    con = sqlite3.connect(f"file:{fdb_path}?mode=ro", uri=True)
    try:
        src = lookup_species(con, source_name)
        if not src:
            raise ValueError(f"no species named {source_name!r} in Species")
        src_species, src_genetic, src_name_actual = src

        fam = species_family(con, src_genetic)
        donor_prefabs = {r[0]: r[1] for r in con.execute(
            "SELECT SpeciesID, Prefab FROM Species WHERE GeneticSpeciesID = ?",
            (src_genetic,))}

        family_list = []
        for sid, sname in fam:
            family_list.append({
                "SpeciesID": sid,
                "Name": sname,
                "Prefab": donor_prefabs.get(sid, "")
            })

        # Scan all species-referencing tables
        stables = species_tables(con)
        table_info = {}
        for t, idents in sorted(stables.items()):
            # Count rows for this donor
            clauses, params = [], []
            for col, space in idents:
                if space == "species":
                    marks = ",".join("?" * len(fam))
                    clauses.append(f'"{col}" IN ({marks})')
                    params.extend(sid for sid, _ in fam)
                else:
                    clauses.append(f'"{col}" = ?')
                    params.append(src_genetic)
            sql = f'SELECT COUNT(*) FROM "{t}" WHERE ' + " OR ".join(clauses)
            count = con.execute(sql, params).fetchone()[0]
            if count > 0:
                table_info[t] = {
                    "row_count": count,
                    "ident_columns": [(c, s) for c, s in idents]
                }

        # Full species list for the UI picker
        all_species = []
        for row in con.execute(
                "SELECT Name, SpeciesID, GeneticSpeciesID FROM Species ORDER BY Name"):
            all_species.append({
                "Name": row[0], "SpeciesID": row[1],
                "GeneticSpeciesID": row[2]
            })

        return {
            "source": {"name": src_name_actual, "SpeciesID": src_species,
                        "GeneticSpeciesID": src_genetic},
            "family": family_list,
            "tables": table_info,
            "species_list": all_species,
        }
    finally:
        con.close()


def plan_species(config):
    """Plan a species clone without writing anything.

    config keys:
        source:     donor species name (required)
        name:       new species name (required)
        fdb:        path to c0dinosaurs.fdb (default: standard location)
        exp_fdb:    path to c0expeditions.fdb (default: standard location)
        species_id: explicit SpeciesID or None
        genetic_id: explicit GeneticSpeciesID or None
        id_floor:   lowest auto id (default 900)
        prefab:     override Species.Prefab or None
        overrides:  {(table, col): value_str, ...}
        only:       set of table names or None
        skip:       set of table names or None
        no_scaffold:     bool
        no_prefab_check: bool
        no_cosmetics:    bool
        cosmetics:       int (number of cosmetic variants per member)
        icon:       species icon name for tech tree (default: donor name)
        out:        output directory or None

    Returns (plan, report) where plan is the data needed by generate_species().
    """
    fdb_path = config.get("fdb", DEFAULT_SOURCE_FDB)
    exp_fdb_path = config.get("exp_fdb", DEFAULT_SOURCE_EXP_FDB)
    source_name = config["source"]
    new_name = config["name"]

    if not os.path.isfile(fdb_path):
        raise ValueError(f"source fdb not found: {fdb_path}")

    con = sqlite3.connect(f"file:{fdb_path}?mode=ro", uri=True)
    try:
        src = lookup_species(con, source_name)
        if not src:
            raise ValueError(f"no species named {source_name!r} in Species")
        src_species, src_genetic, src_name = src

        if lookup_species(con, new_name):
            raise ValueError(f"a species named {new_name!r} already exists")

        id_floor = config.get("id_floor", DEFAULT_ID_FLOOR)
        new_species = config.get("species_id") or pick_free_id(
            con, "Species", "SpeciesID", id_floor, RESERVED_SPECIES_IDS)
        new_genetic = config.get("genetic_id") or pick_free_id(
            con, "GeneticSpecies", "GeneticSpeciesID", id_floor)

        if new_species in RESERVED_SPECIES_IDS:
            raise ValueError(
                f"SpeciesID {new_species} is reserved "
                f"({sorted(RESERVED_SPECIES_IDS)})")

        overrides = dict(config.get("overrides", {}))
        if config.get("prefab"):
            overrides[("Species", "Prefab")] = config["prefab"]
        overrides[("GeneticSpecies", "Name")] = new_name

        tables = species_tables(con)
        only = config.get("only")
        skip = config.get("skip")
        if only:
            allow = {s.strip().lower() for s in only} if isinstance(only, set) else \
                    {s.strip().lower() for s in only.split(",")}
            tables = {t: v for t, v in tables.items() if t.lower() in allow}
        if skip:
            deny = {s.strip().lower() for s in skip} if isinstance(skip, set) else \
                   {s.strip().lower() for s in skip.split(",")}
            tables = {t: v for t, v in tables.items() if t.lower() not in deny}

        explicit_base = config.get("species_id")
        id_map, name_map = build_family_maps(
            con, src_name, new_name, src_genetic, new_species,
            explicit_base=explicit_base)

        report = {
            "source": {"name": src_name, "SpeciesID": src_species,
                        "GeneticSpeciesID": src_genetic},
            "new": {"name": new_name, "SpeciesID": id_map[src_species],
                    "GeneticSpeciesID": new_genetic},
            "family": {str(o): {"SpeciesID": n, "Name": name_map[o]}
                       for o, n in id_map.items()},
            "tables": {}, "warnings": [], "overrides_applied": [],
        }

        donor_prefabs = {r[0]: r[1] for r in con.execute(
            "SELECT SpeciesID, Prefab FROM Species WHERE GeneticSpeciesID = ?",
            (src_genetic,))}

        no_scaffold = config.get("no_scaffold", False)
        prefab_map = None if no_scaffold else {
            old: name_map[old] for old in id_map}

        cloned = {}
        preserved = set()   # donor asset references deliberately left alone
        for t in sorted(tables):
            cols, rows = clone_rows(con, t, tables[t], id_map, name_map,
                                    src_genetic, new_genetic, prefab_map,
                                    src_name=src_name, new_name=new_name,
                                    preserved=preserved)
            if not rows:
                continue
            apply_overrides(t, cols, rows, overrides, report)

            ident_names = {c for c, _ in tables[t]}
            pk_cols = [name for name, decl, is_pk in columns(con, t) if is_pk]
            for name, decl, is_pk in columns(con, t):
                if is_pk and "INT" in decl and name not in ident_names:
                    # If it's part of a composite primary key, we assume the other 
                    # identity column changing guarantees uniqueness.
                    if len(pk_cols) > 1:
                        continue
                    report["warnings"].append(
                        f"{t}.{name} is a non-identity INTEGER PRIMARY KEY "
                        f"copied verbatim - may collide on merge; set it with "
                        f"--set {t}.{name}=<free value>")

            cloned[t] = (cols, rows)
            report["tables"][t] = len(rows)

        # Say so out loud rather than silently: these still point at the DONOR's
        # assets, which is intentional (the files exist and the formats are not
        # all authorable), but it means the clone shares them.
        if preserved:
            report["preserved_donor_assets"] = sorted(preserved)

        # Expeditions FDB cloning
        exp_plan = None
        if os.path.isfile(exp_fdb_path) and not no_scaffold:
            exp_plan = _plan_expeditions(
                exp_fdb_path, src_name, new_name, id_map, name_map, report)

        members = [(name_map[old], donor_prefabs.get(old))
                    for old in sorted(id_map)]

        # Cosmetic planning
        #
        # PREFERRED PATH: derive one stub per REAL SpeciesCosmeticSets row.
        # A species can have many sets - Velociraptor's female alone has 10
        # (Blue, Charlie, Delta, Echo, JWR, 93...) - with arbitrary Prefab names
        # like 'VelociraptorBlue' that follow no _NN convention. Naming the new
        # prefabs after the SetID makes them unique by construction, because
        # SetID is part of the table's primary key.
        #
        # This replaced a count-based scheme that emitted `<member>_01..._NN`
        # and collapsed every set onto `<member>_01` when the donor's Prefab had
        # no trailing _NN - which tripped `UNIQUE constraint failed:
        # SpeciesCosmeticSets.Prefab` on 103 of the game's species.
        cosmetic_count = 0 if config.get("no_cosmetics") else \
                         config.get("cosmetics", 1)
        cosmetic_plan = []
        set_prefab_names = {}     # (new SpeciesID, SetID) -> new prefab name
        member_by_new_id = {id_map[old]: name_map[old] for old in id_map}

        sets_rows = cloned.get("SpeciesCosmeticSets")
        if sets_rows and not no_scaffold and not config.get("no_cosmetics"):
            idx = load_prefab_index()
            s_cols, s_rows = sets_rows
            si, seti = s_cols.index("SpeciesID"), s_cols.index("SetID")
            pi = s_cols.index("Prefab") if "Prefab" in s_cols else None
            donor_prefab_by_member = {name_map[old]: donor_prefabs.get(old)
                                      for old in id_map}
            for row in s_rows:
                member = member_by_new_id.get(row[si])
                if not member:
                    continue
                set_id = row[seti] or 1
                cosm_name = f"{member}_{int(set_id):02d}"
                set_prefab_names[(row[si], set_id)] = cosm_name

                # Seed pattern/variant names from the donor's own cosmetic
                # prefab when the index can find it, so the shape is right.
                patterns = f"{new_name}_PatternSet_{int(set_id):02d}"
                variants = f"{new_name}_VariantSet_{int(set_id):02d}"
                donor_cosm = donor_cosmetics(
                    idx, donor_prefab_by_member.get(member)) if idx else []
                if donor_cosm:
                    _, d_props = donor_cosm[min(int(set_id), len(donor_cosm)) - 1]
                    patterns = d_props.get("MaterialPatternsName", patterns)
                    variants = d_props.get("MaterialVariantsName", variants)

                cosmetic_plan.append({
                    "name": cosm_name,
                    "parent": member,
                    "patterns": patterns,
                    "variants": variants,
                })

        # FALLBACK: donor has no cosmetic sets at all - emit the requested
        # number of blank stubs so there is still something to customise.
        elif cosmetic_count > 0 and not no_scaffold:
            idx = load_prefab_index()
            for prefab_name, donor in members:
                donor_cosm = donor_cosmetics(idx, donor) if idx else []
                for nn in range(1, cosmetic_count + 1):
                    suffix = f"_{nn:02d}"
                    cosm_name = f"{prefab_name}{suffix}"
                    # Pre-populate from donor cosmetics if available
                    if nn <= len(donor_cosm):
                        d_suffix, d_props = donor_cosm[nn - 1]
                        patterns = d_props.get("MaterialPatternsName",
                                               f"{new_name}_PatternSet{suffix}")
                        variants = d_props.get("MaterialVariantsName",
                                               f"{new_name}_VariantSet{suffix}")
                    else:
                        patterns = f"{new_name}_PatternSet{suffix}"
                        variants = f"{new_name}_VariantSet{suffix}"
                    cosmetic_plan.append({
                        "name": cosm_name,
                        "parent": prefab_name,
                        "patterns": patterns,
                        "variants": variants,
                    })

        # Expand a single --scale into the per-member map the scale module
        # wants. Done HERE because it needs id_map/name_map, which only exist
        # once the family is resolved. The UI can instead set config["scaling"]
        # directly for per-species values.
        # "scale" is what the GUI sends per species; "scale_all" is the CLI flag.
        _scale_in = config.get("scale") or config.get("scale_all")
        if _scale_in and not config.get("scaling"):
            _sc = float(_scale_in)
            _map = {}
            for _old in id_map:
                _map[id_map[_old]] = _sc      # by SpeciesID
                _map[name_map[_old]] = _sc    # by genome/name fallback
            config["scaling"] = _map

        # Keep SpeciesCosmeticSets.Prefab in step with the stubs we actually
        # write, or the DB points at a prefab that does not exist.
        #
        # Vanilla names a cosmetic after the PREFAB ("Acrocanthosaurus_Female_01",
        # because Species.Prefab is "Acrocanthosaurus_Female") while the base
        # Species row is just "Acrocanthosaurus". Our stubs are named after the
        # mod's own prefabs, so the blanket text rename produced
        # "Preservosaurus_Female_01" while the file written was
        # "preservosaurus_01.lua" - a dangling reference, and a silent one.
        # The mod owns its prefabs, so the DB is repointed at them.
        # Names come from set_prefab_names, keyed (SpeciesID, SetID), which is
        # the table's own primary key - so they cannot collide. Deriving the
        # name from the donor's Prefab string instead is what caused
        # "UNIQUE constraint failed: SpeciesCosmeticSets.Prefab".
        if set_prefab_names and "SpeciesCosmeticSets" in cloned:
            cols, rows = cloned["SpeciesCosmeticSets"]
            if "Prefab" in cols and "SpeciesID" in cols and "SetID" in cols:
                pi = cols.index("Prefab")
                si, seti = cols.index("SpeciesID"), cols.index("SetID")
                for row in rows:
                    fixed = set_prefab_names.get((row[si], row[seti] or 1))
                    if fixed and row[pi] != fixed:
                        report.setdefault("cosmetic_prefab_repointed", []).append(
                            f"SpeciesCosmeticSets.Prefab {row[pi]!r} -> {fixed!r}")
                        row[pi] = fixed

                # Belt and braces: the column is UNIQUE, so prove it before the
                # INSERT rather than letting SQLite report it with no context.
                seen = {}
                for row in rows:
                    seen.setdefault(row[pi], []).append((row[si], row[seti]))
                clashes = {k: v for k, v in seen.items() if len(v) > 1}
                if clashes:
                    report.setdefault("warnings", []).append(
                        "SpeciesCosmeticSets.Prefab would collide (UNIQUE): "
                        + "; ".join(f"{k!r} used by {v}" for k, v in clashes.items()))

        plan = {
            "fdb_path": fdb_path,
            "exp_fdb_path": exp_fdb_path,
            "cloned": cloned,
            "tables_schema": tables,
            "id_map": id_map,
            "name_map": name_map,
            "src_genetic": src_genetic,
            "new_genetic": new_genetic,
            "donor_prefabs": donor_prefabs,
            "members": members,
            "prefab_map": prefab_map,
            "exp_plan": exp_plan,
            "cosmetic_plan": cosmetic_plan,
            "config": config,
        }

        return plan, report
    finally:
        con.close()


def _plan_expeditions(exp_fdb_path, src_name, new_name, id_map, name_map,
                      report):
    """Plan the expeditions FDB cloning.

    Genomes: one row per family member, keyed by GenomeID (string = species name)
             and SpeciesID (integer). Both must be rewritten.
    Fossils: one row per species, FossilID = "DNA_<Name>", GenomeID = "<Name>"
    DigSiteFossils: links fossils to dig sites by FossilID
    """
    con = sqlite3.connect(f"file:{exp_fdb_path}?mode=ro", uri=True)
    try:
        exp_tables = {}

        # Genomes: clone rows matching any family member's SpeciesID
        genome_cols = [r[1] for r in con.execute('PRAGMA table_info("Genomes")')]
        sid_idx = genome_cols.index("SpeciesID")
        gid_idx = genome_cols.index("GenomeID")

        family_sids = list(id_map.keys())
        marks = ",".join("?" * len(family_sids))
        genome_rows = []
        for row in con.execute(
                f'SELECT * FROM "Genomes" WHERE SpeciesID IN ({marks})',
                family_sids).fetchall():
            row = list(row)
            old_sid = row[sid_idx]
            if old_sid in id_map:
                row[sid_idx] = id_map[old_sid]
                row[gid_idx] = name_map[old_sid]
            genome_rows.append(row)

        if genome_rows:
            exp_tables["Genomes"] = (genome_cols, genome_rows)

        # Fossils: clone rows where GenomeID matches a family member name
        fossil_cols = [r[1] for r in con.execute('PRAGMA table_info("Fossils")')]
        fid_idx = fossil_cols.index("FossilID")
        fgid_idx = fossil_cols.index("GenomeID")
        old_names = {name for _, name in
                     con.execute(f'SELECT SpeciesID, Name FROM '
                                 f'(SELECT {",".join("?" * len(family_sids))})',
                                 family_sids).fetchall()} if False else set()
        # Get old family member names
        old_names = set()
        for old_sid in id_map:
            # Reverse lookup - find original name for this SpeciesID
            for row in con.execute(
                    'SELECT GenomeID FROM Genomes WHERE SpeciesID = ?',
                    (old_sid,)):
                old_names.add(row[0])

        for table_name in ["Fossils", "FossilsRebirth"]:
            if table_name not in [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]:
                continue
            fcols = [r[1] for r in con.execute(
                f'PRAGMA table_info("{table_name}")')]
            fi = fcols.index("FossilID")
            fg = fcols.index("GenomeID")
            fossil_rows = []
            for oname in old_names:
                for row in con.execute(
                        f'SELECT * FROM "{table_name}" WHERE GenomeID = ?',
                        (oname,)).fetchall():
                    row = list(row)
                    row[fi] = f"DNA_{new_name}"
                    row[fg] = new_name
                    fossil_rows.append(row)
            if fossil_rows:
                exp_tables[table_name] = (fcols, fossil_rows)

        # DigSiteFossils: clone rows referencing donor fossils
        for table_name in ["DigSiteFossils", "DigSiteFossilsChallenge",
                           "DigSiteFossilsRebirth"]:
            if table_name not in [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")]:
                continue
            dcols = [r[1] for r in con.execute(
                f'PRAGMA table_info("{table_name}")')]
            di = dcols.index("FossilID")
            ds_rows = []
            for oname in old_names:
                old_fossil_id = f"DNA_{oname}"
                for row in con.execute(
                        f'SELECT * FROM "{table_name}" WHERE FossilID = ?',
                        (old_fossil_id,)).fetchall():
                    row = list(row)
                    row[di] = f"DNA_{new_name}"
                    ds_rows.append(row)
            if ds_rows:
                exp_tables[table_name] = (dcols, ds_rows)

        # DigSites: clone the donor's dig site with a new SiteID
        # (create a simple new dig site pointing at the same location)
        ds_cols = [r[1] for r in con.execute('PRAGMA table_info("DigSites")')]
        dsid_idx = ds_cols.index("SiteID")
        # Find dig sites that have the donor's fossils
        donor_sites = set()
        for oname in old_names:
            old_fossil_id = f"DNA_{oname}"
            for row in con.execute(
                    'SELECT DISTINCT SiteID FROM DigSiteFossils WHERE FossilID = ?',
                    (old_fossil_id,)):
                donor_sites.add(row[0])

        if donor_sites:
            # Clone the first dig site for the new species
            first_site = sorted(donor_sites)[0]
            site_row = con.execute(
                'SELECT * FROM DigSites WHERE SiteID = ?',
                (first_site,)).fetchone()
            if site_row:
                site_row = list(site_row)
                new_site_id = f"{new_name}Formation"
                site_row[dsid_idx] = new_site_id
                # Update LocationID to a unique value
                if "LocationID" in ds_cols:
                    lid_idx = ds_cols.index("LocationID")
                    # Use a high number to avoid collisions
                    site_row[lid_idx] = id_map[list(id_map.keys())[0]] * 100 + 11
                if "TaskID" in ds_cols:
                    tid_idx = ds_cols.index("TaskID")
                    new_task_id = id_map[list(id_map.keys())[0]] * 100 + 11
                    old_task_id = site_row[tid_idx]
                    site_row[tid_idx] = new_task_id
                    
                    # Clone the task
                    if old_task_id is not None:
                        tcols = [r[1] for r in con.execute('PRAGMA table_info("Tasks")')]
                        t_id_idx = tcols.index("ID")
                        task_row = con.execute('SELECT * FROM Tasks WHERE ID = ?', (old_task_id,)).fetchone()
                        if task_row:
                            task_row = list(task_row)
                            task_row[t_id_idx] = new_task_id
                            exp_tables["Tasks"] = (tcols, [task_row])

                exp_tables["DigSites"] = (ds_cols, [site_row])

                # Update DigSiteFossils to use the new site ID
                for tname in ["DigSiteFossils", "DigSiteFossilsChallenge"]:
                    if tname in exp_tables:
                        dcols, drows = exp_tables[tname]
                        si = dcols.index("SiteID")
                        for row in drows:
                            row[si] = new_site_id

        report["exp_tables"] = {t: len(r) for t, (_, r) in exp_tables.items()}
        return exp_tables
    finally:
        con.close()


def serialize_lua_properties(props, indent=8):
    if not props:
        return ""
    lines = []
    ind = " " * indent
    lines.append(f"Properties = {{")
    for k, v in props.items():
        if isinstance(v, dict):
            lines.append(f"{ind}    {k} = {{")
            for sub_k, sub_v in v.items():
                if isinstance(sub_v, list):
                    items = ", ".join(f"'{x}'" for x in sub_v)
                    if k == "AssetPackages":
                        if items:
                            lines.append(f"{ind}        {sub_k} = {{ __inheritance = 'Append', {items} }},")
                        else:
                            lines.append(f"{ind}        {sub_k} = {{ __inheritance = 'Append' }},")
                    else:
                        lines.append(f"{ind}        {sub_k} = {{ {items} }},")
                elif isinstance(sub_v, str):
                    lines.append(f"{ind}        {sub_k} = '{sub_v}',")
                elif isinstance(sub_v, bool):
                    lines.append(f"{ind}        {sub_k} = {'true' if sub_v else 'false'},")
                else:
                    lines.append(f"{ind}        {sub_k} = {sub_v},")
            lines.append(f"{ind}    }},")
    lines.append(f"{ind}}},")
    return "\n".join(lines)


def generate_species(mod_name, plans, report, config):
    """Write the FDB(s), scaffold Luas, and build script to disk for multiple species.

    Returns dict with paths to generated files.
    """
    out_dir = config.get("out") or os.path.join(DEFAULT_OUT_ROOT, mod_name)
    main_dir = os.path.join(out_dir, "Main")
    init_dir = os.path.join(out_dir, "Init")
    os.makedirs(main_dir, exist_ok=True)
    os.makedirs(init_dir, exist_ok=True)

    paths = {}
    report["output_fdb"] = ""
    report["output_exp_fdb"] = ""

    if not plans:
        return paths

    # Accumulate all FDB clones
    fdb_path = os.path.join(main_dir, f"{mod_name.lower()}dinosaurs.fdb")
    exp_fdb_path = os.path.join(main_dir, f"{mod_name.lower()}expeditions.fdb")
    
    # Write dinosaurs FDB
    first_plan = plans[0]
    src_con = sqlite3.connect(f"file:{first_plan['fdb_path']}?mode=ro", uri=True)
    try:
        wanted_tables = set()
        for p in plans:
            wanted_tables.update(p["cloned"].keys())
        out_con = create_mod_fdb(src_con, fdb_path, sorted(wanted_tables))
        for p in plans:
            for t, (cols, rows) in p["cloned"].items():
                if not rows: continue
                ph = ",".join("?" * len(cols))
                collist = ",".join(f'"{c}"' for c in cols)
                out_con.executemany(f'INSERT OR REPLACE INTO "{t}" ({collist}) VALUES ({ph})', rows)
        out_con.commit()
        out_con.close()
    finally:
        src_con.close()
    
    report["output_fdb"] = fdb_path
    paths["dinosaurs_fdb"] = fdb_path
    
    # Write expeditions FDB
    has_exp = any(p.get("exp_plan") for p in plans)
    if has_exp:
        exp_src_con = sqlite3.connect(f"file:{first_plan['exp_fdb_path']}?mode=ro", uri=True)
        try:
            wanted_exp_tables = set()
            for p in plans:
                if p.get("exp_plan"):
                    wanted_exp_tables.update(p["exp_plan"].keys())
            exp_out = create_mod_fdb(exp_src_con, exp_fdb_path, sorted(wanted_exp_tables))
            for p in plans:
                if not p.get("exp_plan"): continue
                for t, (cols, rows) in p["exp_plan"].items():
                    if not rows: continue
                    ph = ",".join("?" * len(cols))
                    collist = ",".join(f'"{c}"' for c in cols)
                    exp_out.executemany(f'INSERT OR REPLACE INTO "{t}" ({collist}) VALUES ({ph})', rows)
            exp_out.commit()
            exp_out.close()
        finally:
            exp_src_con.close()
        report["output_exp_fdb"] = exp_fdb_path
        paths["expeditions_fdb"] = exp_fdb_path

    no_scaffold = config.get("no_scaffold", False)
    build_path = None
    if not no_scaffold:
        if not config.get("no_prefab_check"):
            for p in plans:
                check_donor_prefabs(p["members"], report)

        written, build_path = write_scaffold(out_dir, mod_name, plans, config, report)
        report["scaffold"] = written
        paths["scaffold"] = written
        paths["build_script"] = build_path

    report_path = os.path.join(out_dir, "species_gen_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    paths["report"] = report_path

    return paths


# --------------------------------------------------- post-build FDB editing
#
# Editing a mod AFTER it has been generated. Deliberately NOT routed through the
# clone pipeline: the rows already exist with their final SpeciesIDs, so they can
# be read and written directly, which avoids inventing a key scheme to address a
# row that does not exist yet.
#
# Used by the Cosmetics and Expeditions pages.

COSMETIC_TABLES = ("SpeciesCosmeticSets", "SpeciesCosmeticVariants",
                   "SpeciesCosmeticPatterns")


def list_generated_mods(root=None):
    """Generated mods that have a dinosaurs FDB, newest first."""
    root = root or os.path.join(BASE, "Generated")
    out = []
    if not os.path.isdir(root):
        return out
    for name in os.listdir(root):
        main = os.path.join(root, name, "Main")
        if not os.path.isdir(main):
            continue
        fdbs = [f for f in os.listdir(main) if f.endswith("dinosaurs.fdb")]
        exps = [f for f in os.listdir(main) if f.endswith("expeditions.fdb")]
        if fdbs:
            out.append({
                "name": name,
                "fdb": os.path.join(main, fdbs[0]),
                "exp_fdb": os.path.join(main, exps[0]) if exps else None,
                "mtime": os.path.getmtime(os.path.join(main, fdbs[0])),
            })
    return sorted(out, key=lambda m: -m["mtime"])


def ensure_table(fdb_path, table, source_fdb=None):
    """Create `table` in a mod FDB by copying the schema from the game DB.

    A mod FDB only contains tables the donor had ROWS in, so a donor with no
    cosmetic variants produces a mod with no SpeciesCosmeticVariants table at
    all - and then there is nowhere to add one. 201 species do have variants
    (2,779 rows), so this is a normal state to be in, not an error.
    Returns True if the table exists (or was created).
    """
    con = sqlite3.connect(fdb_path)
    exists = bool(list(con.execute(f'PRAGMA table_info("{table}")')))
    if exists:
        con.close()
        return True
    src = sqlite3.connect(source_fdb or DEFAULT_SOURCE_FDB)
    ddl = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    src.close()
    if not ddl or not ddl[0]:
        con.close()
        return False
    with con:
        con.execute(ddl[0])
    con.close()
    return True


def read_table(fdb_path, table):
    """-> {columns: [...], pk: [...], rows: [[...], ...]} or None."""
    if not os.path.isfile(fdb_path):
        return None
    con = sqlite3.connect(fdb_path)
    try:
        info = list(con.execute(f'PRAGMA table_info("{table}")'))
    except sqlite3.Error:
        return None
    if not info:
        return None
    cols = [r[1] for r in info]
    pk = [r[1] for r in info if r[5]]
    rows = [list(r) for r in con.execute(f'SELECT * FROM "{table}"')]
    con.close()
    return {"columns": cols, "pk": pk, "rows": rows}


def write_table_rows(fdb_path, table, columns, rows, report=None):
    """Replace a table's contents.

    Whole-table replace inside one transaction rather than per-row UPDATEs:
    the editable tables are small, and it means a UNIQUE clash rolls the whole
    edit back instead of leaving the mod half-written.
    """
    con = sqlite3.connect(fdb_path)
    try:
        with con:
            con.execute(f'DELETE FROM "{table}"')
            ph = ",".join("?" * len(columns))
            collist = ",".join(f'"{c}"' for c in columns)
            con.executemany(
                f'INSERT INTO "{table}" ({collist}) VALUES ({ph})', rows)
    except sqlite3.IntegrityError as e:
        con.close()
        raise ValueError(f"{table}: {e}. Nothing was written - the whole edit "
                         f"was rolled back.")
    con.close()
    if report is not None:
        report.setdefault("edited_tables", []).append(
            f"{table}: {len(rows)} row(s)")
    return len(rows)


def validate_cosmetics(fdb_path):
    """Consistency checks for the three cosmetic tables.

    NumVariants / NumPatterns on a SET must match the number of child rows, and
    Prefab is UNIQUE table-wide. Both are silent breakages in game, so they are
    surfaced as explicit messages rather than left to SQLite.
    """
    problems = []
    sets_ = read_table(fdb_path, "SpeciesCosmeticSets")
    if not sets_:
        return problems
    sc, srows = sets_["columns"], sets_["rows"]
    si, ti = sc.index("SpeciesID"), sc.index("SetID")

    seen = {}
    if "Prefab" in sc:
        pi = sc.index("Prefab")
        for r in srows:
            seen.setdefault(r[pi], []).append((r[si], r[ti]))
        for k, v in seen.items():
            if k is not None and len(v) > 1:
                problems.append(f"Prefab {k!r} is UNIQUE but used by {v}")

    for child, count_col, idx_col in (
            ("SpeciesCosmeticVariants", "NumVariants", "VariantIndex"),
            ("SpeciesCosmeticPatterns", "NumPatterns", "PatternIndex")):
        t = read_table(fdb_path, child)
        if not t or count_col not in sc:
            continue
        cc, crows = t["columns"], t["rows"]
        csi, cti = cc.index("SpeciesID"), cc.index("SetID")
        counts = {}
        for r in crows:
            counts[(r[csi], r[cti])] = counts.get((r[csi], r[cti]), 0) + 1
        ni = sc.index(count_col)
        for r in srows:
            declared, actual = r[ni], counts.get((r[si], r[ti]), 0)
            if declared is not None and actual and int(declared) != actual:
                problems.append(
                    f"Species {r[si]} set {r[ti]}: {count_col}={declared} but "
                    f"{actual} {child} row(s) exist")
    return problems


DIGSITE_MIRRORS = ("DigSites", "DigSitesRebirth")
DIGSITE_FOSSIL_MIRRORS = ("DigSiteFossils", "DigSiteFossilsChallenge",
                          "DigSiteFossilsRebirth")


def validate_digsite(row):
    """The CHECK constraints DigSites enforces, reported readably.

    SQLite raises these with no context, and two of them are non-obvious:
    the yield columns must be NULL for capture sites and non-NULL otherwise,
    and MarineLocation is only valid on a capture site.
    """
    problems = []
    if not row.get("SiteID"):
        problems.append("SiteID is required and must be unique")
    if row.get("LocationID") in (None, ""):
        problems.append("LocationID is required, unique, and >= 0")
    capture = bool(row.get("CaptureSite"))
    if capture:
        if row.get("NormalFossilYield") or row.get("JunkFossilYield"):
            problems.append(
                "capture sites must leave NormalFossilYield/JunkFossilYield empty")
    else:
        if not row.get("NormalFossilYield") or not row.get("JunkFossilYield"):
            problems.append(
                "non-capture sites require both NormalFossilYield and JunkFossilYield")
        if row.get("MarineLocation"):
            problems.append("MarineLocation is only valid on a capture site")
    return problems


def add_digsite(exp_fdb, row, fossils=None, mirror=True, report=None):
    """Insert a dig site (+ its fossils) into a mod's expeditions FDB.

    `mirror` also writes the Rebirth/Challenge tables - a site added only to
    DigSites simply will not exist in those modes.
    """
    problems = validate_digsite(row)
    if problems:
        raise ValueError("; ".join(problems))
    if not os.path.isfile(exp_fdb):
        raise ValueError(f"expeditions FDB not found: {exp_fdb}")

    con = sqlite3.connect(exp_fdb)
    written = []
    try:
        with con:
            for tbl in (DIGSITE_MIRRORS if mirror else ("DigSites",)):
                info = list(con.execute(f'PRAGMA table_info("{tbl}")'))
                if not info:
                    continue
                cols = [r[1] for r in info]
                use = {k: v for k, v in row.items() if k in cols}
                ph = ",".join("?" * len(use))
                con.execute(
                    f'INSERT INTO "{tbl}" ({",".join(chr(34)+c+chr(34) for c in use)}) '
                    f'VALUES ({ph})', list(use.values()))
                written.append(tbl)

            for f in (fossils or []):
                for tbl in (DIGSITE_FOSSIL_MIRRORS if mirror
                            else ("DigSiteFossils",)):
                    info = list(con.execute(f'PRAGMA table_info("{tbl}")'))
                    if not info:
                        continue
                    cols = [r[1] for r in info]
                    rec = {"SiteID": row["SiteID"], "FossilID": f.get("FossilID"),
                           "Size": f.get("Size"), "Quantity": f.get("Quantity")}
                    use = {k: v for k, v in rec.items() if k in cols}
                    ph = ",".join("?" * len(use))
                    con.execute(
                        f'INSERT INTO "{tbl}" ({",".join(chr(34)+c+chr(34) for c in use)}) '
                        f'VALUES ({ph})', list(use.values()))
                    written.append(tbl)
    except sqlite3.IntegrityError as e:
        con.close()
        raise ValueError(f"dig site rejected: {e}")
    con.close()
    if report is not None:
        report.setdefault("digsites_added", []).append(
            f"{row['SiteID']} -> {sorted(set(written))}")
    return sorted(set(written))


# ------------------------------------------------------------------ scaling
#
# Optional per-species render scaling. The mechanism is PROVEN (the Deinosuchus
# "Deinodoot" mod): hook Helpers.DinosaurUtils.InstantiateDinosaur and call
# api.transform.SetScale on the entity it returns.
#
# The module is DERIVED FROM the working file rather than retyped, because that
# file carries several hard-won behaviours that are easy to lose in a rewrite:
#   * a re-apply timer - the game rewrites the transform when a dinosaur is
#     placed/released, so the scale must be re-applied periodically;
#   * a discovery grace period - save-restored dinosaurs never pass through
#     InstantiateDinosaur, and scaling one mid-restore leaves it T-posed,
#     frozen and unclickable;
#   * ACSE hook retry paths - AddLuaHooks only fires for modules that are NOT
#     already loaded, so it needs Init+Advance retries (see jwe3-acse-lua-hooks).
# Only the identifiers and the two scale tables are substituted.
#
# CAUTION carried over from that work: collision/pathing envelopes are NOT
# verified to follow SetScale. ~0.5-0.6 is known good; large upscales are much
# less tested. 5.25 was used for Deinodoot but only as a visual experiment.
# Vendored into templates/ so SpeciesGenerator stays self-contained (it ships
# standalone with Run_Species_Generator.bat). Falls back to the original in the
# mod kit if someone deletes the local copy. Refresh with:
#   cp ../Modded/Deinosuchus/database.mddeinosuchusscaledata.lua \
#      templates/scaledata.template.lua
SCALE_TEMPLATE = os.path.join(BASE, "templates", "scaledata.template.lua")
SCALE_TEMPLATE_FALLBACK = os.path.join(
    os.path.dirname(BASE), "Modded", "Deinosuchus",
    "database.mddeinosuchusscaledata.lua")


def _replace_lua_table(src, var_name, body):
    """Swap the contents of `<var> = { ... }` for a generated body."""
    pat = re.compile(re.escape(var_name) + r"\s*=\s*\{.*?\n\}", re.S)
    return pat.sub(f"{var_name} = {{\n{body}\n}}", src, count=1)


def write_scale_module(main_dir, mod_name, scales, report,
                       template=SCALE_TEMPLATE):
    """Generate database.<mod>scaledata.lua.

    `scales` maps SpeciesID -> float, and optionally species NAME -> float for
    the genome fallback (call sites that pass sGenomeID rather than nSpeciesID).
    Returns the written filename, or None if the template is unavailable.
    """
    if not os.path.isfile(template):
        template = SCALE_TEMPLATE_FALLBACK
    if not os.path.isfile(template):
        report.setdefault("warnings", []).append(
            f"scaling requested but template not found: {SCALE_TEMPLATE} - "
            "no scale module generated")
        return None

    with open(template, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()

    by_id, by_name = {}, {}
    for k, v in (scales or {}).items():
        (by_name if isinstance(k, str) else by_id)[k] = float(v)

    id_body = "\n".join(f"    [{k}] = {v}," for k, v in sorted(by_id.items()))
    name_body = "\n".join(f'    ["{k}"] = {v},'
                          for k, v in sorted(by_name.items()))

    src = _replace_lua_table(src, "MDDeinosuchusScaleData.tRenderScalesBySpeciesID",
                             id_body or "    -- (none)")
    src = _replace_lua_table(src, "MDDeinosuchusScaleData.tRenderScalesByGenome",
                             name_body or "    -- (none)")
    # Rename EVERY occurrence, not just the module identifier. The template also
    # carries `__MDDeinosuchusScaleHooked`, a marker set on the hooked module to
    # make installation idempotent - if two generated mods both kept that name,
    # the second would see it already set and silently skip installing its own
    # hook, so only one mod's dinosaurs would scale. This also fixes the trace
    # prefix and the comments in one go.
    src = src.replace("MDDeinosuchus", mod_name)

    fn = os.path.join(main_dir, f"database.{mod_name.lower()}scaledata.lua")
    with open(fn, "w") as f:
        f.write(src)
    report["scaling"] = {"by_species_id": by_id, "by_name": by_name}
    report.setdefault("warnings", []).append(
        "scaling enabled: collision/pathing envelopes are NOT verified to "
        "follow SetScale - large upscales are lightly tested. Check the "
        "dinosaur can still path and be selected in game.")
    return os.path.basename(fn)


# ---------------------------------------------------------------- assetpkgs
#
# An AssetPackage tells the game WHERE an OVL lives. A prefab says
#     AssetPackages = { Default = { 'Velociraptor', 'Capiraptor' } }
# and each of those names must resolve to an <name>.assetpkg file in the mod's
# Init/ folder. The format is one line of XML (base game ships 1834 of them):
#
#     <AssetpkgRoot game="Jurassic World Evolution 3">
#         <asset_path>ovldata\Content0\Dinosaurs\Land\Acrocanthosaurus\Female\Acrocanthosaurus_Female</asset_path>
#     </AssetpkgRoot>
#
# Vanilla path conventions:
#     model  ovldata\Content0\Dinosaurs\Land\<Species>\<Variant>\<Species>_<Variant>
#     audio  ovldata\Content0\Audio\<Species>_media\<Species>_media
#     mod    ovldata\<ModName>\<subpath>\<AssetName>
#
# The asset_path must match where the OVL is ACTUALLY installed. The generator
# cannot know that - it emits the conventional mod path and flags it for review.
ASSETPKG_XML = ('<AssetpkgRoot game="Jurassic World Evolution 3">\n'
                '\t<asset_path>{path}</asset_path>\n'
                '</AssetpkgRoot>\n')


# Real folder names under ovldata\Content0\Dinosaurs (verified in the install).
# Note it is Water, NOT "Sea", and there is a Shared bucket for cross-species
# assets. Variant folders beneath are Female / Male / Juvenile.
ASSET_CATEGORIES = ("Land", "Water", "Air", "Shared")
ASSET_VARIANTS = ("Female", "Male", "Juvenile")


def build_asset_path(root, category=None, species=None, variant=None,
                     leaf=None):
    """Compose an asset_path from parts, stopping wherever the caller stops.

    Vanilla shape:
        ovldata\\Content0\\Dinosaurs\\Land\\Acrocanthosaurus\\Female\\Acrocanthosaurus_Female
        ^root                        ^cat  ^species          ^variant ^leaf

    Every component after `root` is optional, so a HYBRID that ships one flat
    package can stop at the species level:
        ovldata\\MyMod\\Dinosaurs\\Indominus\\Indominus
    The leaf defaults to "<species>_<variant>" when a variant is given, else
    "<species>" - matching how the base game names the innermost folder/package.
    """
    parts = [p for p in (root, category, species, variant) if p]
    if leaf is None:
        if species and variant:
            leaf = f"{species}_{variant}"
        elif species:
            leaf = species
    if leaf:
        parts.append(leaf)
    return "\\".join(parts)


def default_asset_path(mod_name, package_name, category=None):
    """Conventional mod path for a generated package.

    package_name is a family member prefab name such as Preservosaurus_Male,
    so it is split back into species + variant to mirror the vanilla layout.
    """
    species, variant = package_name, None
    for v in ASSET_VARIANTS:
        if package_name.endswith(f"_{v}"):
            species, variant = package_name[: -(len(v) + 1)], v
            break
    return build_asset_path(rf"ovldata\{mod_name}\Dinosaurs",
                            category=category, species=species,
                            variant=variant, leaf=package_name)


def write_assetpkgs(out_dir, packages, report):
    """packages: {package_name: asset_path}. Writes Init/<name>.assetpkg."""
    init_dir = os.path.join(out_dir, "Init")
    os.makedirs(init_dir, exist_ok=True)
    written = []
    mod_name = os.path.basename(out_dir)
    for name, path in sorted(packages.items()):
        fn = os.path.join(init_dir, f"{name.lower()}.assetpkg")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(ASSETPKG_XML.format(path=path))
        written.append(os.path.basename(fn))

        # Construct matching local folder structure inside the mod directory
        parts = [p for p in path.replace("/", "\\").split("\\") if p]
        lowered_parts = [p.lower() for p in parts]
        if "ovldata" in lowered_parts:
            idx = lowered_parts.index("ovldata")
            if idx + 2 < len(parts):
                rel_sub = os.path.join(*parts[idx + 2:])
                target_folder = os.path.join(out_dir, rel_sub)
                os.makedirs(target_folder, exist_ok=True)
            elif idx + 1 < len(parts):
                rel_sub = os.path.join(*parts[idx + 1:])
                target_folder = os.path.join(out_dir, rel_sub)
                os.makedirs(target_folder, exist_ok=True)
        elif parts:
            target_folder = os.path.join(out_dir, *parts)
            os.makedirs(target_folder, exist_ok=True)

    if written:
        report.setdefault("assetpkgs", []).extend(written)
        report.setdefault("warnings", []).append(
            "assetpkg asset_path values are CONVENTIONAL GUESSES - they must "
            "point at where your OVL is actually installed, or the model will "
            "not load. Check Init/*.assetpkg before shipping.")
    return written



def audit_asset_packages(main_dir, init_dir, report):
    """Every AssetPackages name a prefab references must have an .assetpkg.

    A missing one fails silently - the package simply resolves to nothing and
    the dinosaur has no model. Same class of silent break as a dangling prefab
    reference, so it gets the same up-front check.
    """
    referenced = set()
    if os.path.isdir(main_dir):
        for fn in os.listdir(main_dir):
            if not fn.endswith(".lua"):
                continue
            with open(os.path.join(main_dir, fn), errors="ignore") as f:
                txt = f.read()
            for m in re.finditer(r"AssetPackages\s*=\s*\{(.*?)\}\s*,?\s*\}",
                                 txt, re.S):
                for s in re.findall(r"'([^']+)'", m.group(1)):
                    # __inheritance = 'Append' is a merge directive, not a
                    # package name - the _01 cosmetic stubs all carry one.
                    if s in ("Append", "Prepend", "Replace", "Overwrite"):
                        continue
                    referenced.add(s)
    have = set()
    if os.path.isdir(init_dir):
        have = {f[:-len(".assetpkg")].lower()
                for f in os.listdir(init_dir) if f.endswith(".assetpkg")}
    # Vanilla package names resolve from the base game, so only flag names that
    # look like they belong to THIS mod (i.e. we generated a prefab for them).
    missing = sorted(r for r in referenced if r.lower() not in have)
    if missing:
        report["assetpkg_unresolved"] = missing
    return referenced, missing


def write_scaffold(out_dir, mod_name, plans, config, report):
    import uuid as uuid_mod
    main_dir = os.path.join(out_dir, "Main")
    init_dir = os.path.join(out_dir, "Init")
    os.makedirs(main_dir, exist_ok=True)
    os.makedirs(init_dir, exist_ok=True)
    written = []


    all_prefab_names = []
    
    # Accumulated templates
    ui_rewards = []
    nodes = []
    rebirth_rewards = []
    ingen_data = []
    ingen_techtree = []
    ingen_genomes = []

    for plan in plans:
        new_name = plan["config"]["name"]
        members = plan["members"]
        cosmetic_plan = plan.get("cosmetic_plan", [])
        prefab_overrides = plan["config"].get("prefab_overrides", {})

        # --- Prefab Luas ---
        for prefab_name, donor in members:
            # Match family member string to override key (e.g. "Adult", "Juvenile")
            member_key = "Adult"
            if prefab_name.lower() != new_name.lower():
                member_key = prefab_name[len(new_name):].lstrip('_')
            if not member_key: member_key = "Adult"
            
            props = prefab_overrides.get(member_key, {}).get("Properties", {})
            props_str = serialize_lua_properties(props, indent=8)
            
            path = os.path.join(main_dir, f"{prefab_name.lower()}.lua")
            with open(path, "w") as f:
                f.write(PREFAB_LUA.format(mod=prefab_name, name=prefab_name,
                                          donor=donor or "", properties=props_str))
            written.append(os.path.basename(path))
            all_prefab_names.append(prefab_name)

        # --- Cosmetic variant Luas ---
        for cosm in cosmetic_plan:
            path = os.path.join(main_dir, f"{cosm['name'].lower()}.lua")
            with open(path, "w") as f:
                f.write(COSMETIC_LUA.format(
                    mod=cosm["name"], name=cosm["name"],
                    parent=cosm["parent"], patterns=cosm["patterns"],
                    variants=cosm["variants"],
                ))
            written.append(os.path.basename(path))
            all_prefab_names.append(cosm["name"])
            
        # Tech tree accumulators
        icon = plan["config"].get("icon", new_name)
        ui_rewards.append(f'    TechTree_{new_name} = {{\n        icon = "",\n        label = "{new_name}"\n    }}')
        nodes.append(f'    {new_name}1A = {{\n        streamedIcon = "icons.dinosaurSpecies.{icon}",\n        image = "{icon}",\n        conditions = {{\n            {{preset = "Rating", Target = "0"}}\n        }},\n        rewards = {{\n            {{id = "TechTree_{new_name}"}}\n        }}\n    }}')
        rebirth_rewards.append(f'                    {{id = "TechTree_{new_name}"}}')
        ingen_data.append(f'        {new_name} = {{}}')
        ingen_techtree.append(f'        "TechTree_{new_name}"')
        ingen_genomes.append(f'        "{new_name}"')

    # Join accumulated lists
    ui_rewards_str = ",\n".join(ui_rewards)
    nodes_str = ",\n".join(nodes)
    rebirth_rewards_str = ",\n".join(rebirth_rewards)
    ingen_data_str = ",\n".join(ingen_data)
    ingen_techtree_str = ",\n".join(ingen_techtree)
    ingen_genomes_str = ",\n".join(ingen_genomes)

    # --- PrefabData ---
    prefab_list = "\n".join(f"        {p!r}," for p in all_prefab_names)
    path = os.path.join(main_dir, f"database.{mod_name.lower()}prefabdata.lua")
    with open(path, "w") as f:
        f.write(PREFABDATA_LUA.format(mod_name=mod_name, prefab_list=prefab_list))
    written.append(os.path.basename(path))

    # --- Icon Mount and PPUIPKG ---
    icons = config.get("icons", [])
    if not icons:
        # Default: auto-create icon definitions for all species in the mod
        icons = []
        for p in plans:
            sp_conf = p.get("config", {})
            sp_name = sp_conf.get("name", "NewSpecies")
            icon_name = sp_conf.get("icon") or sp_name
            icons.append({
                "id": f"icons.dinosaurSpecies.{icon_name}",
                "path": f"uigameface/img/dinosaurs/{icon_name.lower()}.png",
                "assetPackage": mod_name
            })

    # Create UI dir
    ui_dir = os.path.join(out_dir, "UI", mod_name)
    os.makedirs(ui_dir, exist_ok=True)

    # Write manager Lua
    icon_lua_path = os.path.join(main_dir, f"managers.{mod_name.lower()}iconmount.lua")
    with open(icon_lua_path, "w") as f:
        f.write(ICON_MOUNT_LUA.format(mod_name=mod_name))
    written.append(os.path.basename(icon_lua_path))
    icon_require = f'\n    table.insert(_tContentToCall, require("Managers.{mod_name}IconMount"))'

    # Group icons by asset_package and emit PPUIPKG files under UI/<pkg_name>/
    icons_by_pkg = {}
    for icon in icons:
        pkg_name = icon.get("assetPackage") or icon.get("asset_package") or mod_name
        icons_by_pkg.setdefault(pkg_name, []).append(icon)

    if not icons_by_pkg:
        icons_by_pkg[mod_name] = []

    for pkg_name, pkg_icons in icons_by_pkg.items():
        pkg_ui_dir = os.path.join(out_dir, "UI", pkg_name)
        os.makedirs(pkg_ui_dir, exist_ok=True)
        ppuipkg_path = os.path.join(pkg_ui_dir, f"userinterfaceimages{pkg_name.lower()}.ppuipkg")
        lines = [
            f'<PPUIPKGRoot file_count="0" icondata_count="{len(pkg_icons)}" game="Jurassic World Evolution 3">',
            f'\t<basic_path>{pkg_name}/UI</basic_path>',
            '\t<files />',
            '\t<types>'
        ]
        for icon in pkg_icons:
            img_path = icon.get("path") or icon.get("image_name") or f"uigameface/img/dinosaurs/{mod_name.lower()}.png"
            lines.append('\t\t<userinterfaceicondata>')
            lines.append(f'\t\t\t<image_name>{img_path}</image_name>')
            lines.append(f'\t\t\t<asset_package>{pkg_name}</asset_package>')
            lines.append('\t\t</userinterfaceicondata>')
            
            # Construct nested folder structure inside UI/<pkg_name>/ matching icon image path
            norm_img_path = img_path.replace("/", os.sep).replace("\\", os.sep)
            dir_name = os.path.dirname(norm_img_path)
            if dir_name:
                icon_folder = os.path.join(pkg_ui_dir, dir_name)
                os.makedirs(icon_folder, exist_ok=True)


        lines.append('\t</types>')
        lines.append('</PPUIPKGRoot>')
        with open(ppuipkg_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        written.append(os.path.relpath(ppuipkg_path, out_dir))



    # --- LuaDatabase ---
    path = os.path.join(main_dir, f"database.{mod_name.lower()}luadatabase.lua")
    with open(path, "w") as f:
        f.write(LUADATABASE_LUA.format(
            mod_name=mod_name,
            scale_require=(SCALE_REQUIRE.format(mod_name=mod_name)
                           if config.get("scaling") else ""),
            icon_require=icon_require))
    written.append(os.path.basename(path))

    # --- Tech tree ---
    path = os.path.join(main_dir, f"database.{mod_name.lower()}techtreedata.lua")
    with open(path, "w") as f:
        f.write(TECHTREE_LUA.format(mod_name=mod_name, ui_rewards=ui_rewards_str, nodes=nodes_str))
    written.append(os.path.basename(path))

    # --- Rebirth hidden species tech tree ---
    path = os.path.join(main_dir, f"database.{mod_name.lower()}rebirthhiddenspeciestechtree.lua")
    with open(path, "w") as f:
        f.write(REBIRTH_TECHTREE_LUA.format(mod_name=mod_name, rebirth_rewards=rebirth_rewards_str))
    written.append(os.path.basename(path))

    # --- InGen database ---
    path = os.path.join(main_dir, f"database.{mod_name.lower()}ingendatabasedata.lua")
    with open(path, "w") as f:
        f.write(INGEN_DATABASE_LUA.format(mod_name=mod_name, ingen_data=ingen_data_str, ingen_techtree=ingen_techtree_str, ingen_genomes=ingen_genomes_str))
    written.append(os.path.basename(path))

    # --- Shared Dinosaur Mods tech tree ---
    path = os.path.join(main_dir, "techtrees.trees.dinosaurmodstechtree.lua")
    with open(path, "w") as f:
        f.write(DINOSAUR_MODS_TECHTREE_LUA)
    written.append(os.path.basename(path))

    # --- Init database config ---
    path = os.path.join(init_dir, f"databases.{mod_name.lower()}.lua")
    with open(path, "w") as f:
        f.write(INIT_DATABASE_LUA.format(mod_name=mod_name))
    written.append(f"Init/{os.path.basename(path)}")

    # --- Manifest ---
    with open(os.path.join(out_dir, "Manifest.xml"), "w") as f:
        f.write(MANIFEST_XML.format(name=mod_name, uuid=uuid_mod.uuid4()))
    written.append("Manifest.xml")

    # --- Build script ---
    target = (r"C:\Program Files (x86)\Steam\steamapps\common"
              r"\Jurassic World Evolution 3\Win64\ovldata" + "\\" + mod_name)
    build_dir = os.path.join(BASE, "BuildScripts")
    os.makedirs(build_dir, exist_ok=True)
    build_path = os.path.join(build_dir, f"build_and_install_{mod_name.lower()}.py")
    with open(build_path, "w", encoding="utf-8") as f:
        f.write(BUILD_PY.format(name=mod_name, base=BASE, target=target))
    written.append(os.path.relpath(build_path, out_dir))


    # --- Optional per-species scaling ---
    # config["scaling"] = {SpeciesID or "Name": float}. Both key kinds are
    # supported because InstantiateDinosaur call sites pass either nSpeciesID or
    # sGenomeID, and the proven module checks both in that order.
    scaling = config.get("scaling")
    if scaling:
        fn = write_scale_module(main_dir, mod_name, scaling, report)
        if fn:
            written.append(fn)

    # --- AssetPackages ---
    # Prefabs reference package names; each needs an .assetpkg in Init/ or the
    # model silently fails to load. Emit one per package this mod introduces,
    # then audit what the prefabs actually reference.
    referenced, _ = audit_asset_packages(main_dir, init_dir, report)
    # One package per FAMILY MEMBER (the _NN cosmetics ride on their parent's
    # package). Emitted whether or not a prefab lists it yet: the whole point is
    # to give the author a package to aim at their own OVL. Anything the prefabs
    # already reference that looks mod-owned is included too.
    members_only = {p for p in all_prefab_names if not re.search(r"_\d{2}$", p)}
    mod_owned = set(members_only) | {
        r for r in referenced
        if r.lower() in {p.lower() for p in all_prefab_names}
        or r.lower().startswith(mod_name.lower())}


    explicit = config.get("asset_packages") or {}
    # config["asset_category"] = Land | Water | Air | Shared (None = flat path,
    # which is what a hybrid shipping one package wants)
    category = config.get("asset_category")
    packages = {name: explicit.get(
                    name, default_asset_path(mod_name, name, category))
                for name in sorted(mod_owned)}
    packages.update({k: v for k, v in explicit.items() if k not in packages})
    if packages:
        written += [f"Init/{w}" for w in write_assetpkgs(out_dir, packages, report)]

    # re-audit: anything still unresolved belongs to the BASE GAME (fine) or is
    # a typo (not fine) - reported either way so it can be eyeballed.
    audit_asset_packages(main_dir, init_dir, report)

    return written, build_path


# ================================================================ CLI

def main():
    ap = argparse.ArgumentParser(
        description="Clone a JWE3 species into a new one (data layer).")
    ap.add_argument("--source", default=None,
                    help="donor species Name from the Species table, "
                         "e.g. Triceratops")
    ap.add_argument("--name", default=None,
                    help="new species Name (must be unique)")
    ap.add_argument("--fdb", default=DEFAULT_SOURCE_FDB,
                    help="source c0dinosaurs.fdb")
    ap.add_argument("--exp-fdb", default=DEFAULT_SOURCE_EXP_FDB,
                    help="source c0expeditions.fdb")
    ap.add_argument("--out", default=None,
                    help="output directory (default Generated/<name>)")
    ap.add_argument("--species-id", type=int, default=None)
    ap.add_argument("--genetic-id", type=int, default=None)
    ap.add_argument("--id-floor", type=int, default=DEFAULT_ID_FLOOR,
                    help="lowest id to auto-assign from (default 900)")
    ap.add_argument("--prefab", default=None,
                    help="override Species.Prefab")
    ap.add_argument("--scale", type=float, default=None,
                    help="enable render scaling and apply this scale to every "
                         "generated family member (e.g. 1.5). Collision and "
                         "pathing are NOT verified to follow it - keep it "
                         "modest and test in game.")
    ap.add_argument("--set", action="append", default=[],
                    metavar="Table.Column=value",
                    help="override a column on every cloned row of that "
                         "table")
    ap.add_argument("--only", default=None,
                    help="comma-separated table allow-list")
    ap.add_argument("--skip", default=None,
                    help="comma-separated table deny-list")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-scaffold", action="store_true",
                    help="write only the FDB, no prefab Lua / ACSE / "
                         "build script")
    ap.add_argument("--no-prefab-check", action="store_true",
                    help="skip verifying donor prefabs exist in "
                         "JWE3_Prefabs.lua")
    ap.add_argument("--no-cosmetics", action="store_true",
                    help="skip generating cosmetic _01 variant stubs")
    ap.add_argument("--cosmetics", type=int, default=1,
                    help="number of cosmetic variants per family member "
                         "(default 1)")
    ap.add_argument("--icon", default=None,
                    help="species icon name for tech tree node "
                         "(default: new species name)")
    ap.add_argument("--from-config", default=None,
                    help="load settings from a JSON config file")
    args = ap.parse_args()

    has_prefab_dump = False
    import glob
    if glob.glob(os.path.join(BASE, "*_Prefabs.lua")):
        has_prefab_dump = True
        
    if not has_prefab_dump:
        print(f"WARNING: prefab dump not found in {BASE} - donor prefabs unverified",
              file=sys.stderr)

    # Load from config file if specified
    if args.from_config:
        if not os.path.isfile(args.from_config):
            print(f"ERROR: config file not found: {args.from_config}")
            return 1
        with open(args.from_config) as f:
            config = json.load(f)
        # CLI args override config file
        if args.source:
            config["source"] = args.source
        if args.name:
            config["name"] = args.name
    else:
        if not args.source or not args.name:
            print("ERROR: --source and --name are required "
                  "(or use --from-config)")
            return 1

        # Parse --set overrides
        overrides = {}
        for item in args.set:
            if "=" not in item or "." not in item.split("=")[0]:
                print(f"ERROR: --set expects Table.Column=value, "
                      f"got {item!r}")
                return 1
            lhs, val = item.split("=", 1)
            t, c = lhs.split(".", 1)
            overrides[(t, c)] = val

        config = {
            "source": args.source,
            "name": args.name,
            "fdb": args.fdb,
            "exp_fdb": args.exp_fdb,
            "out": args.out,
            "species_id": args.species_id,
            "genetic_id": args.genetic_id,
            "id_floor": args.id_floor,
            "prefab": args.prefab,
            "overrides": overrides,
            "only": args.only,
            "skip": args.skip,
            "no_scaffold": args.no_scaffold,
            "no_prefab_check": args.no_prefab_check,
            "no_cosmetics": args.no_cosmetics,
            "cosmetics": args.cosmetics,
            "scale_all": args.scale,
            "icon": args.icon or args.name,
        }

    # Validate required fields
    if "source" not in config or "name" not in config:
        print("ERROR: 'source' and 'name' are required in config")
        return 1

    try:
        plan, report = plan_species(config)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    # Print summary
    print(f"cloning {report['source']['name']} "
          f"(Genetic {report['source']['GeneticSpeciesID']}) -> "
          f"{config['name']} "
          f"(Genetic {report['new']['GeneticSpeciesID']})")
    print("family members:")
    for old_str, info in sorted(report["family"].items(),
                                 key=lambda x: int(x[0])):
        print(f"  Species {int(old_str):4d} -> {info['SpeciesID']:4d}   "
              f"{info['Name']}")
    print(f"\n{len(report['tables'])} tables, "
          f"{sum(report['tables'].values())} rows\n")
    for t, count in sorted(report["tables"].items()):
        print(f"  {t:42s} {count:4d} row(s)")

    if report.get("exp_tables"):
        print(f"\nexpeditions FDB:")
        for t, count in sorted(report["exp_tables"].items()):
            print(f"  {t:42s} {count:4d} row(s)")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        for w in dict.fromkeys(report["warnings"]):
            print("  WARNING:", w)
        return 0

    try:
        mod_name = config.get("mod_name") or config["name"]
        plans = [{"config": config, **plan}]
        paths = generate_species(mod_name, plans, report, config)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    print(f"\nwrote {paths['dinosaurs_fdb']}")
    if "expeditions_fdb" in paths:
        print(f"wrote {paths['expeditions_fdb']}")
    if "scaffold" in paths:
        print("\nscaffold:")
        for w in paths["scaffold"]:
            print("   ", w)
    print(f"wrote {paths['report']}")

    for w in dict.fromkeys(report["warnings"]):
        print("  WARNING:", w)
    if "build_script" in paths:
        print(f"\nNEXT: python "
              f"{os.path.basename(paths['build_script'])}   "
              f"(packs + installs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

ICON_MOUNT_LUA = '''local global = _G
local api = global.api
local pcall = global.pcall
local ipairs = global.ipairs
local require = global.require
local Mutators = require("Environment.ModuleMutators")

local {mod_name}IconMount = module(..., Mutators.Manager())

local c_tOverlays = {{
    {{"{mod_name}", "{mod_name}/UI/{mod_name}"}}
}}
local c_nGate = 120

{mod_name}IconMount.Init = function(self, _tProperties, _tEnvironment)
    self.nGate = c_nGate
    self.bLoadReq = false
end

{mod_name}IconMount._Mount = function(self)
    if global.__b{mod_name}IconsMapped then return end
    local ui2 = api.ui2
    if not self.bLoadReq then
        self.bLoadReq = true
        for _, t in ipairs(c_tOverlays) do
            pcall(function() ui2.LoadOverlay(t[1], t[2]) end)
        end
        return
    end
    for _, t in ipairs(c_tOverlays) do
        local bLoaded = false
        pcall(function() bLoaded = ui2.IsOverlayLoaded(t[1]) == true end)
        if not bLoaded then return end
    end
    for _, t in ipairs(c_tOverlays) do
        pcall(function() ui2.MapResources(t[1]) end)
    end
    global.__b{mod_name}IconsMapped = true
end

{mod_name}IconMount.Advance = function(self, _dt, _udt)
    if global.__b{mod_name}IconsMapped then return end
    if self.nGate > 0 then self.nGate = self.nGate - 1 return end
    self:_Mount()
end

Mutators.VerifyManagerModule({mod_name}IconMount)
'''
