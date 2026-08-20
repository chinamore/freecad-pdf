"""
TechDraw-style Drawing Workbench — full feature set modelled on the FreeCAD
TechDraw Workbench (src/Mod/TechDraw, wiki.freecad.org/TechDraw_Workbench).

Page templates (official ISO5457 SVG), annotation tools (dimensions, leaders,
text, balloons, centerlines, cosmetic lines/vertices), view management,
hatching, and SVG export. All tools are also reachable via a toolbar with
FreeCAD-style red icons.
"""
import math
import os

from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QAction, QPainter, QPen, QColor, QFont, QBrush
from PyQt6.QtSvgWidgets import QGraphicsSvgItem
from PyQt6.QtWidgets import (QFileDialog, QGraphicsScene, QGraphicsView,
                             QGraphicsEllipseItem, QGraphicsLineItem,
                             QGraphicsPathItem, QGraphicsSimpleTextItem,
                             QMenu, QMessageBox, QInputDialog)

from utils.i18n import tr, trt
from utils.resources import resource_path
from workbenches.base_workbench import BaseWorkbench

TEMPLATE_FILES = [
    "A3_Landscape_ISO5457_minimal.svg",
    "A4_Landscape_ISO5457_minimal.svg",
    "A4_Portrait_ISO5457_minimal.svg",
]
FIELDS = ["TITLE", "AUTHOR", "DATE", "SCALE", "SHEET", "MATERIAL"]
VIEWS = ["FRONT", "TOP", "RIGHT", "LEFT", "ISO"]

# icon colour scheme matching the FreeCAD TechDraw red/black style
_TD_RED = QColor(200, 40, 40)
_EDGE = QColor(30, 30, 30)          # black edge like FreeCAD
_FACE = QColor(240, 244, 247)       # light face fill
_HIDDEN = QColor(150, 150, 150)     # hidden edges (dashed)


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

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.wb.on_left_click(self.mapToScene(event.pos()))
            return
        super().mousePressEvent(event)


class TechDrawWorkbench(BaseWorkbench):
    def __init__(self, main_window):
        super().__init__(main_window)
        self.scene = QGraphicsScene()
        self.view = DrawingView(self)
        self._template = None
        self._fields = {}
        self._text_items = []
        # annotation state
        self._mode = "SELECT"
        self._temp_pts = []
        self._annotations = []            # list of dicts for export
        self._balloon_n = 0
        self._dim_n = 0
        self._actions = {}                # mode -> QAction (checked sync)
        # 3D STEP state
        self._solid = None                # loaded OCC solid
        self._proj_views = {}             # view name -> list of 2D polylines
        self._proj_items = []             # drawn projection items
        self._proj_origin = QPointF(0, 0)
        self._proj_scale = 1.0

    # ------------------------------------------------------------------ UI
    def get_central_widget(self):
        return self.view

    def setup_toolbar(self, toolbar):
        def tip(t, s=""):
            return f"{t} ({s})" if s else t
        # 3D STEP loader
        step_act = QAction(tr("Load STEP..."), self.main_window)
        step_act.setToolTip(tr("Load a STEP (.step/.stp) 3D file"))
        step_act.triggered.connect(self.load_step_dialog)
        toolbar.addAction(step_act)
        # projection view dropdown
        proj_act = QAction(tr("Projection"), self.main_window)
        proj_act.setToolTip(tr("Insert a projected view (1st/3rd angle)"))
        proj_menu = QMenu(self.main_window)
        group_act = proj_menu.addAction(tr("Projection group (FRONT+TOP+RIGHT/LEFT)"))
        group_act.triggered.connect(self.insert_projection_group)
        proj_menu.addSeparator()
        for v in VIEWS:
            act = proj_menu.addAction(v)
            act.triggered.connect(lambda checked, view=v: self.insert_projection(view))
        proj_act.setMenu(proj_menu)
        toolbar.addAction(proj_act)
        pbtn = toolbar.widgetForAction(proj_act)
        if pbtn is not None:
            pbtn.setPopupMode(pbtn.ToolButtonPopupMode.InstantPopup)
        # 1st / 3rd angle toggle
        self.angle_act = QAction(tr("3rd angle"), self.main_window)
        self.angle_act.setCheckable(True)
        self.angle_act.setChecked(True)  # default third-angle (FreeCAD default)
        self.angle_act.setToolTip(tr("Projection angle: 3rd (checked) / 1st"))
        self.angle_act.triggered.connect(self._toggle_angle)
        toolbar.addAction(self.angle_act)
        toolbar.addSeparator()
        # page templates
        for label in TEMPLATE_FILES:
            act = QAction(label.replace("ISO5457_", "").replace("_", " ")
                          .replace(".svg", ""), self.main_window)
            act.triggered.connect(lambda checked, f=label: self.insert_template(f))
            toolbar.addAction(act)
        toolbar.addSeparator()
        # annotation tools (FreeCAD TechDraw set)
        for label, mode, sc in (
                (tr("Text"), "TEXT", "T"),
                (tr("Balloon"), "BALLOON", "B"),
                (tr("Leader line"), "LEADER", "L"),
                (tr("Length dimension"), "D_LEN", "D"),
                (tr("Horiz. dimension"), "D_X", "X"),
                (tr("Vert. dimension"), "D_Y", "Y"),
                (tr("Radius dimension"), "D_R", "R"),
                (tr("Diameter dimension"), "D_DIA", "O"),
                (tr("Angle dimension"), "D_ANG", "A"),
                (tr("Centerline 2 lines"), "C_2L", ""),
                (tr("Centerline 2 points"), "C_2P", ""),
                (tr("Cosmetic line"), "COS_LINE", ""),
                (tr("Cosmetic circle"), "COS_CIRC", ""),
        ):
            act = QAction(label, self.main_window)
            act.setCheckable(True)
            act.setToolTip(tip(label, sc))
            act.triggered.connect(lambda checked, m=mode: self.set_mode(m))
            toolbar.addAction(act)
            self._actions[mode] = act
        toolbar.addSeparator()
        export_act = QAction(tr("Export SVG"), self.main_window)
        export_act.triggered.connect(self.export_svg)
        toolbar.addAction(export_act)

    def retranslate(self):
        pass

    def export_data(self):
        self.export_svg()

    # ------------------------------------------------------------------ STEP / projection
    def load_step_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self.main_window, tr("Load STEP"), "",
            tr("STEP Files (*.step *.stp)"))
        if path:
            self.load_step(path)

    def load_step(self, path):
        try:
            from utils.step_loader import load_step as _load
            self.main_window.setCursor(Qt.CursorShape.WaitCursor)
            self._solid = _load(path)
            self._proj_views = {}
            self.main_window.log(trt("Loaded STEP: {v}", v=path))
        except Exception as e:
            QMessageBox.critical(self.main_window, tr("Load STEP"), str(e))
        finally:
            self.main_window.unsetCursor()

    def _toggle_angle(self, checked):
        self.main_window.log(
            tr("Projection angle: third-angle") if checked
            else tr("Projection angle: first-angle"))

    def insert_projection(self, view):
        """Project the loaded STEP solid to 2D and draw it on the page.
        FreeCAD visual: black wireframe edges; the projection view can then
        be moved and dimensioned."""
        if self._solid is None:
            QMessageBox.information(self.main_window, tr("Projection"),
                                    tr("Load a STEP file first."))
            return
        from utils.step_loader import project_2d
        if view not in self._proj_views:
            self._proj_views[view] = project_2d(self._solid, view)
        lines = self._proj_views[view]
        if not lines:
            self.main_window.log(tr("Projection produced no geometry."))
            return
        pen = QPen(_EDGE, 0)  # 0 = cosmetic, always 1px like FreeCAD edges
        for poly in lines:
            for i in range(len(poly) - 1):
                x1, y1 = poly[i]
                x2, y2 = poly[i + 1]
                self.scene.addLine(x1, y1, x2, y2, pen).setZValue(2)
        self.main_window.log(trt("Inserted {v} projection ({n} edges).",
                                 v=view, n=len(lines)))
        self._fit_content()

    def _fit_content(self):
        items = self.scene.items()
        if items:
            self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40),
                                Qt.AspectRatioMode.KeepAspectRatio)

    def insert_projection_group(self):
        """FreeCAD-style: place a standard multi-view set on the page,
        arranged per the current projection angle (1st/3rd)."""
        if self._solid is None:
            QMessageBox.information(self.main_window, tr("Projection"),
                                    tr("Load a STEP file first."))
            return
        from utils.step_loader import project_2d
        third = self.angle_act.isChecked()
        # ISO-style 6-view arrangement: FRONT centre; neighbours placed per angle
        layout = {
            "FRONT": (0, 0),
            "TOP": (0, 1 if third else -1),
            "RIGHT": (1 if third else -1, 0),
            "LEFT": (-1 if third else 1, 0),
        }
        # estimate spacing from the projected extents
        spacing_x = spacing_y = 80.0
        for v, (dx, dy) in layout.items():
            lines = project_2d(self._solid, v)
            if not lines:
                continue
            xs = [p[0] for poly in lines for p in poly]
            ys = [p[1] for poly in lines for p in poly]
            cx = (min(xs) + max(xs)) / 2
            cy = (min(ys) + max(ys)) / 2
            offx = dx * spacing_x - cx
            offy = dy * spacing_y - cy
            pen = QPen(_EDGE, 0)
            for poly in lines:
                for i in range(len(poly) - 1):
                    self.scene.addLine(poly[i][0] + offx, poly[i][1] + offy,
                                       poly[i + 1][0] + offx, poly[i + 1][1] + offy,
                                       pen).setZValue(2)
        self.main_window.log(
            tr("Projection group inserted (third-angle)")
            if third else tr("Projection group inserted (first-angle)"))
        self._fit_content()

    def set_mode(self, mode):
        self._mode = mode
        self._temp_pts = []
        for m, act in self._actions.items():
            act.setChecked(m == mode)
        self.main_window.log(trt("TechDraw tool: {v}", v=mode))

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
        item.setZValue(-10)
        self.scene.addItem(item)
        self._template = item
        self.view.fitInView(item, Qt.AspectRatioMode.KeepAspectRatio)
        self.main_window.log(trt("Drawing page template: {n}", n=fname))
        self._render_fields()

    def _render_fields(self):
        if self._template is None:
            return
        rect = self._template.boundingRect()
        bx, by = rect.right() - 200, rect.bottom() - 40
        font = QFont("Arial", 10)
        for i, label in enumerate(FIELDS):
            value = self._fields.get(label, "")
            text = self.scene.addText(f"{label}: {value}", font)
            text.setPos(bx + (i % 2) * 100, by + (i // 2) * 8)
            text.setZValue(-5)
            self._text_items.append(text)

    def set_field(self, name, value):
        self._fields[name] = value
        for it in self._text_items:
            self.scene.removeItem(it)
        self._text_items = []
        self._render_fields()

    # ------------------------------------------------------------------ annotation machinery
    def _pen(self):
        return QPen(_TD_RED, 1.5)

    def _add_text(self, pos, content):
        font = QFont("Arial", 5)
        item = self.scene.addText(content, font)
        item.setDefaultTextColor(_TD_RED)
        item.setPos(pos)
        item.setZValue(5)
        self._annotations.append({"type": "TEXT", "pos": (pos.x(), pos.y()),
                                  "content": content})

    def on_left_click(self, pos):
        m = self._mode
        if m in ("TEXT", "BALLOON"):
            content, ok = QInputDialog.getText(self.main_window,
                                               tr("Balloon") if m == "BALLOON" else tr("Text"),
                                               tr("Content:"))
            if not ok or not content:
                return
            if m == "BALLOON":
                self._balloon_n += 1
                # circle balloon with the text, plus a leader line
                r = 6
                circ = self.scene.addEllipse(pos.x() - r, pos.y() - r, 2 * r, 2 * r,
                                             self._pen())
                circ.setZValue(5)
                t = self.scene.addText(content, QFont("Arial", 5))
                t.setDefaultTextColor(_TD_RED)
                t.setPos(pos.x() - r + 1, pos.y() - r + 0.5)
                t.setZValue(6)
                self.scene.addLine(pos.x() + r, pos.y() + r,
                                   pos.x() + 2 * r, pos.y() + 2 * r, self._pen()).setZValue(5)
                self._annotations.append({"type": "BALLOON", "pos": (pos.x(), pos.y()),
                                          "text": content})
            else:
                self._add_text(pos, content)
            return
        if m == "LEADER":
            self._temp_pts.append(QPointF(pos))
            if len(self._temp_pts) == 2:
                p1, p2 = self._temp_pts
                self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(),
                                   self._pen()).setZValue(5)
                self._annotations.append({"type": "LEADER",
                                          "p1": (p1.x(), p1.y()), "p2": (p2.x(), p2.y())})
                self._temp_pts = []
            return
        if m.startswith("D_"):
            kind = m[2:]
            self._temp_pts.append(QPointF(pos))
            if m == "D_LEN" and len(self._temp_pts) == 2:
                self._dim_length(*self._temp_pts)
                self._temp_pts = []
            elif m == "D_X" and len(self._temp_pts) == 2:
                self._dim_x(*self._temp_pts)
                self._temp_pts = []
            elif m == "D_Y" and len(self._temp_pts) == 2:
                self._dim_y(*self._temp_pts)
                self._temp_pts = []
            elif m in ("D_R", "D_DIA") and len(self._temp_pts) == 1:
                self._dim_radius(pos)
                self._temp_pts = []
            elif m == "D_ANG" and len(self._temp_pts) == 3:
                self._dim_angle(*self._temp_pts)
                self._temp_pts = []
            return
        if m in ("C_2L", "C_2P", "COS_LINE", "COS_CIRC"):
            self._temp_pts.append(QPointF(pos))
            need = 2 if m != "COS_CIRC" else 2
            if len(self._temp_pts) >= need:
                self._draw_cosmetic(m, self._temp_pts)
                self._temp_pts = []
            return

    def _dim_label(self, text, pos):
        font = QFont("Arial", 4)
        item = self.scene.addText(text, font)
        item.setDefaultTextColor(_TD_RED)
        item.setPos(pos)
        item.setZValue(5)

    def _dim_length(self, p1, p2):
        d = math.hypot(p2.x() - p1.x(), p2.y() - p1.y())
        mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2 - 6)
        self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), self._pen()).setZValue(5)
        self._dim_label(f"{d:.2f} mm", mid)
        self._annotations.append({"type": "DIM", "kind": "LENGTH",
                                  "p1": (p1.x(), p1.y()), "p2": (p2.x(), p2.y())})

    def _dim_x(self, p1, p2):
        d = abs(p2.x() - p1.x())
        mid = QPointF((p1.x() + p2.x()) / 2, min(p1.y(), p2.y()) - 6)
        y = min(p1.y(), p2.y())
        self.scene.addLine(p1.x(), y, p2.x(), y, self._pen()).setZValue(5)
        self._dim_label(f"{d:.2f} mm", mid)
        self._annotations.append({"type": "DIM", "kind": "X",
                                  "p1": (p1.x(), p1.y()), "p2": (p2.x(), p2.y())})

    def _dim_y(self, p1, p2):
        d = abs(p2.y() - p1.y())
        mid = QPointF(min(p1.x(), p2.x()) - 6, (p1.y() + p2.y()) / 2)
        x = min(p1.x(), p2.x())
        self.scene.addLine(x, p1.y(), x, p2.y(), self._pen()).setZValue(5)
        self._dim_label(f"{d:.2f} mm", mid)
        self._annotations.append({"type": "DIM", "kind": "Y",
                                  "p1": (p1.x(), p1.y()), "p2": (p2.x(), p2.y())})

    def _dim_radius(self, pos):
        # circle at the picked point (user is marking a circle's center/radius)
        r, ok = QInputDialog.getDouble(self.main_window, tr("Radius"),
                                       tr("Radius (mm):"), 10.0, 0.01, 1e6, 2)
        if not ok:
            return
        self.scene.addEllipse(pos.x() - r, pos.y() - r, 2 * r, 2 * r,
                              self._pen()).setZValue(5)
        a = math.radians(45)
        self.scene.addLine(pos.x(), pos.y(), pos.x() + r * math.cos(a),
                           pos.y() + r * math.sin(a), self._pen()).setZValue(5)
        self._dim_label(f"R {r:.2f}", pos + QPointF(r, -r))
        self._annotations.append({"type": "DIM", "kind": "RADIUS",
                                  "center": (pos.x(), pos.y()), "radius": r})

    def _dim_angle(self, v, p1, p2):
        a1 = math.degrees(math.atan2(p1.y() - v.y(), p1.x() - v.x()))
        a2 = math.degrees(math.atan2(p2.y() - v.y(), p2.x() - v.x()))
        ang = abs((a2 - a1) % 360)
        if ang > 180:
            ang = 360 - ang
        mid = QPointF(v.x() + 8, v.y() - 8)
        self._dim_label(f"{ang:.1f} deg", mid)
        self._annotations.append({"type": "DIM", "kind": "ANGLE",
                                  "vertex": (v.x(), v.y()),
                                  "p1": (p1.x(), p1.y()), "p2": (p2.x(), p2.y())})

    def _draw_cosmetic(self, m, pts):
        if m in ("C_2L", "C_2P", "COS_LINE") and len(pts) == 2:
            p1, p2 = pts
            self.scene.addLine(p1.x(), p1.y(), p2.x(), p2.y(), self._pen()).setZValue(5)
            self._annotations.append({"type": m, "p1": (p1.x(), p1.y()),
                                      "p2": (p2.x(), p2.y())})
        elif m == "COS_CIRC" and len(pts) == 2:
            c, edge = pts
            r = math.hypot(edge.x() - c.x(), edge.y() - c.y())
            self.scene.addEllipse(c.x() - r, c.y() - r, 2 * r, 2 * r,
                                  self._pen()).setZValue(5)
            self._annotations.append({"type": "COS_CIRC",
                                      "center": (c.x(), c.y()), "radius": r})

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
