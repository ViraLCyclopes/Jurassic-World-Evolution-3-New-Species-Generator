"""Read and write the `.tex` header that must accompany every PNG in an OVL.

A UI image is NOT embedded in the .ppuipkg - the package only REFERENCES it.
The bytes ship as a pair beside the package:

    <image_name>.png    the actual image
    <image_name>.tex    a small XML header describing it

Both are required. Ship the .png alone and the OVL packs without the texture.

Header shape, surveyed across all 7,744 vanilla .tex files in Base Game/UI:

    <TexHeader compression_type="DdsType.BC7_UNORM" width="232" height="232"
               num_mips="1" texel="wnl8lyc1tu3dsokz"
               game="Jurassic World Evolution 3" ovs="Dinosaur_Small"
               num_mips_low="1" num_mips_high="1" flag="0">
        <compression_pad>0 0 0</compression_pad>
        <texel_ref />
        <texel_padding />
    </TexHeader>

What varies and what does not:

  * `width` / `height`  MUST match the PNG. 255 distinct sizes in vanilla.
  * `ovs`               the OVS stream name. 3,192 distinct. This is the same
                        value as the ppuipkg's <asset_package> - keep them in
                        step or the icon and its texture disagree about which
                        stream they live in.
  * `texel`             PER-OVS-STREAM, not per-file: only 22 distinct values
                        across 7,744 files, and their counts line up with the
                        stream sizes. Reuse the value already in use for a
                        stream; only invent one for a brand-new stream.
  * `compression_type`  BC7_UNORM (7,363) or BC1_UNORM (381). BC7 is the default.
  * `num_mips`, `num_mips_low`, `num_mips_high`, `flag`, `game`
                        CONSTANT in every vanilla file (1/1/1/0/JWE3).
"""

import os
import re
import struct

GAME = "Jurassic World Evolution 3"
DEFAULT_COMPRESSION = "DdsType.BC7_UNORM"
# Only invent a texel name for a stream that has none; prefer copying the value
# an existing .tex in the same stream already uses.
DEFAULT_TEXEL = "wnl8lyc1tu3dsokz"

TEX_TEMPLATE = (
    '<TexHeader compression_type="{compression}" width="{width}" '
    'height="{height}" num_mips="1" texel="{texel}" game="{game}" '
    'ovs="{ovs}" num_mips_low="1" num_mips_high="1" flag="0">\n'
    '\t<compression_pad>0 0 0</compression_pad>\n'
    '\t<texel_ref />\n'
    '\t<texel_padding />\n'
    '</TexHeader>\n'
)


def png_size(path_or_bytes):
    """(width, height) straight out of the PNG IHDR chunk.

    Avoids a Pillow dependency - the generator and the tool both already ship
    with PyQt, but this is used in places where no QApplication exists.
    Returns None if the data is not a PNG.
    """
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes[:33])
    else:
        with open(path_or_bytes, "rb") as f:
            data = f.read(33)

    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return (width, height)


def read_tex(path):
    """Parse a .tex header into a dict, or None if it does not look like one."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            head = f.readline()
    except OSError:
        return None
    if "TexHeader" not in head:
        return None

    out = {}
    for key, value in re.findall(r'(\w+)="([^"]*)"', head):
        out[key] = value
    for key in ("width", "height", "num_mips", "flag"):
        if key in out:
            try:
                out[key] = int(out[key])
            except ValueError:
                pass
    return out


def write_tex(path, width, height, ovs,
              texel=DEFAULT_TEXEL, compression=DEFAULT_COMPRESSION):
    """Write a .tex header. `width`/`height` must be the PNG's real size."""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(TEX_TEMPLATE.format(
            compression=compression, width=int(width), height=int(height),
            texel=texel, game=GAME, ovs=ovs))
    return path


def texel_for_stream(search_dirs, ovs):
    """Find the texel name an existing .tex already uses for this OVS stream.

    Reusing it keeps a new texture consistent with the stream it joins; falls
    back to DEFAULT_TEXEL when the stream is new (a mod's own package).
    """
    for root_dir in search_dirs:
        if not root_dir or not os.path.isdir(root_dir):
            continue
        for root, _dirs, files in os.walk(root_dir):
            for name in files:
                if not name.endswith(".tex"):
                    continue
                info = read_tex(os.path.join(root, name))
                if info and info.get("ovs") == ovs and info.get("texel"):
                    return info["texel"]
    return DEFAULT_TEXEL


def install_png(image_root, image_name, png_bytes, ovs,
                texel=None, compression=DEFAULT_COMPRESSION):
    """Write the .png + .tex pair for one referenced icon.

    `image_root` is the directory holding the .ppuipkg - `image_name` from the
    package's <types> section is relative to it.

    cobra-tools names an extracted texture `<entry>.png` where the entry itself
    already ends in .png, giving `foo.png.png` alongside `foo.png.tex`. That
    doubled extension is the on-disk convention and is NOT a mistake; the
    CobblestoneBlock mod ships exactly this pair.

    Returns (png_path, tex_path, (width, height)).
    """
    size = png_size(png_bytes)
    if not size:
        raise ValueError("not a PNG (no IHDR) - refusing to write a .tex "
                         "whose dimensions would be a guess")

    rel = image_name.replace("/", os.sep).replace("\\", os.sep)
    base = os.path.join(image_root, rel)
    os.makedirs(os.path.dirname(base), exist_ok=True)

    png_path = base + ".png"
    tex_path = base + ".tex"

    with open(png_path, "wb") as f:
        f.write(png_bytes)

    if texel is None:
        texel = texel_for_stream([image_root], ovs)
    write_tex(tex_path, size[0], size[1], ovs, texel, compression)

    return png_path, tex_path, size


def find_image_pair(image_root, image_name):
    """Locate the on-disk art for a <types> reference.

    Returns (png_path or None, tex_path or None). Handles both the doubled
    `foo.png.png` convention and a plain `foo.png`.
    """
    rel = image_name.replace("/", os.sep).replace("\\", os.sep)
    base = os.path.join(image_root, rel)

    png = None
    for candidate in (base + ".png", base):
        if os.path.isfile(candidate):
            png = candidate
            break

    tex = base + ".tex"
    if not os.path.isfile(tex):
        tex = None
    return png, tex
