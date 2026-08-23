"""Harvest the vanilla dinosaur-species SVG icons out of a ppuipkg.

SVGs are embedded inside the package rather than shipped as loose files (see
`core/ppuipkg.py`), so they cannot be picked up off disk - they have to be
decoded out. This vendors them into `templates/icons/dinosaurSpecies/` so the
generator has real art to hand a new species.

    python extract_ui_svgs.py                     # default package + filter
    python extract_ui_svgs.py --pkg X.ppuipkg --filter icons/ --out DIR
    python extract_ui_svgs.py --list              # just show what is inside
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.ppuipkg import read_package, extract_files, write_package

HERE = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PKG = os.path.join(
    HERE, "..", "Base Game", "UI", "userinterfaceimagesiconsc0.ppuipkg")
DEFAULT_OUT = os.path.join(HERE, "templates", "icons")
DEFAULT_FILTER = "img/icons/dinosaurspecies/"


def rasterise_svgs(svg_paths, out_dir, size=256):
    """Render each SVG to a transparent PNG whose LONGEST edge is `size` px.

    The SVG's own aspect ratio is preserved. Forcing a square stretches any
    icon whose viewBox is not square; the vanilla dinosaur icons happen to be
    24x24, but nothing guarantees that for art you inject yourself.

    Uses PyQt5's QtSvg, already a dependency of the GUI, so this needs no extra
    install. A QApplication must exist before QImage/QPainter are used, but the
    renderer needs no window - QGuiApplication is enough and works headless.
    """
    try:
        from PyQt5.QtGui import QGuiApplication, QImage, QPainter, QColor
        from PyQt5.QtSvg import QSvgRenderer
        from PyQt5.QtCore import QByteArray, QRectF
    except ImportError as exc:
        print(f"  PNG export needs PyQt5 with QtSvg ({exc}); skipping.")
        return []

    app = QGuiApplication.instance() or QGuiApplication([])
    os.makedirs(out_dir, exist_ok=True)

    written, failed = [], []
    for svg_path in svg_paths:
        with open(svg_path, "rb") as f:
            data = f.read()

        renderer = QSvgRenderer(QByteArray(data))
        if not renderer.isValid():
            failed.append(os.path.basename(svg_path))
            continue

        native = renderer.defaultSize()
        nw = max(1, native.width())
        nh = max(1, native.height())
        scale = size / float(max(nw, nh))
        out_w = max(1, int(round(nw * scale)))
        out_h = max(1, int(round(nh * scale)))

        image = QImage(out_w, out_h, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, out_w, out_h))
        painter.end()

        dest = os.path.join(
            out_dir, os.path.splitext(os.path.basename(svg_path))[0] + ".png")
        if image.save(dest, "PNG"):
            written.append(dest)
        else:
            failed.append(os.path.basename(svg_path))

    if failed:
        print(f"  WARNING: {len(failed)} SVG(s) failed to rasterise: "
              f"{', '.join(failed[:5])}{' ...' if len(failed) > 5 else ''}")
    del app
    return written


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pkg", default=DEFAULT_PKG, help="source .ppuipkg")
    ap.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--filter", default=DEFAULT_FILTER,
                    help="case-insensitive substring an entry must contain")
    ap.add_argument("--list", action="store_true",
                    help="list contents and exit, writing nothing")
    ap.add_argument("--verify", action="store_true",
                    help="round-trip every embedded file through the writer "
                         "and assert the bytes survive")
    ap.add_argument("--png", metavar="DIR", nargs="?", const="",
                    help="also rasterise every extracted SVG to PNG. Defaults "
                         "to a 'png' folder beside --out.")
    ap.add_argument("--png-size", type=int, default=256,
                    help="square PNG edge in px (default 256)")
    args = ap.parse_args()

    pkg = os.path.normpath(args.pkg)
    if not os.path.isfile(pkg):
        print(f"ERROR: no such package: {pkg}")
        return 2

    basic, files, icons = read_package(pkg)
    print(f"package      : {pkg}")
    print(f"basic_path   : {basic}")
    print(f"embedded     : {len(files)} file(s)")
    print(f"icon refs    : {len(icons)} userinterfaceicondata entr(ies)")

    if args.list:
        for name, data in files:
            print(f"  {len(data):>8}  {name}")
        return 0

    if args.verify:
        import tempfile
        tmp = os.path.join(tempfile.mkdtemp(), "roundtrip.ppuipkg")
        write_package(tmp, basic, files, icons)
        _b2, files2, icons2 = read_package(tmp)
        ok = (files == files2 and icons == icons2)
        print(f"round-trip   : {'IDENTICAL' if ok else 'MISMATCH'} "
              f"({len(files2)} files, {len(icons2)} icon refs)")
        if not ok:
            return 1

    needle = args.filter.lower()
    out = os.path.normpath(args.out)
    written = extract_files(pkg, out, lambda n: needle in n.lower())

    print(f"extracted    : {len(written)} file(s) -> {out}")
    for path in written[:5]:
        print(f"  {os.path.relpath(path, out)}")
    if len(written) > 5:
        print(f"  ... and {len(written) - 5} more")

    if not written:
        print(f"WARNING: nothing matched filter {args.filter!r}. "
              f"Entry names are case-sensitive in the package but this "
              f"filter is not; check --list for the real names.")
        return 0

    if args.png is not None:
        png_dir = os.path.normpath(args.png) if args.png else os.path.join(out, "png")
        svgs = [p for p in written if p.lower().endswith(".svg")]
        pngs = rasterise_svgs(svgs, png_dir, args.png_size)
        print(f"rasterised   : {len(pngs)}/{len(svgs)} SVG(s) "
              f"-> {png_dir}  ({args.png_size}x{args.png_size})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
