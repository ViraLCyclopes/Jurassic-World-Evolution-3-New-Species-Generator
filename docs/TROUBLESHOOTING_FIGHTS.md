# "My species won't fight properly"

Symptom-first guide. Fights are the single most fragile thing about a generated
species, because they are the only subsystem that resolves animations **by name
through the FDB** instead of through the motiongraph.

If you only read one line: **the clip token in your OVL and the animation name
columns in the FDB must say the same thing.** See
[CUSTOM_ANIMATIONS.md](CUSTOM_ANIMATIONS.md).

---

## Symptoms that are all the SAME bug

These look like three or four separate problems. They are not - they are one
failure seen from different angles, and chasing them separately wastes days.

| what you see | what is actually happening |
|---|---|
| the animals stand apart and never close | the fight animation was never found, so neither actor is moved onto the fight circle |
| one animal plays no attack animation | its swing is gated on being in position, which never happens |
| the other animal still takes damage | the fight resolves logically; damage does not need proximity |
| "heavily misaligned" animations | correct animations playing at positions that were never established |
| a stiff, bind-like pose during a fight | same thing - no fight animation is driving that animal |

### How to confirm it in ten seconds

Pause mid-fight and measure the gap between the two animals. A working fight
sits inside the fight circle; a broken one is well outside it.

```
IndominusRex + Acro   (both vanilla)     7.73 m    correct
YourSpecies  + Acro   (names disagree)  15.41 m    broken
```

`DynamicFight` gives `TheatreRadius 11.0` and `MinFightRadius 6.0` for that pair,
so a correct fight lands between those two numbers.

---

## The fix

Make the two sides agree. Either is valid:

```
OVL clips  YourSpecies$FightAttackARight     FDB  RetargetSpeciesNameOverride = YourSpecies
OVL clips  IndominusRex$FightAttackARight    FDB  RetargetSpeciesNameOverride = IndominusRex
```

The generator writes the **donor's** name into those columns, because the default
workflow borrows the donor's animations and that is correct for it. If you shipped
a renamed OVL with your own clip names, you have to update the columns to match -
that is the whole bug.

Columns to check, in `SpeciesCosmeticSets`, on the **adult** rows:

* `AnimationPackageNameOverride`
* `RetargetSpeciesNameOverride`
* `WorldSpaceMotionSpeciesNameOverride`

Remember the FDB the game reads is the one **packed into `Main.ovl`**. Loose
`.fdb` files sitting beside the mod are ignored, so editing those changes nothing.

---

## Things it is NOT

Every one of these was checked by measurement while this was being diagnosed, and
every one came back clean. Do not spend the time again:

* **the fight tables** - `DynamicFight` is keyed on **animation set**
  (`TheropodLarge`), which a renamed species inherits correctly. The row exists
  and both `CanFinish` flags are set.
* **the motiongraph contents** - reverse the rename and diff against the donor:
  **zero differing lines**. The rename is faithful.
* **the `.wsm` files** - same count as the donor, correctly prefixed, none lost.
* **the animation streams** - `anim_dynamicfight` is byte-identical to the donor's.
* **species stats, combat flags, archetypes** - identical to the donor.
* **prefab scale or rotation.**
* **the new `SpeciesID` / `GeneticSpeciesID`** not existing in the base tables.

Also worth knowing: the fight system is **unchanged from JWE2** - same tables,
same columns, same animation-set keying - so a JWE2-era trick will not sidestep
this, and it is not a JWE3 regression.

---

## Fights that are broken for ordinary reasons

Rule these out before assuming a name problem:

* **No pairing exists.** `DynamicFight` is keyed on `(AnimSet1, AnimSet2)` and the
  rows are ONE-WAY. Check both orderings before concluding a pair is legal.
* **Same-species fights are gated** by territorial and social rules and are hard
  to provoke naturally. Difficulty starting one is not evidence of a bug.
* **Jump attacks are keyed on `GeneticSpeciesID`**, not animation set, so a new
  species inherits no jump-attack rows at all. That is a separate limitation and
  does not affect ordinary fights.

---

## A warning while testing

**Do not delete an animal that is mid-fight or paused mid-animation.** It hard
crashes the game with no crash dump - reproduced repeatedly. Let the fight finish
and deselect the animal first.
