"""PPUIPKG Inspector - view, extract and inject files in a JWE3 UI package.

    python ppuipkg_tool.py [path/to/file.ppuipkg]

Two panes: the embedded <files> section (SVGs, whose bytes live INSIDE the
package and nowhere else) and the referenced <types> section (PNG icon data,
which only names a .tex/.png that ships separately in the same OVL). See
`core/ppuipkg.py` for why the two behave differently.

Everything is edited in memory; nothing touches disk until Save. Save writes
through `core.ppuipkg.write_package`, which is round-trip verified against the
vanilla 991-file icons package.
"""

import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QFileDialog,
    QMessageBox, QTabWidget, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QInputDialog, QHeaderView, QLineEdit,
)
from PyQt5.QtGui import QPainter, QColor, QImage, QKeySequence
from PyQt5.QtWidgets import QShortcut
from PyQt5.QtCore import QByteArray, QRectF, QSize
from PyQt5.QtSvg import QSvgRenderer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core.ppuipkg import read_package, write_package  # noqa: E402
from core.tex import (png_size, read_tex, install_png, find_image_pair,  # noqa: E402
                      DEFAULT_COMPRESSION)

# Native Windows file dialogs. They ignore the app palette, so they do not match
# the dark theme - that is a deliberate trade: Qt's own file dialog is far worse
# to navigate with (no shell places, no recent folders, no search).
DLG_OPTS = QFileDialog.Options()

# Palette lifted from species_gen_ui/app.css so the tool matches the generator
# rather than shipping as a default-white Qt window. Keep in step with :root
# there if that theme changes.
BG_MAIN = "#0c1016"
BG_CARD = "#161c26"
BG_INPUT = "#1e2632"
BG_HOVER = "#28323f"
TEXT_MAIN = "#e0e6ed"
TEXT_MUTED = "#8a96a8"
ACCENT = "#40a0ff"
ACCENT_HOVER = "#60c0ff"
ACCENT_DEEP = "#2080ff"
WARN = "#ffd275"
ERROR = "#ff6060"
SUCCESS = "#60ff90"
BORDER = "#2b3a4a"


# Every format observed inside vanilla <files> sections, surveyed across all 24
# packages in Base Game/UI. All of them are plain UTF-8 text - there is no CSS /
# HTML / JS in a ppuipkg at all (that lives in the separate UIGameface tree,
# indexed by ResourceList.xml). <types> is 100% .png across 7,744 references.
FILE_KINDS = {
    ".svg":      ("SVG icon", "vector art - rendered below"),
    ".iconlist": ("Icon list", "newline-separated PNG variant filenames for one build-menu item"),
    ".iconset":  ("Icon set", "newline-separated list of icon folder names"),
    ".octl":     ("Icon control", "list of .iconSet paths"),
    ".py":       ("Python", "Frontier dev script shipped inside the package"),
    ".bat":      ("Batch", "Frontier dev script shipped inside the package"),
    ".json":     ("JSON", "text"),
    ".xml":      ("XML", "text"),
    ".txt":      ("Text", "text"),
    ".css":      ("CSS", "text"),
    ".html":     ("HTML", "text"),
    ".js":       ("JavaScript", "text"),
}


def image_name_from_disk(filename):
    """On-disk filename -> the `image_name` a <types> row should carry.

    cobra-tools extracts a texture entry called `foo.png` as the pair
    `foo.png.png` + `foo.png.tex`, so the reference keeps the single `.png`:

        foo.png.png -> foo.png
        foo.png.tex -> foo.png
        foo.png     -> foo.png
    """
    low = filename.lower()
    if low.endswith(".tex"):
        return filename[:-4]
    if low.endswith(".png.png"):
        return filename[:-4]
    return filename


def derive_image_name(path, root):
    """Path under `root` -> a forward-slash image_name, or None if outside it.

    Vanilla is unambiguous here: all 7,744 image_name values start at
    `uigameface/` and resolve against the folder holding the .ppuipkg. So a file
    at <root>/uigameface/icons/coolthing/jomama.png.tex becomes
    `uigameface/icons/coolthing/jomama.png`.
    """
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:          # different drive on Windows
        return None
    if rel.startswith(".."):
        return None
    return image_name_from_disk(rel.replace(os.sep, "/"))


def describe_kind(name):
    ext = os.path.splitext(name)[1].lower()
    return FILE_KINDS.get(ext, ("Unknown", "not a format seen in vanilla packages"))


def as_text(data):
    """Decode if this really is text, else None. Rejects mostly-binary blobs."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text:
        return ""
    printable = sum(ch.isprintable() or ch in "\r\n\t" for ch in text)
    return text if printable / len(text) > 0.9 else None


def hex_dump(data, limit=4096):
    """Classic offset / hex / ascii view for anything that is not text."""
    out = []
    for off in range(0, min(len(data), limit), 16):
        chunk = data[off:off + 16]
        hexes = " ".join(f"{b:02X}" for b in chunk).ljust(47)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        out.append(f"{off:08X}  {hexes}  {ascii_}")
    if len(data) > limit:
        out.append(f"... {len(data) - limit:,} more bytes")
    return "\n".join(out)


def fit_rect(src, dst_w, dst_h):
    """Largest rect of `src`'s aspect that fits in dst, centred (letterboxed).

    QSvgWidget / QSvgRenderer.render(painter) stretch to fill the target, which
    warps every icon whose widget is not the same shape as its viewBox - the
    vanilla dinosaur icons are square (viewBox "0 0 24 24") and were being
    smeared across a wide pane.
    """
    sw = max(1, src.width())
    sh = max(1, src.height())
    scale = min(dst_w / sw, dst_h / sh)
    w, h = sw * scale, sh * scale
    return QRectF((dst_w - w) / 2.0, (dst_h - h) / 2.0, w, h)


def paint_checkerboard(p, target, cell=12):
    """Checkerboard behind a target rect, so alpha reads as transparent."""
    p.save()
    p.setClipRect(target)
    light, dark = QColor("#2a3341"), QColor("#222a36")
    row = 0
    y = int(target.top()) - cell
    while y < target.bottom() + cell:
        col = 0
        x = int(target.left()) - cell
        while x < target.right() + cell:
            p.fillRect(x, y, cell, cell, light if (row + col) % 2 else dark)
            x += cell
            col += 1
        y += cell
        row += 1
    p.restore()


class RasterPreview(QWidget):
    """Aspect-correct PNG preview, never upscaled past 1:1.

    The <types> images are not in the package - this loads them from disk via
    the image root, which is also what makes a missing file obvious.
    """

    def __init__(self):
        super().__init__()
        self._image = None
        self.intrinsic = QSize(0, 0)
        self.message = "Select a reference to preview its art."

    def load_path(self, path):
        self._image = None
        self.intrinsic = QSize(0, 0)
        if path and os.path.isfile(path):
            img = QImage(path)
            if not img.isNull():
                self._image = img
                self.intrinsic = QSize(img.width(), img.height())
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_CARD))
        if self._image is None:
            p.setPen(QColor(TEXT_MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
            p.end()
            return

        target = fit_rect(self.intrinsic, self.width() - 16, self.height() - 16)
        # Do not blow a 24px icon up to fill the pane; show it at true size.
        if target.width() > self.intrinsic.width():
            target = QRectF(
                (self.width() - self.intrinsic.width()) / 2.0,
                (self.height() - self.intrinsic.height()) / 2.0,
                self.intrinsic.width(), self.intrinsic.height())
        else:
            target = QRectF(target.left() + 8, target.top() + 8,
                            target.width(), target.height())

        paint_checkerboard(p, target)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(target, self._image)
        p.end()


class SvgPreview(QWidget):
    """Aspect-correct SVG preview with a checkerboard behind the alpha."""

    def __init__(self):
        super().__init__()
        self._renderer = None
        self.intrinsic = QSize(0, 0)

    def load(self, data):
        if not data:
            self._renderer = None
            self.intrinsic = QSize(0, 0)
        else:
            r = QSvgRenderer(QByteArray(bytes(data)))
            self._renderer = r if r.isValid() else None
            self.intrinsic = r.defaultSize() if r.isValid() else QSize(0, 0)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_CARD))
        if not self._renderer:
            p.end()
            return

        target = fit_rect(self.intrinsic, self.width(), self.height())
        paint_checkerboard(p, target)
        p.setRenderHint(QPainter.Antialiasing, True)
        self._renderer.render(p, target)
        p.end()

STYLESHEET = f"""
QMainWindow, QWidget {{
    background: {BG_MAIN};
    color: {TEXT_MAIN};
    font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}}
QLabel {{ color: {TEXT_MAIN}; background: transparent; }}

QPushButton {{
    background: {BG_INPUT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 14px;
}}
QPushButton:hover  {{ background: {BG_HOVER}; border-color: {ACCENT}; }}
QPushButton:pressed{{ background: {ACCENT_DEEP}; color: #fff; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; border-color: {BORDER}; }}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-top: 2px solid {ACCENT};
    background: {BG_CARD};
    top: -1px;
}}
/* Unselected tabs sit BEHIND the pane: darker, recessed, muted, and nudged
   down. Selected gets the accent bar and merges with the pane below it.
   Hover must stay clearly weaker than selected - lifting an inactive tab to
   full white made it read as the open one. */
QTabBar::tab {{
    background: {BG_MAIN};
    color: {TEXT_MUTED};
    border: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    border-top: 2px solid transparent;
    padding: 7px 18px;
    margin-right: 2px;
    margin-top: 3px;
    min-width: 120px;
}}
/* Do NOT change font-weight or padding on :selected. QTabBar computes each
   tab's size hint from the base font BEFORE the stylesheet's selected rule
   applies, so bolding the active tab overflows its own width and clips the
   label ("Embedded files" rendered as "mbedded files"). Differentiate with
   colour, background and the accent bar only - those cost no extra width. */
QTabBar::tab:selected {{
    background: {BG_CARD};
    color: {ACCENT};
    border-top: 2px solid {ACCENT};
    border-bottom: 1px solid {BG_CARD};
    margin-top: 0px;
}}
QTabBar::tab:hover:!selected {{
    background: {BG_INPUT};
    color: {TEXT_MUTED};
}}

QListWidget, QPlainTextEdit, QTableWidget {{
    background: {BG_CARD};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 4px;
    selection-background-color: {ACCENT_DEEP};
    selection-color: #ffffff;
}}
QListWidget::item {{ padding: 5px 7px; }}
QListWidget::item:hover {{ background: {BG_HOVER}; }}
QListWidget::item:selected {{ background: {ACCENT_DEEP}; color: #ffffff; }}

QHeaderView::section {{
    background: {BG_INPUT};
    color: {TEXT_MUTED};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 6px 8px;
}}
QTableWidget {{ gridline-color: {BORDER}; }}
QTableWidget QTableCornerButton::section {{ background: {BG_INPUT}; border: none; }}

QSplitter::handle {{ background: {BORDER}; width: 3px; }}

QScrollBar:vertical, QScrollBar:horizontal {{
    background: {BG_MAIN}; border: none;
}}
QScrollBar:vertical {{ width: 11px; }}
QScrollBar:horizontal {{ height: 11px; }}
QScrollBar::handle {{ background: {BG_HOVER}; border-radius: 5px; min-height: 26px; }}
QScrollBar::handle:hover {{ background: {ACCENT_DEEP}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMessageBox, QInputDialog {{ background: {BG_CARD}; }}
QLineEdit, QSpinBox {{
    background: {BG_INPUT};
    color: {TEXT_MAIN};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 5px 8px;
    selection-background-color: {ACCENT_DEEP};
}}
QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit::placeholder {{ color: {TEXT_MUTED}; }}
"""


class PPUIPkgTool(QMainWindow):

    def __init__(self, path=None):
        super().__init__()
        self.path = None
        self.basic = "Content0/UI"
        self.files = []   # [(name, bytes)]
        self.icons = []   # [(image_name, asset_package)]
        self.dirty = False

        self.setWindowTitle("PPUIPKG Inspector")
        self.resize(1150, 720)
        # Themed here rather than only in main(), so the window matches the
        # generator however it is launched (imported, embedded, or run direct).
        self.setStyleSheet(STYLESHEET)
        self._build_ui()

        find = QShortcut(QKeySequence.Find, self)
        find.activated.connect(self._focus_search)

        # Drop copied/renamed .png + .tex pairs (or .svg) straight onto the
        # window; the reference lines are derived rather than typed out.
        self.setAcceptDrops(True)

        if path:
            self.load(path)
        else:
            self._refresh()

    # ---------------------------------------------------------------- UI ---
    def _build_ui(self):
        root = QWidget()
        outer = QVBoxLayout(root)

        bar = QHBoxLayout()
        for label, slot in (
            ("Open...", self.on_open),
            ("Save", self.on_save),
            ("Save As...", self.on_save_as),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            bar.addWidget(b)
        bar.addStretch(1)
        self.lbl_header = QLabel("No package loaded")
        self.lbl_header.setStyleSheet(f"color:{TEXT_MUTED};")
        bar.addWidget(self.lbl_header)
        outer.addLayout(bar)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_files_tab(), "Embedded files  <files>")
        self.tabs.addTab(self._build_icons_tab(), "Icon references  <types>")
        outer.addWidget(self.tabs)

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet(f"color:{SUCCESS};")
        outer.addWidget(self.lbl_status)

        self.setCentralWidget(root)

    def _build_files_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        note = QLabel(
            "SVG bytes are stored INSIDE the package - there is no loose .svg "
            "anywhere in the game. Deleting an entry here destroys the only copy.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{WARN}; padding:2px 0 4px 0;")
        lay.addWidget(note)

        split = QSplitter(Qt.Horizontal)

        left = QWidget()
        llay = QVBoxLayout(left)
        llay.setContentsMargins(0, 0, 0, 0)

        search_row = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText(
            "Search files...  (space-separated terms must all match)")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self.txt_search, 1)
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.txt_search.clear)
        search_row.addWidget(btn_clear)
        llay.addLayout(search_row)

        self.lbl_filter = QLabel("")
        self.lbl_filter.setStyleSheet(f"color:{TEXT_MUTED};")
        self.lbl_filter.setVisible(False)
        llay.addWidget(self.lbl_filter)

        self.list_files = QListWidget()
        # Ctrl/Shift multi-select: extract or export any subset, not just one.
        self.list_files.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_files.currentRowChanged.connect(self.on_file_selected)
        self.list_files.itemSelectionChanged.connect(self._update_selection_label)
        llay.addWidget(self.list_files, 1)

        split.addWidget(left)

        right = QWidget()
        rlay = QVBoxLayout(right)
        self.svg_preview = SvgPreview()
        self.svg_preview.setMinimumHeight(220)
        rlay.addWidget(self.svg_preview, 1)
        self.lbl_dims = QLabel("")
        self.lbl_dims.setStyleSheet(f"color:{TEXT_MUTED};")
        rlay.addWidget(self.lbl_dims)
        self.txt_source = QPlainTextEdit()
        self.txt_source.setReadOnly(True)
        self.txt_source.setStyleSheet("font-family:Consolas,monospace;font-size:11px;")
        rlay.addWidget(self.txt_source, 1)
        split.addWidget(right)
        split.setSizes([380, 720])
        lay.addWidget(split, 1)

        self.lbl_selection = QLabel("")
        self.lbl_selection.setStyleSheet(f"color:{TEXT_MUTED};")
        lay.addWidget(self.lbl_selection)

        btns = QHBoxLayout()
        for label, slot in (
            ("Inject / Replace...", self.on_inject),
            ("Select all", self.on_select_all),
            ("Extract...", self.on_extract),
            ("Extract all...", self.on_extract_all),
            ("Export SVG...", self.on_export_svg),
            ("Export PNG...", self.on_export_png),
            ("Rename...", self.on_rename),
            ("Delete", self.on_delete),
        ):
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)
        return page

    # ------------------------------------------------- search / selection ---
    def _focus_search(self):
        """Ctrl+F focuses the search box of whichever tab is open."""
        box = self.txt_icon_search if self.tabs.currentIndex() == 1 else self.txt_search
        box.setFocus()
        box.selectAll()

    def _on_search_changed(self, _text):
        self._refresh()
        # Show something immediately rather than an empty preview pane.
        if self.list_files.count():
            self.list_files.setCurrentRow(0)
        else:
            self.on_file_selected(-1)

    def matches_filter(self, name):
        """All space-separated terms must appear (case-insensitive, substring).

        Matched against the entry path AND its kind label, so "icon list" finds
        the .iconList manifests as readily as a filename fragment does.
        """
        terms = self.txt_search.text().lower().split() if self.txt_search else []
        if not terms:
            return True
        kind, _blurb = describe_kind(name)
        haystack = f"{name} {kind}".lower()
        return all(t in haystack for t in terms)

    def visible_indices(self):
        """Indices into self.files currently shown, in list order."""
        return [self.list_files.item(r).data(Qt.UserRole)
                for r in range(self.list_files.count())]

    def selected_rows(self):
        """Indices into self.files for the selected rows.

        NOTE: these are FILE indices, not list rows. With a filter active the
        two diverge, and every action (extract, rename, delete) must use the
        file index or it will operate on the wrong entry.
        """
        model = self.list_files.selectionModel()
        if not model:
            return []
        idxs = [self.list_files.item(i.row()).data(Qt.UserRole)
                for i in model.selectedRows()]
        return sorted(i for i in idxs if i is not None)

    def selected_files(self):
        """(name, bytes) list plus whether it came from an explicit selection.

        With nothing selected the buttons act on what is VISIBLE - the filtered
        set, not the whole package. Filtering to "dinosaurSpecies" and hitting
        Export SVG should export those, not all 991.
        """
        rows = self.selected_rows()
        if not rows:
            return [self.files[i] for i in self.visible_indices()
                    if i is not None and i < len(self.files)], False
        return [self.files[r] for r in rows if r < len(self.files)], True

    def on_select_all(self):
        """Selects the VISIBLE rows, which is what the user can see."""
        self.list_files.selectAll()

    def _update_selection_label(self):
        rows = self.selected_rows()
        filtered = bool(self.txt_search and self.txt_search.text().strip())
        if not rows:
            vis = [i for i in self.visible_indices()
                   if i is not None and i < len(self.files)]
            svg = sum(1 for i in vis if self.files[i][0].lower().endswith(".svg"))
            scope = (f"the {len(vis)} shown file(s)" if filtered
                     else f"ALL {len(self.files)} file(s)")
            self.lbl_selection.setText(
                f"Nothing selected - export/extract buttons will act on "
                f"{scope} ({svg} SVG).")
        else:
            svg = sum(1 for r in rows
                      if r < len(self.files) and self.files[r][0].lower().endswith(".svg"))
            self.lbl_selection.setText(
                f"{len(rows)} file(s) selected ({svg} SVG) - "
                f"export/extract will act on the selection.")

    def _build_icons_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)

        note = QLabel(
            "PNGs are NOT stored in the package - these rows only REFERENCE "
            "them. The real bytes live beside the .ppuipkg as a "
            "<name>.png.png + <name>.png.tex pair, and the .tex must name the "
            "same OVS stream as asset_package. The buttons below keep all "
            "three in step.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{TEXT_MUTED}; padding:2px 0 4px 0;")
        lay.addWidget(note)

        drop_hint = QLabel(
            "Tip: duplicate an existing .png + .tex pair, rename both, drop them "
            "anywhere on this window. The image_name is derived from where they "
            "sit relative to the .ppuipkg (vanilla always starts at "
            "'uigameface/'), and the asset_package is read from the .tex's ovs.")
        drop_hint.setWordWrap(True)
        drop_hint.setStyleSheet(f"color:{ACCENT}; padding:2px 0 4px 0;")
        lay.addWidget(drop_hint)

        root_row = QHBoxLayout()
        root_row.addWidget(QLabel("Image root:"))
        self.txt_image_root = QLineEdit()
        self.txt_image_root.setPlaceholderText(
            "folder the image_name paths are relative to "
            "(defaults to the folder holding the .ppuipkg)")
        self.txt_image_root.textChanged.connect(lambda _t: self._refresh_icon_status())
        root_row.addWidget(self.txt_image_root, 1)
        b_root = QPushButton("Browse...")
        b_root.clicked.connect(self.on_pick_image_root)
        root_row.addWidget(b_root)
        lay.addLayout(root_row)

        isplit = QSplitter(Qt.Horizontal)

        isearch_row = QHBoxLayout()
        self.txt_icon_search = QLineEdit()
        self.txt_icon_search.setPlaceholderText(
            "Search icons...  (matches image_name and asset_package; "
            "space-separated terms must all match)")
        self.txt_icon_search.setClearButtonEnabled(True)
        self.txt_icon_search.textChanged.connect(self._on_icon_search_changed)
        isearch_row.addWidget(self.txt_icon_search, 1)
        b_iclear = QPushButton("Clear")
        b_iclear.clicked.connect(self.txt_icon_search.clear)
        isearch_row.addWidget(b_iclear)
        lay.addLayout(isearch_row)

        self.lbl_icon_filter = QLabel("")
        self.lbl_icon_filter.setStyleSheet(f"color:{TEXT_MUTED};")
        self.lbl_icon_filter.setVisible(False)
        lay.addWidget(self.lbl_icon_filter)

        self.tbl_icons = QTableWidget(0, 3)
        self.tbl_icons.setHorizontalHeaderLabels(
            ["image_name", "asset_package", "art on disk"])
        self.tbl_icons.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_icons.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tbl_icons.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_icons.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_icons.itemChanged.connect(self.on_icon_edited)
        self.tbl_icons.itemSelectionChanged.connect(self.on_icon_row_selected)
        isplit.addWidget(self.tbl_icons)

        iright = QWidget()
        irlay = QVBoxLayout(iright)
        irlay.setContentsMargins(8, 0, 0, 0)
        self.png_preview = RasterPreview()
        self.png_preview.setMinimumHeight(240)
        irlay.addWidget(self.png_preview, 1)
        self.lbl_png_info = QLabel("")
        self.lbl_png_info.setStyleSheet(f"color:{TEXT_MUTED};")
        self.lbl_png_info.setWordWrap(True)
        irlay.addWidget(self.lbl_png_info)
        isplit.addWidget(iright)
        isplit.setSizes([700, 400])

        lay.addWidget(isplit, 1)

        btns = QHBoxLayout()
        for label, slot, tip in (
            ("Inject PNG (new)...", self.on_png_add,
             "Pick a PNG: writes the .png + .tex pair and ADDS the matching "
             "<types> reference."),
            ("Replace PNG...", self.on_png_replace,
             "Swap the art for the selected reference. Rewrites the .tex to "
             "the new image's dimensions; the reference is untouched."),
            ("Reveal art", self.on_png_reveal,
             "Open the folder containing the selected reference's art."),
            ("Add reference", self.on_icon_add,
             "Add an empty <types> row to fill in by hand."),
            ("Delete reference", self.on_icon_delete,
             "Remove the <types> row. Does NOT delete files from disk."),
        ):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.lbl_icon_status = QLabel("")
        self.lbl_icon_status.setStyleSheet(f"color:{TEXT_MUTED};")
        self.lbl_icon_status.setWordWrap(True)
        lay.addWidget(self.lbl_icon_status)
        return page

    def matches_icon_filter(self, image_name, asset_package):
        """All space-separated terms must appear in the path OR the package."""
        box = getattr(self, "txt_icon_search", None)
        terms = box.text().lower().split() if box else []
        if not terms:
            return True
        haystack = f"{image_name} {asset_package}".lower()
        return all(t in haystack for t in terms)

    def _on_icon_search_changed(self, _text):
        self._refresh()
        if self.tbl_icons.rowCount():
            self.tbl_icons.selectRow(0)
        self.on_icon_row_selected()

    def icon_index_at(self, row):
        """Map a TABLE ROW to an index into self.icons (they differ when filtered)."""
        if row < 0 or row >= self.tbl_icons.rowCount():
            return -1
        cell = self.tbl_icons.item(row, 0)
        idx = cell.data(Qt.UserRole) if cell else None
        return idx if idx is not None and idx < len(self.icons) else -1

    def on_icon_row_selected(self):
        """Load the selected reference's art off disk and describe it."""
        row = self.icon_index_at(self.tbl_icons.currentRow())
        if row < 0 or row >= len(self.icons):
            self.png_preview.message = "Select a reference to preview its art."
            self.png_preview.load_path(None)
            self.lbl_png_info.setText("")
            return

        image_name, pkg = self.icons[row]
        root = self.image_root()
        png, tex = find_image_pair(root, image_name) if root else (None, None)

        if not png:
            self.png_preview.message = (
                "No art on disk for this reference.\n"
                "Use 'Inject PNG (new)...' or fix the image root.")
            self.png_preview.load_path(None)
            self.lbl_png_info.setText(
                f"{image_name}\nasset_package: {pkg}\nexpected under: {root or '(none)'}")
            return

        self.png_preview.load_path(png)

        size = png_size(png)
        info = read_tex(tex) if tex else None
        lines = [image_name, f"asset_package: {pkg}"]
        if size:
            lines.append(f"PNG: {size[0]}x{size[1]}")
        if info:
            tex_size = (info.get("width"), info.get("height"))
            flag = "" if (not size or tex_size == size) else "   <-- MISMATCH"
            lines.append(
                f"tex: {tex_size[0]}x{tex_size[1]}  "
                f"{info.get('compression_type', '?')}  "
                f"ovs={info.get('ovs', '?')}{flag}")
            if info.get("ovs") and info["ovs"] != pkg:
                lines.append(
                    f"WARNING: tex ovs '{info['ovs']}' != asset_package '{pkg}' "
                    f"- the header and the reference disagree about the stream.")
        else:
            lines.append("tex: MISSING - the OVL will pack without this texture.")
        self.lbl_png_info.setText("\n".join(lines))

    # ------------------------------------------------------ drag & drop ---
    DROPPABLE = (".png", ".tex", ".svg")

    def dragEnterEvent(self, event):
        if not event.mimeData().hasUrls():
            return
        for url in event.mimeData().urls():
            if url.toLocalFile().lower().endswith(self.DROPPABLE):
                event.acceptProposedAction()
                return

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        paths = [p for p in paths
                 if p and os.path.isfile(p) and p.lower().endswith(self.DROPPABLE)]
        if not paths:
            return
        event.acceptProposedAction()
        self.handle_dropped(paths)

    def handle_dropped(self, paths):
        """Add references (and embed SVGs) for dropped files.

        A dropped .png and .tex of the SAME icon collapse to one reference -
        dragging both halves of a pair is the normal case.
        """
        if not self.path:
            QMessageBox.information(
                self, "Drop", "Open a package first, so paths can be made "
                              "relative to it.")
            return

        root = self.image_root()
        svgs = [p for p in paths if p.lower().endswith(".svg")]
        arts = [p for p in paths if not p.lower().endswith(".svg")]

        added, updated, embedded, outside, problems = [], [], [], [], []

        # --- SVGs go in the <files> section, byte-for-byte ------------------
        for path in svgs:
            with open(path, "rb") as f:
                data = f.read()
            name = derive_image_name(path, root)
            if not name:
                # Outside the tree: still embeddable, just needs a name.
                name = f"UIGameface/img/icons/{os.path.basename(path)}"
            existing = [i for i, (n, _d) in enumerate(self.files) if n == name]
            if existing:
                self.files[existing[0]] = (name, data)
                updated.append(name)
            else:
                self.files.append((name, data))
                embedded.append(name)

        # --- PNG / TEX become <types> references ---------------------------
        by_ref = {}
        for path in arts:
            name = derive_image_name(path, root)
            if not name:
                outside.append(path)
                continue
            by_ref.setdefault(name, []).append(path)

        for image_name, members in sorted(by_ref.items()):
            png, tex = find_image_pair(root, image_name)
            if not png:
                problems.append(f"{image_name} - no .png beside it "
                                f"(expected {image_name}.png)")
                continue
            if not tex:
                problems.append(f"{image_name} - no .tex beside it; the OVL "
                                f"would pack without this texture")

            size = png_size(png)
            info = read_tex(tex) if tex else None
            if size and info and (info.get("width"), info.get("height")) != size:
                problems.append(
                    f"{image_name} - tex says "
                    f"{info.get('width')}x{info.get('height')} but the png is "
                    f"{size[0]}x{size[1]}")

            # asset_package, in order of trustworthiness:
            #   1. the dropped .tex's own ovs
            #   2. what other references in the same folder already use
            #   3. ask
            pkg = (info or {}).get("ovs")
            if not pkg:
                folder = os.path.dirname(image_name)
                siblings = [p for n, p in self.icons
                            if os.path.dirname(n) == folder]
                pkg = siblings[0] if siblings else None
            if not pkg:
                choices = self._known_packages()
                if choices:
                    pkg, ok = QInputDialog.getItem(
                        self, "Asset package",
                        f"OVS stream for {os.path.basename(image_name)}:",
                        choices + ["<new...>"], 0, False)
                    if not ok:
                        continue
                    if pkg == "<new...>":
                        pkg = None
                if not pkg:
                    pkg, ok = QInputDialog.getText(
                        self, "Asset package",
                        f"OVS stream for {os.path.basename(image_name)}:",
                        text="MyMod_Icons")
                    if not ok or not pkg.strip():
                        continue
                    pkg = pkg.strip()

            existing = [i for i, (n, _p) in enumerate(self.icons) if n == image_name]
            if existing:
                self.icons[existing[0]] = (image_name, pkg)
                updated.append(f"{image_name}  [{pkg}]")
            else:
                self.icons.append((image_name, pkg))
                added.append(f"{image_name}  [{pkg}]")

        if added or updated or embedded:
            self._mark_dirty()
            self.tabs.setCurrentIndex(1 if (added or updated) and not embedded else 0)

        lines = []
        if added:
            lines.append(f"Added {len(added)} reference(s):\n  " + "\n  ".join(added[:8]))
        if updated:
            lines.append(f"Updated {len(updated)}:\n  " + "\n  ".join(updated[:8]))
        if embedded:
            lines.append(f"Embedded {len(embedded)} SVG(s):\n  " + "\n  ".join(embedded[:8]))
        if outside:
            lines.append(
                f"{len(outside)} file(s) are NOT under the image root and were "
                f"skipped - copy them under:\n  {root}\n  " +
                "\n  ".join(os.path.basename(p) for p in outside[:6]))
        if problems:
            lines.append("Warnings:\n  " + "\n  ".join(problems[:8]))
        if not lines:
            lines.append("Nothing to do.")
        if added or updated or embedded:
            lines.append("Save the package to write these changes.")

        QMessageBox.information(self, "Dropped files", "\n\n".join(lines))
        self.lbl_status.setText(
            f"Drop: +{len(added)} added, {len(updated)} updated, "
            f"{len(embedded)} embedded, {len(outside)} skipped.")

    # ------------------------------------------------------ PNG plumbing ---
    def image_root(self):
        """Folder the <types> image_name paths resolve against.

        Defaults to the directory holding the .ppuipkg, which is the actual
        convention: a mod's package sits at <Mod>/UI/<Mod>/x.ppuipkg with its
        art under <Mod>/UI/<Mod>/uigameface/..., and vanilla's extracted
        Content0/UI package sits beside its own uigameface/ tree the same way.
        """
        typed = self.txt_image_root.text().strip() if self.txt_image_root else ""
        if typed:
            return typed
        return os.path.dirname(self.path) if self.path else ""

    def on_pick_image_root(self):
        start = self.image_root() or ""
        out = QFileDialog.getExistingDirectory(
            self, "Folder the image_name paths are relative to", start, DLG_OPTS)
        if out:
            self.txt_image_root.setText(out)

    def _refresh_icon_status(self):
        """Fill the 'art on disk' column for every reference."""
        root = self.image_root()
        if not hasattr(self, "tbl_icons"):
            return

        # Status is computed for EVERY reference, not just the visible rows, so
        # the summary underneath still counts what a filter is hiding.
        status = {}
        missing = 0
        for idx, (img, _pkg) in enumerate(self.icons):
            png, tex = find_image_pair(root, img) if root else (None, None)

            if png and tex:
                info = read_tex(tex) or {}
                size = png_size(png)
                if size and (info.get("width"), info.get("height")) != size:
                    text = (f"size mismatch: png {size[0]}x{size[1]} "
                            f"vs tex {info.get('width')}x{info.get('height')}")
                    colour = ERROR
                    missing += 1
                else:
                    text = f"OK  {size[0]}x{size[1]}" if size else "OK"
                    colour = SUCCESS
            elif png:
                text = "no .tex - will not pack"
                colour = ERROR
                missing += 1
            elif tex:
                text = "no .png"
                colour = ERROR
                missing += 1
            else:
                text = "missing"
                colour = WARN
                missing += 1
            status[idx] = (text, colour)

        self.tbl_icons.blockSignals(True)
        for row in range(self.tbl_icons.rowCount()):
            idx = self.icon_index_at(row)
            if idx < 0:
                continue
            text, colour = status[idx]
            cell = QTableWidgetItem(text)
            cell.setForeground(QColor(colour))
            cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            self.tbl_icons.setItem(row, 2, cell)
        self.tbl_icons.blockSignals(False)

        if not root:
            self.lbl_icon_status.setText(
                "No image root - open a package, or set one above.")
            self.lbl_icon_status.setStyleSheet(f"color:{TEXT_MUTED};")
            return

        orphans = self.scan_orphan_images(root)
        bits = []
        if missing:
            bits.append(f"{missing} of {len(self.icons)} reference(s) have no "
                        f"usable art")
        else:
            bits.append(f"All {len(self.icons)} reference(s) resolve")
        if orphans:
            # Art sitting in the tree that nothing points at: the game will
            # never show it, and it is usually a typo'd image_name.
            shown = ", ".join(orphans[:3])
            more = f" (+{len(orphans) - 3} more)" if len(orphans) > 3 else ""
            bits.append(f"{len(orphans)} PNG(s) on disk are NOT referenced: "
                        f"{shown}{more}")
        bits.append(f"root: {root}")

        self.lbl_icon_status.setText("   |   ".join(bits))
        self.lbl_icon_status.setStyleSheet(
            f"color:{WARN if (missing or orphans) else SUCCESS};")

    def scan_orphan_images(self, root):
        """PNGs under the image root that no <types> row references.

        Walks the folders beside the package and reports art the package has
        forgotten about - the mirror of a reference whose art is missing.
        """
        if not root or not os.path.isdir(root) or not self.icons:
            return []

        referenced = set()
        folders = set()
        for img, _pkg in self.icons:
            rel = img.replace("\\", "/")
            referenced.add(rel.lower())
            # cobra-tools writes foo.png as foo.png.png on disk.
            referenced.add(rel.lower() + ".png")
            folders.add(os.path.dirname(rel))

        # Only look in folders THIS package already uses. Scanning the whole
        # root is meaningless for vanilla, where one UI/ directory holds the art
        # for all 24 packages and every other package's images look orphaned.
        orphans = []
        for folder in sorted(folders):
            abs_folder = os.path.join(root, folder.replace("/", os.sep))
            if not os.path.isdir(abs_folder):
                continue
            for name in sorted(os.listdir(abs_folder)):
                if not name.lower().endswith(".png"):
                    continue
                full = os.path.join(abs_folder, name)
                if not os.path.isfile(full):
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                low = rel.lower()
                plain = low[:-4] if low.endswith(".png.png") else low
                if low in referenced or plain in referenced:
                    continue
                orphans.append(rel)
        return sorted(orphans)

    def _known_packages(self):
        """asset_package values already used in this file, most common first."""
        counts = {}
        for _img, pkg in self.icons:
            if pkg:
                counts[pkg] = counts.get(pkg, 0) + 1
        return [p for p, _c in sorted(counts.items(), key=lambda kv: -kv[1])]

    def on_png_add(self):
        """WAY 1 - inject a new PNG: writes the pair AND adds the reference."""
        if not self.path:
            QMessageBox.information(
                self, "Inject PNG", "Open a package first so the image root is known.")
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "PNG to inject", "", "PNG image (*.png);;All files (*)",
            options=DLG_OPTS)
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()

        size = png_size(data)
        if not size:
            QMessageBox.warning(
                self, "Not a PNG",
                "That file has no PNG header. The .tex records the image's "
                "dimensions, so they cannot be guessed - refusing.")
            return

        stem = os.path.splitext(os.path.basename(path))[0].lower()
        # Seed from an existing row so the convention is obvious rather than invented.
        sample = self.icons[0][0] if self.icons else \
            "uigameface/img/dinosaurspecies/small/x.png"
        folder = os.path.dirname(sample)
        default_name = f"{folder}/{stem}.png" if folder else f"{stem}.png"

        image_name, ok = QInputDialog.getText(
            self, "Reference path",
            "image_name - the path the GAME looks this icon up by,\n"
            "relative to the image root:",
            text=default_name)
        if not ok or not image_name.strip():
            return
        image_name = image_name.strip().replace("\\", "/")

        packages = self._known_packages()
        default_pkg = packages[0] if packages else "MyMod_Icons"
        if packages:
            pkg, ok = QInputDialog.getItem(
                self, "Asset package",
                "OVS stream this texture belongs to.\n"
                "The .tex header is written with ovs set to this value:",
                packages + ["<new...>"], 0, False)
            if not ok:
                return
            if pkg == "<new...>":
                pkg, ok = QInputDialog.getText(
                    self, "New asset package", "Name:", text=default_pkg)
                if not ok or not pkg.strip():
                    return
                pkg = pkg.strip()
        else:
            pkg, ok = QInputDialog.getText(
                self, "Asset package", "OVS stream name:", text=default_pkg)
            if not ok or not pkg.strip():
                return
            pkg = pkg.strip()

        existing = [i for i, (img, _p) in enumerate(self.icons) if img == image_name]
        if existing:
            if QMessageBox.question(
                    self, "Reference exists",
                    f"'{image_name}' is already referenced.\n\n"
                    f"Overwrite its art and update the reference?") != QMessageBox.Yes:
                return

        try:
            png_path, tex_path, size = install_png(
                self.image_root(), image_name, data, pkg)
        except Exception as exc:
            QMessageBox.critical(self, "Inject failed", str(exc))
            return

        if existing:
            self.icons[existing[0]] = (image_name, pkg)
        else:
            self.icons.append((image_name, pkg))

        self._mark_dirty()
        QMessageBox.information(
            self, "PNG injected",
            f"Wrote the pair ({size[0]}x{size[1]}):\n{png_path}\n{tex_path}\n\n"
            f"and {'updated' if existing else 'added'} the reference\n"
            f"  {image_name}  ->  {pkg}\n\n"
            f"Save the package to write the <types> change.")
        self.lbl_status.setText(f"Injected {image_name} ({pkg}) - unsaved reference change.")

    def on_png_replace(self):
        """WAY 2 - swap art for an EXISTING reference. Reference unchanged."""
        row = self.icon_index_at(self.tbl_icons.currentRow())
        if row < 0:
            QMessageBox.information(
                self, "Replace PNG", "Select a reference row first.")
            return
        if not self.image_root():
            QMessageBox.information(
                self, "Replace PNG", "Set an image root first.")
            return

        image_name, pkg = self.icons[row]
        path, _ = QFileDialog.getOpenFileName(
            self, f"New art for {os.path.basename(image_name)}", "",
            "PNG image (*.png);;All files (*)", options=DLG_OPTS)
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()

        size = png_size(data)
        if not size:
            QMessageBox.warning(self, "Not a PNG", "That file has no PNG header.")
            return

        old_png, old_tex = find_image_pair(self.image_root(), image_name)
        old_info = read_tex(old_tex) if old_tex else None
        old_size = (old_info.get("width"), old_info.get("height")) if old_info else None

        warn = ""
        if old_size and old_size != size:
            warn = (f"\n\nNOTE: dimensions change {old_size[0]}x{old_size[1]} "
                    f"-> {size[0]}x{size[1]}. The .tex is rewritten to match, "
                    f"but UI layouts expecting the old size may look wrong.")

        if QMessageBox.question(
                self, "Replace art",
                f"Replace the art for:\n  {image_name}\n\n"
                f"asset_package: {pkg}{warn}") != QMessageBox.Yes:
            return

        try:
            # Keep the stream's existing texel and compression rather than
            # resetting them to defaults on a simple art swap.
            png_path, tex_path, size = install_png(
                self.image_root(), image_name, data, pkg,
                texel=(old_info or {}).get("texel"),
                compression=(old_info or {}).get("compression_type",
                                                 DEFAULT_COMPRESSION))
        except Exception as exc:
            QMessageBox.critical(self, "Replace failed", str(exc))
            return

        self._refresh_icon_status()
        self.on_icon_row_selected()
        QMessageBox.information(
            self, "Art replaced",
            f"Rewrote ({size[0]}x{size[1]}):\n{png_path}\n{tex_path}\n\n"
            f"The <types> reference did not change, so the package itself "
            f"needs no save.")
        self.lbl_status.setText(f"Replaced art for {image_name}.")

    def on_png_reveal(self):
        row = self.icon_index_at(self.tbl_icons.currentRow())
        if row < 0:
            return
        image_name, _pkg = self.icons[row]
        png, tex = find_image_pair(self.image_root(), image_name)
        target = png or tex
        if not target:
            QMessageBox.information(
                self, "Reveal art",
                f"Nothing on disk for:\n  {image_name}\n\nunder "
                f"{self.image_root() or '(no image root)'}")
            return
        os.startfile(os.path.dirname(target))

    # ------------------------------------------------------------- state ---
    def _refresh(self):
        # Rebuilding the list drops the selection; suppress the label churn so
        # it is computed once at the end from the real state.
        self.list_files.blockSignals(True)
        self.list_files.clear()
        shown = 0
        for idx, (name, data) in enumerate(self.files):
            if not self.matches_filter(name):
                continue
            kind, _blurb = describe_kind(name)
            item = QListWidgetItem(f"[{kind}]  {name}   ({len(data):,} B)",
                                   self.list_files)
            # The row is NOT the file index once a filter is active - every
            # action reads this back instead of using the row number.
            item.setData(Qt.UserRole, idx)
            item.setToolTip(name)
            if kind == "Unknown":
                item.setForeground(QColor(WARN))
            shown += 1
        self.list_files.blockSignals(False)

        if self.txt_search and self.txt_search.text().strip():
            self.lbl_filter.setText(
                f"Showing {shown} of {len(self.files)} embedded file(s)."
                + ("   No match - try fewer terms." if not shown else ""))
            self.lbl_filter.setStyleSheet(
                f"color:{WARN if not shown else TEXT_MUTED};")
            self.lbl_filter.setVisible(True)
        else:
            self.lbl_filter.setVisible(False)

        self.tbl_icons.blockSignals(True)
        visible = [(i, img, pkg) for i, (img, pkg) in enumerate(self.icons)
                   if self.matches_icon_filter(img, pkg)]
        self.tbl_icons.setRowCount(len(visible))
        for row, (idx, img, pkg) in enumerate(visible):
            cell = QTableWidgetItem(img)
            # Same trap as the files list: with a filter on, the table row is
            # NOT the index into self.icons. Every action reads this back.
            cell.setData(Qt.UserRole, idx)
            self.tbl_icons.setItem(row, 0, cell)
            self.tbl_icons.setItem(row, 1, QTableWidgetItem(pkg))
        self.tbl_icons.blockSignals(False)

        if self.txt_icon_search and self.txt_icon_search.text().strip():
            self.lbl_icon_filter.setText(
                f"Showing {len(visible)} of {len(self.icons)} reference(s)."
                + ("   No match - try fewer terms." if not visible else ""))
            self.lbl_icon_filter.setStyleSheet(
                f"color:{WARN if not visible else TEXT_MUTED};")
            self.lbl_icon_filter.setVisible(True)
        else:
            self.lbl_icon_filter.setVisible(False)

        # Resolve every reference against the folders beside the package, so
        # missing art (and art nothing points at) is visible on load.
        self._refresh_icon_status()
        self._update_selection_label()

        star = " *" if self.dirty else ""
        name = os.path.basename(self.path) if self.path else "No package loaded"
        self.lbl_header.setText(
            f"{name}{star}   basic_path={self.basic}   "
            f"file_count={len(self.files)}  icondata_count={len(self.icons)}")

    def _mark_dirty(self):
        self.dirty = True
        self._refresh()

    def load(self, path):
        try:
            self.basic, self.files, self.icons = read_package(path)
        except Exception as exc:
            QMessageBox.critical(self, "Cannot read package", str(exc))
            return
        self.path = path
        self.dirty = False
        # Drop any stale filter, or a new package can open looking empty.
        for box in (self.txt_search, self.txt_icon_search):
            if box:
                box.blockSignals(True)
                box.clear()
                box.blockSignals(False)
        self._refresh()
        self.lbl_status.setText(
            f"Loaded {len(self.files)} embedded file(s), {len(self.icons)} icon reference(s).")
        if self.files:
            self.list_files.setCurrentRow(0)

    # ------------------------------------------------------------ actions --
    def on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ppuipkg", "", "PPUIPKG (*.ppuipkg);;All files (*)",
            options=DLG_OPTS)
        if path:
            self.load(path)

    def _write(self, path):
        # cobra-tools sorts streamed archives case-sensitively. Any local OVS
        # name before STATIC makes that stream archive 0, which JWE3's native
        # UI overlay loader cannot safely load. Catch this before writing a
        # package that appears valid but will crash once packed.
        root = self.image_root() or os.path.dirname(path)
        unsafe = []
        for image_name, _pkg in self.icons:
            _png, tex = find_image_pair(root, image_name) if root else (None, None)
            info = read_tex(tex) if tex else None
            ovs = info.get("ovs") if info else None
            if ovs and ovs < "STATIC":
                unsafe.append(f"{image_name}: ovs={ovs}")
        if unsafe:
            QMessageBox.critical(
                self, "Unsafe UI archive order",
                "These local texture streams sort before STATIC and can crash "
                "JWE3 during LoadOverlay:\n\n" + "\n".join(unsafe[:12]) +
                "\n\nUse lowercase, namespaced asset_package/ovs names and "
                "keep each .tex ovs identical to its PPUIPKG asset_package.")
            return False
        try:
            write_package(path, self.basic, self.files, self.icons)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        # Read it straight back: a package that cannot be re-read is a package
        # whose embedded art is gone.
        try:
            _b, f2, i2 = read_package(path)
            if f2 != self.files or i2 != self.icons:
                QMessageBox.warning(
                    self, "Verify failed",
                    "The saved package did not read back identically. "
                    "Keep your original until this is understood.")
                return False
        except Exception as exc:
            QMessageBox.warning(self, "Verify failed", f"Saved but unreadable: {exc}")
            return False

        self.path = path
        self.dirty = False
        self._refresh()
        self.lbl_status.setText(f"Saved and verified: {path}")
        return True

    def on_save(self):
        if not self.path:
            return self.on_save_as()
        self._write(self.path)

    def on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ppuipkg as", self.path or "", "PPUIPKG (*.ppuipkg)",
            options=DLG_OPTS)
        if path:
            self._write(path)

    def file_index_at(self, row):
        """Map a LIST ROW to an index into self.files (they differ when filtered)."""
        if row < 0 or row >= self.list_files.count():
            return -1
        idx = self.list_files.item(row).data(Qt.UserRole)
        return idx if idx is not None and idx < len(self.files) else -1

    def on_file_selected(self, row):
        self.svg_preview.load(None)
        self.txt_source.setPlainText("")
        self.lbl_dims.setText("")
        idx = self.file_index_at(row)
        if idx < 0:
            return
        name, data = self.files[idx]
        kind, blurb = describe_kind(name)

        if name.lower().endswith(".svg"):
            self.svg_preview.load(data)
            self.svg_preview.setVisible(True)
            size = self.svg_preview.intrinsic
            if size.width() and size.height():
                from math import gcd
                g = gcd(size.width(), size.height()) or 1
                self.lbl_dims.setText(
                    f"{kind}  |  viewBox {size.width()}x{size.height()} px  |  aspect "
                    f"{size.width() // g}:{size.height() // g}  |  {len(data):,} bytes")
            else:
                self.lbl_dims.setText(
                    f"{kind}  |  {len(data):,} bytes - did not parse, no preview")
            self.txt_source.setPlainText(data.decode("utf-8", "replace"))
            return

        # Non-SVG: no canvas to draw, so give the space to the source view.
        self.svg_preview.load(None)
        self.svg_preview.setVisible(False)

        text = as_text(data)
        if text is not None:
            lines = text.count("\n") + 1
            self.lbl_dims.setText(
                f"{kind}  |  {blurb}  |  {len(data):,} bytes, {lines:,} line(s)")
            self.txt_source.setPlainText(text)
        else:
            self.lbl_dims.setText(
                f"{kind}  |  binary, showing hex  |  {len(data):,} bytes")
            self.txt_source.setPlainText(hex_dump(data))

    def on_inject(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Inject file", "",
            "Package contents (*.svg *.iconList *.iconSet *.octl *.json *.xml *.txt);;"
            "SVG (*.svg);;All files (*)",
            options=DLG_OPTS)
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()

        idx = self.file_index_at(self.list_files.currentRow())
        default = self.files[idx][0] if idx >= 0 else (
            f"UIGameface/img/icons/dinosaurSpecies/{os.path.basename(path)}")
        name, ok = QInputDialog.getText(
            self, "Entry name",
            "Path inside the package (this is what the game looks up):",
            text=default)
        if not ok or not name.strip():
            return
        name = name.strip()

        for i, (existing, _d) in enumerate(self.files):
            if existing == name:
                if QMessageBox.question(
                        self, "Replace entry",
                        f"'{name}' already exists. Replace its bytes?") != QMessageBox.Yes:
                    return
                self.files[i] = (name, data)
                break
        else:
            self.files.append((name, data))

        self._mark_dirty()
        self.lbl_status.setText(f"Injected {len(data):,} B as '{name}' (unsaved).")

    def _write_flat(self, items, out):
        """Write (name, bytes) into one folder by basename, suffixing clashes."""
        written, clashes = 0, 0
        for name, data in items:
            base = os.path.basename(name)
            dest = os.path.join(out, base)
            if os.path.exists(dest):
                stem, ext = os.path.splitext(base)
                n = 2
                while os.path.exists(os.path.join(out, f"{stem}_{n}{ext}")):
                    n += 1
                dest = os.path.join(out, f"{stem}_{n}{ext}")
                clashes += 1
            with open(dest, "wb") as f:
                f.write(data)
            written += 1
        return written, clashes

    def on_extract(self):
        rows = self.selected_rows()
        if not rows:
            QMessageBox.information(
                self, "Extract",
                "Select one or more files first, or use 'Extract all...'.")
            return

        # One file: let the user name it. Several: pick a destination folder.
        if len(rows) == 1:
            name, data = self.files[rows[0]]
            path, _ = QFileDialog.getSaveFileName(
                self, "Extract to", os.path.basename(name), "All files (*)",
                options=DLG_OPTS)
            if not path:
                return
            with open(path, "wb") as f:
                f.write(data)
            self.lbl_status.setText(f"Extracted {name} -> {path}")
            return

        out = QFileDialog.getExistingDirectory(
            self, f"Extract {len(rows)} selected file(s) into", "", DLG_OPTS)
        if not out:
            return
        written, clashes = self._write_flat(
            [self.files[r] for r in rows], out)
        msg = f"Extracted {written} file(s) to:\n{out}"
        if clashes:
            msg += f"\n\n{clashes} name clash(es) suffixed _2, _3, ..."
        QMessageBox.information(self, "Extract", msg)
        self.lbl_status.setText(f"Extracted {written} file(s) -> {out}")

    def on_extract_all(self):
        if not self.files:
            return
        out = QFileDialog.getExistingDirectory(self, "Extract all into", "", DLG_OPTS)
        if not out:
            return
        for name, data in self.files:
            dest = os.path.join(out, name.replace("/", os.sep))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(data)
        self.lbl_status.setText(f"Extracted {len(self.files)} file(s) -> {out}")

    def on_export_svg(self):
        """Dump every embedded SVG into one flat folder, as SVG.

        Distinct from "Extract all...", which writes EVERY embedded file and
        rebuilds the nested UIGameface/img/... tree. This is the "just give me
        the vector art" button.
        """
        scope, from_selection = self.selected_files()
        svgs = [(n, d) for n, d in scope if n.lower().endswith(".svg")]
        if not svgs:
            QMessageBox.information(
                self, "Export SVG",
                "No SVGs in the selection." if from_selection
                else "No SVGs in this package.")
            return

        where = "selected" if from_selection else "all"
        out = QFileDialog.getExistingDirectory(
            self, f"Export {len(svgs)} {where} SVG(s) into", "", DLG_OPTS)
        if not out:
            return

        written, clashes = self._write_flat(svgs, out)
        msg = (f"Exported {written} SVG(s) "
               f"({'selection' if from_selection else 'whole package'}) to:\n{out}")
        if clashes:
            msg += f"\n\n{clashes} name clash(es) were suffixed _2, _3, ..."
        QMessageBox.information(self, "Export SVG", msg)
        self.lbl_status.setText(f"Exported {written} SVG(s) -> {out}")

    def on_export_png(self):
        """Rasterise every embedded SVG into a folder as PNG."""
        scope, from_selection = self.selected_files()
        svgs = [(n, d) for n, d in scope if n.lower().endswith(".svg")]
        if not svgs:
            QMessageBox.information(
                self, "Export PNG",
                "No SVGs in the selection." if from_selection
                else "No SVGs in this package.")
            return

        where = "selected" if from_selection else "all"
        out = QFileDialog.getExistingDirectory(
            self, f"Export {len(svgs)} {where} SVG(s) as PNG into", "", DLG_OPTS)
        if not out:
            return

        size, ok = QInputDialog.getInt(self, "PNG size", "Longest edge (px):",
                                       256, 16, 4096, 16)
        if not ok:
            return

        done, failed = 0, []
        for name, data in svgs:
            renderer = QSvgRenderer(QByteArray(data))
            if not renderer.isValid():
                failed.append(name)
                continue

            # Honour the SVG's own aspect: scale the LONGEST edge to `size`
            # rather than forcing a square, which warped non-square icons.
            native = renderer.defaultSize()
            nw = max(1, native.width())
            nh = max(1, native.height())
            scale = size / float(max(nw, nh))
            out_w = max(1, int(round(nw * scale)))
            out_h = max(1, int(round(nh * scale)))

            img = QImage(out_w, out_h, QImage.Format_ARGB32)
            img.fill(QColor(0, 0, 0, 0))
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing, True)
            renderer.render(p, QRectF(0, 0, out_w, out_h))
            p.end()
            dest = os.path.join(
                out, os.path.splitext(os.path.basename(name))[0] + ".png")
            if img.save(dest, "PNG"):
                done += 1
            else:
                failed.append(name)

        msg = (f"Exported {done}/{len(svgs)} SVG(s) with the longest edge at "
               f"{size}px (aspect preserved) to:\n{out}")
        if failed:
            msg += f"\n\nFailed ({len(failed)}): " + ", ".join(failed[:6])
        QMessageBox.information(self, "Export PNG", msg)
        self.lbl_status.setText(f"Exported {done} PNG(s) -> {out}")

    def on_rename(self):
        idx = self.file_index_at(self.list_files.currentRow())
        if idx < 0:
            return
        name, data = self.files[idx]
        new, ok = QInputDialog.getText(self, "Rename entry", "New path:", text=name)
        if ok and new.strip() and new.strip() != name:
            self.files[idx] = (new.strip(), data)
            self._mark_dirty()

    def on_delete(self):
        rows = self.selected_rows()
        if not rows:
            return
        if len(rows) == 1:
            what = f"'{self.files[rows[0]][0]}'"
        else:
            what = f"{len(rows)} entries"
        if QMessageBox.question(
                self, "Delete entries",
                f"Delete {what}?\n\nThe bytes live only in this package - "
                f"there is no copy on disk.") != QMessageBox.Yes:
            return
        # Reverse order so earlier indices stay valid as we remove.
        for row in sorted(rows, reverse=True):
            del self.files[row]
        self._mark_dirty()

    def on_icon_edited(self, item):
        col = item.column()
        idx = self.icon_index_at(item.row())
        if idx < 0:
            return
        img, pkg = self.icons[idx]
        self.icons[idx] = (item.text(), pkg) if col == 0 else (img, item.text())
        self.dirty = True

    def on_icon_add(self):
        # A new row would usually be hidden by an active filter; clear it so the
        # row the user just asked for is actually on screen.
        if self.txt_icon_search and self.txt_icon_search.text().strip():
            self.txt_icon_search.blockSignals(True)
            self.txt_icon_search.clear()
            self.txt_icon_search.blockSignals(False)
        self.icons.append(("uigameface/img/dinosaurspecies/small/dinosaurs_small_x.png",
                           "MyMod_Dinosaur_Small"))
        self._mark_dirty()

    def on_icon_delete(self):
        idx = self.icon_index_at(self.tbl_icons.currentRow())
        if idx < 0:
            return
        del self.icons[idx]
        self._mark_dirty()

    def closeEvent(self, event):
        if self.dirty and QMessageBox.question(
                self, "Unsaved changes",
                "Discard unsaved changes?") != QMessageBox.Yes:
            event.ignore()
            return
        event.accept()


def apply_theme(app):
    """Dark Fusion palette + the stylesheet.

    The stylesheet alone leaves the NATIVE bits light - QFileDialog, QMessageBox
    and the window chrome around them are painted from the palette, not from
    QSS, which is why the tool still read as white in places. Fusion is the only
    built-in style that fully honours a custom palette on Windows.
    """
    from PyQt5.QtGui import QPalette
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG_MAIN))
    pal.setColor(QPalette.WindowText, QColor(TEXT_MAIN))
    pal.setColor(QPalette.Base, QColor(BG_CARD))
    pal.setColor(QPalette.AlternateBase, QColor(BG_INPUT))
    pal.setColor(QPalette.ToolTipBase, QColor(BG_CARD))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT_MAIN))
    pal.setColor(QPalette.Text, QColor(TEXT_MAIN))
    pal.setColor(QPalette.Button, QColor(BG_INPUT))
    pal.setColor(QPalette.ButtonText, QColor(TEXT_MAIN))
    pal.setColor(QPalette.BrightText, QColor(ERROR))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT_DEEP))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(TEXT_MUTED))

    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)


def main():
    app = QApplication(sys.argv)
    apply_theme(app)
    path = sys.argv[1] if len(sys.argv) > 1 else None
    win = PPUIPkgTool(path)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
