-----------------------------------------------------------------------
--/  @file   Database.MDDeinosuchusScaleData.lua
--/
--/  @brief  Render-scale hook for the Deinodoot (Deinosuchus) species.
--/
--/          Same technique as the JWE3 "Breeding Hybrids" mod: wrap
--/          Helpers.DinosaurUtils.InstantiateDinosaur and call
--/          api.transform.SetScale() on the entity ID it returns.
--/
--/          The wrapper is installed through several redundant paths,
--/          because a single ACSE require-hook on helpers.dinosaurutils
--/          is missed if that module was already loaded before the hook
--/          list was collected (this is why Breeding Hybrids also wraps
--/          genome-library manager methods as a lazy installer):
--/            1. Immediately, when ACSE collects AddLuaHooks.
--/            2. ACSE require-hook on helpers.dinosaurutils itself.
--/            3. ACSE require-hooks on modules that load with the park
--/               world (hatchery, spawn manager, genome library, ...).
--/            4. BH-style method wraps on the genome library manager /
--/               UI mode that retry the install at runtime.
--/          All paths are idempotent (guarded by a flag on the module).
--/
--/  @note   Tune the scale values in the two tables below. Species IDs
--/          take priority over genome names. Values are uniform
--/          multipliers on the Dimetrodon rig the Deinodoot uses.
--/
--/  @note   Applying the scale once at spawn is not enough: the game
--/          sets the dinosaur transform again when the hatchery places
--/          the animal, wiping the spawn-time scale. Like the Planet Zoo
--/          JuvenileScale component (which re-applies every 30s from
--/          Advance), we track scaled entities and re-apply the scale
--/          every few seconds from GenomeLibraryManager.Advance.
--/
--/  @note   With the ACSEDebug mod installed, the console shows
--/          "MDDeinosuchus:" trace lines, and two commands are added:
--/          DeinoScaleStatus and SetDinoScale <entityID> <scale>.
-----------------------------------------------------------------------
local global = _G
local api = global.api
local pairs = global.pairs
local ipairs = global.ipairs
local type = global.type
local pcall = global.pcall
local require = global.require
local tostring = global.tostring
local unpack = global.unpack or (global.table and global.table.unpack)

local MDDeinosuchusScaleData = module(...)

-- Scale by species ID (from mddeinosuchusdinosaurs.fdb, Species table)
MDDeinosuchusScaleData.tRenderScalesBySpeciesID = {
    [41726] = 5.25, -- Deinodoot (adult female)
    [41727] = 5.25, -- Deinodoot_Male (adult male)
    [41728] = 5.25, -- Deinodoot_Juvenile
}

-- Fallback: scale by genome / species name, for call sites that pass
-- sGenomeID (or sGenome) instead of nSpeciesID.
MDDeinosuchusScaleData.tRenderScalesByGenome = {
    ["Deinodoot"]          = 5.25,
    ["Deinodoot_Male"]     = 5.25,
    ["Deinodoot_Juvenile"] = 5.25,
}

-- Entities we have scaled, and the re-application timer. The transform
-- gets rewritten by the game when the dinosaur is placed/released, so
-- the scale is re-applied periodically from a wrapped Advance below.
MDDeinosuchusScaleData.tScaledEntities = {}
MDDeinosuchusScaleData.fReapplyInterval = 2.0 -- seconds
MDDeinosuchusScaleData._fReapplyAccum = 0
MDDeinosuchusScaleData._nReapplyPasses = 0

-- Save-restored dinosaurs never pass through InstantiateDinosaur, so
-- they must be discovered in the world (dinosaursAPI:GetDinosaurs) and
-- adopted. Discovery only starts this many seconds after a world begins,
-- so we never touch entities that are still async-restoring (scaling an
-- entity mid-restore breaks it: T-pose/frozen/unclickable).
MDDeinosuchusScaleData.fDiscoveryGrace = 10.0 -- seconds
MDDeinosuchusScaleData._fWorldAge = 0
MDDeinosuchusScaleData._tLastWorld = nil

-- Resolve the render scale for one InstantiateDinosaur params table,
-- or nil if this dinosaur is not ours.
MDDeinosuchusScaleData._GetScaleFor = function(tDinosaurData)
    if type(tDinosaurData) ~= "table" then
        return nil
    end
    local nSpeciesID = tDinosaurData.nSpeciesID
    if nSpeciesID and MDDeinosuchusScaleData.tRenderScalesBySpeciesID[nSpeciesID] then
        return MDDeinosuchusScaleData.tRenderScalesBySpeciesID[nSpeciesID]
    end
    local sGenome = tDinosaurData.sGenomeID or tDinosaurData.sGenome
    if sGenome and MDDeinosuchusScaleData.tRenderScalesByGenome[sGenome] then
        return MDDeinosuchusScaleData.tRenderScalesByGenome[sGenome]
    end
    return nil
end

-- Wrap InstantiateDinosaur on the Helpers.DinosaurUtils module table.
-- DinosaurUtils.InstantiateDinosaur is dot-called with the dinosaur
-- params table first; the first return value is the entity ID.
MDDeinosuchusScaleData._InstallScaleHook = function(tModule)
    if type(tModule) ~= "table" or tModule.__MDDeinosuchusScaleHooked then
        return false
    end
    local fnOriginal = tModule.InstantiateDinosaur
    if type(fnOriginal) ~= "function" then
        return false
    end
    tModule.__MDDeinosuchusScaleHooked = true

    tModule.InstantiateDinosaur = function(tDinosaurData, ...)
        local tResults = { fnOriginal(tDinosaurData, ...) }
        pcall(function()
            local fScale = MDDeinosuchusScaleData._GetScaleFor(tDinosaurData)
            if fScale and type(tResults[1]) == "number" and tResults[1] ~= 0 then
                api.transform.SetScale(tResults[1], fScale)
                -- Stamp the entry with the current world's API table so
                -- reapply can tell this world's entities apart from stale
                -- IDs left over from a previous session (entity IDs are
                -- REUSED between save loads).
                MDDeinosuchusScaleData.tScaledEntities[tResults[1]] = {
                    fScale = fScale,
                    tWorld = api.world.GetWorldAPIs(),
                }
                api.debug.Trace(
                    "MDDeinosuchus: SetScale(" .. tostring(tResults[1]) ..
                    ", " .. tostring(fScale) .. ") + tracked for reapply"
                )
            end
        end)
        return unpack(tResults)
    end

    api.debug.Trace("MDDeinosuchus: InstantiateDinosaur scale hook installed")
    return true
end

-- Lazy installer: fetch (or load) Helpers.DinosaurUtils and patch it.
-- Safe to call any number of times, from any point in the boot/park
-- lifecycle.
MDDeinosuchusScaleData._TryInstall = function()
    local bOK, tDinosaurUtils = pcall(require, "Helpers.DinosaurUtils")
    if bOK and type(tDinosaurUtils) == "table" then
        MDDeinosuchusScaleData._InstallScaleHook(tDinosaurUtils)
    end
end

-- Re-apply the scale to every tracked entity. Called (throttled) from
-- the wrapped GenomeLibraryManager.Advance, so it keeps winning against
-- whatever the placement/release code writes into the transform.
MDDeinosuchusScaleData._ReapplyScales = function(nDeltaTime)
    MDDeinosuchusScaleData._fWorldAge =
        MDDeinosuchusScaleData._fWorldAge + (nDeltaTime or 0)
    MDDeinosuchusScaleData._fReapplyAccum =
        MDDeinosuchusScaleData._fReapplyAccum + (nDeltaTime or 0)
    if MDDeinosuchusScaleData._fReapplyAccum < MDDeinosuchusScaleData.fReapplyInterval then
        return
    end
    MDDeinosuchusScaleData._fReapplyAccum = 0

    -- Entity IDs are reused between save loads, so only touch entities
    -- tracked in THIS world session; silently drop anything stale.
    -- SetScale on a stale ID during a reload hits the new world's
    -- entities mid-initialization and breaks them (T-pose, frozen).
    local tCurrentWorld = nil
    pcall(function()
        tCurrentWorld = api.world.GetWorldAPIs()
    end)

    -- Detect a world change and restart the discovery grace timer.
    if tCurrentWorld ~= MDDeinosuchusScaleData._tLastWorld then
        MDDeinosuchusScaleData._tLastWorld = tCurrentWorld
        MDDeinosuchusScaleData._fWorldAge = 0
    end

    -- Discovery: adopt untracked Deinodoots already in the world (save
    -- restore does not go through InstantiateDinosaur). Only after the
    -- grace period, so restoring entities are never touched.
    if tCurrentWorld and
            MDDeinosuchusScaleData._fWorldAge >= MDDeinosuchusScaleData.fDiscoveryGrace then
        pcall(function()
            local dinosAPI = tCurrentWorld.dinosaurs
            if not dinosAPI then
                return
            end
            local tDinosaurs = dinosAPI:GetDinosaurs(true)
            for _, nEntityID in ipairs(tDinosaurs) do
                if not MDDeinosuchusScaleData.tScaledEntities[nEntityID] then
                    local sSpeciesName = dinosAPI:GetBaseSpeciesName(nEntityID)
                    local fScale = sSpeciesName and
                        MDDeinosuchusScaleData.tRenderScalesByGenome[sSpeciesName]
                    if fScale then
                        MDDeinosuchusScaleData.tScaledEntities[nEntityID] = {
                            fScale = fScale,
                            tWorld = tCurrentWorld,
                        }
                        api.debug.Trace("MDDeinosuchus: adopted world dinosaur " ..
                            tostring(nEntityID) .. " (" .. sSpeciesName .. ")")
                    end
                end
            end
        end)
    end

    local nCount = 0
    local nDropped = 0
    for nEntityID, tEntry in pairs(MDDeinosuchusScaleData.tScaledEntities) do
        if type(tEntry) ~= "table" or tEntry.tWorld ~= tCurrentWorld then
            MDDeinosuchusScaleData.tScaledEntities[nEntityID] = nil
            nDropped = nDropped + 1
        else
            pcall(api.transform.SetScale, nEntityID, tEntry.fScale)
            nCount = nCount + 1
        end
    end

    if nDropped > 0 then
        api.debug.Trace("MDDeinosuchus: dropped " .. tostring(nDropped) ..
            " stale tracked entities from a previous world session")
    end

    -- Trace the first few passes only, to confirm it runs without
    -- spamming the log forever.
    if nCount > 0 and MDDeinosuchusScaleData._nReapplyPasses < 5 then
        MDDeinosuchusScaleData._nReapplyPasses =
            MDDeinosuchusScaleData._nReapplyPasses + 1
        api.debug.Trace(
            "MDDeinosuchus: reapplied scale to " .. tostring(nCount) ..
            " entities (pass " ..
            tostring(MDDeinosuchusScaleData._nReapplyPasses) .. ")"
        )
    end
end

-- BH-style runtime retry: wrap a few frequently-called methods so the
-- installer keeps being retried once the park world is really up.
MDDeinosuchusScaleData._tRetryMethods = {
    ["managers.genomelibrarymanager"] = {
        "_RefreshDataStoreForItem",
        "_RefreshSynthesiseDinosaurButton",
        "_OnDinosaurCohabitationSettingsChangedMessage",
    },
    ["editors.genomelibrary.genomelibraryuimode"] = {
        "Run",
        "_Handle_UI_ModifyGenome",
        "_UpdateDisplayedDino",
    },
}

MDDeinosuchusScaleData._WrapRetryMethods = function(tModule, tMethodNames)
    if type(tModule) ~= "table" or tModule.__MDDeinosuchusScaleRetryWrapped then
        return
    end
    tModule.__MDDeinosuchusScaleRetryWrapped = true
    for _, sMethod in ipairs(tMethodNames) do
        local fnOriginal = tModule[sMethod]
        if type(fnOriginal) == "function" then
            tModule[sMethod] = function(...)
                pcall(MDDeinosuchusScaleData._TryInstall)
                return fnOriginal(...)
            end
        end
    end

    MDDeinosuchusScaleData._WrapAdvance(tModule)
end

-- Piggyback the periodic scale re-application on a manager's per-frame
-- Advance. Applied to every hooked manager that has one; the reapply
-- itself is throttled, so multiple wrapped Advances are harmless.
MDDeinosuchusScaleData._WrapAdvance = function(tModule)
    if type(tModule) ~= "table" or tModule.__MDDeinosuchusScaleAdvanceWrapped then
        return
    end
    local fnAdvance = tModule.Advance
    if type(fnAdvance) ~= "function" then
        return
    end
    tModule.__MDDeinosuchusScaleAdvanceWrapped = true
    tModule.Advance = function(self, nDeltaTime, ...)
        pcall(MDDeinosuchusScaleData._ReapplyScales, nDeltaTime)
        return fnAdvance(self, nDeltaTime, ...)
    end

    -- Clear all tracked entities when the world tears down (manager
    -- Shutdown), so an in-session save reload never reapplies scale to
    -- stale entity IDs from the previous session.
    local fnShutdown = tModule.Shutdown
    if type(fnShutdown) == "function" then
        tModule.Shutdown = function(...)
            MDDeinosuchusScaleData.tScaledEntities = {}
            MDDeinosuchusScaleData._fReapplyAccum = 0
            MDDeinosuchusScaleData._fWorldAge = 0
            MDDeinosuchusScaleData._tLastWorld = nil
            api.debug.Trace("MDDeinosuchus: world teardown, cleared tracked entities")
            return fnShutdown(...)
        end
    end
end

-- Modules that load together with the park world; when any of them is
-- first required we know DinosaurUtils is loadable and patch it.
MDDeinosuchusScaleData._tCarrierModules = {
    "components.hatchery",
    "components.nestingarea",
    "managers.dinosaurspawnmanager",
    "managers.dinosaurloanmanager",
}

-- ACSE content hook: register all install paths.
MDDeinosuchusScaleData.AddLuaHooks = function(_fnAdd)
    -- Path 2: direct require-hook (works when DinosaurUtils loads late)
    _fnAdd("helpers.dinosaurutils", MDDeinosuchusScaleData._InstallScaleHook)

    -- Path 3: carrier modules (also gain the Advance reapply wrap when
    -- they have a per-frame Advance, e.g. the spawn/loan managers)
    for _, sModuleName in ipairs(MDDeinosuchusScaleData._tCarrierModules) do
        local sName = sModuleName
        _fnAdd(sName, function(tModule)
            api.debug.Trace("MDDeinosuchus: module hook fired for " .. sName)
            MDDeinosuchusScaleData._TryInstall()
            MDDeinosuchusScaleData._WrapAdvance(tModule)
        end)
    end

    -- Path 4: retry wraps on genome library manager / UI mode
    for sModuleName, tMethods in pairs(MDDeinosuchusScaleData._tRetryMethods) do
        local sName = sModuleName
        local tMethodNames = tMethods
        _fnAdd(sName, function(tModule)
            api.debug.Trace("MDDeinosuchus: module hook fired for " .. sName)
            MDDeinosuchusScaleData._TryInstall()
            MDDeinosuchusScaleData._WrapRetryMethods(tModule, tMethodNames)
        end)
    end

    -- Path 1: try right now, in case DinosaurUtils is already loaded
    pcall(MDDeinosuchusScaleData._TryInstall)
end

-- Debug console commands (visible with the ACSEDebug mod installed).
MDDeinosuchusScaleData.AddLuaCommands = function(_fnAdd)
    _fnAdd("&Deino&Scale&Status", {
        function(tEnv, tArgs)
            local bOK, tDinosaurUtils = pcall(require, "Helpers.DinosaurUtils")
            local bLoaded = bOK and type(tDinosaurUtils) == "table"
            local sMsg = "DinosaurUtils loaded: " .. tostring(bLoaded)
            if bLoaded then
                sMsg = sMsg .. " | scale hook installed: " ..
                    tostring(tDinosaurUtils.__MDDeinosuchusScaleHooked == true)
            end
            return true, sMsg
        end,
        "Reports whether the Deinodoot scale hook is installed.\n"
    })
    _fnAdd("&Set&Dino&Scale {int32} {float}", {
        function(tEnv, tArgs)
            if #tArgs ~= 2 then
                return false, "Requires an entity ID and a scale value."
            end
            api.transform.SetScale(tArgs[1], tArgs[2])
            return true, "Scale applied to entity " .. tostring(tArgs[1])
        end,
        "Applies a render scale to an entity: SetDinoScale <entityID> <scale>\n"
    })
end
