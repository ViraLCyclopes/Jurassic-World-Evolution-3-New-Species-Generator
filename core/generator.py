import os
import re
import shutil
import uuid as uuid_mod
import sqlite3

from core.templates import (
    BASE_DIR, PREFAB_LUA, COSMETIC_LUA, PREFABDATA_LUA,
    LUADATABASE_LUA, TECHTREE_LUA, REBIRTH_TECHTREE_LUA,
    INGEN_DATABASE_LUA, DINOSAUR_MODS_TECHTREE_LUA,
    INIT_DATABASE_LUA, ICON_MOUNT_LUA, ICON_MANAGER_DATABASE_BLOCK,
    MANIFEST_XML,
    SCALE_TEMPLATE, SCALE_TEMPLATE_FALLBACK, SCALE_CONTROLLER_TEMPLATE, SCALE_REQUIRE,
    DEFAULT_SPECIES_STATS, DEFAULT_GENOMES, DEFAULT_SPECIALISATION,
    DEFAULT_EXPEDITIONS, DEFAULT_BUILDING_UPGRADES
)
from core.database import clone_fdb, clone_expeditions_fdb, ensure_table
from core.localizations import generate_species_localizations
from core.ppuipkg import (
    normalise_mod_asset_package, read_package, write_package,
)
from core.tex import (png_size, read_tex, write_tex,
                      DEFAULT_TEXEL, DEFAULT_COMPRESSION)


# --- Default (placeholder) icon set -----------------------------------------
#
# Vendored vanilla art the generator can hand a new species so it has SOMETHING
# in every icon slot until the author supplies their own. Harvested by
# `extract_ui_svgs.py`; the PNG pair was copied out of the extracted UI tree.
ICON_TEMPLATE_DIR = os.path.join(BASE_DIR, "templates", "icons")
PLACEHOLDER_SVG = os.path.join(
    ICON_TEMPLATE_DIR, "UIGameface", "img", "icons", "dinosaurSpecies",
    "Allosaurus.svg")
PLACEHOLDER_PNGS = {
    # slot: (template stem, path segment, image-name prefix)
    "small":    ("placeholder_small",    "small",    "dinosaurs_small"),
    "headshot": ("placeholder_headshot", "headshot", "dinosaurs_headshot"),
}


def _default_icon_asset_package(mod_name, slot):
    """Namespaced UI stream whose lowercase spelling keeps STATIC first."""
    return normalise_mod_asset_package(
        mod_name, f"{mod_name}_Dinosaur_{slot.capitalize()}")


def audit_ui_texture_archives(ui_dir):
    """Reject local texture streams that cobra-tools sorts before STATIC.

    This is a pre-pack safety rail for the native LoadOverlay crash diagnosed
    with ArthurianInitiative. PPUIPKG references without a local .tex are not
    checked because they may intentionally target a vanilla/external stream.
    """
    unsafe = []
    if not os.path.isdir(ui_dir):
        return
    for root, _dirs, files in os.walk(ui_dir):
        for name in files:
            if not name.lower().endswith(".tex"):
                continue
            path = os.path.join(root, name)
            info = read_tex(path) or {}
            ovs = info.get("ovs")
            if ovs and ovs < "STATIC":
                unsafe.append((os.path.relpath(path, ui_dir), ovs))
    if unsafe:
        details = "; ".join(f"{path}: ovs={ovs!r}" for path, ovs in unsafe)
        raise ValueError(
            "unsafe JWE3 UI archive order: local OVS names sorting before "
            f"STATIC would put a streamed archive first ({details}). Use a "
            "lowercase, namespaced asset_package/ovs name.")


def default_icon_name_for(sp_conf):
    """The name the GAME will ask for when it wants this species' icon.

    `components.hatchery.lua` builds `"Dinosaurs_Small_" .. sDinoIcon`, and
    `GeneLibraryManager:GetIconForGenome()` resolves sDinoIcon from
    `SpeciesCosmeticSets.DinoIcon` **falling back to the GenomeID**. DinoIcon is
    NULL in all 431 vanilla rows, so the fallback is the only path that ever
    runs and the name is simply the genome / species name.
    """
    return sp_conf.get("genome") or sp_conf.get("name") or ""


def asset_package_gender_subdir(package_name):
    """Return the generated family-member folder for an asset package.

    Match a complete suffix, never a substring: ``female`` contains ``male``,
    which previously sent every ``*_Female`` package into the Male folder.
    Optional numeric suffixes cover family variants without misclassifying a
    species whose own name happens to contain one of these words.
    """
    match = re.search(
        r"_(female|male|juvenile)(?:_\d+)?$",
        (package_name or "").lower())
    if match:
        return match.group(1).capitalize()
    return "Female"


def build_default_icon_set(out_dir, mod_name, plans, report):
    """Give every species a full placeholder icon set.

    Returns `(icon_refs, embedded_files, written)` ready to hand to
    `write_package()`:
      * `icon_refs`     - <types> entries; the .tex/.png pairs are copied out
                          beside them as real OVL entries.
      * `embedded_files` - <files> entries; SVGs are embedded byte-for-byte.

    Asset packages are namespaced per mod rather than reusing vanilla's
    `Dinosaur_Small` / `Dinosaur_Headshot` OVS names, per the project's
    namespace-everything-shared rule.
    """
    icon_refs = []
    embedded = []
    written = []
    kept_png = []

    pkg_ui_dir = os.path.join(out_dir, "UI", mod_name)

    svg_template = None
    if os.path.isfile(PLACEHOLDER_SVG):
        with open(PLACEHOLDER_SVG, "rb") as f:
            svg_template = f.read()
    else:
        report.setdefault("warnings", []).append(
            f"default icons: no placeholder SVG at {PLACEHOLDER_SVG} - "
            f"run extract_ui_svgs.py; tech-tree icons will fall back to the "
            f"donor's vanilla icon.")

    for plan in plans:
        sp_conf = plan.get("config", {})
        species = sp_conf.get("name")
        if not species:
            continue
        icon_name = default_icon_name_for(sp_conf)
        lower = icon_name.lower()

        # --- PNG portraits: referenced by <types>, shipped as .tex/.png ------
        for slot, (stem, segment, prefix) in PLACEHOLDER_PNGS.items():
            src_png = os.path.join(ICON_TEMPLATE_DIR, f"{stem}.png")
            src_tex = os.path.join(ICON_TEMPLATE_DIR, f"{stem}.png.tex")
            if not (os.path.isfile(src_png) and os.path.isfile(src_tex)):
                report.setdefault("warnings", []).append(
                    f"default icons: missing placeholder pair for '{slot}' in "
                    f"{ICON_TEMPLATE_DIR}; skipping that slot.")
                continue

            rel_dir = f"uigameface/img/dinosaurspecies/{segment}"
            base = f"{prefix}_{lower}.png"

            dest_dir = os.path.join(pkg_ui_dir, rel_dir.replace("/", os.sep))
            os.makedirs(dest_dir, exist_ok=True)
            # cobra-tools wants the pair: <name>.png.png is the image, and
            # <name>.png.tex the texture header. Both are needed or the OVL
            # packs without the texture - see the CobblestoneBlock layout.
            #
            asset_package = _default_icon_asset_package(mod_name, slot)

            # Never overwrite: once the placeholder is down, the file on disk
            # may be the author's real art. Regenerating must leave it alone.
            dest_png = os.path.join(dest_dir, base + ".png")
            dest_tex = os.path.join(dest_dir, base + ".tex")

            if os.path.exists(dest_png):
                kept_png.append(f"{rel_dir}/{base}.png")
            else:
                shutil.copyfile(src_png, dest_png)

            if os.path.exists(dest_tex):
                # Preserve the author's image/encoding choices, but migrate a
                # legacy generator-owned uppercase OVS name. Leaving it in
                # place would make the next pack crash even though the newly
                # written PPUIPKG reference is lowercase.
                current = read_tex(dest_tex) or {}
                current_ovs = current.get("ovs", "")
                safe_current = normalise_mod_asset_package(
                    mod_name, current_ovs)
                if current_ovs != safe_current:
                    size = png_size(dest_png) or png_size(src_png)
                    write_tex(
                        dest_tex,
                        size[0] if size else current.get("width", 232),
                        size[1] if size else current.get("height", 232),
                        ovs=safe_current,
                        texel=current.get("texel", DEFAULT_TEXEL),
                        compression=current.get(
                            "compression_type", DEFAULT_COMPRESSION))
                else:
                    kept_png.append(f"{rel_dir}/{base}.tex")
            else:
                # Do NOT just copy the donor .tex: its ovs="Dinosaur_Small"
                # names the VANILLA stream, while the package we emit says
                # <asset_package>Mod_Dinosaur_Small</asset_package>. The header
                # and the reference must name the same stream, so author it.
                size = png_size(dest_png) or png_size(src_png)
                donor = read_tex(src_tex) or {}
                write_tex(dest_tex,
                          size[0] if size else donor.get("width", 232),
                          size[1] if size else donor.get("height", 232),
                          ovs=asset_package,
                          texel=donor.get("texel", DEFAULT_TEXEL),
                          compression=donor.get("compression_type",
                                                DEFAULT_COMPRESSION))

            icon_refs.append((f"{rel_dir}/{base}", asset_package))
            written.append(f"UI/{mod_name}/{rel_dir}/{base}")

        # --- SVG line icon: EMBEDDED in the package, not a separate entry ----
        if svg_template and icon_name:
            embedded.append(
                (f"UIGameface/img/icons/dinosaurSpecies/{icon_name}.svg",
                 svg_template))

    report["default_icons"] = {
        "png_refs": len(icon_refs),
        "svgs_embedded": len(embedded),
        "existing_png_kept": kept_png,
        "note": "placeholder art - replace the files under UI/ with your own; "
                "regenerating will not overwrite them",
    }
    return icon_refs, embedded, written


def plan_species(config):
    """Inspect source dinosaur prefabs and construct generation plan."""
    name = config["name"]
    source = config["source"]
    cosmetics = config.get("cosmetics", {})
    variants = cosmetics.get("variants", 1)
    patterns = cosmetics.get("patterns", 1)

    donor_female_pref = config.get("donor_prefabs", {}).get("Female") or source
    has_female_suffix = donor_female_pref.lower().endswith("_female") or source.lower().endswith("_female")
    fem_target = f"{name}_Female" if has_female_suffix else name

    family_members = config.get("family_members")
    if family_members and isinstance(family_members, list) and len(family_members) > 0:
        members = []
        base_src = source[:-7] if source.endswith("_Female") else source
        for m in family_members:
            if isinstance(m, dict):
                if m.get("enabled") is False or m.get("checked") is False:
                    continue
                m_name = m.get("Name") or m.get("name") or name
                m_pref = m.get("Prefab") or m.get("prefab") or m.get("donor") or source
            elif isinstance(m, (list, tuple)) and len(m) >= 2:
                m_name, m_pref = m[0], m[1]
            else:
                m_name, m_pref = str(m), source

            # Ignore CC variants
            if "cc" in m_name.lower() or "cc" in m_pref.lower():
                continue

            has_fem = m_pref.lower().endswith("_female")
            if m_name == source or m_name == base_src or m_name == f"{base_src}_Female":
                target_prefab_name = f"{name}_Female" if has_fem else name
            elif m_name.startswith(base_src):
                suffix = m_name[len(base_src):]
                target_prefab_name = name + suffix
            elif m_name.startswith(name):
                target_prefab_name = m_name
            else:
                target_prefab_name = f"{name}_{m_name}"

            members.append((target_prefab_name, m_pref))

        if not members:
            members = [
                (fem_target, donor_female_pref),
                (f"{name}_Male", config.get("donor_prefabs", {}).get("Male") or f"{source}_Male"),
                (f"{name}_Juvenile", config.get("donor_prefabs", {}).get("Juvenile") or f"{source}_Juvenile"),
            ]
    else:
        members = [
            (fem_target, donor_female_pref),
            (f"{name}_Male", config.get("donor_prefabs", {}).get("Male") or f"{source}_Male"),
            (f"{name}_Juvenile", config.get("donor_prefabs", {}).get("Juvenile") or f"{source}_Juvenile"),
        ]

    cosmetic_plan = []
    for v in range(1, variants + 1):
        v_str = f"{v:02d}"
        cosmetic_plan.append({
            "name": f"{fem_target}_{v_str}",
            "parent": fem_target,
            "pattern_set": f"{name}_PatternSet_{v_str}",
            "variant_set": f"{name}_VariantSet_{v_str}",
        })
        cosmetic_plan.append({
            "name": f"{name}_Male_{v_str}",
            "parent": f"{name}_Male",
            "pattern_set": f"{name}_PatternSet_{v_str}",
            "variant_set": f"{name}_VariantSet_{v_str}",
        })
        cosmetic_plan.append({
            "name": f"{name}_Juvenile_{v_str}",
            "parent": f"{name}_Juvenile",
            "pattern_set": f"{name}_PatternSet_{v_str}",
            "variant_set": f"{name}_VariantSet_{v_str}",
        })



    report = {"warnings": []}
    return {
        "members": members,
        "cosmetic_plan": cosmetic_plan,
        "variants": variants,
        "patterns": patterns,
    }, report


def serialize_lua_properties(props_dict, indent=8):
    """Serialize a dictionary of property overrides into formatted Lua syntax."""
    if not props_dict:
        return ""
    ind = " " * indent
    lines = []
    for k, v in sorted(props_dict.items()):
        if isinstance(v, dict):
            v = v.get("Default")

        if v is None or v == "" or (isinstance(v, (list, tuple, dict)) and len(v) == 0):
            continue

        if isinstance(v, list):
            items_str = ", ".join(f"'{item}'" for item in v)
            lines.append(f"{ind}{k} = {{\n{ind}    Default = {{ {items_str} }}\n{ind}}},")
        elif isinstance(v, bool):
            lines.append(f"{ind}{k} = {{\n{ind}    Default = {str(v).lower()}\n{ind}}},")
        elif isinstance(v, (int, float)):
            lines.append(f"{ind}{k} = {{\n{ind}    Default = {v}\n{ind}}},")
        elif isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                continue
            lines.append(f"{ind}{k} = {{\n{ind}    Default = '{v_str}'\n{ind}}},")
        else:
            lines.append(f"{ind}{k} = {{\n{ind}    Default = '{v}'\n{ind}}},")
    return "\n".join(lines)


AP_INHERITANCE_MODES = ("Append", "Replace", "Inherit")
AP_INHERITANCE_DEFAULT = "Append"

# '__inheritance' entries are merge DIRECTIVES, not package names - filter them
# out of any user-supplied list before re-emitting it.
_AP_DIRECTIVE_WORDS = {"append", "overwrite", "modify", "prepend", "replace"}


def _resolve_ap_inheritance(config, species_config, member_key, override_dict):
    """Pick the AssetPackages inheritance mode for one family member.

    Resolution order, most specific first: the member's own prefab override,
    then the species setting (either a bare string for the whole family or a
    dict keyed by member), then the mod-wide default, then 'Append'.
    """
    def _norm(v):
        if not v:
            return None
        v = str(v).strip().capitalize()
        return v if v in AP_INHERITANCE_MODES else None

    # 'Adult' and 'Female' name the same member depending on whether the donor's
    # female prefab carries a suffix, so either key may be used to address it.
    keys = [member_key]
    if member_key == "Adult":
        keys.append("Female")
    elif member_key == "Female":
        keys.append("Adult")

    mode = _norm((override_dict or {}).get("AssetPackageInheritance"))
    if mode:
        return mode

    sp = (species_config or {}).get("asset_package_inheritance")
    if isinstance(sp, dict):
        for k in keys + ["Default"]:
            mode = _norm(sp.get(k))
            if mode:
                return mode
    else:
        mode = _norm(sp)
        if mode:
            return mode

    return _norm((config or {}).get("asset_package_inheritance")) or AP_INHERITANCE_DEFAULT


def _asset_packages_block(prefab_name, override, mode, indent=8):
    """Render an AssetPackages property block for a base prefab stub.

    WHY THIS EXISTS: a child prefab's AssetPackages list REPLACES its parent's
    unless it carries an __inheritance directive. A stub that names only its own
    package therefore drops the donor's model and animation packages, and
    nothing reports it - the same silent class as inheriting a missing prefab.
    The dump leans heavily on the directive: 3,395 'Append' against 1,967
    'Overwrite'.

      Append   keep the parent's packages and add ours (default, safe)
      Replace  ours only - the donor's are dropped
      Inherit  emit nothing and ride entirely on the parent
    """
    if mode == "Inherit":
        return ""

    if isinstance(override, dict):
        override = override.get("Default")
    if isinstance(override, str):
        names = [override]
    elif isinstance(override, (list, tuple)):
        names = [str(n) for n in override
                 if str(n).strip().lower() not in _AP_DIRECTIVE_WORDS]
    else:
        names = []
    if not names:
        names = [prefab_name]

    ind = " " * indent
    lines = [f"{ind}AssetPackages = {{", f"{ind}    Default = {{"]
    lines += [f"{ind}        '{n}'," for n in names]
    if mode == "Append":
        lines.append(f"{ind}        __inheritance = 'Append'")
    else:
        lines[-1] = lines[-1].rstrip(",")
    lines += [f"{ind}    }}", f"{ind}}},"]
    return "\n".join(lines)


def _replace_lua_table(src, var_name, body):
    """Swap the contents of `<var> = { ... }` for a generated body."""
    pat = re.compile(re.escape(var_name) + r"\s*=\s*\{.*?\n\}", re.S)
    return pat.sub(f"{var_name} = {{\n{body}\n}}", src)


def _cosmetic_plan_from_fdb(dst_dino_fdb, plan):
    """Rebuild a plan's cosmetic Lua stub list from the ALREADY-CLONED FDB rows,
    instead of a fixed per-config count.

    WHY THIS EXISTS: plan_species() (called before the FDB exists) has no way
    to know how many cosmetic sets a donor actually has, so an earlier version
    generated a fixed `variants`-count worth of stubs (default 1) per member.
    A donor can have far more - Velociraptor has 16 across its 3 members - and
    clone_fdb() (core/database.py) already writes ALL of them into
    SpeciesCosmeticSets with correct, collision-free Prefab names keyed by
    SetID. The result was SpeciesCosmeticSets.Prefab pointing at 13 .lua files
    that were never written - a SILENT dangling reference (the model loads,
    the extra skins just do not exist), the same class of bug fixed once
    already for the same table (see SPECIES_GEN_HANDOFF.md).

    Reading the just-cloned FDB back means the .lua files and the FDB CANNOT
    disagree, because both are now driven by the same rows.
    """
    resolved_members = plan.get("_resolved_members") or []
    if not resolved_members:
        return plan.get("cosmetic_plan", [])

    sid_to_member = {m["target_sid"]: m for m in resolved_members}
    target_sids = list(sid_to_member.keys())
    if not target_sids:
        return []

    con = sqlite3.connect(f"file:{dst_dino_fdb}?mode=ro", uri=True)
    try:
        cols_info = con.execute('PRAGMA table_info("SpeciesCosmeticSets")').fetchall()
        cols = [c[1] for c in cols_info]
        if not cols or not {"SpeciesID", "SetID", "Prefab"}.issubset(cols):
            return []
        ph = ",".join("?" * len(target_sids))
        rows = con.execute(
            f'SELECT SpeciesID, SetID, Prefab FROM "SpeciesCosmeticSets" '
            f'WHERE SpeciesID IN ({ph})', target_sids).fetchall()
    finally:
        con.close()

    new_name = plan["config"]["name"]
    cosmetic_plan = []
    for sid, set_id, prefab in rows:
        member = sid_to_member.get(sid)
        if member is None or not prefab:
            continue
        nn = f"{int(set_id or 1):02d}"
        cosmetic_plan.append({
            # the exact name the FDB references - no drift possible
            "name": prefab,
            # the PREFAB to inherit, never target_name: they diverge for a
            # donor whose female prefab is suffixed (Dimetrodon), and an
            # inherited prefab that does not exist renders nothing, silently.
            "parent": member["target_prefab"],
            "pattern_set": f"{new_name}_PatternSet_{nn}",
            "variant_set": f"{new_name}_VariantSet_{nn}",
        })
    return cosmetic_plan


def normalise_scale_range(value, fallback=1.0):
    """Coerce one `scales` entry into a `(min, max)` pair.

    Accepts a bare number (fixed size, `min == max`, which is how every mod
    generated before size variation existed is expressed), a two-element
    list/tuple, or a dict with min/max keys. Planet Zoo's own bands are the
    reference shape: `SizeData.MinScaleFemale` / `MaxScaleFemale` etc.
    """
    lo = hi = None
    if isinstance(value, dict):
        for lo_key in ("min", "fMin", "Min", "MinScale"):
            if value.get(lo_key) is not None:
                lo = value[lo_key]
                break
        for hi_key in ("max", "fMax", "Max", "MaxScale"):
            if value.get(hi_key) is not None:
                hi = value[hi_key]
                break
        # A dict carrying only one bound is a fixed size, not half a band.
        if lo is None:
            lo = hi
        if hi is None:
            hi = lo
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        lo, hi = value[0], value[1]
    else:
        lo = hi = value

    try:
        lo = float(lo)
        hi = float(hi)
    except (ValueError, TypeError):
        return None

    if hi < lo:
        lo, hi = hi, lo
    return (lo, hi)


def write_scale_module(main_dir, mod_name, scaling_map, report):
    """Write `<ModName>ScaleData.lua` and `Components.<ModName>ScaleController.lua`."""
    if not scaling_map:
        return None

    path_primary = SCALE_TEMPLATE
    path_fallback = SCALE_TEMPLATE_FALLBACK
    tmpl_path = path_primary if os.path.isfile(path_primary) else path_fallback

    if not os.path.isfile(tmpl_path):
        report.setdefault("warnings", []).append(
            f"Scale template missing at both {path_primary} and {path_fallback}")
        return None

    with open(tmpl_path, "r", encoding="utf-8") as f:
        tmpl = f.read()

    by_id = {}
    by_name = {}
    for k, v in scaling_map.items():
        rng = normalise_scale_range(v)
        if rng is None:
            continue
        try:
            by_id[int(k)] = rng
        except (ValueError, TypeError):
            by_name[str(k)] = rng

    def _band(rng):
        return "{{ fMin = {0}, fMax = {1} }}".format(_lua_num(rng[0]), _lua_num(rng[1]))

    id_lines = [f"        [{sid}] = {_band(rng)}," for sid, rng in sorted(by_id.items())]
    name_lines = [f'        ["{sname}"] = {_band(rng)},'
                  for sname, rng in sorted(by_name.items())]

    out = _replace_lua_table(tmpl, "MDDeinosuchusScaleData.tRenderScalesBySpeciesID", "\n".join(id_lines))
    out = _replace_lua_table(out, "MDDeinosuchusScaleData.tRenderScalesByGenome", "\n".join(name_lines))
    out = _apply_scale_mod_name(out, mod_name, by_name)

    file_name = f"database.{mod_name.lower()}scaledata.lua"
    out_path = os.path.join(main_dir, file_name)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out)

    written = [file_name]

    # The controller is the lifecycle half: without it nothing re-applies
    # the scale and nothing is written into the save.
    if os.path.isfile(SCALE_CONTROLLER_TEMPLATE):
        with open(SCALE_CONTROLLER_TEMPLATE, "r", encoding="utf-8") as f:
            ctrl = f.read()
        ctrl = _apply_scale_mod_name(ctrl, mod_name, by_name)
        ctrl_name = f"components.{mod_name.lower()}scalecontroller.lua"
        with open(os.path.join(main_dir, ctrl_name), "w", encoding="utf-8") as f:
            f.write(ctrl)
        written.append(ctrl_name)
    else:
        report.setdefault("warnings", []).append(
            "Scale controller template missing at "
            f"{SCALE_CONTROLLER_TEMPLATE}; sizes will not persist across a save.")

    report["scaling"] = {
        "by_species_id": {k: list(v) for k, v in by_id.items()},
        "by_name": {k: list(v) for k, v in by_name.items()},
        "files": written,
    }
    return file_name


def _lua_num(value):
    """Render a float without Python's trailing-zero noise."""
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _apply_scale_mod_name(src, mod_name, by_name):
    """Rename the template's Deinosuchus placeholders to this mod.

    The lowercase pass matters: ACSE exposes a component manager as
    `api.<lowercased component name>`, and the controller is required by the
    lowercase module path, so `MDDeinosuchus` alone is not enough.
    """
    src = re.sub(r"MDDeinosuchusScaleData", f"{mod_name}ScaleData", src)
    src = re.sub(r"MDDeinosuchus", mod_name, src)
    src = re.sub(r"mddeinosuchus", mod_name.lower(), src)
    for sname in sorted(by_name.keys()):
        base_sname = sname.split("_")[0]
        src = re.sub(r"Deinodoots", f"{base_sname}s", src)
        src = re.sub(r"Deinodoot", base_sname, src)
    return src


def audit_asset_packages(main_dir, init_dir, report):
    """Audit referenced vs defined asset package files."""
    referenced = set()
    pat = re.compile(r"""AssetPackageLoader\s*=\s*\{\s*PackageNames\s*=\s*\{\s*['"]([^'"]+)['"]""")

    # The species stubs are built on the PROPERTY form - the dinosaur's main
    # Properties block, where AssetPackages sits alongside ModelName,
    # MotionGraphName and MaterialLayersName. This audit previously matched only
    # the AssetPackageLoader component, which the stubs never emit, so every
    # generated package reference went unchecked and the audit always passed.
    # '__inheritance' entries are merge directives, not package names (§3e).
    prop_pat = re.compile(r"AssetPackages\s*=\s*\{\s*Default\s*=\s*\{(.*?)\}", re.S)
    name_pat = re.compile(r"""['"]([^'"]+)['"]""")

    for root, _, files in os.walk(main_dir):
        for file in files:
            if not file.endswith(".lua"):
                continue
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                src = f.read()
            for line in src.splitlines():
                m = pat.search(line)
                if m:
                    referenced.add(m.group(1))
            for m in prop_pat.finditer(src):
                for name in name_pat.findall(m.group(1)):
                    if name.strip().lower() not in _AP_DIRECTIVE_WORDS:
                        referenced.add(name)

    existing = set()
    if os.path.isdir(init_dir):
        for file in os.listdir(init_dir):
            if file.endswith(".assetpkg"):
                existing.add(os.path.splitext(file)[0])

    # .assetpkg files are written lowercased while a prefab references its
    # package in CamelCase ('Deinodoot_Female' vs deinodoot_female.assetpkg),
    # so this comparison has to be case-insensitive or every package reads as
    # missing.
    existing_lower = {e.lower() for e in existing}
    missing = sorted(r for r in referenced if r.lower() not in existing_lower)
    if missing:
        report.setdefault("warnings", []).append(
            f"Asset packages referenced in Lua but missing .assetpkg: {missing}")

    return referenced, existing


def write_scaffold(out_dir, mod_name, plans, config, report):
    """Write prefab Luas, cosmetic Luas, database manifests, and AssetPackages."""
    main_dir = os.path.join(out_dir, "Main")
    init_dir = os.path.join(out_dir, "Init")
    os.makedirs(main_dir, exist_ok=True)
    os.makedirs(init_dir, exist_ok=True)
    written = []

    all_prefab_names = []
    ui_rewards = []
    nodes = []
    rebirth_rewards = []
    ingen_data = []
    ingen_techtree = []
    ingen_genomes = []

    for plan in plans:
        new_name = plan["config"]["name"]
        members = plan["members"]
        cosmetic_plan = plan.get("cosmetic_plan", [])
        prefab_overrides = plan["config"].get("prefab_overrides", {})

        # Prefab Luas
        for prefab_name, default_donor in members:
            member_key = "Adult"
            if prefab_name.lower() != new_name.lower():
                member_key = prefab_name[len(new_name):].lstrip('_')
            if not member_key:
                member_key = "Adult"

            override_dict = (
                prefab_overrides.get(member_key)
                or prefab_overrides.get("Female" if member_key == "Adult" else member_key, {})
                or {}
            )
            donor = override_dict.get("Prefab") or default_donor

            # AssetPackages is emitted separately from the other properties:
            # serialize_lua_properties() cannot express the __inheritance
            # directive, and without it the stub's list would silently replace
            # the donor's packages. Copy first so a user's config is not mutated.
            props = dict(override_dict.get("Properties", {}) or {})
            ap_override = props.pop("AssetPackages", None)
            ap_mode = _resolve_ap_inheritance(
                config, plan["config"], member_key, override_dict)

            props_str = serialize_lua_properties(props, indent=8)
            ap_block = _asset_packages_block(prefab_name, ap_override, ap_mode, indent=8)
            if ap_block:
                props_str = f"{props_str}\n{ap_block}" if props_str else ap_block
                if ap_mode == "Replace":
                    report.setdefault("warnings", []).append(
                        f"{prefab_name}: AssetPackages set to Replace, so the donor's "
                        f"packages ({donor or 'inherited'}) are dropped. The model and "
                        f"animations will not resolve unless your own OVL supplies them."
                    )

            path = os.path.join(main_dir, f"{prefab_name.lower()}.lua")
            with open(path, "w") as f:
                f.write(PREFAB_LUA.format(mod=prefab_name, name=prefab_name,
                                          donor=donor or "", properties=props_str))
            written.append(os.path.basename(path))
            all_prefab_names.append(prefab_name)

        # Cosmetic variant Luas
        for cosm in cosmetic_plan:
            path = os.path.join(main_dir, f"{cosm['name'].lower()}.lua")
            with open(path, "w") as f:
                f.write(COSMETIC_LUA.format(
                    mod=cosm["name"], name=cosm["name"],
                    parent=cosm["parent"], pattern_set=cosm["pattern_set"],
                    variant_set=cosm["variant_set"],
                ))
            written.append(os.path.basename(path))
            all_prefab_names.append(cosm["name"])


        # Tech tree accumulators
        # With no custom icon, reuse the donor's known-good vanilla icon.
        icon = plan["config"].get("icon") or plan["config"].get("source") or new_name
        ui_rewards.append(f'    TechTree_{new_name} = {{\n        icon = "",\n        label = "{new_name}"\n    }}')
        nodes.append(f'    {new_name}1A = {{\n        streamedIcon = "icons.dinosaurSpecies.{icon}",\n        image = "{icon}",\n        conditions = {{\n            {{preset = "Rating", Target = "0"}}\n        }},\n        rewards = {{\n            {{id = "TechTree_{new_name}"}}\n        }}\n    }}')
        rebirth_rewards.append(f'                    {{id = "TechTree_{new_name}"}}')
        ingen_data.append(f'        {new_name} = {{}}')
        ingen_techtree.append(f'        "TechTree_{new_name}"')
        ingen_genomes.append(f'"{new_name}"')

    ui_rewards_str = ",\n".join(ui_rewards)
    nodes_str = ",\n".join(nodes)
    rebirth_rewards_str = ",\n".join(rebirth_rewards)
    ingen_data_str = ",\n".join(ingen_data)
    ingen_techtree_str = ",\n".join(ingen_techtree)
    ingen_genomes_str = ", ".join(ingen_genomes)

    # PrefabData
    prefab_list = "\n".join(f"\t\t'{p}'," for p in all_prefab_names)
    path = os.path.join(main_dir, f"database.{mod_name.lower()}prefabdata.lua")

    with open(path, "w") as f:
        f.write(PREFABDATA_LUA.format(mod_name=mod_name, prefab_list=prefab_list))
    written.append(os.path.basename(path))

    # Icon Mount and PPUIPKG. An empty list means exactly "no custom icons";
    # never fabricate an icon entry because merely mounting a broken UI OVL can
    # crash JWE3 during startup.
    icons = list(config.get("icons") or [])

    # Optional placeholder set: gives every species a full complement of icons
    # (PNG portraits + tech-tree SVG) so no slot is blank before the author has
    # any art. Explicit `icons` still win - this only fills in.
    default_icon_refs, default_svgs, default_written = [], [], []
    if config.get("default_icons"):
        default_icon_refs, default_svgs, default_written = build_default_icon_set(
            out_dir, mod_name, plans, report)
        written.extend(default_written)

    # Remove manager/package definitions left by a previous enabled build.
    icon_lua_path = os.path.join(main_dir, f"managers.{mod_name.lower()}iconmount.lua")
    has_icons = bool(icons or default_icon_refs or default_svgs)
    if not has_icons and os.path.isfile(icon_lua_path):
        os.remove(icon_lua_path)
    if not has_icons:
        ui_root = os.path.join(out_dir, "UI")
        if os.path.isdir(ui_root):
            for root, _dirs, files in os.walk(ui_root):
                for fname in files:
                    if fname.lower().endswith(".ppuipkg"):
                        os.remove(os.path.join(root, fname))

    # Match CobblestoneBlock exactly: one dedicated UI overlay named for the
    # mod. The icon's `asset_package` is an internal OVS name and is NOT the
    # overlay/folder name (Cobblestone uses overlay `CobblestoneBlock` with
    # asset package `images_cobblestoneblock_decoration`).
    overlay_entries = f'\t{{"{mod_name}", "{mod_name}/UI/{mod_name}"}}'
    if has_icons:
        with open(icon_lua_path, "w") as f:
            f.write(ICON_MOUNT_LUA.format(mod_name=mod_name,
                                          overlay_entries=overlay_entries))
        written.append(os.path.basename(icon_lua_path))
    # NOTE: deliberately NOT added to _tContentToCall. This is an ACSE MANAGER
    # (it has Init/Advance and ends in VerifyManagerModule), so it is registered
    # through AddLuaManagers instead - see icon_manager_entry below. Requiring a
    # manager as content is what put the icon code on the boot path.
    icon_require = ""

    if has_icons:
        pkg_name = mod_name
        pkg_ui_dir = os.path.join(out_dir, "UI", mod_name)
        os.makedirs(pkg_ui_dir, exist_ok=True)
        ppuipkg_path = os.path.join(pkg_ui_dir, f"userinterfaceimages{pkg_name.lower()}.ppuipkg")

        # <types> - REFERENCES to .tex/.png that ship as separate OVL entries.
        icon_refs = []
        seen_cfg = set()
        for icon in icons:
            img_path = icon.get("path") or icon.get("image_name") or f"uigameface/img/dinosaurs/{mod_name.lower()}.png"
            asset_package = normalise_mod_asset_package(
                mod_name,
                icon.get("assetPackage")
                or icon.get("asset_package")
                or mod_name)
            if img_path in seen_cfg:
                continue
            seen_cfg.add(img_path)
            icon_refs.append((img_path, asset_package))

            norm_img_path = img_path.replace("/", os.sep).replace("\\", os.sep)
            dir_name = os.path.dirname(norm_img_path)
            if dir_name:
                os.makedirs(os.path.join(pkg_ui_dir, dir_name), exist_ok=True)

        # De-dupe by image_name. The GUI's icon list is populated by reading the
        # mod's OWN package back (syncIconsFromMod), so on the second run the
        # default set arrives twice: once via config["icons"] and once from
        # build_default_icon_set. Explicit config entries win - the author may
        # have retyped an asset package - so this is first-wins, not last.
        seen_refs = {img for img, _pkg in icon_refs}
        for img, pkg in default_icon_refs:
            if img not in seen_refs:
                seen_refs.add(img)
                icon_refs.append((img, pkg))

        # <files> - whole files EMBEDDED byte-for-byte. This is the only way an
        # SVG can ship; there is no loose .svg entry anywhere in the game.
        #
        # REGENERATING MUST NOT DESTROY ART. The embedded bytes ARE the icon -
        # unlike a .png, an author's custom SVG lives nowhere else on disk, so
        # blindly rewriting this package would silently delete it. Same trap
        # that let Capiraptor's hand-tuned scale maxima drift away from its
        # project file. So:
        #   <files>  author wins  - an existing entry is never overwritten, and
        #                           entries we did not generate are preserved.
        #   <types>  generator wins on names it owns (they are just references,
        #                           derived from config), unknown ones preserved.
        existing_files, existing_icons = [], []
        if os.path.isfile(ppuipkg_path):
            try:
                _basic, existing_files, existing_icons = read_package(ppuipkg_path)
            except Exception as exc:
                report.setdefault("warnings", []).append(
                    f"could not parse the existing {os.path.basename(ppuipkg_path)} "
                    f"({exc}). It will be REPLACED - any custom SVGs inside it are "
                    f"lost. Move it aside and re-inject them.")
                existing_files, existing_icons = [], []

        existing_names = {name for name, _ in existing_files}
        merged_files = list(existing_files)
        for name, data in default_svgs:
            if name not in existing_names:
                merged_files.append((name, data))

        generated_refs = {img for img, _pkg in icon_refs}
        merged_icons = list(icon_refs)
        for img, pkg in existing_icons:
            if img not in generated_refs:
                merged_icons.append((img, pkg))

        kept = len(existing_names)
        if kept:
            report.setdefault("preserved_ppuipkg_files", []).extend(sorted(existing_names))

        write_package(ppuipkg_path, f"{pkg_name}/UI",
                      files=merged_files, icons=merged_icons)
        audit_ui_texture_archives(pkg_ui_dir)
        written.append(os.path.relpath(ppuipkg_path, out_dir))

    # Aggregate scaling across all species and family member units
    scaling = dict(config.get("scaling") or {})
    for plan in plans:
        sp_conf = plan.get("config", {})
        if sp_conf.get("scaling_enabled") is False:
            continue
        sp_name = sp_conf.get("name")
        sp_id = sp_conf.get("species_id")

        base_scale = sp_conf.get("scale")
        if base_scale is None:
            base_scale = 1.0
        # A species-level `scale` may itself be a band, so the per-morph
        # fallback is a (min, max) pair rather than a single float.
        base_scale_val = normalise_scale_range(base_scale) or (1.0, 1.0)

        sp_scales = sp_conf.get("scales") or {}
        prefab_overrides = sp_conf.get("prefab_overrides") or {}
        resolved_members = plan.get("_resolved_members") or []

        if resolved_members:
            for rm in resolved_members:
                m_key = rm.get("key", "Female")
                m_sid = rm.get("target_sid")
                m_name = rm.get("target_name")

                m_override = prefab_overrides.get(m_key, {})
                m_scale_val = (
                    sp_scales.get(m_key)
                    if sp_scales.get(m_key) is not None
                    else m_override.get("scale")
                    or m_override.get("RenderScaleMultiplier")
                    or base_scale_val
                )
                s_val = normalise_scale_range(m_scale_val) or base_scale_val

                if m_sid:
                    scaling[int(m_sid)] = s_val
                if m_name:
                    scaling[m_name] = s_val
                if m_key == "Female" and sp_name:
                    scaling[sp_name] = s_val
        else:
            # Default fallback for Female, Male, Juvenile
            defaults = [
                ("Female", sp_id, sp_name),
                ("Male", (int(sp_id) + 1) if sp_id else None, f"{sp_name}_Male" if sp_name else None),
                ("Juvenile", (int(sp_id) + 2) if sp_id else None, f"{sp_name}_Juvenile" if sp_name else None),
            ]
            for m_key, m_sid, m_name in defaults:
                m_override = prefab_overrides.get(m_key, {})
                m_scale_val = (
                    sp_scales.get(m_key)
                    if sp_scales.get(m_key) is not None
                    else m_override.get("scale")
                    or m_override.get("RenderScaleMultiplier")
                    or base_scale_val
                )
                s_val = normalise_scale_range(m_scale_val) or base_scale_val

                if m_sid:
                    scaling[int(m_sid)] = s_val
                if m_name:
                    scaling[m_name] = s_val

    config["scaling"] = scaling


    # LuaDatabase
    path = os.path.join(main_dir, f"database.{mod_name.lower()}luadatabase.lua")
    with open(path, "w") as f:
        f.write(LUADATABASE_LUA.format(
            mod_name=mod_name,
            manager_block=(ICON_MANAGER_DATABASE_BLOCK.format(mod_name=mod_name)
                           if has_icons else ""),
            self_content=(f"    table.insert(_tContentToCall, {mod_name}Database)\n"
                          if has_icons else ""),
            scale_require=(SCALE_REQUIRE.format(mod_name=mod_name)
                           if config.get("scaling") else ""),
            icon_require=icon_require))
    written.append(os.path.basename(path))

    # Tech tree
    path = os.path.join(main_dir, f"database.{mod_name.lower()}techtreedata.lua")
    with open(path, "w") as f:
        f.write(TECHTREE_LUA.format(mod_name=mod_name, ui_rewards=ui_rewards_str, nodes=nodes_str))
    written.append(os.path.basename(path))

    # Rebirth hidden species tech tree
    path = os.path.join(main_dir, f"database.{mod_name.lower()}rebirthhiddenspeciestechtree.lua")
    with open(path, "w") as f:
        f.write(REBIRTH_TECHTREE_LUA.format(mod_name=mod_name, rebirth_rewards=rebirth_rewards_str))
    written.append(os.path.basename(path))

    # InGen database
    path = os.path.join(main_dir, f"database.{mod_name.lower()}ingendatabasedata.lua")
    with open(path, "w") as f:
        f.write(INGEN_DATABASE_LUA.format(mod_name=mod_name, ingen_data=ingen_data_str, ingen_techtree=ingen_techtree_str, ingen_genomes=ingen_genomes_str))
    written.append(os.path.basename(path))

    # Shared Dinosaur Mods tech tree
    path = os.path.join(main_dir, "techtrees.trees.dinosaurmodstechtree.lua")
    with open(path, "w") as f:
        f.write(DINOSAUR_MODS_TECHTREE_LUA)
    written.append(os.path.basename(path))

    # Init database config
    path = os.path.join(init_dir, f"databases.{mod_name.lower()}.lua")
    with open(path, "w") as f:
        f.write(INIT_DATABASE_LUA.format(mod_name=mod_name))
    written.append(f"Init/{os.path.basename(path)}")

    # Manifest
    with open(os.path.join(out_dir, "Manifest.xml"), "w") as f:
        f.write(MANIFEST_XML.format(name=mod_name, uuid=uuid_mod.uuid4()))
    written.append("Manifest.xml")

    # Clean up stale species/cosmetic .lua files in Main
    valid_lua_names = {f"{p.lower()}.lua" for p in all_prefab_names}
    if os.path.isdir(main_dir):
        for fname in os.listdir(main_dir):
            if fname.endswith(".lua"):
                if not (fname.startswith("database.") or fname.startswith("managers.") or fname.startswith("techtrees.")):
                    if fname.lower() not in valid_lua_names:
                        try:
                            os.remove(os.path.join(main_dir, fname))
                        except Exception:
                            pass

    # Optional per-species scaling
    scaling = config.get("scaling")
    if scaling:
        fn = write_scale_module(main_dir, mod_name, scaling, report)
        if fn:
            written.append(fn)
    else:
        stale_scale = os.path.join(main_dir, f"database.{mod_name.lower()}scaledata.lua")
        if os.path.isfile(stale_scale):
            os.remove(stale_scale)

    # AssetPackages
    referenced, _ = audit_asset_packages(main_dir, init_dir, report)
    members_only = {p for p in all_prefab_names if not re.search(r"_\d{2}$", p)}
    mod_owned = set(members_only) | {
        r for r in referenced
        if r.lower() in {p.lower() for p in all_prefab_names}
        or r.lower().startswith(mod_name.lower())}

    # Clean up stale .assetpkg files in Init
    valid_ap_names = {f"{p.lower()}.assetpkg" for p in mod_owned}
    if os.path.isdir(init_dir):
        for fname in os.listdir(init_dir):
            if fname.endswith(".assetpkg"):
                if fname.lower() not in valid_ap_names:
                    try:
                        os.remove(os.path.join(init_dir, fname))
                    except Exception:
                        pass


    root_ap = config.get("asset_packages") or {}
    category = config.get("asset_category") or "Land"

    for pkg in sorted(mod_owned):
        pkg_file = os.path.join(init_dir, f"{pkg.lower()}.assetpkg")

        raw_path = root_ap.get(pkg)
        if not raw_path:
            base_sp_name = None
            for p in plans:
                sp_n = p["config"]["name"]
                if pkg.lower().startswith(sp_n.lower()):
                    base_sp_name = sp_n
                    break
            if not base_sp_name:
                base_sp_name = pkg.split('_')[0]

            gender_sub = asset_package_gender_subdir(pkg)

            raw_path = f"ovldata\\{mod_name}\\Dinosaurs\\{category}\\{base_sp_name}\\{gender_sub}\\{pkg}"

        asset_path_str = raw_path.replace("/", "\\")
        if not asset_path_str.lower().startswith("ovldata\\"):
            clean_path = asset_path_str.lstrip("\\/")
            asset_path_str = f"ovldata\\{mod_name}\\{clean_path}"


        xml_content = (
            f'<AssetpkgRoot game="Jurassic World Evolution 3">\n'
            f'\t<asset_path>{asset_path_str}</asset_path>\n'
            f'</AssetpkgRoot>\n'
        )
        with open(pkg_file, "w", encoding="utf-8") as f:
            f.write(xml_content)
        written.append(f"Init/{os.path.basename(pkg_file)}")

        rel_folder = asset_path_str
        ovl_prefix = f"ovldata\\{mod_name}\\".lower()
        if rel_folder.lower().startswith(ovl_prefix):
            rel_folder = rel_folder[len(ovl_prefix):]
        elif rel_folder.lower().startswith("ovldata\\"):
            parts = rel_folder.split("\\", 2)
            rel_folder = parts[2] if len(parts) > 2 else rel_folder

        pkg_dir = os.path.normpath(os.path.join(out_dir, rel_folder))
        os.makedirs(pkg_dir, exist_ok=True)
        rel_posix = rel_folder.replace("\\", "/")
        written.append(rel_posix)



    report["files_written"] = written
    return written




def generate_species(mod_name, plans, report, config):
    """Orchestrate FDB database cloning and scaffolding file generation."""
    out_dir = os.path.join(BASE_DIR, "Generated", mod_name)
    main_dir = os.path.join(out_dir, "Main")
    os.makedirs(main_dir, exist_ok=True)

    src_dino_fdb = config.get("source_dinosaurs_fdb") or os.path.join(BASE_DIR, "extracted_fdbs", "c0dinosaurs.fdb")
    src_exp_fdb = config.get("source_expeditions_fdb") or os.path.join(BASE_DIR, "extracted_fdbs", "c0expeditions.fdb")

    dst_dino_fdb = os.path.join(main_dir, f"{mod_name.lower()}dinosaurs.fdb")
    dst_exp_fdb = os.path.join(main_dir, f"{mod_name.lower()}expeditions.fdb")

    # The FDBs are rebuilt from scratch, so any stale copy is removed first.
    # On Windows this fails with PermissionError if ANYTHING still holds the
    # file open - most often this app's own editor pages, or the .fdb opened in
    # a SQLite browser. The raw WinError 32 is unhelpful, so translate it into
    # something actionable rather than letting it surface as a stack trace.
    for _fdb in (dst_dino_fdb, dst_exp_fdb):
        if not os.path.isfile(_fdb):
            continue
        try:
            os.remove(_fdb)
        except PermissionError:
            raise RuntimeError(
                f"Cannot rebuild '{os.path.basename(_fdb)}' because the file is "
                f"open in another program.\n\n"
                f"Close anything using it - the Edit Built Mod / Expeditions "
                f"pages in this app, or an external SQLite viewer - then "
                f"generate again.\n\nPath: {_fdb}"
            )

    # Clone dinosaurs.fdb & expeditions.fdb
    for plan in plans:
        sp_conf = plan["config"]
        fdb_ov = dict(sp_conf.get("fdb_overrides", {}))
        if "family_members" in sp_conf:
            fdb_ov["family_members"] = sp_conf["family_members"]
        # cosmetics.film_variants opts in to cloning the donor's movie skins
        # (KentrosaurusCC, SpinosaurusJWR, VelociraptorBlue...). Lives on the
        # species config in the UI, but clone_fdb reads fdb_overrides.
        if "cosmetics" in sp_conf:
            fdb_ov["cosmetics"] = sp_conf["cosmetics"]
        dino_res = clone_fdb(
            source_fdb=src_dino_fdb,
            target_fdb=dst_dino_fdb,
            donor_species=sp_conf["source"],
            new_species=sp_conf["name"],
            new_species_id=sp_conf["species_id"],
            new_genetic_id=sp_conf["genetic_id"],
            donor_prefabs=sp_conf.get("donor_prefabs", {}),
            fdb_overrides=fdb_ov,
            report=report
        )

        resolved_members = dino_res.get("_resolved_members") if isinstance(dino_res, dict) else None
        plan["_resolved_members"] = resolved_members


        clone_expeditions_fdb(
            source_exp_fdb=src_exp_fdb,
            target_exp_fdb=dst_exp_fdb,
            donor_species=sp_conf["source"],
            new_species=sp_conf["name"],
            new_species_id=sp_conf["species_id"],
            new_genetic_id=sp_conf["genetic_id"],
            custom_digsite=bool(sp_conf.get("custom_digsite", False)),
            fdb_overrides=sp_conf.get("expeditions_overrides", {}),
            report=report,
            resolved_members=resolved_members
        )



    # Generate localizations across all 14 language subfolders
    for plan in plans:
        sp_conf = plan["config"]
        generate_species_localizations(out_dir, sp_conf["name"], report)

    # Rebuild each plan's cosmetic Lua stub list from the FDB rows clone_fdb
    # just committed, rather than the fixed-count guess plan_species made
    # before the FDB existed. Must happen after the clone loop above (so the
    # rows exist) and before write_scaffold (which is what writes the .lua
    # files) - see _cosmetic_plan_from_fdb for why.
    for plan in plans:
        real_plan = _cosmetic_plan_from_fdb(dst_dino_fdb, plan)
        if real_plan:
            plan["cosmetic_plan"] = real_plan
        elif plan.get("_resolved_members"):
            # resolved but the donor genuinely has 0 cosmetic sets - do not
            # keep the fixed-count guess in this case either, or a stub would
            # be written for a set that was never cloned.
            plan["cosmetic_plan"] = []

    write_scaffold(out_dir, mod_name, plans, config, report)

    return {
        "dinosaurs_fdb": dst_dino_fdb,
        "expeditions_fdb": dst_exp_fdb,
        "output_dir": out_dir
    }
