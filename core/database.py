import os
import sqlite3
import json
import re

from core.templates import (
    DEFAULT_SPECIES_STATS, DEFAULT_GENOMES, DEFAULT_SPECIALISATION,
    DEFAULT_EXPEDITIONS, DEFAULT_BUILDING_UPGRADES,
    RESERVED_SPECIES_IDS, DEFAULT_ID_FLOOR,
    COSMETIC_TABLES, SPECIES_TABLES, EXPEDITION_TABLES
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IDENT_RE = re.compile(r"SpeciesID", re.IGNORECASE)


def table_names(con):
    return [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def columns(con, table):
    """[(name, declared_type, is_pk), ...]"""
    return [(r[1], (r[2] or "").upper(), bool(r[5]))
            for r in con.execute(f'PRAGMA table_info("{table}")')]


def identity_columns(con, table):
    """Columns that reference a species, split by id space."""
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


def lookup_species(con, name):
    row = con.execute(
        "SELECT SpeciesID, GeneticSpeciesID, Name FROM Species "
        "WHERE Name = ? COLLATE NOCASE", (name,)).fetchone()
    return row


def species_family(con, genetic_id):
    return con.execute(
        "SELECT SpeciesID, Name FROM Species WHERE GeneticSpeciesID = ? "
        "ORDER BY SpeciesID", (genetic_id,)).fetchall()


def scan_donor(fdb_path, source_name):
    """Scan the FDB for a species and return its family + available tables."""
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

        stables = species_tables(con)
        table_info = {}
        for t, idents in sorted(stables.items()):
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



def resolve_member_donor(con_src, search_term, default_name):
    """Find (SpeciesID, Name, Prefab) in c0dinosaurs.fdb for a given search_term or default_name."""
    term = (search_term or default_name or "").strip()
    if not term:
        return None
    row = con_src.execute("SELECT SpeciesID, Name, Prefab FROM Species WHERE Prefab = ? COLLATE NOCASE", (term,)).fetchone()
    if row: return row
    row = con_src.execute("SELECT SpeciesID, Name, Prefab FROM Species WHERE Name = ? COLLATE NOCASE", (term,)).fetchone()
    if row: return row
    if default_name and default_name.lower() != term.lower():
        row = con_src.execute("SELECT SpeciesID, Name, Prefab FROM Species WHERE Name = ? COLLATE NOCASE", (default_name,)).fetchone()
        if row: return row
    return None


def clone_fdb(source_fdb, target_fdb, donor_species, new_species,
              new_species_id, new_genetic_id, donor_prefabs=None, fdb_overrides=None, report=None):
    """Clone rows for `donor_species` in `source_fdb` to `target_fdb` under `new_species`.
    Supports per-member donor selection via donor_prefabs dict (Female, Male, Juvenile).
    """
    if report is None:
        report = {}
    fdb_overrides = fdb_overrides or {}
    donor_prefabs = donor_prefabs or {}

    # Opt-in to cloning the donor's FilmVariant cosmetic sets (the movie skins:
    # VelociraptorBlue, KentrosaurusCC, SpinosaurusJWR ...). Off by default -
    # see the SetDefault filter below for why. The UI stores this per species as
    # cosmetics.film_variants.
    keep_film_variants = bool(
        fdb_overrides.get("keep_film_variants")
        or (fdb_overrides.get("cosmetics") or {}).get("film_variants")
    )
    # {src_sid: {SetID, ...}} of cosmetic sets that survived filtering, so the
    # child Variants/Patterns tables can be filtered to match.
    kept_cosmetic_sets = {}

    if new_species_id in RESERVED_SPECIES_IDS:
        report.setdefault("warnings", []).append(
            f"SpeciesID {new_species_id} is in RESERVED_SPECIES_IDS - CHECK constraint will fail!"
        )

    if not os.path.isfile(source_fdb):
        report.setdefault("warnings", []).append(f"Source FDB not found: {source_fdb}")
        return {}

    con_src = sqlite3.connect(f"file:{source_fdb}?mode=ro", uri=True)
    con_dst = sqlite3.connect(target_fdb)

    try:
        cur_src = con_src.cursor()
        cur_dst = con_dst.cursor()

        src_info = lookup_species(con_src, donor_species)
        if not src_info:
            report.setdefault("warnings", []).append(f"Donor species {donor_species!r} not found in {source_fdb}")
            return {}

        src_species_id, src_genetic_id, src_name_actual = src_info
        base_prefix = src_name_actual[:-7] if src_name_actual.endswith("_Female") else src_name_actual

        family_members = fdb_overrides.get("family_members") if isinstance(fdb_overrides, dict) else None
        if family_members and isinstance(family_members, list) and len(family_members) > 0:
            member_specs = []
            idx = 0
            for m in family_members:
                if isinstance(m, dict):
                    if m.get("enabled") is False or m.get("checked") is False:
                        continue
                    m_name = m.get("Name") or m.get("name") or src_name_actual
                    m_pref = m.get("Prefab") or m.get("prefab") or m_name
                else:
                    m_name, m_pref = str(m), str(m)

                donor_fem_pref = donor_prefabs.get("Female") or src_name_actual
                has_fem_suffix = donor_fem_pref.lower().endswith("_female")

                if m_name == src_name_actual or m_name == base_prefix or m_name == f"{base_prefix}_Female":
                    tgt_name = new_species
                    tgt_prefab = f"{new_species}_Female" if has_fem_suffix else new_species
                    gender_key = "Female"
                elif m_name.startswith(base_prefix):
                    suffix = m_name[len(base_prefix):]
                    tgt_name = new_species + suffix
                    tgt_prefab = tgt_name
                    gender_key = suffix.lstrip('_')
                else:
                    tgt_name = f"{new_species}_{m_name}"
                    tgt_prefab = tgt_name
                    gender_key = m_name

                member_specs.append((gender_key, idx, tgt_name, tgt_prefab, m_pref, m_name))
                idx += 1
            if not member_specs:
                donor_fem_pref = donor_prefabs.get("Female") or src_name_actual
                has_fem_suffix = donor_fem_pref.lower().endswith("_female")
                fem_pref = f"{new_species}_Female" if has_fem_suffix else new_species
                member_specs = [
                    ("Female", 0, new_species, fem_pref, donor_prefabs.get("Female"), src_name_actual),
                    ("Male", 1, f"{new_species}_Male", f"{new_species}_Male", donor_prefabs.get("Male"), f"{base_prefix}_Male"),
                    ("Juvenile", 2, f"{new_species}_Juvenile", f"{new_species}_Juvenile", donor_prefabs.get("Juvenile"), f"{base_prefix}_Juvenile")
                ]
        else:
            donor_fem_pref = donor_prefabs.get("Female") or src_name_actual
            has_fem_suffix = donor_fem_pref.lower().endswith("_female")
            fem_pref = f"{new_species}_Female" if has_fem_suffix else new_species
            member_specs = [
                ("Female", 0, new_species, fem_pref, donor_prefabs.get("Female"), src_name_actual),
                ("Male", 1, f"{new_species}_Male", f"{new_species}_Male", donor_prefabs.get("Male"), f"{base_prefix}_Male"),
                ("Juvenile", 2, f"{new_species}_Juvenile", f"{new_species}_Juvenile", donor_prefabs.get("Juvenile"), f"{base_prefix}_Juvenile")
            ]



        resolved_members = []
        member_id_map = {}
        member_name_map = {}
        src_sids = []
        src_names = set()

        for key, idx, tgt_name, tgt_prefab, pref_term, def_name in member_specs:
            row = resolve_member_donor(con_src, pref_term, def_name)
            if not row and key == "Female":
                row = (src_species_id, src_name_actual, donor_prefabs.get("Female") or src_name_actual)

            if row:
                s_id, s_name, s_pref = row
                tgt_sid = new_species_id + idx
                resolved_members.append({
                    "key": key,
                    "target_sid": tgt_sid,
                    "target_name": tgt_name,
                    "target_prefab": tgt_prefab,
                    "src_sid": s_id,
                    "src_name": s_name,
                    "src_prefab": s_pref
                })

                if s_id not in member_id_map:
                    member_id_map[s_id] = tgt_sid
                if s_name not in member_name_map:
                    member_name_map[s_name] = tgt_name
                src_sids.append(s_id)
                src_names.add(s_name)

        cur_src.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
        tables = cur_src.fetchall()
        written_summary = {}

        # --- Donor asset packages, per family member ---
        #
        # A cloned species is RENAMED, and a NULL PackageName resolves off the
        # species' own name. That works in vanilla (Dimetrodon's assets are
        # called Dimetrodon_*) but resolves to nothing for a clone called
        # Deinodoot, so every NULL must be filled with the DONOR's package.
        # This is exactly what the working MDDeinosuchus mod ships: vanilla
        # Dimetrodon has pkg=NULL on both its female and its juvenile, and
        # Deinodoot carries Dimetrodon_Female / Dimetrodon_Juvenile.
        #
        # Read each member's own non-NULL PackageName first so the value is a
        # real PACKAGE name (never a prefab name - different namespaces), and
        # only fall back to a convention when the donor has none anywhere.
        _base_pkg = donor_species[:-7] if donor_species.endswith("_Female") else donor_species

        def _donor_package(member):
            """The donor's real asset-package name for one family member, or None.

            Only rows describing THIS member's own body count. A cosmetic set
            with a non-NULL SpeciesIDOverride belongs to a different body
            variant that happens to be listed on this species - Spinosaurus
            (SpeciesID 40) carries the Rebirth set as SetID 2 with
            PackageName='SpinosaurusJWR_Female' and override=724.

            Skipping the NULL base row and taking that one gave a clone of the
            BASE Spinosaurus the REBIRTH asset package. Dimetrodon never showed
            this because all of its rows are NULL.
            """
            if not member:
                return None
            try:
                cur_src.execute(
                    'SELECT PackageName FROM "SpeciesCosmeticSets" '
                    'WHERE SpeciesID = ? AND PackageName IS NOT NULL '
                    'AND SpeciesIDOverride IS NULL '
                    'ORDER BY (SetDefault = "Standard") DESC, SetID LIMIT 1',
                    (member["src_sid"],))
                row = cur_src.fetchone()
                if row:
                    return row[0]
            except sqlite3.Error:
                pass
            return None

        _by_key = {m.get("key"): m for m in resolved_members}

        # Female: own package, else the <Species>_Female convention.
        donor_female_package = _donor_package(_by_key.get("Female")) or f"{_base_pkg}_Female"

        # Male: own package when the donor male HAS one (Velociraptor_Male,
        # Triceratops_Male are real, distinct male models), otherwise the
        # female's - Dimetrodon has no separate male model, which is why
        # MDDeinosuchus's male reads Dimetrodon_Female. Deliberately NOT the
        # "<Species>_Male" convention: inventing a package the donor never had
        # would point the clone at a file that does not exist.
        donor_male_package = _donor_package(_by_key.get("Male")) or donor_female_package

        # Juvenile: own package, else the <Species>_Juvenile convention. The
        # convention IS needed here - Dimetrodon's juvenile rows are all NULL,
        # yet MDDeinosuchus ships Dimetrodon_Juvenile.
        donor_juvenile_package = (_donor_package(_by_key.get("Juvenile"))
                                  or f"{_base_pkg}_Juvenile")

        donor_packages = {
            "Female": donor_female_package,
            "Male": donor_male_package,
            "Juvenile": donor_juvenile_package,
        }

        # Work out which cosmetic sets survive BEFORE the table loop.
        # sqlite_master returns SpeciesCosmeticPatterns/Variants *before*
        # SpeciesCosmeticSets, so populating this inside the loop would leave
        # the child filter reading an empty dict and keeping every row.
        if not keep_film_variants:
            for m in resolved_members:
                try:
                    cur_src.execute(
                        'SELECT SetID, SetDefault FROM "SpeciesCosmeticSets" '
                        'WHERE SpeciesID = ?', (m["src_sid"],))
                    all_sets = cur_src.fetchall()
                except sqlite3.Error:
                    continue
                if not all_sets:
                    continue
                std = {sid for sid, sd in all_sets if sd == "Standard"}
                # Fallback: DistortusRex/Mutadon have ONLY FilmVariant sets, so
                # filtering them to nothing would strip their cosmetics entirely.
                kept_cosmetic_sets[m["src_sid"]] = std or {s for s, _ in all_sets}

        # --- Cosmetic sets describing a DIFFERENT BODY ----------------------
        #
        # This runs AFTER the SetDefault filter above, which is the primary one:
        # FilmVariant = individual skins (Velociraptor's 13 of them), Standard =
        # the ordinary variants/patterns set. This pass only looks at what
        # survived that, so it can never reintroduce skins.
        #
        # Among the survivors, some Standard sets describe a different BODY.
        # Two columns flag them and NEITHER catches all:
        #
        #   BodyType non-NULL          34 sets
        #   SpeciesIDOverride non-NULL  9 sets   <- 5 of these have NULL BodyType
        #   either                     39 sets
        #
        # Spinosaurus's Rebirth set has only the override; Brachiosaurus's
        # 'Brachiosaurus01_01' has only BodyType. There is no hard rule about
        # which sets carry an override - it is used loosely - so treat it as a
        # HINT, and only act on it when the target is outside this clone, which
        # is a dangling reference by definition rather than a judgement call.
        #
        # BodyType may well be inert in JWE3 (it appears to do nothing in game).
        # It is used here only as a reliable MARKER in the data, not because the
        # engine reads it. What actually selects a body is the set's `Prefab` -
        # and note the clone rewrites Prefab to '<member>_<NN>' anyway, so a
        # cloned variant set would inherit the BASE member's prefab and come out
        # a visual duplicate of _01. That is the real reason to drop it: the
        # clone cannot reproduce the variant body, only a broken echo of it.
        #
        # UILabel looks like a third signal but is unreliable - 29 rows disagree
        # with BodyType (GiganotosaurusJW_Female_01 is BodyType
        # 'Giganotosaurus22' yet labelled Default, while Mosasaurus_Female_02 is
        # labelled 'Deluxe' with BodyType NULL because it is a SKIN).
        #
        # FALLBACK, same shape as the FilmVariant filter above: 10 species have
        # ONLY body-variant sets - Patagotitan's single set is BodyType
        # 'Dreadnoughtus', and Pteranodon_Juvenile / Allosaurus_Juvenile /
        # Giganotosaurus_Juvenile / Iguanodon_Juvenile are the same. For those
        # the variant body IS the species, so dropping would strip every
        # cosmetic. Only drop when something survives.
        cloned_src_ids = {m["src_sid"] for m in resolved_members}
        dropped_variant_sets = []
        for m in resolved_members:
            try:
                cur_src.execute(
                    'SELECT SetID, Prefab, BodyType, SpeciesIDOverride '
                    'FROM "SpeciesCosmeticSets" WHERE SpeciesID = ?',
                    (m["src_sid"],))
                set_rows = cur_src.fetchall()
            except sqlite3.Error:
                continue
            if not set_rows:
                continue

            drop = {
                sid for sid, _pref, body, ov in set_rows
                if body is not None
                or (ov is not None and ov not in cloned_src_ids)
            }
            if not drop:
                continue

            current = kept_cosmetic_sets.get(
                m["src_sid"], {sid for sid, _p, _b, _o in set_rows})
            survivors = current - drop
            if not survivors:
                # Every set is a variant: this IS the species' only body.
                continue

            kept_cosmetic_sets[m["src_sid"]] = survivors
            for sid, pref, body, ov in set_rows:
                if sid not in drop or sid not in current:
                    continue
                why = f"BodyType={body!r}" if body is not None else f"override -> species {ov}"
                dropped_variant_sets.append(f"{pref} (SetID {sid}, {why})")

        if dropped_variant_sets:
            report.setdefault("warnings", []).append(
                "Skipped %d cosmetic set(s) describing a body this mod does not "
                "include: %s. They would have rendered the VANILLA body under "
                "your species' name." % (len(dropped_variant_sets),
                                         ", ".join(dropped_variant_sets)))
            report["dropped_variant_cosmetic_sets"] = dropped_variant_sets

        BASE_ONLY_TABLES = {"SpeciesWildCapture", "SpeciesCohabitation", "SpeciesNewBonus"}

        for tbl_name, create_sql in tables:
            if tbl_name.startswith("sqlite_"):
                continue

            cur_dst.execute(create_sql)
            cur_src.execute(f'PRAGMA table_info("{tbl_name}")')
            cols = [info[1] for info in cur_src.fetchall()]

            has_sp_id = "SpeciesID" in cols
            has_gen_id = "GeneticSpeciesID" in cols
            ident_cols = identity_columns(con_src, tbl_name)
            pk_cols = [info[1] for info in sorted(
                cur_src.execute(f'PRAGMA table_info("{tbl_name}")').fetchall(),
                key=lambda info: info[5]) if info[5]]
            has_name = "Name" in cols
            has_sp_name = "SpeciesName" in cols or "Species" in cols
            has_enum = "EnumName" in cols

            if not (ident_cols or has_name or has_sp_name or has_enum):
                continue

            new_rows = []
            seen_pks = set()

            if has_sp_id:
                target_members = [m for m in resolved_members if m.get("key") == "Female"] if tbl_name in BASE_ONLY_TABLES else resolved_members
                for m in target_members:
                    cur_src.execute(f'SELECT * FROM "{tbl_name}" WHERE "SpeciesID" = ?', (m["src_sid"],))

                    rows = cur_src.fetchall()

                    # Cosmetic sets: keep only the base skin by default.
                    #
                    # SetDefault distinguishes 'Standard' (the species' own base
                    # skin, 334 rows game-wide) from 'FilmVariant' (movie skins -
                    # Velociraptor's Blue/Charlie/Delta/Echo/'93/JWR, 73 rows).
                    # Cloning FilmVariants gives a new species a pile of skins it
                    # has no assets for, and some are DLC-gated (PDLCRebirth), so
                    # a mod should not be shipping them at all.
                    #
                    # Fallback: DistortusRex and Mutadon have ONLY FilmVariant
                    # rows, so filtering unconditionally would leave them with no
                    # cosmetics at all - keep everything in that case.
                    # Cosmetic sets and their children are filtered against the
                    # same precomputed kept-set list, so a Standard-only clone
                    # cannot end up with Variants/Patterns orphaned onto a set
                    # that was dropped.
                    if (tbl_name in ("SpeciesCosmeticSets",
                                     "SpeciesCosmeticVariants",
                                     "SpeciesCosmeticPatterns")
                            and "SetID" in cols
                            and m["src_sid"] in kept_cosmetic_sets):
                        set_i = cols.index("SetID")
                        keep = kept_cosmetic_sets[m["src_sid"]]
                        rows = [r for r in rows if r[set_i] in keep]
                    for row in rows:
                        row_dict = dict(zip(cols, row))
                        row_dict["SpeciesID"] = m["target_sid"]

                        if "GeneticSpeciesID" in row_dict:
                            row_dict["GeneticSpeciesID"] = new_genetic_id

                        # Relationship tables may carry several identity
                        # columns (PreySpeciesID, OtherSpeciesID,
                        # PredatorGeneticSpeciesID, ...). Repoint every donor
                        # family reference, not only the primary SpeciesID.
                        for ident_col, ident_space in ident_cols:
                            if ident_col == "SpeciesID":
                                continue
                            value = row_dict.get(ident_col)
                            if ident_space == "genetic" and value == src_genetic_id:
                                row_dict[ident_col] = new_genetic_id
                            elif ident_space == "species" and value in member_id_map:
                                row_dict[ident_col] = member_id_map[value]

                        if "Name" in row_dict:
                            row_dict["Name"] = m["target_name"]
                        if "SpeciesName" in row_dict:
                            row_dict["SpeciesName"] = m["target_name"]
                        if "Species" in row_dict:
                            row_dict["Species"] = m["target_name"]
                        if "EnumName" in row_dict:
                            row_dict["EnumName"] = m["target_name"]

                        # A Prefab column names a PREFAB, so it must use
                        # target_prefab - NOT target_name. The two differ
                        # whenever the donor's female prefab carries a _Female
                        # suffix: cloning Dimetrodon gives target_name
                        # 'Deinodoot' but target_prefab 'Deinodoot_Female', and
                        # the stub written to Main/ is deinodoot_female.lua.
                        # Using the name here pointed Species.Prefab at a
                        # 'Deinodoot' that does not exist, and made the cosmetic
                        # stub inherit the same missing parent - both SILENT
                        # (compiles, spawns, renders nothing). Donors like
                        # Velociraptor hid this because their female prefab
                        # (VelociraptorJWE) has no suffix, so the two coincide.
                        if tbl_name == "Species" and "Prefab" in row_dict:
                            row_dict["Prefab"] = m["target_prefab"]

                        if tbl_name == "SpeciesCosmeticSets":
                            set_id = row_dict.get("SetID", 1) or 1
                            row_dict["Prefab"] = f"{m['target_prefab']}_{set_id:02d}"

                            # --- Animation / motion routing for a NEW species ---
                            #
                            # A cloned species has a NEW NAME (e.g. Keemstar) and
                            # therefore NO animations of its own. Vanilla can leave
                            # AnimationPackageNameOverride NULL because the engine
                            # resolves "Velociraptor" successfully; a clone named
                            # "Keemstar" cannot - NULL would resolve to nothing.
                            #
                            # Pattern taken from the working MDDeinosuchus mod
                            # (Deinodoot, donor Dimetrodon):
                            #   Female   pkg=Dimetrodon_Female  anim=Dimetrodon_Female  wsm=Dimetrodon
                            #   Male     pkg=Dimetrodon_Female  anim=Dimetrodon_Female  wsm=Dimetrodon
                            #   Juvenile pkg=Dimetrodon_Juvenile anim=NULL              wsm=NULL
                            # i.e. adult female AND male both drive off the donor's
                            # FEMALE animation package; juveniles keep their own and
                            # take no overrides.
                            #
                            # Values must be ASSET PACKAGE names (Velociraptor_Female),
                            # NOT prefab names (VelociraptorJWE) - different namespaces.
                            # An earlier version filled these with Species.Prefab,
                            # which is why clones came out with
                            # AnimationPackageNameOverride='VelociraptorJWE'.
                            m_key = m.get("key", "Female")

                            # PackageName: keep whatever the donor row had, and
                            # fill it in ONLY when the donor left it NULL. The
                            # clone is renamed, so a NULL here would resolve off
                            # a name that has no assets. Applies to the juvenile
                            # too - MDDeinosuchus's juvenile carries
                            # Dimetrodon_Juvenile where vanilla Dimetrodon's is
                            # NULL.
                            if "PackageName" in row_dict and not row_dict.get("PackageName"):
                                filled = donor_packages.get(m_key)
                                if filled:
                                    row_dict["PackageName"] = filled
                                else:
                                    report.setdefault("warnings", []).append(
                                        f"{m.get('target_name')}: donor has no {m_key} asset "
                                        f"package and none could be derived; PackageName left "
                                        f"NULL. The model will not resolve in game."
                                    )

                            if m_key == "Juvenile":
                                # Animations deliberately left as the donor had
                                # them (NULL in every observed case). A NULL
                                # AnimationPackageNameOverride falls back to this
                                # set's own PackageName, which is now filled.
                                pass
                            elif "AnimationPackageNameOverride" in row_dict:
                                if donor_female_package:
                                    row_dict["AnimationPackageNameOverride"] = donor_female_package
                                elif not row_dict.get("AnimationPackageNameOverride"):
                                    report.setdefault("warnings", []).append(
                                        f"{m.get('target_name')}: could not determine the donor's "
                                        f"female animation package; AnimationPackageNameOverride "
                                        f"left as-is. Animations may not resolve in game."
                                    )



                        row_overrides = fdb_overrides.get(tbl_name, {})
                        for k, v in row_overrides.items():
                            if k in row_dict:
                                row_dict[k] = v

                        # Tables without a declared PK are relationship sets,
                        # not one-row-per-species tables. Deduplicating them by
                        # SpeciesID collapsed AmbushAttackData's 226 prey rows
                        # and SpeciesCohabitation to a single row. Use the real
                        # PK when present, otherwise the complete transformed
                        # row is its identity.
                        pk_val = ((tbl_name,) + tuple(row_dict[c] for c in pk_cols)
                                  if pk_cols else
                                  (tbl_name,) + tuple(row_dict[c] for c in cols))

                        if pk_val not in seen_pks:
                            seen_pks.add(pk_val)
                            new_rows.append([row_dict[c] for c in cols])


            elif has_gen_id:
                cur_src.execute(f'SELECT * FROM "{tbl_name}" WHERE "GeneticSpeciesID" = ?', (src_genetic_id,))
                rows = cur_src.fetchall()
                for row in rows:
                    row_dict = dict(zip(cols, row))
                    row_dict["GeneticSpeciesID"] = new_genetic_id

                    for ident_col, ident_space in ident_cols:
                        if ident_col == "GeneticSpeciesID":
                            continue
                        value = row_dict.get(ident_col)
                        if ident_space == "genetic" and value == src_genetic_id:
                            row_dict[ident_col] = new_genetic_id
                        elif ident_space == "species" and value in member_id_map:
                            row_dict[ident_col] = member_id_map[value]

                    if "Name" in row_dict: row_dict["Name"] = new_species
                    if "SpeciesName" in row_dict: row_dict["SpeciesName"] = new_species
                    if "Species" in row_dict: row_dict["Species"] = new_species
                    if "EnumName" in row_dict: row_dict["EnumName"] = new_species

                    row_overrides = fdb_overrides.get(tbl_name, {})
                    for k, v in row_overrides.items():
                        if k in row_dict:
                            row_dict[k] = v

                    new_rows.append([row_dict[c] for c in cols])

            elif (has_name or has_sp_name or has_enum):
                name_col = "Name" if has_name else ("SpeciesName" if "SpeciesName" in cols else ("Species" if "Species" in cols else "EnumName"))
                for m in resolved_members:
                    cur_src.execute(f'SELECT * FROM "{tbl_name}" WHERE "{name_col}" = ?', (m["src_name"],))
                    rows = cur_src.fetchall()
                    for row in rows:
                        row_dict = dict(zip(cols, row))
                        row_dict[name_col] = m["target_name"]

                        row_overrides = fdb_overrides.get(tbl_name, {})
                        for k, v in row_overrides.items():
                            if k in row_dict:
                                row_dict[k] = v

                        new_rows.append([row_dict[c] for c in cols])

            # Clone reverse/secondary relationships where the donor appears
            # only in a non-primary identity column. This keeps entries such
            # as vanilla predator -> new prey and other species -> new
            # cohabitation partner. Rows already handled above deduplicate on
            # their real PK or full transformed contents.
            secondary_idents = [
                (col, space) for col, space in ident_cols
                if col not in ("SpeciesID", "GeneticSpeciesID")
            ]
            if secondary_idents:
                clauses, params = [], []
                for ident_col, ident_space in secondary_idents:
                    if ident_space == "genetic":
                        clauses.append(f'"{ident_col}" = ?')
                        params.append(src_genetic_id)
                    elif src_sids:
                        marks = ",".join("?" for _ in src_sids)
                        clauses.append(f'"{ident_col}" IN ({marks})')
                        params.extend(src_sids)
                if clauses:
                    cur_src.execute(
                        f'SELECT * FROM "{tbl_name}" WHERE ' + " OR ".join(clauses),
                        params)
                    for row in cur_src.fetchall():
                        row_dict = dict(zip(cols, row))
                        for ident_col, ident_space in ident_cols:
                            value = row_dict.get(ident_col)
                            if ident_space == "genetic" and value == src_genetic_id:
                                row_dict[ident_col] = new_genetic_id
                            elif ident_space == "species" and value in member_id_map:
                                row_dict[ident_col] = member_id_map[value]

                        row_overrides = fdb_overrides.get(tbl_name, {})
                        for k, v in row_overrides.items():
                            if k in row_dict:
                                row_dict[k] = v

                        pk_val = ((tbl_name,) + tuple(row_dict[c] for c in pk_cols)
                                  if pk_cols else
                                  (tbl_name,) + tuple(row_dict[c] for c in cols))
                        if pk_val not in seen_pks:
                            seen_pks.add(pk_val)
                            new_rows.append([row_dict[c] for c in cols])

            if new_rows:
                placeholders = ", ".join(["?"] * len(cols))
                col_list = ", ".join([f'"{c}"' for c in cols])
                insert_sql = f'INSERT INTO "{tbl_name}" ({col_list}) VALUES ({placeholders})'
                cur_dst.executemany(insert_sql, new_rows)
                written_summary[tbl_name] = len(new_rows)

        con_dst.commit()
        written_summary["_resolved_members"] = resolved_members
        report.setdefault("tables", {}).update(written_summary)
        return written_summary

    finally:
        con_src.close()
        con_dst.close()




def clone_expeditions_fdb(source_exp_fdb, target_exp_fdb, donor_species, new_species,
                         new_species_id, new_genetic_id, custom_digsite=False,
                         fdb_overrides=None, report=None, resolved_members=None):
    """Clone expedition FDB tables (Genomes, Fossils, DigSiteFossils, Tasks, DigSites).

    If `custom_digsite` is False (default):
        Attaches the new species fossil directly to the donor species' base formation(s)
        without creating a new dig site location.
    If `custom_digsite` is True:
        Creates a new custom dig site location ({new_species}Formation) and task.
    """
    if report is None:
        report = {}
    fdb_overrides = fdb_overrides or {}

    if not os.path.isfile(source_exp_fdb):
        report.setdefault("warnings", []).append(f"Expeditions source FDB not found: {source_exp_fdb}")
        return {}

    con_src = sqlite3.connect(f"file:{source_exp_fdb}?mode=ro", uri=True)
    con_dst = sqlite3.connect(target_exp_fdb)

    try:
        cur_src = con_src.cursor()
        cur_dst = con_dst.cursor()

        cur_src.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
        tables = [r for r in cur_src.fetchall() if not r[0].startswith("sqlite_")]
        for tbl_name, create_sql in tables:
            cur_dst.execute(create_sql)

        written_summary = {}

        # 1. Genomes (clones all family member setups)
        cur_src.execute('PRAGMA table_info("Genomes")')
        gcols = [r[1] for r in cur_src.fetchall()]
        new_grows = []

        if resolved_members:
            for rm in resolved_members:
                cur_src.execute('SELECT * FROM "Genomes" WHERE SpeciesID = ? OR GenomeID = ?', (rm["src_sid"], rm["src_name"]))
                grows = cur_src.fetchall()
                if not grows and rm["key"] == "Female":
                    cur_src.execute('SELECT * FROM "Genomes" WHERE GenomeID = ?', (donor_species,))
                    grows = cur_src.fetchall()
                for grow in grows:
                    gdict = dict(zip(gcols, grow))
                    gdict["GenomeID"] = rm["target_name"]
                    if "SpeciesID" in gdict:
                        gdict["SpeciesID"] = rm["target_sid"]
                    if "IDB_Genus" in gdict:
                        gdict["IDB_Genus"] = f"Genus_{new_species}"
                    for k, v in fdb_overrides.get("Genomes", {}).items():
                        if k in gdict:
                            gdict[k] = v
                    new_grows.append([gdict[c] for c in gcols])
        else:
            cur_src.execute('SELECT * FROM "Genomes" WHERE GenomeID = ? OR SpeciesID = ?', (donor_species, new_species_id))
            grows = cur_src.fetchall()
            if not grows:
                cur_src.execute('SELECT * FROM "Genomes" WHERE GenomeID = ?', (donor_species,))
                grows = cur_src.fetchall()

            for grow in grows:
                gdict = dict(zip(gcols, grow))
                gdict["GenomeID"] = new_species
                if "SpeciesID" in gdict:
                    gdict["SpeciesID"] = new_species_id
                if "IDB_Genus" in gdict:
                    gdict["IDB_Genus"] = f"Genus_{new_species}"
                for k, v in fdb_overrides.get("Genomes", {}).items():
                    if k in gdict:
                        gdict[k] = v
                new_grows.append([gdict[c] for c in gcols])


        if new_grows:
            placeholders = ", ".join(["?"] * len(gcols))
            col_list = ", ".join([f'"{c}"' for c in gcols])
            cur_dst.executemany(f'INSERT INTO "Genomes" ({col_list}) VALUES ({placeholders})', new_grows)
            written_summary["Genomes"] = len(new_grows)


        # 2. Fossils & FossilsRebirth
        donor_fossil_id = f"DNA_{donor_species}"
        new_fossil_id = f"DNA_{new_species}"

        for ftable in ["Fossils", "FossilsRebirth"]:
            cur_src.execute(f'SELECT name FROM sqlite_master WHERE type="table" AND name="{ftable}"')
            if not cur_src.fetchone():
                continue
            cur_src.execute(f'PRAGMA table_info("{ftable}")')
            fcols = [r[1] for r in cur_src.fetchall()]
            cur_src.execute(f'SELECT * FROM "{ftable}" WHERE GenomeID = ? OR FossilID = ?', (donor_species, donor_fossil_id))
            frows = cur_src.fetchall()
            new_frows = []
            for frow in frows:
                fdict = dict(zip(fcols, frow))
                fdict["FossilID"] = new_fossil_id
                fdict["GenomeID"] = new_species
                if "TechTreeRewardID" in fdict and fdict["TechTreeRewardID"]:
                    fdict["TechTreeRewardID"] = f"TechTree_{new_species}"
                for k, v in fdb_overrides.get(ftable, {}).items():
                    if k in fdict:
                        fdict[k] = v
                new_frows.append([fdict[c] for c in fcols])

            if new_frows:
                placeholders = ", ".join(["?"] * len(fcols))
                col_list = ", ".join([f'"{c}"' for c in fcols])
                cur_dst.executemany(f'INSERT INTO "{ftable}" ({col_list}) VALUES ({placeholders})', new_frows)
                written_summary[ftable] = len(new_frows)

        # 3. DigSiteFossils, DigSiteFossilsRebirth, DigSiteFossilsChallenge
        donor_sites = set()
        for dstable in ["DigSiteFossils", "DigSiteFossilsRebirth", "DigSiteFossilsChallenge"]:
            cur_src.execute(f'SELECT name FROM sqlite_master WHERE type="table" AND name="{dstable}"')
            if not cur_src.fetchone():
                continue
            cur_src.execute(f'PRAGMA table_info("{dstable}")')
            dscols = [r[1] for r in cur_src.fetchall()]
            cur_src.execute(f'SELECT * FROM "{dstable}" WHERE FossilID = ?', (donor_fossil_id,))
            dsrows = cur_src.fetchall()
            new_dsrows = []
            for dsrow in dsrows:
                dsdict = dict(zip(dscols, dsrow))
                donor_sites.add(dsdict.get("SiteID"))
                dsdict["FossilID"] = new_fossil_id
                if custom_digsite:
                    dsdict["SiteID"] = f"{new_species}Formation"
                for k, v in fdb_overrides.get(dstable, {}).items():
                    if k in dsdict:
                        dsdict[k] = v
                new_dsrows.append([dsdict[c] for c in dscols])

            if new_dsrows:
                placeholders = ", ".join(["?"] * len(dscols))
                col_list = ", ".join([f'"{c}"' for c in dscols])
                cur_dst.executemany(f'INSERT INTO "{dstable}" ({col_list}) VALUES ({placeholders})', new_dsrows)
                written_summary[dstable] = len(new_dsrows)

        # 4. If custom_digsite is True, clone DigSites & Tasks for custom location
        if custom_digsite and donor_sites:
            first_donor_site = sorted(list(donor_sites))[0]
            new_site_id = f"{new_species}Formation"
            new_task_id = new_species_id * 100 + 11
            new_location_id = new_species_id * 100 + 11

            for s_tbl in ["DigSites", "DigSitesRebirth"]:
                cur_src.execute(f'SELECT name FROM sqlite_master WHERE type="table" AND name="{s_tbl}"')
                if not cur_src.fetchone():
                    continue
                cur_src.execute(f'PRAGMA table_info("{s_tbl}")')
                scols = [r[1] for r in cur_src.fetchall()]
                cur_src.execute(f'SELECT * FROM "{s_tbl}" WHERE SiteID = ?', (first_donor_site,))
                srow = cur_src.fetchone()
                if srow:
                    sdict = dict(zip(scols, srow))
                    sdict["SiteID"] = new_site_id
                    if "LocationID" in sdict:
                        sdict["LocationID"] = new_location_id
                    if "TaskID" in sdict:
                        old_task_id = sdict["TaskID"]
                        sdict["TaskID"] = new_task_id
                        cur_src.execute('PRAGMA table_info("Tasks")')
                        tcols = [r[1] for r in cur_src.fetchall()]
                        cur_src.execute('SELECT * FROM "Tasks" WHERE ID = ?', (old_task_id,))
                        trow = cur_src.fetchone()
                        if trow:
                            tdict = dict(zip(tcols, trow))
                            tdict["ID"] = new_task_id
                            placeholders = ", ".join(["?"] * len(tcols))
                            col_list = ", ".join([f'"{c}"' for c in tcols])
                            cur_dst.execute(f'INSERT INTO "Tasks" ({col_list}) VALUES ({placeholders})', [tdict[c] for c in tcols])
                            written_summary["Tasks"] = 1

                    placeholders = ", ".join(["?"] * len(scols))
                    col_list = ", ".join([f'"{c}"' for c in scols])
                    cur_dst.execute(f'INSERT INTO "{s_tbl}" ({col_list}) VALUES ({placeholders})', [sdict[c] for c in scols])
                    written_summary[s_tbl] = 1

        con_dst.commit()
        report.setdefault("exp_tables", {}).update(written_summary)
        return written_summary
    finally:
        con_src.close()
        con_dst.close()



def ensure_table(fdb_path, table_name):
    """Ensure table exists in target FDB, copying schema from c0dinosaurs.fdb if needed."""
    con_dst = sqlite3.connect(fdb_path)
    cur_dst = con_dst.cursor()
    cur_dst.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,))
    if cur_dst.fetchone():
        con_dst.close()
        return True

    c0_path = os.path.join(BASE_DIR, "extracted_fdbs", "c0dinosaurs.fdb")
    if not os.path.isfile(c0_path):
        con_dst.close()
        return False

    con_src = sqlite3.connect(f"file:{c0_path}?mode=ro", uri=True)
    cur_src = con_src.cursor()
    cur_src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,))
    row = cur_src.fetchone()
    con_src.close()

    if not row or not row[0]:
        con_dst.close()
        return False

    cur_dst.execute(row[0])
    con_dst.commit()
    con_dst.close()
    return True


def read_table(fdb_path, table_name):
    """Read columns and rows from an FDB table."""
    if not os.path.isfile(fdb_path):
        return None
    con = sqlite3.connect(f"file:{fdb_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,))
        if not cur.fetchone():
            return None

        cur.execute(f'SELECT * FROM "{table_name}"')
        cols = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        return {"columns": cols, "rows": rows}
    finally:
        con.close()


def write_table_rows(fdb_path, table_name, columns, rows, report=None):
    """Replace all rows in `table_name` within `fdb_path`."""
    if report is None:
        report = {}
    if not os.path.isfile(fdb_path):
        raise FileNotFoundError(f"Target database file missing: {fdb_path}")

    ensure_table(fdb_path, table_name)
    con = sqlite3.connect(fdb_path)
    try:
        cur = con.cursor()
        cur.execute(f'DELETE FROM "{table_name}"')
        if rows:
            placeholders = ", ".join(["?"] * len(columns))
            col_list = ", ".join([f'"{c}"' for c in columns])
            insert_sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({placeholders})'
            cur.executemany(insert_sql, rows)
        con.commit()
        report.setdefault("tables", {})[table_name] = len(rows)
        return len(rows)
    finally:
        con.close()


def validate_cosmetics(fdb_path):
    """Validate cosmetic variant/pattern index pointers in species database."""
    problems = []
    con = sqlite3.connect(f"file:{fdb_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing = {r[0] for r in cur.fetchall()}
        needed = {"SpeciesCosmeticSets", "SpeciesCosmeticVariants", "SpeciesCosmeticPatterns"}
        if not needed.issubset(existing):
            return problems

        # Real column names (confirmed against the game schema - PRAGMA
        # table_info on c0dinosaurs.fdb): SpeciesCosmeticSets keys on
        # (SpeciesID, SetID) and its counts are NumVariants / NumPatterns.
        # The child tables key on the SAME (SpeciesID, SetID) pair, not a
        # standalone CosmeticSetID - a set from one species and a set from
        # another can both be SetID 1, so both columns are needed to match.
        cur.execute('SELECT SpeciesID, SetID, Prefab, NumVariants, NumPatterns '
                   'FROM "SpeciesCosmeticSets"')
        sets = cur.fetchall()

        seen_prefabs = {}
        for sp_id, set_id, prefab, v_count, p_count in sets:
            if prefab is not None:
                seen_prefabs.setdefault(prefab, []).append((sp_id, set_id))

            cur.execute('SELECT COUNT(*) FROM "SpeciesCosmeticVariants" '
                       'WHERE SpeciesID=? AND SetID=?', (sp_id, set_id))
            v_actual = cur.fetchone()[0]
            if v_count is not None and v_actual != v_count:
                problems.append(
                    f"Species {sp_id} set {set_id}: NumVariants={v_count} but "
                    f"found {v_actual} row(s) in SpeciesCosmeticVariants.")

            cur.execute('SELECT COUNT(*) FROM "SpeciesCosmeticPatterns" '
                       'WHERE SpeciesID=? AND SetID=?', (sp_id, set_id))
            p_actual = cur.fetchone()[0]
            if p_count is not None and p_actual != p_count:
                problems.append(
                    f"Species {sp_id} set {set_id}: NumPatterns={p_count} but "
                    f"found {p_actual} row(s) in SpeciesCosmeticPatterns.")

        # Prefab is UNIQUE table-wide - this is the exact constraint that
        # crashed generation before the SetID-based naming fix, so catching a
        # reintroduced clash here (e.g. from a manual edit) is worth the cost
        # of one more pass over rows already in memory.
        for prefab, owners in seen_prefabs.items():
            if len(owners) > 1:
                problems.append(
                    f"Prefab {prefab!r} is UNIQUE but used by {owners}")

        return problems
    finally:
        con.close()


def add_digsite(exp_fdb, site_row, fossil_rows, mirror=True, report=None):
    """Add a dig site and fossil yield rows to an expeditions FDB database."""
    if report is None:
        report = {}

    con = sqlite3.connect(exp_fdb)
    written = {}
    try:
        cur = con.cursor()

        # Insert DigSite
        cur.execute('PRAGMA table_info("DigSites")')
        site_cols = [r[1] for r in cur.fetchall()]
        s_vals = [site_row.get(c) for c in site_cols]
        placeholders = ", ".join(["?"] * len(site_cols))
        col_list = ", ".join([f'"{c}"' for c in site_cols])
        cur.execute(f'DELETE FROM "DigSites" WHERE DigSiteID = ?', (site_row.get("DigSiteID"),))
        cur.execute(f'INSERT INTO "DigSites" ({col_list}) VALUES ({placeholders})', s_vals)
        written["DigSites"] = 1

        # Insert Fossils
        if fossil_rows:
            cur.execute('PRAGMA table_info("Fossils")')
            f_cols = [r[1] for r in cur.fetchall()]
            f_rows = [[fr.get(c) for c in f_cols] for fr in fossil_rows]
            placeholders = ", ".join(["?"] * len(f_cols))
            col_list = ", ".join([f'"{c}"' for c in f_cols])

            for fr in fossil_rows:
                if fr.get("FossilID"):
                    cur.execute('DELETE FROM "Fossils" WHERE FossilID = ?', (fr.get("FossilID"),))

            cur.executemany(f'INSERT INTO "Fossils" ({col_list}) VALUES ({placeholders})', f_rows)
            written["Fossils"] = len(fossil_rows)

        con.commit()
        report.setdefault("exp_tables", {}).update(written)
        return written
    finally:
        con.close()


def list_generated_mods():
    """List all generated mod details inside Generated directory."""
    gen_dir = os.path.join(BASE_DIR, "Generated")
    if not os.path.isdir(gen_dir):
        return []
    mods = []
    for item in os.listdir(gen_dir):
        fp = os.path.join(gen_dir, item)
        if os.path.isdir(fp) and not item.startswith(".") and item.lower() != "logs":
            main_dir = os.path.join(fp, "Main")
            dino_fdb = os.path.join(main_dir, f"{item.lower()}dinosaurs.fdb")
            exp_fdb = os.path.join(main_dir, f"{item.lower()}expeditions.fdb")

            if not os.path.isfile(dino_fdb) and os.path.isdir(main_dir):
                for f in os.listdir(main_dir):
                    if f.endswith("dinosaurs.fdb"):
                        dino_fdb = os.path.join(main_dir, f)
                    elif f.endswith("expeditions.fdb"):
                        exp_fdb = os.path.join(main_dir, f)

            final_dino = dino_fdb if (os.path.isfile(dino_fdb) if dino_fdb else False) else None
            final_exp = exp_fdb if (os.path.isfile(exp_fdb) if exp_fdb else False) else None

            if final_dino or final_exp:
                mods.append({
                    "name": item,
                    "path": fp,
                    "fdb": final_dino,
                    "dino_fdb": final_dino,
                    "exp_fdb": final_exp
                })
    return sorted(mods, key=lambda x: x["name"])



def allocate_species_ids(species_configs, fdb_path=None, floor=DEFAULT_ID_FLOOR):
    """Ensure every species in species_configs has a valid species_id and genetic_id.
    Auto-assigns unique random IDs (3000 to 999999) if missing.
    """
    import random

    c0_path = os.path.join(BASE_DIR, "extracted_fdbs", "c0dinosaurs.fdb")
    if fdb_path is None:
        fdb_path = c0_path if os.path.isfile(c0_path) else None

    used_sids = set()
    used_gids = set()

    if fdb_path and os.path.isfile(fdb_path):
        con = sqlite3.connect(f"file:{fdb_path}?mode=ro", uri=True)
        try:
            cur = con.cursor()
            for r in cur.execute("SELECT SpeciesID, GeneticSpeciesID FROM Species").fetchall():
                if r[0]: used_sids.add(int(r[0]))
                if r[1]: used_gids.add(int(r[1]))
        finally:
            con.close()

    for config in species_configs:
        sid = config.get("species_id")
        gid = config.get("genetic_id")
        if sid:
            try:
                used_sids.add(int(sid))
            except (ValueError, TypeError):
                pass
        if gid:
            try:
                used_gids.add(int(gid))
            except (ValueError, TypeError):
                pass

    for config in species_configs:
        sid = config.get("species_id")
        if sid is None or sid == "" or str(sid).strip() == "":
            candidate = random.randint(floor, 999999)
            while candidate in used_sids or candidate in RESERVED_SPECIES_IDS:
                candidate = random.randint(floor, 999999)
            config["species_id"] = candidate
            used_sids.add(candidate)
        else:
            config["species_id"] = int(sid)

        gid = config.get("genetic_id")
        if gid is None or gid == "" or str(gid).strip() == "":
            candidate = random.randint(floor, 999999)
            while candidate in used_gids:
                candidate = random.randint(floor, 999999)
            config["genetic_id"] = candidate
            used_gids.add(candidate)
        else:
            config["genetic_id"] = int(gid)

    return species_configs

