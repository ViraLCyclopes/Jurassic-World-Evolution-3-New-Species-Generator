# Shipping your own animations (custom motiongraph / OVL)

By default a generated species **borrows the donor's animations**. That is the
supported path, it works, and you should stay on it unless you specifically need
your own clips. This document is for when you leave it.

Read [ANIMATION_NAME_RESOLUTION.md](ANIMATION_NAME_RESOLUTION.md) first if you
want to know *why* any of this is required.

---

## The one rule

> **Whatever your OVL calls its animation clips, the FDB has to say the same
> name.**

Everything below is a consequence of that sentence.

The generator points three `SpeciesCosmeticSets` columns at the **donor**,
because a borrowed-animation species genuinely has no clips of its own:

```
PackageName                          IndominusRex
AnimationPackageNameOverride         IndominusRex
RetargetSpeciesNameOverride          IndominusRex
WorldSpaceMotionSpeciesNameOverride  (NULL)
```

If you ship a renamed OVL whose clips are called `YourSpecies$FightAttackARight`
and leave those columns naming the donor, the engine looks up
`IndominusRex$FightAttackARight`, finds nothing, and **fights break** while
everything else keeps working. See
[TROUBLESHOOTING_FIGHTS.md](TROUBLESHOOTING_FIGHTS.md) for what that looks like -
it is not obvious, and it cost a full day to find.

---

## Option A - keep the donor's clip names (simplest)

Ship your own OVL for the model and textures, but leave the animation clips
named after the donor. Change nothing in the FDB.

```python
from source.formats.ovl.species_rename import rename_family

# rename the FILE and the model/material tokens, but NOT the clip token
rename_family(donor_ovl, out_dir, "IndominusRex", "YourSpecies")
```

...then rename the clip token back:

```python
# note the trailing '$' - that is what makes it hit clip references only
rename_family(staged_ovl, out_dir2,
              "YourSpecies$", "IndominusRex$",
              stem="YourSpecies")          # keep the archive filename
```

The `$` matters. A clip reference is always `<Token>$<ClipName>`, so
`"YourSpecies$" -> "IndominusRex$"` rewrites every `<mani>` reference and every
`*_srb.wsm` filename, while leaving the bare `YourSpecies` motiongraph name
alone.

**Use this when** you only want a custom model, textures or materials.

---

## Option B - use your own clip names (full control)

Rename everything, including the clip token, and then **tell the FDB about it**.

1. Rename the family normally:

   ```python
   rename_family(donor_ovl, out_dir, "IndominusRex", "YourSpecies")
   ```

2. Update the three columns in `SpeciesCosmeticSets` for the adult rows:

   ```sql
   UPDATE SpeciesCosmeticSets SET
       AnimationPackageNameOverride        = 'YourSpecies',
       RetargetSpeciesNameOverride         = 'YourSpecies',
       WorldSpaceMotionSpeciesNameOverride = 'YourSpecies'
   WHERE SpeciesID = <your adult species id>;
   ```

   `PackageName` is deliberately NOT in that list. It is a different namespace:
   an **asset package** name, which normally carries a `_Female` / `_Male` /
   `_Juvenile` suffix (`Acrocanthosaurus_Female`), whereas the three columns
   above take a bare **clip token** (`Acrocanthosaurus`). A package name never
   contains a `$`; a clip reference always does.

   In practice the prefab is what loads packages anyway -

   ```lua
   AssetPackages = { 'YourSpecies', __inheritance = 'Append' }
   ```

   appends onto the donor's list, so both packages are resident whatever the
   column says. Leaving `PackageName` on the donor is game-verified working.
   Setting it to your own package is arguably more consistent but is UNTESTED -
   if you change it, test that the model still renders.

3. Repack the FDB into `Main.ovl` (the packed copy is the one the game reads -
   loose `.fdb` files beside the mod are ignored).

**Use this when** you want to author into the graph - for example growing VFX
datastreams so a roar emits fire. Those live in the graph, so they only exist if
the species actually uses its own graph.

---

## Juveniles and males

The generator follows the pattern from shipped mods, and you should too:

| row | PackageName | AnimationPackageNameOverride | WSM override |
|---|---|---|---|
| Female (adult) | donor female pkg | donor female pkg | donor |
| Male (adult) | donor female pkg | donor female pkg | donor |
| Juvenile | donor juvenile pkg | NULL | NULL |

Adult males drive off the **female** animation package - that is what vanilla
does too (`TyrannosaurusRex_Male_01` has
`AnimationPackageNameOverride = 'TyrannosaurusRex_Female'`). Juveniles keep their
own package and take no overrides.

If you go with Option B, apply your name to the **adult** rows only, and only if
your OVL actually ships clips under that name for them. A male or juvenile whose
OVL was never renamed still needs the donor's name.

---

## Verifying before you ship

Two silent failure modes, both worth a minute:

**1. The names agree.** Extract your OVL and compare the clip prefix against the
FDB columns:

```bash
python ovl_tool_cmd.py extract YourSpecies.ovl -o out -g "Jurassic World Evolution 3"
ls out | grep -i '\.wsm$' | sed 's/\$.*//' | sort -u     # the clip token
```

That token must equal `AnimationPackageNameOverride` for Option B, or the
donor's name for Option A.

**2. Fights actually work.** Nothing else exercises the retarget path, so a
species can look perfect and still be broken. Put one in a pen with a vanilla
carnivore of a compatible animation set and watch a real fight - see the
troubleshooting doc for what a failure looks like.
