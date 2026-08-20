"""
TechDraw-style Drawing Workbench — a dedicated workbench for page templates.

Uses the official FreeCAD ISO5457 SVG templates (assets/templates/*) to render
the sheet on a QGraphicsView canvas, plus editable title-block fields
(TITLE / AUTHOR / DATE / SCALE / SHEET / MATERIAL). Exports the page to SVG.
"""
import os

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QPainter, QPen, QColor, QFont
from PyQt6.QtSvgWidgets import QGraphicsSvgItem
from PyQt6.QtWidgets import (QFileDialog, QFormLayout, QGraphicsScene,
                             QGraphicsView, QLineEdit, QMessageBox, QWidget,
                             QLabel)

from utils.i18n import tr, trt
from utils.resources import resource_path
from workbenches.base_workbench import BaseWorkbench

TEMPLATE_FILES = [
    "A3_Landscape_ISO5457_minimal.svg",
    "A4_Landscape_ISO5457_minimal.svg",
    "A4_Portrait_ISO5457_minimal.svg",
]
FIELDS = ["TITLE", "AUTHOR", "DATE", "SCALE", "SHEET", "MATERIAL"]


class DrawingView(QGraphicsView):
    """Sheet view (wheel zoom, drag-pan, fit-to-window)."""

    def __init__(self, workbench):
        super().__init__(workbench.scene)
        self.wb = workbench
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)


class TechDrawWorkbench(BaseWorkbench):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.scene = QGraphicsScene()
        self.view = DrawingView(self)
        self._template = None
        self._fields = {}
        self._text_items = []

    # ------------------------------------------------------------------ UI
    def get_central_widget(self):
        return self.view

    def setup_toolbar(self, toolbar):
        for label in TEMPLATE_FILES:
            act = QAction(label.replace(".svg", "").replace("_", " "),
                          self.main_window)
            act.triggered.connect(
                lambda checked, f=label: self.insert_template(f))
            toolbar.addAction(act)

        toolbar.addSeparator()
        export_act = QAction(tr("Export SVG"), self.main_window)
        export_act.triggered.connect(self.export_svg)
        toolbar.addAction(export_act)

    def retranslate(self):
        pass

    def export_data(self):
        """BaseWorkbench hook: route JSON export to SVG export here."""
        self.export_svg()

    # ------------------------------------------------------------------ templates
    def insert_template(self, fname):
        path = resource_path(f"assets/templates/{fname}")
        if not os.path.exists(path):
            QMessageBox.warning(self.main_window, tr("Template"),
                                tr("Template file not found:") + f"\n{path}")
            return
        for it in self._text_items:
            self.scene.removeItem(it)
        self._text_items = []
        if self._template is not None:
            self.scene.removeItem(self._template)
        item = QGraphicsSvgItem(path)
        item.setZValue(0)
        self.scene.addItem(item)
        self._template = item
        self.view.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)
        self.main_window.log(trt("Drawing page template: {n}", n=fname))
        self._render_fields()

    def _render_fields(self):
        if self._template is None:
            return
        rect = self._template.boundingRect()
        # title-block goes bottom-right; reserve a block under the frame
        bx = rect.right() - 200
        by = rect.bottom() - 40
        font = QFont("Arial", 10)
        for i, label in enumerate(FIELDS):
            value = self._fields.get(label, "")
            text = self.scene.addText(f"{label}: {value}", font)
            text.setPos(bx + (i % 2) * 100, by + (i // 2) * 8)
            text.setZValue(1)
            self._text_items.append(text)

    def set_field(self, name, value):
        self._fields[name] = value
        for it in self._text_items:
            self.scene.removeItem(it)
        self._text_items = []
        self._render_fields()

    # ------------------------------------------------------------------ dock
    def update_dock_views(self, tree_widget, property_table):
        tree_widget.clear()
        tree_widget.addItem(tr("Page Template Fields"))
        property_table.setRowCount(0)

    # ------------------------------------------------------------------ export
    def export_svg(self):
        if self._template is None:
            QMessageBox.information(self.main_window, tr("Export SVG"),
                                    tr("Insert a page template first."))
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, tr("Export SVG"), "", tr("SVG Files (*.svg)"))
        if not file_path:
            return
        from PyQt6.QtSvg import QSvgGenerator
        rect = self.scene.itemsBoundingRect()
        gen = QSvgGenerator()
        gen.setFileName(file_path)
        gen.setSize(rect.size().toSize())
        gen.setViewBox(rect)
        gen.setTitle("TechDraw Page")
        painter = QPainter(gen)
        self.scene.render(painter, rect, rect)
        painter.end()
        self.main_window.log(trt("Drawing page exported to {v}", v=file_path))
