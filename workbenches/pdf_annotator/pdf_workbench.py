"""
Workbench 1: PDF Bubble Annotator
Full-featured FAI / PPAP ballooning workbench.

Digested and converted from the HTML5 reference implementation
(pdf.js viewer + pdf-lib vector export) to native PyQt6 + PyMuPDF:
open / page / zoom, click-to-add draggable balloons with per-balloon style,
undo / redo, vector PDF export, PNG / batch PNG export, and printing.
"""
import json
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGraphicsView, QGraphicsScene,
    QGraphicsEllipseItem, QGraphicsTextItem, QGraphicsItemGroup, QGraphicsItem,
    QFileDialog, QMessageBox, QSpinBox, QCheckBox, QPushButton, QColorDialog,
    QTableWidgetItem,
)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (
    QColor, QPen, QBrush, QFont, QAction, QPixmap, QImage, QPainter,
)
from PyQt6.QtPrintSupport import QPrinter, QPrintDialog

try:
    import fitz  # PyMuPDF
except ImportError:  # PyMuPDF >= 1.26 prefers the new module name
    import pymupdf as fitz

from utils.i18n import tr
from workbenches.base_workbench import BaseWorkbench
from workbenches.pdf_annotator.models import Bubble

BASE_SCALE = 1.5  # zoom factor that means "100 %" (matches the HTML tool)


def _hex_to_rgb01(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


class BubbleItem(QGraphicsItemGroup):
    """Graphics representation of a Bubble model (circle + centered label)."""

    def __init__(self, bubble, workbench):
        super().__init__()
        self.bubble = bubble
        self.wb = workbench

        self.circle = QGraphicsEllipseItem()
        self.label = QGraphicsTextItem()
        self.addToGroup(self.circle)
        self.addToGroup(self.label)

        self.setFlags(
            QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable |
            QGraphicsItemGroup.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.sync()

    def sync(self):
        b = self.bubble
        r = b.size / 2
        self.circle.setRect(-r, -r, b.size, b.size)

        pen = QPen(QColor(b.outer_color), b.border)
        if self.isSelected():
            pen.setStyle(Qt.PenStyle.DashLine)
        self.circle.setPen(pen)

        if b.fill_color and b.fill_color != "transparent":
            self.circle.setBrush(QBrush(QColor(b.fill_color)))
        else:
            self.circle.setBrush(QBrush(Qt.BrushStyle.NoBrush))

        font = QFont("Arial")
        font.setPixelSize(b.font)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setDefaultTextColor(QColor(b.font_color))
        self.label.setPlainText(b.text)
        bounds = self.label.boundingRect()
        self.label.setPos(-bounds.width() / 2, -bounds.height() / 2)

    def itemChange(self, change, value):
        Change = QGraphicsItem.GraphicsItemChange
        if change == Change.ItemPositionChange and self.wb.page_w:
            # Clamp dragging to the page area
            x = min(max(value.x(), 0.0), self.wb.page_w)
            y = min(max(value.y(), 0.0), self.wb.page_h)
            return QPointF(x, y)
        if change == Change.ItemPositionHasChanged:
            self.wb.on_bubble_moved(self)
        if change == Change.ItemSelectedHasChanged:
            self.sync()
        return super().itemChange(change, value)


class PDFCanvasView(QGraphicsView):
    """Canvas view: click-to-add, right-click delete, Delete key, Ctrl+wheel zoom."""

    def __init__(self, workbench):
        super().__init__(workbench.scene)
        self.wb = workbench
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.wb.add_mode:
            pos = self.mapToScene(event.pos())
            if self.wb.point_on_page(pos):
                self.wb.add_bubble_at(pos)
                return
        if event.button() == Qt.MouseButton.RightButton:
            item = self.itemAt(event.pos())
            while item is not None and not isinstance(item, BubbleItem):
                item = item.parentItem()
            if item is not None:
                self.wb.remove_bubble(item.bubble.id)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self.wb.on_mouse_moved(self.mapToScene(event.pos()))
        super().mouseMoveEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.wb.remove_selected()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.wb.zoom_step(1 if event.angleDelta().y() > 0 else -1)
        else:
            super().wheelEvent(event)


class PDFAnnotatorWorkbench(BaseWorkbench):
    def __init__(self, main_window):
        super().__init__(main_window)

        # PDF state
        self.doc = None
        self.pdf_path = ""
        self.page_no = 1
        self.zoom = BASE_SCALE
        self.page_w = 0.0   # current page size in scene px
        self.page_h = 0.0

        # Balloon state
        self.bubbles = []           # list[Bubble], all pages
        self.items = {}             # id -> BubbleItem (current page only)
        self.selected_id = None
        self.add_mode = False
        self.history = []           # JSON snapshots for undo
        self.future = []

        # Toolbar-editable balloon style defaults. Widgets are rebuilt on
        # every workbench switch; the values live here, not in the widgets
        # (reusing QWidgets across QToolBar.clear() leaves them hidden and
        # disabled, making them unclickable)
        self.def_outer = "#ef3340"
        self.def_fill = "#ffffff"
        self.def_font_color = "#ef3340"
        self.def_transparent = True
        self.ui_state = {"seq": 1, "size": 28, "border": 2, "font": 13}

        # Scene / view
        self.scene = QGraphicsScene()
        self.scene.selectionChanged.connect(self._on_selection_changed)
        self.view = PDFCanvasView(self)

        # Central widget: info bar + canvas
        self.container = QWidget()
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QWidget()
        bar.setStyleSheet("background:#26364d; color:#fff;")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(10, 4, 10, 4)
        self.file_info_label = QLabel(tr("No drawing opened"))
        self.file_info_label.setStyleSheet("color:#fff;")
        self.tool_coord_label = QLabel(
            tr("Tool:") + f" <b>{tr('Select')}</b> | " + tr("Coords:") + " —")
        self.tool_coord_label.setStyleSheet("color:#fff;")
        bar_layout.addWidget(self.file_info_label)
        bar_layout.addStretch(1)
        bar_layout.addWidget(self.tool_coord_label)
        layout.addWidget(bar)
        layout.addWidget(self.view, 1)

    # ------------------------------------------------------------------ UI
    def _color_button(self, attr):
        btn = QPushButton()
        btn.setFixedSize(30, 24)
        btn.setStyleSheet(f"background-color: {getattr(self, attr)}; border:1px solid #888;")
        btn.clicked.connect(lambda: self._pick_color(attr, btn))
        return btn

    def _pick_color(self, attr, btn):
        color = QColorDialog.getColor(QColor(getattr(self, attr)), self.main_window)
        if color.isValid():
            setattr(self, attr, color.name())
            btn.setStyleSheet(f"background-color: {color.name()}; border:1px solid #888;")

    def get_central_widget(self):
        return self.container

    def setup_toolbar(self, toolbar):
        open_act = QAction(tr("Open PDF"), self.main_window)
        open_act.triggered.connect(self.main_window.open_pdf)
        toolbar.addAction(open_act)

        export_pdf_act = QAction(tr("Export PDF"), self.main_window)
        export_pdf_act.triggered.connect(self.export_pdf)
        toolbar.addAction(export_pdf_act)

        png_act = QAction(tr("Export PNG"), self.main_window)
        png_act.triggered.connect(self.export_png)
        toolbar.addAction(png_act)

        batch_act = QAction(tr("Batch PNG"), self.main_window)
        batch_act.triggered.connect(self.export_png_batch)
        toolbar.addAction(batch_act)

        print_act = QAction(tr("Print"), self.main_window)
        print_act.triggered.connect(self.print_page)
        toolbar.addAction(print_act)

        toolbar.addSeparator()

        add_act = QAction(tr("Add Bubble"), self.main_window)
        add_act.setCheckable(True)
        add_act.setChecked(self.add_mode)
        add_act.triggered.connect(self.toggle_add_mode)
        toolbar.addAction(add_act)

        # Widgets are rebuilt on every switch; values live in ui_state
        def spin(key, lo, hi, w):
            s = QSpinBox(minimum=lo, maximum=hi, value=self.ui_state[key])
            s.setFixedWidth(w)
            s.valueChanged.connect(lambda v, k=key: self.ui_state.update({k: v}))
            return s

        self.seq_spin = spin("seq", 1, 9999, 64)
        size_spin = spin("size", 10, 120, 58)
        border_spin = spin("border", 1, 15, 52)
        font_spin = spin("font", 6, 60, 52)
        transparent_chk = QCheckBox(tr("Transparent"))
        transparent_chk.setChecked(self.def_transparent)
        transparent_chk.toggled.connect(lambda v: setattr(self, "def_transparent", v))

        for text, widget in (
            (tr("Seq"), self.seq_spin), (tr("Size"), size_spin),
            (tr("Border"), border_spin), (tr("Font"), font_spin),
            (tr("Outer"), self._color_button("def_outer")),
            (tr("Fill"), self._color_button("def_fill")),
            (None, transparent_chk), (tr("Text"), self._color_button("def_font_color")),
        ):
            if text:
                toolbar.addWidget(QLabel(f" {text} "))
            toolbar.addWidget(widget)

        toolbar.addSeparator()

        page_text = (f" {self.page_no} / {self.doc.page_count} " if self.doc else " 0 / 0 ")
        self.page_label = QLabel(page_text)
        zoom_text = f"{round(self.zoom / BASE_SCALE * 100)}%"
        self.zoom_label = QLabel(zoom_text)
        self.zoom_label.setMinimumWidth(44)

        prev_act = QAction("◀", self.main_window)
        prev_act.triggered.connect(lambda: self.go_page(self.page_no - 1))
        toolbar.addAction(prev_act)
        toolbar.addWidget(self.page_label)
        next_act = QAction("▶", self.main_window)
        next_act.triggered.connect(lambda: self.go_page(self.page_no + 1))
        toolbar.addAction(next_act)

        zoom_out_act = QAction("−", self.main_window)
        zoom_out_act.triggered.connect(lambda: self.zoom_step(-1))
        toolbar.addAction(zoom_out_act)
        toolbar.addWidget(self.zoom_label)
        zoom_in_act = QAction("＋", self.main_window)
        zoom_in_act.triggered.connect(lambda: self.zoom_step(1))
        toolbar.addAction(zoom_in_act)
        fit_act = QAction(tr("Fit"), self.main_window)
        fit_act.triggered.connect(self.zoom_fit)
        toolbar.addAction(fit_act)

        toolbar.addSeparator()

        undo_act = QAction(tr("Undo"), self.main_window)
        undo_act.triggered.connect(self.undo)
        toolbar.addAction(undo_act)
        redo_act = QAction(tr("Redo"), self.main_window)
        redo_act.triggered.connect(self.redo)
        toolbar.addAction(redo_act)
        clear_act = QAction(tr("Clear"), self.main_window)
        clear_act.triggered.connect(self.clear_balloons)
        toolbar.addAction(clear_act)
        renumber_act = QAction(tr("Renumber"), self.main_window)
        renumber_act.triggered.connect(self.renumber_balloons)
        toolbar.addAction(renumber_act)

    # ------------------------------------------------------- PDF handling
    def load_pdf(self, file_path):
        try:
            doc = fitz.open(file_path)
        except Exception as e:
            QMessageBox.critical(self.main_window, tr("Open Failed"),
                                 tr("Could not open PDF:") + f"\n{e}")
            return
        self.doc = doc
        self.pdf_path = file_path
        self.page_no = 1
        self.zoom = BASE_SCALE
        self.bubbles = []
        self.selected_id = None
        self.history = []
        self.future = []
        self.ui_state["seq"] = 1
        self._sync_seq_spin()
        self.render_page()
        self.main_window.log(f"Loaded PDF: {file_path} ({doc.page_count} pages)")

    def render_page(self):
        if not self.doc:
            return
        page = self.doc[self.page_no - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888).copy()

        self.scene.clear()
        self.items = {}
        self.scene.addPixmap(QPixmap.fromImage(img))
        self.page_w, self.page_h = float(pix.width), float(pix.height)
        self.scene.setSceneRect(0, 0, self.page_w, self.page_h)

        for b in self.bubbles:
            if b.page == self.page_no:
                self._add_item(b)

        name = os.path.basename(self.pdf_path)
        self.file_info_label.setText(
            f"{name} · {tr('Page')} {self.page_no}/{self.doc.page_count}")
        self.page_label.setText(f" {self.page_no} / {self.doc.page_count} ")
        self.zoom_label.setText(f"{round(self.zoom / BASE_SCALE * 100)}%")
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def go_page(self, n):
        if not self.doc:
            return
        n = max(1, min(self.doc.page_count, n))
        if n != self.page_no:
            self.page_no = n
            self.selected_id = None
            self.render_page()

    def zoom_step(self, direction):
        if not self.doc:
            return
        self.zoom = max(0.5, min(6.0, self.zoom + 0.25 * direction))
        self.render_page()

    def zoom_fit(self):
        if not self.doc:
            return
        rect = self.doc[self.page_no - 1].rect
        vw = max(self.view.viewport().width() - 60, 100)
        vh = max(self.view.viewport().height() - 60, 100)
        self.zoom = max(0.5, min(3.0, min(vw / rect.width, vh / rect.height)))
        self.render_page()

    # ------------------------------------------------------- balloon logic
    def point_on_page(self, pos):
        return self.doc is not None and 0 <= pos.x() <= self.page_w and 0 <= pos.y() <= self.page_h

    def toggle_add_mode(self, checked):
        self.add_mode = checked
        tool = "Bubble" if checked else "Select"
        self.main_window.log(f"Balloon placement mode: {checked}")
        self._update_tool_coord(None)

    def retranslate(self):
        """Hook called by MainWindow.retranslate() to refresh the info bar."""
        if not self.doc:
            self.file_info_label.setText(tr("No drawing opened"))
        else:
            name = os.path.basename(self.pdf_path)
            self.file_info_label.setText(
                f"{name} · {tr('Page')} {self.page_no}/{self.doc.page_count}")
        self._update_tool_coord(None)

    def _update_tool_coord(self, pos):
        tool = tr("Bubble") if self.add_mode else tr("Select")
        if pos is not None and self.doc:
            coord = f"{pos.x() / self.zoom:.1f}, {pos.y() / self.zoom:.1f}"
        else:
            coord = "—"
        self.tool_coord_label.setText(
            tr("Tool:") + f" <b>{tool}</b> | " + tr("Coords:") + f" {coord}")

    def on_mouse_moved(self, pos):
        self._update_tool_coord(pos)

    def _sync_seq_spin(self):
        spin = getattr(self, "seq_spin", None)
        if spin is not None:
            spin.blockSignals(True)
            spin.setValue(self.ui_state["seq"])
            spin.blockSignals(False)

    def make_bubble(self, nx, ny):
        return Bubble(
            page=self.page_no, nx=nx, ny=ny, text=str(self.ui_state["seq"]),
            size=self.ui_state["size"], border=self.ui_state["border"],
            font=self.ui_state["font"], outer_color=self.def_outer,
            fill_color="transparent" if self.def_transparent else self.def_fill,
            font_color=self.def_font_color,
        )

    def _add_item(self, bubble):
        item = BubbleItem(bubble, self)
        item.setPos(bubble.nx * self.page_w, bubble.ny * self.page_h)
        self.scene.addItem(item)
        self.items[bubble.id] = item

    def add_bubble_at(self, pos):
        self.snapshot()
        bubble = self.make_bubble(pos.x() / self.page_w, pos.y() / self.page_h)
        self.bubbles.append(bubble)
        self._add_item(bubble)
        self.ui_state["seq"] += 1
        self._sync_seq_spin()
        self.main_window.log(
            f"Added Balloon #{bubble.text} on page {bubble.page} "
            f"at ({bubble.nx * 100:.1f}%, {bubble.ny * 100:.1f}%)"
        )
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def on_bubble_moved(self, item):
        b = item.bubble
        b.nx = min(max(item.pos().x() / self.page_w, 0.0), 1.0)
        b.ny = min(max(item.pos().y() / self.page_h, 0.0), 1.0)
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def remove_bubble(self, bubble_id):
        if not any(b.id == bubble_id for b in self.bubbles):
            return
        self.snapshot()
        self.bubbles = [b for b in self.bubbles if b.id != bubble_id]
        item = self.items.pop(bubble_id, None)
        if item is not None:
            self.scene.removeItem(item)
        if self.selected_id == bubble_id:
            self.selected_id = None
        self.main_window.log(tr("Removed balloon."))
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def remove_selected(self):
        if self.selected_id:
            self.remove_bubble(self.selected_id)

    def _on_selection_changed(self):
        selected = [it for it in self.scene.selectedItems() if isinstance(it, BubbleItem)]
        self.selected_id = selected[0].bubble.id if selected else None
        self._update_property_table(self.main_window.property_table)

    def clear_balloons(self):
        if not self.bubbles:
            return
        self.snapshot()
        self.bubbles = []
        self.selected_id = None
        self.ui_state["seq"] = 1
        self._sync_seq_spin()
        self.render_page()
        self.main_window.log(tr("Cleared all balloons."))

    def renumber_balloons(self):
        if not self.bubbles:
            return
        self.snapshot()
        counters = {}
        for b in self.bubbles:
            counters[b.page] = counters.get(b.page, 0) + 1
            b.text = str(counters[b.page])
        self.ui_state["seq"] = counters.get(self.page_no, 0) + 1
        self._sync_seq_spin()
        self.render_page()
        self.main_window.log(tr("Auto-renumbered balloons sequentially per page."))

    # ------------------------------------------------------- undo / redo
    def snapshot(self):
        self.history.append(json.dumps([b.to_dict() for b in self.bubbles]))
        if len(self.history) > 50:
            self.history.pop(0)
        self.future = []

    def _restore(self, state):
        self.bubbles = [Bubble.from_dict(d) for d in json.loads(state)]
        self.selected_id = None
        self.render_page()

    def undo(self):
        if not self.history:
            return
        self.future.append(json.dumps([b.to_dict() for b in self.bubbles]))
        self._restore(self.history.pop())
        self.main_window.log(tr("Undo."))

    def redo(self):
        if not self.future:
            return
        self.history.append(json.dumps([b.to_dict() for b in self.bubbles]))
        self._restore(self.future.pop())
        self.main_window.log(tr("Redo."))

    # ------------------------------------------------------- export
    def _require_doc(self):
        if not self.doc:
            QMessageBox.warning(self.main_window, tr("No PDF"),
                                tr("Please open a PDF drawing first."))
            return False
        return True

    def export_pdf(self):
        """Vector export: draw balloons into a copy of the source PDF."""
        if not self._require_doc():
            return
        default = os.path.splitext(self.pdf_path)[0] + " - Annotated.pdf"
        out_path, _ = QFileDialog.getSaveFileName(
            self.main_window, tr("Export Annotated PDF"), default, tr("PDF Files (*.pdf)"))
        if not out_path:
            return
        try:
            doc = fitz.open(self.pdf_path)
            for b in self.bubbles:
                page = doc[b.page - 1]
                w, h = page.rect.width, page.rect.height
                x, y = b.nx * w, b.ny * h
                radius = b.size / BASE_SCALE / 2
                fill = None if b.fill_color == "transparent" else _hex_to_rgb01(b.fill_color)
                page.draw_circle((x, y), radius,
                                 color=_hex_to_rgb01(b.outer_color), fill=fill,
                                 width=b.border / BASE_SCALE)
                fs = b.font / BASE_SCALE
                tw = fitz.get_text_length(b.text, fontname="hebo", fontsize=fs)
                page.insert_text((x - tw / 2, y + fs * 0.35), b.text,
                                 fontname="hebo", fontsize=fs,
                                 color=_hex_to_rgb01(b.font_color))
            doc.save(out_path)
            doc.close()
        except Exception as e:
            QMessageBox.critical(self.main_window, tr("Export Failed"),
                                 tr("Could not write PDF:") + f"\n{e}")
            return
        self.main_window.log(f"Exported annotated PDF: {out_path}")
        QMessageBox.information(self.main_window, tr("Success"),
                                f"Exported {len(self.bubbles)} balloons to:\n{out_path}")

    def _draw_badge(self, painter, b, img_w, img_h, render_scale):
        ratio = render_scale / BASE_SCALE
        x, y = b.nx * img_w, b.ny * img_h
        r = b.size / 2 * ratio

        pen = QPen(QColor(b.outer_color))
        pen.setWidthF(max(1.0, b.border * ratio))
        painter.setPen(pen)
        if b.fill_color and b.fill_color != "transparent":
            painter.setBrush(QBrush(QColor(b.fill_color)))
        else:
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawEllipse(QPointF(x, y), r, r)

        font = QFont("Arial")
        font.setPixelSize(max(8, round(b.font * ratio)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(b.font_color))
        painter.drawText(QRectF(x - r, y - r, 2 * r, 2 * r),
                         Qt.AlignmentFlag.AlignCenter, b.text)

    def _render_page_image(self, page_no, render_scale):
        page = self.doc[page_no - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(render_scale, render_scale), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format.Format_RGB888).copy()
        painter = QPainter(img)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for b in self.bubbles:
            if b.page == page_no:
                self._draw_badge(painter, b, img.width(), img.height(), render_scale)
        painter.end()
        return img

    def export_png(self):
        if not self._require_doc():
            return
        stem = os.path.splitext(os.path.basename(self.pdf_path))[0]
        out_path, _ = QFileDialog.getSaveFileName(
            self.main_window, tr("Export Current Page PNG"),
            f"{stem}-page-{self.page_no}.png", tr("PNG Files (*.png)"))
        if not out_path:
            return
        try:
            self._render_page_image(self.page_no, 3).save(out_path, "PNG")
        except Exception as e:
            QMessageBox.critical(self.main_window, tr("Export Failed"),
                                 tr("Could not write PNG:") + f"\n{e}")
            return
        self.main_window.log(f"Exported PNG: {out_path}")

    def export_png_batch(self):
        if not self._require_doc():
            return
        out_dir = QFileDialog.getExistingDirectory(
            self.main_window, tr("Choose PNG Output Folder"))
        if not out_dir:
            return
        stem = os.path.splitext(os.path.basename(self.pdf_path))[0]
        try:
            for n in range(1, self.doc.page_count + 1):
                self._render_page_image(n, 3).save(
                    os.path.join(out_dir, f"{stem}-page-{n}.png"), "PNG")
        except Exception as e:
            QMessageBox.critical(self.main_window, tr("Export Failed"),
                                 tr("Batch PNG failed:") + f"\n{e}")
            return
        self.main_window.log(f"Batch exported {self.doc.page_count} pages to {out_dir}")
        QMessageBox.information(self.main_window, tr("Success"),
                                f"Exported {self.doc.page_count} pages to:\n{out_dir}")

    def print_page(self):
        if not self._require_doc():
            return
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        dialog = QPrintDialog(printer, self.main_window)
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return
        img = self._render_page_image(self.page_no, 3)
        painter = QPainter(printer)
        rect = printer.pageRect(QPrinter.Unit.DevicePixel)
        scaled = img.scaled(rect.width(), rect.height(),
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
        painter.drawImage(int(rect.x() + (rect.width() - scaled.width()) / 2),
                          int(rect.y() + (rect.height() - scaled.height()) / 2), scaled)
        painter.end()
        self.main_window.log(tr("Sent current page to printer."))

    def export_data(self):
        """JSON export of all balloons (File menu / Ctrl+E)."""
        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, tr("Export Balloons JSON"), "", tr("JSON Files (*.json)"))
        if not file_path:
            return
        data = {
            "source": self.pdf_path,
            "standard": "ISO 2859-1 / FAI",
            "balloons": [b.to_dict() for b in self.bubbles],
        }
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except OSError as e:
            QMessageBox.critical(self.main_window, tr("Export Failed"),
                                 tr("Could not write file:") + f"\n{e}")
            return
        QMessageBox.information(self.main_window, tr("Success"),
                                f"Exported {len(self.bubbles)} balloons to JSON!")

    # ------------------------------------------------------- dock views
    def update_dock_views(self, tree_widget, property_table):
        tree_widget.clear()
        for b in self.bubbles:
            if b.page == self.page_no:
                tree_widget.addItem(
                    f"{tr('Balloon')} {b.text} - ({b.nx * 100:.1f}%, {b.ny * 100:.1f}%)")
        self._update_property_table(property_table)

    def _update_property_table(self, property_table):
        rows = [
            (tr("PDF File"), os.path.basename(self.pdf_path) if self.pdf_path else "—"),
            (tr("Page"), f"{self.page_no} / {self.doc.page_count}" if self.doc else "—"),
            (tr("Balloons (Total)"), str(len(self.bubbles))),
            (tr("Balloons (This Page)"),
             str(sum(1 for b in self.bubbles if b.page == self.page_no))),
            (tr("Inspection Standard"), "ISO 2859-1 / FAI"),
        ]
        selected = next((b for b in self.bubbles if b.id == self.selected_id), None)
        if selected:
            rows += [
                (tr("Selected Balloon"), selected.text),
                (tr("Position"), f"({selected.nx * 100:.1f}%, {selected.ny * 100:.1f}%)"),
                (tr("Size / Border / Font"),
                 f"{selected.size} / {selected.border} / {selected.font} px"),
            ]
        property_table.setRowCount(len(rows))
        for i, (key, value) in enumerate(rows):
            property_table.setItem(i, 0, QTableWidgetItem(key))
            property_table.setItem(i, 1, QTableWidgetItem(value))
