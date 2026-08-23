-----------------------------------------------------------------------
--/  @file   Database.MDDeinosuchusScaleData.lua
--/
--/  @brief  Per-species render-scale bands, and the spawn hook that
--/          rolls an individual scale inside them.
--/
--/          Planet Zoo stores adult size variation per animal in
--/          animals.fdb (SizeData.MinScaleMale / MaxScaleMale /
--/          MinScaleFemale / MaxScaleFemale) and rolls it natively.
--/          JWE3's dinosaur database has no equivalent column, so the
--/          bands live here and the roll happens in Lua.
--/
--/          This module owns the DATA and the HOOK. The lifecycle -
--/          re-applying the scale, discovering save-restored animals,
--/          and persisting each rolled value into the save - lives in
--/          Components.MDDeinosuchusScaleController.
--/
--/  @note   Tune the bands in the two tables below. Species IDs take
--/          priority over genome names. Each entry is a uniform
--/          multiplier band; fMin == fMax gives a fixed size, which is
--/          how a mod with no size variation is expressed.
--/
--/  @note   The hook is installed through several redundant paths,
--/          because a single ACSE require-hook on helpers.dinosaurutils
--/          is missed if that module was already loaded before the hook
--/          list was collected. All paths are idempotent.
--/
--/  @note   With the ACSEDebug mod installed, the console shows
--/          "MDDeinosuchus:" trace lines and gains the commands
--/          MDDeinosuchusScaleStatus and MDDeinosuchusSetScale.
--/
--/  @see    https://github.com/OpenNaja/ACSE
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

-- Scale bands by species ID (from the mod's dinosaurs.fdb, Species table).
MDDeinosuchusScaleData.tRenderScalesBySpeciesID = {
    [41726] = { fMin = 5.25, fMax = 5.25 }, -- Deinodoot (adult female)
    [41727] = { fMin = 5.25, fMax = 5.25 }, -- Deinodoot_Male (adult male)
    [41728] = { fMin = 5.25, fMax = 5.25 }, -- Deinodoot_Juvenile
}

-- Fallback: bands by genome / species name, for call sites that pass
-- sGenomeID (or sGenome) instead of nSpeciesID, and for the discovery
-- pass, which only has a species name to go on.
MDDeinosuchusScaleData.tRenderScalesByGenome = {
    ["Deinodoot"]          = { fMin = 5.25, fMax = 5.25 },
    ["Deinodoot_Male"]     = { fMin = 5.25, fMax = 5.25 },
    ["Deinodoot_Juvenile"] = { fMin = 5.25, fMax = 5.25 },
}

--//
--// @brief Fetch the live scale controller, or nil before the world is up.
--//
MDDeinosuchusScaleData._GetController = function()
    return api.mddeinosuchusscalecontroller
end

--//
--// @brief Resolve the scale band for one InstantiateDinosaur params
--//        table, or nil if this dinosaur is not ours.
--//
MDDeinosuchusScaleData._GetRangeFor = function(tDinosaurData)
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

--//
--// @brief Wrap InstantiateDinosaur on the Helpers.DinosaurUtils module.
--//        It is dot-called with the dinosaur params table first, and
--//        its first return value is the new entity ID.
--//
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
            local tRange = MDDeinosuchusScaleData._GetRangeFor(tDinosaurData)
            local controller = MDDeinosuchusScaleData._GetController()
            if tRange and controller and type(tResults[1]) == "number" then
                controller:TrackDinosaur(tResults[1], tRange)
            end
        end)
        return unpack(tResults)
    end

    api.debug.Trace("MDDeinosuchus: InstantiateDinosaur scale hook installed")
    return true
end

--//
--// @brief Lazy installer. Safe to call any number of times, from any
--//        point in the boot/park lifecycle.
--//
MDDeinosuchusScaleData._TryInstall = function()
    local bOK, tDinosaurUtils = pcall(require, "Helpers.DinosaurUtils")
    if bOK and type(tDinosaurUtils) == "table" then
        MDDeinosuchusScaleData._InstallScaleHook(tDinosaurUtils)
    end
end

-- Modules that load together with the park world; when any of them is
-- first required we know DinosaurUtils is loadable and patch it.
MDDeinosuchusScaleData._tCarrierModules = {
    "components.hatchery",
    "components.nestingarea",
    "managers.dinosaurspawnmanager",
    "managers.dinosaurloanmanager",
    "managers.genomelibrarymanager",
}

--//
--// @brief ACSE content hook: register the scale controller component.
--//
MDDeinosuchusScaleData.AddLuaComponents = function(_fnAdd)
    _fnAdd("MDDeinosuchusScaleController", "components.mddeinosuchusscalecontroller")
end

--//
--// @brief ACSE content hook: install the instantiate hook.
--//
MDDeinosuchusScaleData.AddLuaHooks = function(_fnAdd)
    -- Direct require-hook, for when DinosaurUtils loads late.
    _fnAdd("helpers.dinosaurutils", MDDeinosuchusScaleData._InstallScaleHook)

    -- Carrier modules, for when it has already loaded.
    for _, sModuleName in ipairs(MDDeinosuchusScaleData._tCarrierModules) do
        _fnAdd(sModuleName, function(tModule)
            MDDeinosuchusScaleData._TryInstall()
        end)
    end

    -- And try right now, in case it is loaded already.
    pcall(MDDeinosuchusScaleData._TryInstall)
end

--//
--// @brief Debug console commands (visible with the ACSEDebug mod).
--//
MDDeinosuchusScaleData.AddLuaCommands = function(_fnAdd)
    _fnAdd("&MDDeinosuchus&Scale&Status", {
        function(tEnv, tArgs)
            local bOK, tDinosaurUtils = pcall(require, "Helpers.DinosaurUtils")
            local bLoaded = bOK and type(tDinosaurUtils) == "table"
            local sMsg = "DinosaurUtils loaded: " .. tostring(bLoaded)
            if bLoaded then
                sMsg = sMsg .. " | hook installed: " ..
                    tostring(tDinosaurUtils.__MDDeinosuchusScaleHooked == true)
            end
            local controller = MDDeinosuchusScaleData._GetController()
            sMsg = sMsg .. " | controller: " .. tostring(controller ~= nil)
            if controller then
                sMsg = sMsg .. " | tracked: " .. tostring(controller:GetTrackedCount())
            end
            return true, sMsg
        end,
        "Reports whether the scale hook and controller are live.\n"
    })
    _fnAdd("&MDDeinosuchus&Set&Scale {int32} {float}", {
        function(tEnv, tArgs)
            if #tArgs ~= 2 then
                return false, "Requires an entity ID and a scale value."
            end
            local controller = MDDeinosuchusScaleData._GetController()
            if not controller then
                return false, "Scale controller is not active."
            end
            controller:SetDinosaurScale(tArgs[1], tArgs[2])
            return true, "Scale applied to entity " .. tostring(tArgs[1])
        end,
        "Overrides one dinosaur's scale: MDDeinosuchusSetScale <entityID> <scale>\n"
    })
end
