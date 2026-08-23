"""Read and write JWE3 `.ppuipkg` UI packages.

A ppuipkg has TWO INDEPENDENT SECTIONS and they work in opposite ways. Getting
this backwards is the whole reason SVG icons were unsupported for so long:

    <files>   file_count      whole files EMBEDDED byte-for-byte in the XML.
                              This is how every SVG ships - there is no separate
                              .svg entry in the OVL. Verified: all 991 <files>
                              children of Content0's userinterfaceimagesiconsc0
                              are .svg, and the extracted UI tree contains zero
                              loose .svg files.

    <types>   icondata_count  REFERENCES only - an image path plus the OVS
                              asset package it lives in. The actual .tex/.png
                              pair ships as separate entries in the same OVL.

Both counts in the root element must match their section exactly.

Byte encoding: `<file_content>` is space-separated decimals written **signed**
(-128..127), matching Frontier's own packages and the reference reader at
`JWE 3 Luas/Base Game/UI/PPUIPkgFile.py`. Writing them unsigned corrupts every
byte >= 0x80 - which a pure-ASCII SVG hides and anything else does not.

Do NOT route this through that reference script: its docstring says it ignores
userinterfaceicondata entries, and `_write_files()` hardcodes
`icondata_count='0'` with an empty <types>, so it cannot round-trip a package
that has both sections.
"""

import os
import xml.etree.ElementTree as ET


GAME = "Jurassic World Evolution 3"


def normalise_mod_asset_package(mod_name, asset_package):
    """Return a safe spelling for an OVS stream owned by ``mod_name``.

    cobra-tools sorts OVL archives by their case-sensitive names. JWE3 UI
    overlays must keep the built-in ``STATIC`` archive first; a mod-owned
    stream beginning with an uppercase A-R sorts ahead of it and can crash the
    native overlay loader. Lowercase mod-owned names sort after ``STATIC`` and
    match the layout proven by CobblestoneBlock.

    Vanilla/external package names are deliberately left alone. They may be
    references to an already mapped overlay rather than streams shipped by the
    mod.
    """
    mod_name = (mod_name or "").strip()
    package = (asset_package or mod_name).strip()
    if not mod_name:
        return package
    owned_prefix = mod_name.casefold() + "_"
    if (package.casefold() == mod_name.casefold()
            or package.casefold().startswith(owned_prefix)):
        return package.lower()
    return package


def decode_bytes(text):
    """`<file_content>` decimal text -> bytes. Signed, per the vanilla format."""
    if not text:
        return b""
    return b"".join(int(tok).to_bytes(1, "big", signed=True) for tok in text.split())


def encode_bytes(data):
    """bytes -> `<file_content>` decimal text, signed to match vanilla."""
    return " ".join(str(b - 256 if b > 127 else b) for b in bytearray(data))


def read_package(path):
    """Parse a ppuipkg into `(basic_path, files, icons)`.

    `files` is a list of `(name, bytes)`; `icons` a list of
    `(image_name, asset_package)`.
    """
    root = ET.parse(path).getroot()

    basic_el = root.find("basic_path")
    basic = basic_el.text if basic_el is not None else "Content0/UI"

    files = []
    files_el = root.find("files")
    if files_el is not None:
        for entry in files_el:
            name = entry.find("file_name")
            content = entry.find("file_content")
            if name is None or name.text is None:
                continue
            raw = decode_bytes(content.text if content is not None else "")

            declared = entry.get("file_size")
            if declared is not None and int(declared) != len(raw):
                raise ValueError(
                    f"{path}: {name.text} declares file_size={declared} "
                    f"but decodes to {len(raw)} bytes")
            files.append((name.text, raw))

    icons = []
    types_el = root.find("types")
    if types_el is not None:
        for entry in types_el:
            image = entry.find("image_name")
            pkg = entry.find("asset_package")
            if image is None or image.text is None:
                continue
            icons.append((image.text, pkg.text if pkg is not None else ""))

    return basic, files, icons


def write_package(path, basic_path, files=None, icons=None):
    """Write a ppuipkg with both sections, tab-indented like the vanilla ones.

    `files`: iterable of `(name, bytes)` to EMBED.
    `icons`: iterable of `(image_name, asset_package)` to REFERENCE.
    """
    files = list(files or [])
    icons = list(icons or [])

    lines = [
        f'<PPUIPKGRoot file_count="{len(files)}" '
        f'icondata_count="{len(icons)}" game="{GAME}">',
        f'\t<basic_path>{basic_path}</basic_path>',
    ]

    # An empty section is written self-closing, exactly as vanilla does it.
    if files:
        lines.append('\t<files>')
        for name, data in files:
            lines.append(f'\t\t<ppuipkgfile file_size="{len(data)}">')
            lines.append(f'\t\t\t<file_name>{name.replace(os.sep, "/")}</file_name>')
            lines.append(f'\t\t\t<file_content>{encode_bytes(data)}</file_content>')
            lines.append('\t\t</ppuipkgfile>')
        lines.append('\t</files>')
    else:
        lines.append('\t<files />')

    if icons:
        lines.append('\t<types>')
        for image_name, asset_package in icons:
            lines.append('\t\t<userinterfaceicondata>')
            lines.append(f'\t\t\t<image_name>{image_name}</image_name>')
            lines.append(f'\t\t\t<asset_package>{asset_package}</asset_package>')
            lines.append('\t\t</userinterfaceicondata>')
        lines.append('\t</types>')
    else:
        lines.append('\t<types />')

    lines.append('</PPUIPKGRoot>')

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def extract_files(pkg_path, out_dir, name_filter=None):
    """Write every embedded file out to `out_dir`, preserving its inner path.

    `name_filter` is an optional callable taking the entry name. Returns the
    list of paths written.
    """
    _basic, files, _icons = read_package(pkg_path)
    written = []
    for name, data in files:
        if name_filter and not name_filter(name):
            continue
        dest = os.path.join(out_dir, name.replace("/", os.sep))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        written.append(dest)
    return written
