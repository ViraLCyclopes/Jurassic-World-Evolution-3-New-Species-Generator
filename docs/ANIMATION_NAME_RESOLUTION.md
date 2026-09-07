# How the engine finds a species' animations

Reference for the `SpeciesCosmeticSets` columns that route animation lookups, and
why fights resolve differently from everything else.

Everything here was established by measurement in a running game on 2026-09-05,
not from documentation.

---

## The columns

| column | namespace | what it does |
|---|---|---|
| `PackageName` | asset package | which package the prefab loads (model, textures, materials) |
| `AnimationPackageNameOverride` | asset package | which package the **animations** come from |
| `RetargetSpeciesNameOverride` | species/clip token | the name used to resolve **retargeted** clips |
| `WorldSpaceMotionSpeciesNameOverride` | species/clip token | the name used to resolve `*_srb.wsm` world-space motion |

Two different namespaces are in play and they are easy to confuse. Package names
look like `Velociraptor_Female`; clip tokens look like `Velociraptor`. An earlier
generator bug filled these with **prefab** names (`VelociraptorJWE`), which is a
third namespace again and resolves to nothing.

`NULL` is meaningful, not missing. Vanilla leaves these NULL constantly, because a
vanilla species' own name already resolves. A **renamed** species cannot rely on
that - its name resolves to nothing unless its OVL genuinely ships clips under it.

---

## Why fights are the only thing that breaks

This is the part that makes the bug so hard to see.

**Ordinary animations** - idle, walk, drink, eat, roar - come straight out of the
motiongraph. The graph references its own clips by name, those clips are in the
same OVL, and it all resolves internally. A rename keeps graph and clips
consistent, so nothing breaks.

**Fight animations are retargeted.** A fight pairs two *different* species, and
the engine has to map the animation onto both skeletons. That path resolves **by
name**, through `RetargetSpeciesNameOverride` - the one lookup that asks the FDB
instead of the graph.

So if the FDB names the donor while the OVL ships clips under your name, exactly
one subsystem fails, and it is the one nobody tests first.

### What the failure looks like

Measured, paused mid-fight, comparing a broken modded species against vanilla:

```
IndominusRex + Acro   (both vanilla)    7.73 m apart   fights correctly
YourSpecies  + Acro   (names disagree) 15.41 m apart   broken
```

`DynamicFight` for that pair gives `TheatreRadius 11.0`, `MinFightRadius 6.0`.
Vanilla lands between those bounds. The broken species is outside the circle and
is never pulled onto it, because the fight animation it needs was never found.

Three symptoms follow from that single fact, and they look like three separate
bugs:

* **no attack animation** - the swing is gated on being in position
* **the partner still takes damage** - the fight resolves logically without
  needing proximity
* **"heavily misaligned" animations, sometimes a stiff bind-like pose** - correct
  animations playing at positions that were never established

---

## Things that are NOT the cause

All of these were checked by measurement while chasing this, and all came back
clean. Do not re-spend the time:

* the `DynamicFight` / `HuntAttack` / `JumpAttack` tables - keyed on
  **animation set** (`TheropodLarge`), which a renamed species inherits correctly
* the pairing direction - the row exists with both `CanFinish` flags set
* the motiongraph contents - reverse the rename and diff against the donor:
  **zero differing lines**. `rename_contents` is faithful.
* the `.wsm` set - same count as the donor (377), correctly prefixed, none dropped
* `coord_group` values - identical across JWE2, JWE3 and renamed graphs, and none
  contain a species name
* the `anim_dynamicfight` streams - byte-identical to the donor's
* species dimensions, combat flags, archetypes - identical to the donor
* prefab `Transform` scale/rotation
* the new `SpeciesID` / `GeneticSpeciesID` not existing in base tables

The fight system is also **unchanged from JWE2** - same 12 tables, identical
`DynamicFight` columns, same animation-set keying - so this is not a JWE3
regression and no JWE2-era technique sidesteps it.

---

## The two consistent configurations

Either side can move, as long as they agree:

| | clip token in the OVL | FDB overrides | notes |
|---|---|---|---|
| donor animations | `IndominusRex$...` | `IndominusRex` | generator default |
| own animations | `YourSpecies$...` | `YourSpecies` | needed to author into the graph |

Both are game-verified. Mixing them is the bug.
