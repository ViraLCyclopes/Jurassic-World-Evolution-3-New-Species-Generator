import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SOURCE_FDB = os.path.join(BASE_DIR, "extracted_fdbs", "c0dinosaurs.fdb")
DEFAULT_SOURCE_EXP_FDB = os.path.join(BASE_DIR, "extracted_fdbs", "c0expeditions.fdb")
DEFAULT_OUT_ROOT = os.path.join(BASE_DIR, "Generated")

# Species.SpeciesID carries an explicit CHECK constraint banning these.
RESERVED_SPECIES_IDS = {59, 61, 63, 64, 65, 323}

# Start well above vanilla (3000+) so future DLCs cannot collide.
DEFAULT_ID_FLOOR = 3000



# FDB Table Sets
COSMETIC_TABLES = [
    "SpeciesCosmeticVariants", "SpeciesCosmeticPatterns",
    "SpeciesCosmeticSets", "SpeciesCosmetics"
]

SPECIES_TABLES = [
    "Species", "GeneticSpecies", "SpeciesStats", "Genome",
    "SpeciesCosmeticSets", "SpeciesCosmetics",
    "SpeciesCosmeticVariants", "SpeciesCosmeticPatterns"
]

EXPEDITION_TABLES = [
    "DigSites", "Genomes", "Fossils", "Tasks"
]

# Scale Templates
SCALE_TEMPLATE = os.path.join(BASE_DIR, "templates", "scaledata.template.lua")
SCALE_TEMPLATE_FALLBACK = os.path.join(
    os.path.dirname(BASE_DIR), "Modded", "Deinosuchus",
    "database.mddeinosuchusscaledata.lua")
# Lifecycle host for the scale data: re-applies the scale, discovers
# save-restored dinosaurs, and persists each rolled value into the save.
SCALE_CONTROLLER_TEMPLATE = os.path.join(
    BASE_DIR, "templates", "scalecontroller.template.lua")

SCALE_REQUIRE = """
    table.insert(_tContentToCall, require("Database.{mod_name}ScaleData"))"""

# --- Templates ---

PREFAB_LUA = '''local global = _G
local api = global.api
local require = global.require
local pairs = global.pairs
local ipairs = global.ipairs

local {mod} = module(...)

{mod}.GetRoot = function()
    return {{
        Prefab = "{donor}",
        Properties = {{
{properties}
        }},
    }}
end

{mod}.GetFlattenedRoot = function()
    local tPrefab = api.entity.CompilePrefab({mod}.GetRoot(), '{mod}')
    return api.entity.FindPrefab('{mod}')
end

return {mod}
'''

COSMETIC_LUA = '''local global = _G
local api = global.api
local require = global.require
local pairs = global.pairs
local ipairs = global.ipairs

local {mod} = module(...)

{mod}.GetRoot = function()
    return {{
        Prefab = "{parent}",
        Properties = {{
            MaterialPatternsName = {{
                Default = "{pattern_set}"
            }},
            MaterialVariantsName = {{
                Default = "{variant_set}"
            }},
            AssetPackages = {{
                Default = {{
                    __inheritance = "Append"
                }}
            }}
        }},
    }}
end


{mod}.GetFlattenedRoot = function()
    local tPrefab = api.entity.CompilePrefab({mod}.GetRoot(), '{mod}')
    return api.entity.FindPrefab('{mod}')
end

return {mod}
'''


PREFABDATA_LUA = '''local global = _G
local api = global.api
local pairs = global.pairs
local ipairs = global.ipairs
local table = require("common.tableplus")
local require = global.require

-- @package Database
-- @class {mod_name}
local {mod_name}PrefabData = module(...)

{mod_name}PrefabData.AddLuaPrefabs = function(_fnAdd)

    -- Inject the prefabs based on a prebuilt list
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
local pairs = global.pairs
local table = global.table
local require = global.require

local {mod_name}Database = module(...)

{manager_block}
{mod_name}Database.AddContentToCall = function(_tContentToCall)
    -- Guard: without ACSE none of this can register.
    if not api.acse then
        return
    end

{self_content}    table.insert(_tContentToCall, require("Database.{mod_name}PrefabData"))
    table.insert(_tContentToCall, require("Database.{mod_name}TechTreeData"))
    table.insert(_tContentToCall, require("Database.{mod_name}RebirthHiddenSpeciesTechTree"))
    table.insert(_tContentToCall, require("Database.{mod_name}InGenDatabaseData")){scale_require}{icon_require}
end
'''

ICON_MANAGER_DATABASE_BLOCK = '''-- ACSE MANAGERS (things with Init/Advance) are registered here, NOT through
-- AddContentToCall. The icon mount must run per-frame so it can defer touching
-- the UI system until the engine is ready - mounting UI textures at boot
-- crashes JWE3. Registered into both environments; the manager itself guards
-- against mapping twice with a _G flag.
{mod_name}Database.tManagers = {{
    ["Environments.ParkEnvironment"] = {{
        ["Managers.{mod_name}IconMount"] = {{}}
    }},
    ["Environments.StartScreenEnvironment"] = {{
        ["Managers.{mod_name}IconMount"] = {{}}
    }},
}}

{mod_name}Database.AddLuaManagers = function(_fnAdd)
    for sEnv, tMgrs in pairs({mod_name}Database.tManagers) do
        _fnAdd(sEnv, tMgrs)
    end
end
'''



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
    GenomeIDs = {{{ingen_genomes}}}
}}

{mod_name}InGenDatabaseData.AddDefaultUnlocks = function(
    _fnAddDefaultTechTreeUnlock,
    _fnAddDefaultGenomeUnlock,
    _fnAddDefaultInjuryUnlock)

    local tData = {mod_name}InGenDatabaseData.tDefaultUnlockedEntries

    for sID, sTechTreeRewardID in pairs(tData.TechTreeRewardIDs) do
        _fnAddDefaultTechTreeUnlock(sTechTreeRewardID)
    end



    for sID, sGenomeID in pairs(tData.GenomeIDs) do
        _fnAddDefaultGenomeUnlock(sGenomeID)
    end

end
'''

DINOSAUR_MODS_TECHTREE_LUA = '''-----------------------------------------------------------------------
--/  @file   TechTrees.Trees.DinosaurModsTechTree.lua
--/  @brief  Dinosaur Mods research tree. Shared across all dinosaur mods.
--/
--/  @note   DO NOT EDIT THIS FILE. Individual mod content is injected via
--/          Database.<ModName>TechTreeData.lua modules.
-----------------------------------------------------------------------

local global = _G
local DinosaurModsTechTree = module(...)

DinosaurModsTechTree.TechTree = {
    name = "DinosaurModsTechTree",
    nodes = {}
}
'''

INIT_DATABASE_LUA = '''local global = _G
local api = global.api
local table = global.table
local require = require
local string = string
local {mod_name}DatabaseConfig = module(...)

{mod_name}DatabaseConfig.tConfig = {{
    tLoad = {{
        {mod_name}Dinosaurs = {{sSymbol = "{mod_name}Dinosaurs"}},
        {mod_name}Expeditions = {{sSymbol = "{mod_name}Expeditions"}}
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
    if not global.api.acse or global.api.acse.versionNumber < 0.641 then
        return {{}}
    else
        return {mod_name}DatabaseConfig.tConfig
    end
end
'''


# Icon mounting - DO NOT "simplify" this back into AddContentToCall.
#
# Registering mod-served UI textures at BOOT TIME crashes JWE3. That is a
# known, previously-diagnosed engine behaviour in this project: icondata in a
# mod's Main.ovl registers fine, but the engine crashes loading the .tex -
# even with byte-identical vanilla bytes. An earlier version of this template
# called a non-existent `api.ui.RegisterIconPackage` directly inside
# AddContentToCall, which is exactly that boot-time path.
#
# The working pattern (proven by the CobblestoneBlock mod, see
# `JWE 3 Luas/Modded/Cobblestone Deco/Main/managers.cobblestoneblockiconmount.lua`)
# is to DEFER the mount:
#   1. ship the ppuipkg + tex in a DEDICATED UI OVL that nothing loads at boot
#      (Generated/<Mod>/UI/<Mod>/ -> packed to <Mod>/UI/<Mod>.ovl);
#   2. from an ACSE MANAGER, wait for GameMain's own UI overlay, then
#      api.ui2.LoadOverlay(name, path) -> poll IsOverlayLoaded -> MapResources.
# api.ui2 is the engine's own late-load path for Gameface UI packages, so
# deferred self-mounting sidesteps the boot crash entirely.
#
# Every ui2 call is pcall-wrapped: a missing overlay must degrade to "no custom
# icons", never take the game down.
ICON_MOUNT_LUA = '''local global = _G
local api = global.api
local pcall = global.pcall
local ipairs = global.ipairs
local require = global.require
local Mutators = require("Environment.ModuleMutators")

local {mod_name}IconMount = module(..., Mutators.Manager())

-- {{OverlayName, path relative to ovldata, no extension}}
local c_tOverlays = {{
{overlay_entries}
}}
-- Game.GameScript loads and maps this before InitGameDatabase. ACSE discovers
-- this manager during database initialisation, so this is an engine-owned
-- readiness signal rather than an arbitrary frame delay.
local c_sBaseOverlay = "UserInterfaceImagesC0"

{mod_name}IconMount.Init = function(self, _tProperties, _tEnvironment)
    self.bLoadReq = false
    self.bMapped = false
end

{mod_name}IconMount._Mount = function(self)
    if global.__b{mod_name}IconsMapped then return end
    local ui2 = api.ui2
    if not ui2 then return end

    -- Follow Game.GameScript.OnPrepareForFirstGameWorld: do not request a mod
    -- overlay until the base UI overlay has finished loading.
    local bBaseReady = false
    local bReadyCall = pcall(function()
        bBaseReady = ui2.IsOverlayLoaded(c_sBaseOverlay) == true
    end)
    if not bReadyCall or not bBaseReady then return end

    -- Request once. Set the state only if the Lua/native call returned without
    -- an error; otherwise Advance retries on the next tick.
    if not self.bLoadReq then
        local bAllRequested = true
        api.debug.Trace("{mod_name}: requesting icon overlay")
        for _, t in ipairs(c_tOverlays) do
            local bRequested = pcall(function()
                ui2.LoadOverlay(t[1], t[2])
            end)
            if not bRequested then bAllRequested = false end
        end
        self.bLoadReq = bAllRequested
        return
    end

    for _, t in ipairs(c_tOverlays) do
        local bLoaded = false
        pcall(function() bLoaded = ui2.IsOverlayLoaded(t[1]) == true end)
        if not bLoaded then return end
    end

    local bAllMapped = true
    for _, t in ipairs(c_tOverlays) do
        local bMapped = pcall(function()
            ui2.MapResources(t[1])
        end)
        if not bMapped then bAllMapped = false end
    end

    -- _G flag, not a self field: the manager is registered into both the Park
    -- and StartScreen environments, so mapping must happen once per process.
    -- Never claim success after a failed MapResources call; Advance will retry.
    if bAllMapped then
        self.bMapped = true
        global.__b{mod_name}IconsMapped = true
        api.debug.Trace("{mod_name}: icon overlay mapped")
    end
end

{mod_name}IconMount.Advance = function(self, _dt, _udt)
    if global.__b{mod_name}IconsMapped then return end
    self:_Mount()
end

-- ACSE managers must end with this, NOT `return`. Without it the manager
-- silently never runs - no error, no trace.
Mutators.VerifyManagerModule({mod_name}IconMount)
'''

MANIFEST_XML = '''<?xml version="1.0" encoding="utf-8"?>
<ContentPack version="1">
  <Name>{name}</Name>
  <ID>{uuid}</ID>
  <Version>1</Version>
  <Type>Game</Type>
</ContentPack>
'''

# Defaults for missing table values
DEFAULT_SPECIES_STATS = {
    "BaseAppeal": 250, "BaseAppealPerSquareMetre": 0.05,
    "AreaPerDinosaurSquareMetres": 200, "BaseHealth": 500,
    "LifespanYears": 15, "LifespanVarianceYears": 3,
    "BaseResilience": 50, "BaseStamina": 100,
    "CombatRating": 100, "TerritorySquareMetres": 3000,
}

DEFAULT_GENOMES = {
    "Viability": 1.0, "GenomeCost": 100000, "IncubationCost": 50000,
    "IncubationTimeSeconds": 60, "SynthesisCost": 75000,
    "SynthesisTimeSeconds": 45, "BaseSicknessChance": 0.05,
    "BaseMutationChance": 0.10, "BaseClutchSize": 3,
    "MaxClutchSize": 6, "SlotCount": 4, "HatcheryType": "Land",
}

DEFAULT_SPECIALISATION = {
    "EnclosureType": "Land", "MinEnclosureArea": 2500,
    "SocialGroupMin": 1, "SocialGroupMax": 8,
    "PopulationMin": 1, "PopulationMax": 15,
}

DEFAULT_EXPEDITIONS = {
    "ExtractionCost": 25000, "ExtractionTimeSeconds": 30,
    "ExpeditionCost": 50000, "ExpeditionTimeSeconds": 120,
}

DEFAULT_BUILDING_UPGRADES = {
    "SlotIndex": 1, "UpgradeCost": 20000,
}
