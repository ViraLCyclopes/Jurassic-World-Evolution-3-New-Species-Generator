# SpeciesGenerator fix implementation handoff

## Objective and boundaries

Fix the six defects identified in the September 8, 2026 review, with regression coverage. Then address the narrowly scoped hardening items below. This is an implementation plan for Sol or Luna; no implementation has been performed by the review agent.

Work only in `JWE 3 Luas/SpeciesGenerator/` and appropriate project documentation. Read root `CLAUDE.md`, `AI_MOD_INTEROP_RULES.md`, and applicable `AGENTS.md` first. The active implementation is `core/`; `species_gen.py` here is a compatibility shim. Do not edit the superseded `JWE 3 Luas/species_gen.py`.

Use `python`, never `python3`. Do not install mods, modify the live game, regenerate existing user projects for testing, or modify Cobra format readers. The supplied AGENTS instructions and CLAUDE.md disagree about the authoritative Cobra directory; these fixes should not require Cobra. If packing becomes necessary, resolve the applicable instruction precedence and verify the selected tool before using it. Never inject into live archives.

Inspect the working tree before edits and preserve unrelated changes. Use scratch directories and copies of the bundled source FDBs for tests. Do not spawn agents unless the user explicitly requests delegation. Implement the phases sequentially; the tasks below can be handed to either model without requiring concurrent work.

## Evidence from the review

Line numbers are navigation hints, not immutable references.

| Defect | Entry points | Evidence |
| --- | --- | --- |
| Multi-species build fails | `core/database.py`, `clone_fdb` near 474 and `clone_expeditions_fdb` near 789 | Reproduced with two Dimetrodon clones with disjoint IDs: second dinosaur clone raises `OperationalError: table FoodType already exists`. Both functions unconditionally execute schema creation SQL. |
| Failed rebuild loses old FDBs | `core/generator.py`, `generate_species` near 1135 | Isolated failure injection into `clone_fdb` confirmed both previous FDB sentinel files had already been deleted. |
| GUI forgets allocated IDs | `species_gen_ui.py`, `generate` near 126–182; `species_gen_ui/app.js`, Generate/Update callbacks | Backend mutates a parsed payload and saves it, but returns no normalized project. Browser state therefore retains missing IDs. Static code finding. |
| Editor saves to wrong mod | `species_gen_ui/js/cosmetics_expeditions.js`, `setupEditorPage` | Load stores rows without source identity; Save uses current dropdown selections. Switching from A to B can replace B's table with A's rows. Static code finding. |
| Family IDs overlap | `core/database.py`, `allocate_species_ids` and `clone_fdb` | Allocator accepts base IDs 800000 and 800001; cloning uses base + member index. Allocator acceptance reproduced; insertion collision is currently masked by the schema bug. |
| Grid rebuild loses edits | `cosmetics_expeditions.js`, Add Row and `deleteEditorRow` | Inputs are read only on Save; Add/Delete re-render stale model rows. Static code finding. |

These findings are code/tool verified only. Do not claim game verification.

## Phase 1 — Establish regression fixtures and fix multi-species cloning

1. Inspect existing test infrastructure and use it where practical. Add focused tests under the project's test location; use standard-library unittest if no runner is established.
2. Separate destination schema initialization from row cloning, or add an explicit schema-existence check shared by both cloners. Initialize absent tables using the source SQL without rewriting the schema text blindly. Preserve standalone calls that create a fresh destination.
3. On an existing table, verify relevant schema compatibility instead of silently accepting an unrelated schema.
4. Review row insertion across species after removing the first failure. Shared expedition sites/tasks and relationship rows may produce additional key collisions. Deduplicate only identical shared rows with the same key and contents. Conflicting data must raise a diagnostic naming the table/key and species. Do not use blanket `INSERT OR IGNORE` or `REPLACE` to hide conflicts.
5. Ensure reports accumulate per-species results rather than overwriting earlier counts.

Acceptance:

- Clone two distinct names from the same donor into both destination FDBs with disjoint ID ranges; both complete families remain present.
- Repeat with two different donors, including a one-member donor and a normal family.
- Check exact expected identity mappings, nonzero expected row counts, and SQLite integrity. Preserve constraints and donor-asset semantics.
- A conflicting row/schema fails explicitly. A fresh one-species build still works.

## Phase 2 — Allocate complete families and preserve identity

1. Factor donor/member resolution into a read-only planning helper shared with cloning. Use the same enabled-member ordering, fallback rules, and member offsets that cloning actually uses. Avoid maintaining a second independent family-count algorithm.
2. Reserve every generated SpeciesID, not only the base. Check the complete range against source IDs, reserved IDs, and other species in the current project, including explicitly supplied IDs. Use the configured source FDB rather than always the bundled default.
3. Reject duplicate explicit genetic IDs between independent species configurations. Preserve the intentional shared genetic ID within one family. Validate integer inputs and range limits with useful errors; do not silently coerce fractional values.
4. Generate missing IDs using a bounded search over valid complete ranges. Fail clearly if no range is available. Explicit invalid/conflicting IDs should be reported, not silently changed.
5. Return the normalized project, including assigned IDs, in the successful backend result. Apply it to `modProject` in both Generate and Update callbacks and refresh relevant UI fields without resetting unrelated editor state. Save Project must then persist these same IDs.
6. Keep identity stable on subsequent builds. Import the existing manifest UUID when present; create a UUID only for a new project, and persist it in normalized project state. Do not silently change a valid existing UUID.

Acceptance:

- Adjacent overlapping family bases and duplicate explicit IDs fail before output mutation.
- Automatically assigned families cannot overlap, including when candidates are forced to collide in a deterministic test.
- Disabled/reordered members follow the single resolver's actual offsets; do not assume every donor has exactly three members.
- Generate twice from the same browser project with initially blank IDs; assigned IDs and manifest UUID remain identical. Save/reload/Update preserves them too.
- Custom source FDB IDs participate in validation.

## Phase 3 — Make the whole rebuild recoverable

Do this before testing end-to-end generation on anything resembling real user output.

1. Preflight source files, donor resolution, names, IDs, and configuration before altering destination files. Missing required sources or donors must be errors, not successful builds with warnings and empty data.
2. Build into a unique staging directory on the same volume as the output. Existing custom assets/icons must survive: prepare a staged copy or equivalent explicit preservation mechanism before scaffolding. Account for potentially large asset folders; never hard-link files that generation might overwrite.
3. Generate both FDBs, all scaffolding, manifest, and normalized `mod_project.json` in staging. Move project JSON writing out of the backend's post-generation write path so it participates in the same publication operation.
4. Validate staging before publication: SQLite integrity, expected species/family identities, referenced generated prefabs, and expected generated asset packages. Distinguish legitimate vanilla/external references from missing mod-owned references. Audit packages after they are written, not only before.
5. Publish with a recoverable backup/swap protocol. Windows cannot be assumed to atomically exchange two populated directories. If the old folder can be renamed but publishing staging fails, restore the backup. Never delete the sole known-good copy. Preserve a recovery path if rollback itself fails and report it clearly.
6. Keep logs and returned paths meaningful: public result paths must point to final output, not the temporary staging location. A logging failure after publication must not misleadingly report that the build never committed.
7. Clean up only verified, task-owned scratch paths. Check resolved paths stay inside the intended output/staging root before recursive removal or movement. Reject symlink/junction escapes where they could direct writes or cleanup outside that root.

Acceptance:

- Inject failures during dinosaur cloning, expedition cloning, scaffolding, validation, and publication. Original files and project JSON remain byte-identical or are restored.
- Simulate a Windows rename/lock failure, including failure after the old output has moved. Verify recovery behavior and actionable error messages.
- A successful build replaces the generated data together and preserves custom art/assets.
- No changes reach source FDBs or existing user-generated projects during tests.

## Phase 4 — Bind editor state to its source and preserve edits

1. Represent a loaded grid as `{databasePath, tableName, columns, rows}` plus a load/request token. Save must use this captured identity, not whichever dropdown values happen to be selected later.
2. Invalidate/disable the grid's Save action when the selected mod/table changes, or explicitly display and retain the loaded identity. Choose one consistent behavior; invalidation is simplest. Preserve dirty data long enough to make accidental loss avoidable.
3. Ignore late load callbacks after a selection change or newer load request. Clear stale state on load errors.
4. Synchronize input changes into the row model, or capture current inputs before every Add/Delete/re-render. Apply the same behavior to expedition grids using the shared renderer.
5. Preserve existing NULL semantics deliberately; avoid accidentally changing empty-string behavior while fixing state synchronization. Use DOM value assignment or complete escaping when rendering arbitrary text.
6. Preserve mod dropdown selection by stable path/name, not sorted-list index; refreshing the mod list must not silently select a different mod.

Acceptance:

- Load A, choose B, Save: B must not change. Test changing the table selector too.
- Rapidly load A then B with callbacks delivered out of order; only the newest result is editable.
- Edit a cell, add a row, delete a different row, then Save/reload: the edit survives. Cover both grid types.
- Refresh the mod list after inserting an alphabetically earlier mod; selection identity remains unchanged.

## Phase 5 — Narrow hardening follow-ups

### Validate output names and paths

Centralize backend validation before any filesystem writes. Validate mod/species identifiers for their actual uses in Lua variable/module names and Windows filenames. Reject traversal, separators, absolute paths, reserved Windows basenames, trailing spaces/dots, and malformed identifiers with useful messages. Treat explicit external asset references separately from writable output paths; do not break valid vanilla `ovldata` references.

### Track generator-owned files

Replace broad deletion of every unexpected Lua/assetpkg with a persisted manifest of files emitted by generation. Delete only previously tracked obsolete generated files. For legacy projects without a manifest, preserve unknown files and warn rather than guessing ownership. If a tracked file was hand-edited, compare recorded hashes and preserve/report the conflict. Retain the existing custom-icon preservation behavior.

Test that obsolete unmodified generated files disappear, while an unknown custom Lua, custom assetpkg, modified generated file, and replacement icon survive or produce an explicit resolvable conflict.

### Make generation responsive, after correctness fixes

Move heavy generation to a Qt worker, leaving dialogs and widget updates on the GUI thread. Pass an isolated payload and emit structured success/error signals. Disable duplicate Generate/Update requests while running, restore controls on every completion path, and handle window closure safely. Do not introduce forced thread termination or cancellation during publication. This is a separate final change so threading cannot mask correctness failures.

## Completion and handoff

- Run the targeted regressions and one complete scratch build containing multiple species through the shared backend path. Exercise Generate and Update response handling and the editor scenarios in a JS/UI harness or the running GUI.
- If GUI verification is unavailable, clearly label it unverified; static inspection is not a successful click test.
- Validate generated Lua syntax when templates/output are affected. Packing, if explicitly performed later, requires the existing Lua gate and packed-entry verification; successful source generation alone is not packing or game verification.
- Update relevant project handoff notes with the actual implementation and verification, without repeating stale claims from older notes.
- Final report: changed files, each fixed defect, test commands/results, remaining limitations, and any intentionally deferred hardening. Do not claim all work complete while core phases 1–4 remain unfinished.

Suggested handoff prompt: "Implement FIX_IMPLEMENTATION_PLAN.md in phase order. Preserve unrelated work and user-generated mods. Use scratch regression tests, complete the six core fixes before optional hardening, and report verified outcomes without deploying to the game."
