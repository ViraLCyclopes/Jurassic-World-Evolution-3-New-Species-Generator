# September 2026 correctness and recovery fixes

Implemented from `FIX_IMPLEMENTATION_PLAN.md` on 2026-09-08.

## Correctness changes

- Multi-species cloning initializes missing destination schemas and verifies an
  existing table's columns, constraints, foreign keys, and unique keys before
  using it. Identical shared rows deduplicate; conflicting rows fail with the
  species, table, and key in the diagnostic. Per-species and aggregate counts
  are both retained in the report.
- One read-only family resolver now supplies the enabled members and offsets to
  cloning and allocation. Allocation reserves the complete family, validates
  explicit integer values, checks the configured source FDB and other project
  species, and searches deterministically for a complete free range. The
  supported generated-ID ceiling is **99,999,999**.
- Successful GUI responses include the normalized project. Generate and Update
  adopt the assigned IDs and persistent UUID, and `mod_project.json` is written
  inside the staged publication.
- Existing manifest UUIDs are retained. A UUID is created only when no valid
  project/manifest identity exists.
- Generation now preflights names, sources, donors, family identities, and IDs;
  builds a copied project in same-volume staging; validates both SQLite files,
  identities, prefab references, and generated asset packages; then publishes
  using a backup/restore swap. Failed builds do not mutate the old output.
- A generated-file hash manifest replaces broad Lua/asset-package cleanup.
  Unknown files are preserved. Obsolete unmodified generated files are removed;
  hand-edited generated files are preserved, reported, and no longer tracked.
- Writable names reject malformed Lua identifiers, traversal, separators,
  absolute paths, and Windows reserved basenames. External `ovldata` references
  remain references and no longer cause directories outside the mod's own
  namespace to be created.

## GUI/editor changes

- Loaded grids carry their database path, table, and request token. Save uses
  that captured identity, selector changes invalidate Save, and late callbacks
  cannot replace a newer load.
- Cell edits synchronize into the model before Add/Delete/re-render for both
  dinosaur and expedition grids. Empty fields retain the existing NULL behavior,
  and rendered values receive complete HTML escaping.
- Generated-mod dropdowns use stable FDB paths instead of sorted array indexes.
- Generation runs in a Qt worker. Duplicate requests are disabled/rejected,
  controls recover on success/error, and the window will not close during the
  non-cancellable publication step.
- Loading project JSON uses the JSON as a baseline, then imports supported
  external edits from generated prefab Lua files and `.assetpkg` files. The
  current project schema cannot represent arbitrary per-row FDB editor changes;
  those are not guessed or silently translated.
- The Asset Packages editor is authoritative during generation. Each left-hand
  name is emitted with matching case as `<name>.assetpkg`, and each right-hand
  path is written into that file and used to create the matching local folder.
  UI category guesses now match suffixed female prefabs such as
  `Dynamoterror_Female`, and stale legacy package copies cannot overwrite table edits.

## Verification

Run from the SpeciesGenerator directory:

```powershell
python -m unittest discover -s tests -v
node tests\editor_harness.js
node --check species_gen_ui\app.js
node --check species_gen_ui\js\cosmetics_expeditions.js
```

The Python suite covers same-donor and mixed-donor multi-species cloning,
one-member and normal families, schema/row conflicts, source-aware complete
family allocation, the 99,999,999 boundary, UUID stability, every staged failure
checkpoint, simulated Windows publication failure and rollback, ownership-file
behavior, the GUI backend's normalized response, a complete two-species scratch
build, SQLite integrity, and generated Lua syntax through `lupa`.

The Node harness covers captured save identity, out-of-order callbacks, stable
selection identity, HTML escaping, and edit preservation through grid rebuilds.
No generated project was installed. Runtime GUI clicking and in-game behavior
remain unverified.
