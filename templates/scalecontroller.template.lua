-----------------------------------------------------------------------
--/  @file   Components.MDDeinosuchusScaleController.lua
--/
--/  @brief  Per-individual render scale for this mod's dinosaurs.
--/
--/          Planet Zoo drives adult size variation from animals.fdb's
--/          SizeData table (MinScaleMale/MaxScaleMale/MinScaleFemale/
--/          MaxScaleFemale) entirely in native code. JWE3 has no
--/          equivalent table and no native hook, so the same behaviour
--/          is rebuilt here in Lua:
--/
--/            1. A scale is rolled ONCE inside the species' min/max
--/               band, when the dinosaur is instantiated.
--/            2. The rolled value is written into the save through a
--/               world serialisation client, so the animal is the same
--/               size after a save/load.
--/            3. The scale is re-applied every couple of seconds,
--/               because placement/release rewrites the transform.
--/
--/  @note   This is a component MANAGER used as a lifecycle host: no
--/          prefab declares the component. ACSE still calls Init /
--/          Advance / Shutdown on every registered manager, which is
--/          what gives us a world-scoped Init early enough to register
--/          a serialisation client before the load pass runs.
--/
--/  @note   Entity IDs are REUSED between save loads. Never persist a
--/          raw entity ID - worldserialisation:SaveEntityID/LoadEntityID
--/          translate them into and out of save-file space.
--/
--/  @see    https://github.com/OpenNaja/ACSE
-----------------------------------------------------------------------
local global = _G
local api = global.api
local ipairs = global.ipairs
local pairs = global.pairs
local pcall = global.pcall
local type = global.type
local math = global.math
local table = global.table
local tostring = global.tostring
local require = global.require
local Object = require("Common.object")
local Base = require("LuaComponentManagerBase")
local Controller = module(..., Object.subclass(Base))

local SERIALISATION_ID = "MDDeinosuchusScaleController"
local SERIALISATION_VERSION = 1

-- Re-apply cadence. The transform is rewritten by the game when the
-- dinosaur is placed or released, so a one-shot SetScale is not enough.
local REAPPLY_INTERVAL = 2.0

-- Save-restored dinosaurs are still async-rebuilding for a while after
-- the world starts. Scaling one mid-restore breaks it (T-pose, frozen,
-- unclickable), so discovery waits this long before touching anything.
local DISCOVERY_GRACE = 10.0

Controller.tAPI = {
    "SetDinosaurScale",
    "GetDinosaurScale",
    "TrackDinosaur",
    "GetTrackedCount",
}

--//
--// @brief Park-Miller PRNG.
--//
--//        Deliberately NOT math.random: math.randomseed sets global
--//        state, and clobbering the shared random stream would perturb
--//        every other mod (and the base game) that draws from it.
--//
Controller._NextRandom = function(self)
    self._nRandState = (self._nRandState * 16807) % 2147483647
    return (self._nRandState - 1) / 2147483646
end

Controller._SeedRandom = function(self)
    local nSeed = 0
    pcall(function()
        nSeed = math.floor((api.time.GetTotalTime() or 0) * 1000)
    end)
    -- Park-Miller requires a state in [1, 2147483646].
    nSeed = (nSeed % 2147483646) + 1
    self._nRandState = nSeed
    -- Discard the first few draws; a small seed produces a small first
    -- value, which would bias early spawns toward the bottom of the band.
    self:_NextRandom()
    self:_NextRandom()
    self:_NextRandom()
end

--//
--// @brief Roll a scale inside a { fMin, fMax } band.
--//
Controller._RollScale = function(self, tRange)
    if type(tRange) ~= "table" then
        return nil
    end
    local fMin = tRange.fMin or tRange.fMax
    local fMax = tRange.fMax or tRange.fMin
    if not fMin or not fMax then
        return nil
    end
    if fMax < fMin then
        fMin, fMax = fMax, fMin
    end
    if fMax == fMin then
        return fMin
    end
    local fScale = fMin + self:_NextRandom() * (fMax - fMin)
    -- Round to 4dp so the saved value, the applied value and anything
    -- printed by the debug commands all agree exactly.
    return math.floor(fScale * 10000 + 0.5) / 10000
end

Controller.Init = function(self, _tWorldAPIs)
    self.tWorldAPIs = _tWorldAPIs
    self.worldSerialisationAPI = _tWorldAPIs.worldserialisation
    self.dinosaursAPI = _tWorldAPIs.dinosaurs

    -- entityID -> fScale, for dinosaurs we are actively scaling.
    self.tEntities = {}
    -- entityID -> fScale, restored from the save and not yet adopted.
    self.tLoadedScales = {}

    self.fReapplyAccum = 0
    self.fWorldAge = 0
    self.nReapplyPasses = 0

    self:_SeedRandom()

    self.worldSerialisationAPI:RegisterWorldSerialisationClient(
        SERIALISATION_ID,
        SERIALISATION_VERSION,
        function(tSave, tParams)
            return self:WorldSerialisationClient_Save(tSave, tParams)
        end,
        function(tLoad, nLoadedVersion, tParams)
            return self:WorldSerialisationClient_Load(tLoad, nLoadedVersion, tParams)
        end,
        function(nOldVersion)
            return nOldVersion >= 1
        end
    )

    api.debug.Trace("MDDeinosuchus: scale controller initialised")
end

-- ACSE calls Configure() unconditionally on every registered custom
-- component. LuaComponentManagerBase does not provide a default.
Controller.Configure = function(self)
end

Controller.Shutdown = function(self)
    -- Entity IDs are reused between world sessions: anything still held
    -- here would be re-applied to a DIFFERENT entity next world.
    self.tEntities = {}
    self.tLoadedScales = {}
    self.fReapplyAccum = 0
    self.fWorldAge = 0
    api.debug.Trace("MDDeinosuchus: world teardown, cleared tracked entities")
end

Controller.OnWorldActivation = function(self)
end

Controller.OnWorldDeactivation = function(self)
end

--//
--// @brief Adopt a freshly instantiated dinosaur at a rolled scale.
--//        Called from the InstantiateDinosaur hook in the data module.
--//
Controller.TrackDinosaur = function(self, nEntityID, tRange)
    if type(nEntityID) ~= "number" or nEntityID == 0 then
        return nil
    end
    -- A dinosaur restored from a save is instantiated too in some
    -- paths; its saved scale always wins over a fresh roll.
    local fScale = self.tLoadedScales[nEntityID]
    if fScale then
        self.tLoadedScales[nEntityID] = nil
    else
        fScale = self:_RollScale(tRange)
    end
    if not fScale then
        return nil
    end
    self.tEntities[nEntityID] = fScale
    pcall(api.transform.SetScale, nEntityID, fScale)
    api.debug.Trace("MDDeinosuchus: tracking entity " .. tostring(nEntityID) ..
        " at scale " .. tostring(fScale))
    return fScale
end

--//
--// @brief Discover dinosaurs the instantiate hook never saw.
--//
--//        Save-restored animals are rebuilt from serialised components
--//        and do not pass through InstantiateDinosaur, so they have to
--//        be found in the world and matched against the loaded scales.
--//
Controller._DiscoverDinosaurs = function(self)
    local dinosaursAPI = self.dinosaursAPI
    if not dinosaursAPI then
        return
    end
    local tDinosaurs = dinosaursAPI:GetDinosaurs(true)
    if type(tDinosaurs) ~= "table" then
        return
    end
    local ScaleData = require("Database.MDDeinosuchusScaleData")
    for _, nEntityID in ipairs(tDinosaurs) do
        if not self.tEntities[nEntityID] then
            local fScale = self.tLoadedScales[nEntityID]
            if fScale then
                self.tLoadedScales[nEntityID] = nil
                self.tEntities[nEntityID] = fScale
                api.debug.Trace("MDDeinosuchus: restored entity " ..
                    tostring(nEntityID) .. " at saved scale " .. tostring(fScale))
            else
                -- No saved scale: a dinosaur that predates this mod, or
                -- one that arrived by a path the hook does not cover.
                -- Roll it now so it still varies, and it is saved from
                -- here on.
                local sSpeciesName = dinosaursAPI:GetBaseSpeciesName(nEntityID)
                local tRange = sSpeciesName and
                    ScaleData.tRenderScalesByGenome[sSpeciesName]
                if tRange then
                    fScale = self:_RollScale(tRange)
                    if fScale then
                        self.tEntities[nEntityID] = fScale
                        api.debug.Trace("MDDeinosuchus: adopted untracked " ..
                            tostring(sSpeciesName) .. " " .. tostring(nEntityID) ..
                            " at rolled scale " .. tostring(fScale))
                    end
                end
            end
        end
    end
end

Controller.Advance = function(self, _nDeltaTime, _nUnscaledDeltaTime)
    local nDelta = _nDeltaTime or 0
    self.fWorldAge = self.fWorldAge + nDelta
    self.fReapplyAccum = self.fReapplyAccum + nDelta
    if self.fReapplyAccum < REAPPLY_INTERVAL then
        return
    end
    self.fReapplyAccum = 0

    if self.fWorldAge >= DISCOVERY_GRACE then
        pcall(function()
            self:_DiscoverDinosaurs()
        end)
    end

    local nCount = 0
    for nEntityID, fScale in pairs(self.tEntities) do
        pcall(api.transform.SetScale, nEntityID, fScale)
        nCount = nCount + 1
    end

    -- Trace the first few passes only, to confirm it runs without
    -- spamming the log forever.
    if nCount > 0 and self.nReapplyPasses < 5 then
        self.nReapplyPasses = self.nReapplyPasses + 1
        api.debug.Trace("MDDeinosuchus: reapplied scale to " .. tostring(nCount) ..
            " entities (pass " .. tostring(self.nReapplyPasses) .. ")")
    end
end

Controller.WorldSerialisationClient_Save = function(self, _tSave, _tParams)
    _tSave.tScaledEntities = {}
    for nEntityID, fScale in pairs(self.tEntities) do
        table.insert(_tSave.tScaledEntities, {
            entity = self.worldSerialisationAPI:SaveEntityID(nEntityID),
            fScale = fScale,
        })
    end
    api.debug.Trace("MDDeinosuchus: saved " ..
        tostring(#_tSave.tScaledEntities) .. " dinosaur scales")
end

Controller.WorldSerialisationClient_Load = function(self, _tLoad, _nLoadedVersion, _tParams)
    self.tLoadedScales = {}
    local nCount = 0
    for _, tSaved in ipairs(_tLoad.tScaledEntities or {}) do
        local nEntityID = self.worldSerialisationAPI:LoadEntityID(tSaved.entity)
        if nEntityID and tSaved.fScale then
            self.tLoadedScales[nEntityID] = tSaved.fScale
            nCount = nCount + 1
        end
    end
    -- The world has just been rebuilt, so restart the discovery grace:
    -- these entities are still async-restoring.
    self.fWorldAge = 0
    api.debug.Trace("MDDeinosuchus: loaded " .. tostring(nCount) .. " dinosaur scales")
    return true
end

--//
--// Component API
--//

--//
--// @brief Force one dinosaur to a specific scale.
--// usage: api.mddeinosuchusscalecontroller:SetDinosaurScale(54665, 1.2)
--//
Controller.SetDinosaurScale = function(self, nEntityID, fScale)
    if type(nEntityID) ~= "number" or type(fScale) ~= "number" then
        return false
    end
    self.tEntities[nEntityID] = fScale
    pcall(api.transform.SetScale, nEntityID, fScale)
    return true
end

--//
--// @brief Read back the scale this mod is holding for a dinosaur.
--//
Controller.GetDinosaurScale = function(self, nEntityID)
    return self.tEntities[nEntityID]
end

Controller.GetTrackedCount = function(self)
    local nCount = 0
    for _ in pairs(self.tEntities) do
        nCount = nCount + 1
    end
    return nCount
end
