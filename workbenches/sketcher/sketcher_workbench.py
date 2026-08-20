"""
2D Sketcher Workbench — FreeCAD Sketcher parity.

Geometry tools (FreeCAD shortcuts):
  G,P Point | G,L Line | G,M Polyline | G,C Circle | G,A Arc (center)
  G,3 Arc (3 points) | G,R Rectangle | G,T Triangle | G,S Square
  G,N toggle construction geometry of the selection

Constraints (FreeCAD shortcuts):
  C Coincident | O Point-on-object | H Horizontal | V Vertical
  P Parallel | N Perpendicular | T Tangent | E Equal | S Symmetric
  B Block | K Lock | L Distance X | I Distance Y | D Distance
  R Radius | A Angle   (Diameter has no FreeCAD default shortcut)

Interaction (FreeCAD parity):
  - hover preselection highlight; click-select; drag a vertex (single shared
    point) or a whole curve with LIVE solver feedback; constraints are
    re-imposed while dragging and on release
  - auto-constraints on creation: nearly axis-aligned lines get H/V,
    snapped endpoints become structural coincidence (shared points)
  - continuous creation mode (tool stays active until Esc / right-click)
  - constraint badges on the canvas; double-click a dimensional badge
    to edit its value, right-click a badge to remove the constraint
  - colour semantics: normal black / construction blue / selected yellow /
    fully-constrained green / conflicting red / preselection light blue
  - Ctrl+Z / Ctrl+Shift+Z (or Ctrl+Y) undo/redo; Del deletes the selection;
    DOF count and solver messages follow FreeCAD wording
"""
import copy
import json
import math

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import (QAction, QBrush, QColor, QPainter, QPainterPath,
                         QPen, QFont)
from PyQt6.QtWidgets import (QFileDialog, QGraphicsEllipseItem,
                             QGraphicsLineItem, QGraphicsPathItem,
                             QGraphicsScene, QGraphicsSimpleTextItem,
                             QGraphicsView, QInputDialog, QLabel,
                             QMessageBox, QSpinBox, QTableWidgetItem)

from sketcher.models import SketchPoint, SketchLine, SketchCircle, SketchArc
from sketcher.solver import (HAS_SCIPY, SketchSolver, STATUS_EMPTY,
                             STATUS_FULL, STATUS_OVER, STATUS_UNDER)
from utils.i18n import tr, trt
from workbenches.base_workbench import BaseWorkbench

# FreeCAD-style element colours
C_NORMAL = QColor(40, 40, 40)
C_CONSTRUCTION = QColor(70, 130, 220)
C_SELECTED = QColor(255, 200, 0)
C_FULL = QColor(0, 140, 0)
C_INVALID = QColor(220, 40, 40)
C_PRESEL = QColor(120, 190, 255)
C_BADGE_GEO = QColor(0, 110, 0)
C_BADGE_DIM = QColor(30, 60, 160)


def circumcenter(ax, ay, bx, by, cx, cy):
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy


def math_angle(cx, cy, px, py):
    """Angle in degrees of (px,py) around (cx,cy), y-up math convention."""
    return math.degrees(math.atan2(-(py - cy), px - cx))


class SketcherView(QGraphicsView):
    """Canvas view delegating clicks / drags / keys to the workbench."""

    def __init__(self, workbench):
        super().__init__(workbench.scene)
        self.wb = workbench
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        pos = self.mapToScene(event.pos())
        if self.wb.start_drag(event.button(), pos):
            return  # dragging existing geometry: consume, no rubber band
        if not self.wb.on_mouse_press(event.button(), pos):
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = self.mapToScene(event.pos())
        if self.wb.update_drag(pos):
            return
        self.wb.on_hover(pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.wb.end_drag(event.button()):
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self.wb.on_double_click(self.mapToScene(event.pos())):
            super().mouseDoubleClickEvent(event)

    def keyPressEvent(self, event):
        if not self.wb.on_key(event):
            super().keyPressEvent(event)


class SketcherWorkbench(BaseWorkbench):
    # mode -> (clicks needed, label key, shortcut shown in tooltip)
    TOOLS = [
        ("POINT", 1, "Point", "G, P"),
        ("LINE", 2, "Line", "G, L"),
        ("POLYLINE", None, "Polyline", "G, M"),
        ("CIRCLE", 2, "Circle", "G, C"),
        ("ARC_CENTER", 3, "Arc", "G, A"),
        ("ARC3", 3, "Arc (3 pts)", "G, 3"),
        ("RECT", 2, "Rectangle", "G, R"),
        ("TRIANGLE", 2, "Triangle", "G, T"),
        ("SQUARE", 2, "Square", "G, S"),
    ]

    # constraint type -> slot kinds for the FreeCAD-style pick workflow
    _SLOTS = {
        "COINCIDENT": ("point", "point"),
        "POINT_ON": ("point", "curve"),
        "HORIZONTAL": ("line",),
        "VERTICAL": ("line",),
        "PARALLEL": ("line", "line"),
        "PERPENDICULAR": ("line", "line"),
        "TANGENT": ("curve", "curve"),
        "EQUAL": ("curve", "curve"),
        "SYMMETRIC": ("point", "point", "line_or_point"),
        "DISTANCE": ("curve_or_point", "point_or_end"),
        "DISTANCE_X": ("curve_or_point", "point_or_end"),
        "DISTANCE_Y": ("curve_or_point", "point_or_end"),
        "RADIUS": ("round",),
        "DIAMETER": ("round",),
        "ANGLE": ("line", "line"),
        "LOCK": ("geom",),
        "BLOCK": ("geom",),
    }

    def __init__(self, main_window):
        super().__init__(main_window)

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(-1000, -1000, 2000, 2000)
        self.view = SketcherView(self)

        # State machine
        self.draw_mode = "SELECT"
        self.temp_points = []          # in-progress clicks [(QPointF, SketchPoint|None)]
        self.construction_mode = False
        self._poly_last = None         # last point of the running polyline

        # Snapping
        self.snap_on = True
        self.grid_step = 5
        self.snap_px = 12

        # Data models
        self.lines = []
        self.circles = []
        self.arcs = []
        self.points = []               # standalone SketchPoint geometry
        self.constraints = []

        # Graphics bookkeeping
        self.item_of_geom = {}         # geom.id -> QGraphicsItem
        self.geom_of_item = {}         # QGraphicsItem -> geom
        self._hover_geom = None        # preselection highlight
        self._badge_items = []         # constraint badge items
        self._badge_of_item = {}       # badge item -> constraint dict

        self.solver = SketchSolver()
        self.dof = 0
        self.status = STATUS_EMPTY

        # Interaction state
        self._drag = None              # {"points": [...], "last": QPointF}
        self._key_prefix = ""          # "G" arms FreeCAD-style create-tool keys
        self._constr_action = None     # toolbar action kept for sync
        self._pick = None              # {"type", "kinds", "got"}

        # Undo / redo (deep snapshots; shared points keep identity via memo)
        self._undo = []
        self._redo = []

        self._draw_grid()

        # Toolbar label state (the QLabel itself is rebuilt on every
        # workbench switch; see PDF workbench for the rationale)
        self._dof_text = f" {tr('DOF:')} — "

    # ------------------------------------------------------------------ UI
    def _draw_grid(self):
        grid_pen = QPen(QColor(230, 230, 230), 1, Qt.PenStyle.DotLine)
        axis_pen = QPen(QColor(180, 180, 180), 1.5)
        for x in range(-1000, 1000, 50):
            self.scene.addLine(x, -1000, x, 1000, grid_pen)
        for y in range(-1000, 1000, 50):
            self.scene.addLine(-1000, y, 1000, y, grid_pen)
        self.scene.addLine(-1000, 0, 1000, 0, axis_pen)
        self.scene.addLine(0, -1000, 0, 1000, axis_pen)

    def get_central_widget(self):
        return self.view

    def setup_toolbar(self, toolbar):
        for mode, _, label_key, sc in self.TOOLS:
            label = tr(label_key)
            act = QAction(label, self.main_window)
            act.setCheckable(True)
            act.setChecked(self.draw_mode == mode)
            act.setToolTip(f"{label} ({sc})")
            act.triggered.connect(
                lambda checked, m=mode: self.set_draw_mode(m if checked else "SELECT"))
            toolbar.addAction(act)

        constr_act = QAction(tr("Construction"), self.main_window)
        constr_act.setCheckable(True)
        constr_act.setChecked(self.construction_mode)
        constr_act.setToolTip(f"{tr('Construction')} (G, N " + tr("toggles selection") + ")")
        constr_act.triggered.connect(self._toggle_construction)
        toolbar.addAction(constr_act)
        self._constr_action = constr_act

        toolbar.addSeparator()

        snap_act = QAction(tr("Snap"), self.main_window)
        snap_act.setCheckable(True)
        snap_act.setChecked(self.snap_on)
        snap_act.triggered.connect(lambda checked: setattr(self, "snap_on", checked))
        toolbar.addAction(snap_act)
        grid_spin = QSpinBox(minimum=1, maximum=100, value=self.grid_step)
        grid_spin.setFixedWidth(52)
        grid_spin.valueChanged.connect(lambda v: setattr(self, "grid_step", v))
        toolbar.addWidget(QLabel(tr(" Grid ")))
        toolbar.addWidget(grid_spin)

        toolbar.addSeparator()

        for label, sc, handler in (
            (tr("Coincident"), "C", self.add_coincident_constraint),
            (tr("Point-on"), "O", self.add_point_on_constraint),
            ("H", "H", self.add_horizontal_constraint),
            ("V", "V", self.add_vertical_constraint),
            (tr("Parallel"), "P", self.add_parallel_constraint),
            (tr("Perp"), "N", self.add_perpendicular_constraint),
            (tr("Tangent"), "T", self.add_tangent_constraint),
            (tr("Equal"), "E", self.add_equal_constraint),
            (tr("Symmetric"), "S", self.add_symmetric_constraint),
            (tr("Distance"), "D", self.add_length_constraint),
            (tr("Dist X"), "L", self.add_distance_x_constraint),
            (tr("Dist Y"), "I", self.add_distance_y_constraint),
            (tr("Radius"), "R", self.add_radius_constraint),
            (tr("Diameter"), "", self.add_diameter_constraint),
            (tr("Angle"), "A", self.add_angle_constraint),
            (tr("Lock"), "K", self.add_lock_constraint),
            (tr("Block"), "B", self.add_block_constraint),
        ):
            act = QAction(label, self.main_window)
            if sc:
                act.setToolTip(f"{label} ({sc})")
            act.triggered.connect(handler)
            toolbar.addAction(act)

        toolbar.addSeparator()

        undo_act = QAction(tr("Undo"), self.main_window)
        undo_act.setToolTip(f"{tr('Undo')} (Ctrl+Z)")
        undo_act.triggered.connect(self.undo)
        toolbar.addAction(undo_act)
        redo_act = QAction(tr("Redo"), self.main_window)
        redo_act.setToolTip(f"{tr('Redo')} (Ctrl+Shift+Z)")
        redo_act.triggered.connect(self.redo)
        toolbar.addAction(redo_act)
        delete_act = QAction(tr("Delete"), self.main_window)
        delete_act.setToolTip(f"{tr('Delete')} (Del)")
        delete_act.triggered.connect(self.delete_selected)
        toolbar.addAction(delete_act)
        clear_act = QAction(tr("Clear"), self.main_window)
        clear_act.triggered.connect(self.clear_sketch)
        toolbar.addAction(clear_act)

        self.dof_label = QLabel(self._dof_text)
        toolbar.addWidget(self.dof_label)

    def retranslate(self):
        """Hook called by MainWindow.retranslate() to refresh cached strings."""
        has_geom = bool(self._all_geometry())
        self._dof_text = f" {tr('DOF:')} {self.dof if has_geom else '—'} "
        label = getattr(self, "dof_label", None)
        if label is not None:
            label.setText(self._dof_text)

    def _toggle_construction(self, checked):
        self.construction_mode = checked
        act = self._constr_action
        if act is not None:
            try:
                act.setChecked(bool(checked))
            except RuntimeError:
                self._constr_action = None  # toolbar was rebuilt
        self.main_window.log(trt("Construction geometry mode: {v}", v=checked))

    def toggle_construction_of_selection(self):
        """FreeCAD G,N: flip the construction flag of selected geometry."""
        geoms = self.selected_geometry()
        if not geoms:
            self.main_window.log(tr("Select geometry to toggle construction."))
            return
        self.snapshot()
        for g in geoms:
            g.is_construction = not g.is_construction
            self.update_item(g)
        self.main_window.log(trt("Toggled construction flag on {n} element(s).",
                                 n=len(geoms)))

    def set_draw_mode(self, mode):
        self.draw_mode = mode
        self.temp_points = []
        self._poly_last = None
        self._pick = None
        self.main_window.log(trt("Sketcher tool: {v}", v=mode))

    def cancel_temp(self):
        if self._pick is not None:
            self._pick = None
            self.main_window.log(tr("Constraint picking cancelled."))
            return
        if self.temp_points or self._poly_last is not None:
            self.temp_points = []
            self._poly_last = None
            self.main_window.log(tr("In-progress geometry cancelled."))

    # ------------------------------------------------------------------ models
    def _all_geometry(self):
        return self.lines + self.circles + self.arcs + self.points

    def _geom_points(self, geom):
        if isinstance(geom, SketchPoint):
            return (geom,)
        if isinstance(geom, SketchLine):
            return (geom.p1, geom.p2)
        if isinstance(geom, SketchCircle):
            return (geom.center,)
        return (geom.center, geom.p1, geom.p2)

    def _geom_dist(self, geom, pos):
        """Distance from scene point to the geometry's curve (for picking)."""
        px, py = pos.x(), pos.y()
        if isinstance(geom, SketchPoint):
            return math.hypot(px - geom.x, py - geom.y)
        if isinstance(geom, SketchLine):
            ax, ay, bx, by = geom.p1.x, geom.p1.y, geom.p2.x, geom.p2.y
            dx, dy = bx - ax, by - ay
            l2 = dx * dx + dy * dy
            t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
            return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        # circle / arc: distance to the circumference (span ignored for picking)
        return abs(math.hypot(px - geom.center.x, py - geom.center.y) - geom.radius)

    def _find_geom_at(self, pos, tol=None, kinds=None):
        tol = max(4.0, float(self.snap_px)) if tol is None else tol
        best, best_d = None, tol
        for geom in self._all_geometry():
            if kinds and not isinstance(geom, kinds):
                continue
            d = self._geom_dist(geom, pos)
            if d < best_d:
                best, best_d = geom, d
        return best

    def _nearest_point(self, pos, tol=None):
        tol = float(self.snap_px) if tol is None else tol
        best, best_d = None, tol
        for p in self.all_points():
            d = math.hypot(p.x - pos.x(), p.y - pos.y())
            if d < best_d:
                best, best_d = p, d
        return best

    # ------------------------------------------------------------------ dragging
    def start_drag(self, button, pos):
        """FreeCAD-style: grab a single endpoint near the cursor, otherwise
        translate the whole geometry. Only in SELECT mode."""
        if (button != Qt.MouseButton.LeftButton or self.draw_mode != "SELECT"
                or self.temp_points or self._pick is not None):
            return False
        grab = self._nearest_point(pos)
        if grab is not None:
            points = [grab]
        else:
            geom = self._find_geom_at(pos)
            if geom is None:
                return False
            points, seen = [], set()
            for p in self._geom_points(geom):  # dedup by id (unhashable dataclass)
                if p.id not in seen:
                    seen.add(p.id)
                    points.append(p)
        self.snapshot()  # one undo step per drag
        self._drag = {"points": points, "last": QPointF(pos)}
        return True

    def update_drag(self, pos):
        if self._drag is None:
            return False
        last = self._drag["last"]
        dx, dy = pos.x() - last.x(), pos.y() - last.y()
        if dx == 0 and dy == 0:
            return True
        self._drag["last"] = QPointF(pos)
        moved = set()
        for p in self._drag["points"]:
            p.x += dx
            p.y += dy
            moved.add(p.id)
        # FreeCAD live-solve: constraints move along in real time
        self._live_solve()
        for geom in self._all_geometry():
            if any(pt.id in moved for pt in self._geom_points(geom)):
                self.update_item(geom)
        return True

    def end_drag(self, button):
        if self._drag is None or button != Qt.MouseButton.LeftButton:
            return False
        self._drag = None
        self.solve_sketch()  # re-impose constraints after the move
        return True

    def _live_solve(self):
        """Solve without log noise (used while dragging)."""
        try:
            self.dof, _, self.status, _ = self.solver.solve(
                self.lines, self.circles, self.arcs, self.constraints, self.points)
        except Exception:
            return
        for geom in self._all_geometry():
            self.update_item(geom)
        self._update_dof_label()

    # ------------------------------------------------------------------ hover
    def on_hover(self, pos):
        """FreeCAD-style preselection highlight (light blue)."""
        if self.draw_mode != "SELECT" or self._drag is not None:
            self._set_hover(None)
            return
        geom = self._find_geom_at(pos)
        self._set_hover(geom)

    def _set_hover(self, geom):
        if geom is self._hover_geom:
            return
        old = self._hover_geom
        self._hover_geom = geom
        if old is not None:
            self.update_item(old)
        if geom is not None:
            item = self.item_of_geom.get(geom.id)
            if item is not None and not item.isSelected():
                item.setPen(QPen(C_PRESEL, 2.5))

    # ------------------------------------------------------------------ shortcuts
    _CREATE_KEYS = {"P": "POINT", "L": "LINE", "M": "POLYLINE", "C": "CIRCLE",
                    "A": "ARC_CENTER", "3": "ARC3", "R": "RECT",
                    "T": "TRIANGLE", "S": "SQUARE"}

    def on_key(self, event):
        """FreeCAD-style shortcuts. G + letter creates geometry; plain
        letters apply constraints; Esc cancels; Del deletes;
        Ctrl+Z / Ctrl+Shift+Z / Ctrl+Y undo/redo."""
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            if mods & Qt.KeyboardModifier.ShiftModifier:
                self.redo()
            else:
                self.undo()
            return True
        if key == Qt.Key.Key_Y and mods & Qt.KeyboardModifier.ControlModifier:
            self.redo()
            return True
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected()
            self._key_prefix = ""
            return True
        if key == Qt.Key.Key_Escape:
            if self._pick is not None or self.temp_points or self._poly_last is not None:
                self.cancel_temp()
            elif self.draw_mode != "SELECT":
                self.set_draw_mode("SELECT")
            self._key_prefix = ""
            return True
        text = event.text().upper()
        if not text or mods & (Qt.KeyboardModifier.ControlModifier
                               | Qt.KeyboardModifier.AltModifier):
            return False
        if self._key_prefix == "G":
            self._key_prefix = ""
            if text == "N":
                self.toggle_construction_of_selection()
                return True
            mode = self._CREATE_KEYS.get(text)
            if mode:
                self.set_draw_mode(mode)
            return True
        if text == "G":
            self._key_prefix = "G"
            return True
        direct = {
            "C": self.add_coincident_constraint,
            "O": self.add_point_on_constraint,
            "H": self.add_horizontal_constraint,
            "V": self.add_vertical_constraint,
            "P": self.add_parallel_constraint,
            "N": self.add_perpendicular_constraint,
            "T": self.add_tangent_constraint,
            "E": self.add_equal_constraint,
            "S": self.add_symmetric_constraint,
            "B": self.add_block_constraint,
            "K": self.add_lock_constraint,
            "L": self.add_distance_x_constraint,
            "I": self.add_distance_y_constraint,
            "D": self.add_length_constraint,
            "R": self.add_radius_constraint,
            "A": self.add_angle_constraint,
        }
        handler = direct.get(text)
        if handler:
            handler()
            return True
        return False

    # ------------------------------------------------------------------ snap
    def all_points(self):
        seen, out = set(), []
        def add(p):
            if p.id not in seen:
                seen.add(p.id)
                out.append(p)
        for p in self.points:
            add(p)
        for l in self.lines:
            add(l.p1)
            add(l.p2)
        for c in self.circles:
            add(c.center)
        for a in self.arcs:
            add(a.center)
            add(a.p1)
            add(a.p2)
        return out

    def snap(self, pos):
        """Snap to existing endpoint (FreeCAD endpoint snap), else to grid."""
        if not self.snap_on:
            return pos, None
        best, best_d = None, float(self.snap_px)
        for p in self.all_points():
            d = math.hypot(p.x - pos.x(), p.y - pos.y())
            if d < best_d:
                best, best_d = p, d
        if best is not None:
            return QPointF(best.x, best.y), best
        g = self.grid_step
        x = round(pos.x() / g) * g
        y = round(pos.y() / g) * g
        return QPointF(x, y), None

    # ------------------------------------------------------------------ drawing
    def _pen(self, geom):
        if self.status == STATUS_OVER:
            return QPen(C_INVALID, 2)
        if self.status == STATUS_FULL:
            return QPen(C_FULL, 2)
        if getattr(geom, "is_construction", False):
            return QPen(C_CONSTRUCTION, 2, Qt.PenStyle.DashLine)
        return QPen(C_NORMAL, 2)

    def _register_item(self, geom, item):
        self.scene.addItem(item)
        self.item_of_geom[geom.id] = item
        self.geom_of_item[item] = geom

    def draw_item(self, geom):
        if isinstance(geom, SketchPoint):
            item = QGraphicsEllipseItem(geom.x - 2.5, geom.y - 2.5, 5, 5)
            item.setPen(QPen(self._pen(geom).color(), 1.5))
            item.setBrush(QBrush(self._pen(geom).color()))
        elif isinstance(geom, SketchLine):
            item = QGraphicsLineItem(geom.p1.x, geom.p1.y, geom.p2.x, geom.p2.y)
            item.setPen(self._pen(geom))
        elif isinstance(geom, SketchCircle):
            r = geom.radius
            item = QGraphicsEllipseItem(geom.center.x - r, geom.center.y - r, 2 * r, 2 * r)
            item.setPen(self._pen(geom))
        else:
            item = QGraphicsPathItem(self._arc_path(geom))
            item.setPen(self._pen(geom))
        item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
        self._register_item(geom, item)

    # ------------------------------------------------------------------ geometry creation
    def add_point_geom(self, p):
        self.snapshot()
        self.points.append(p)
        self.draw_item(p)
        self.main_window.log(trt("Point added at ({x}, {y}).",
                                 x=round(p.x, 1), y=round(p.y, 1)))
        self.solve_sketch()
        return p

    def add_line(self, p1, p2, construction=None, auto_constrain=False):
        if math.hypot(p2.x - p1.x, p2.y - p1.y) < 0.5:
            self.main_window.log(tr("Line rejected: zero length."))
            return None
        self.snapshot()
        line = SketchLine(p1, p2, self.construction_mode if construction is None
                          else construction)
        self.lines.append(line)
        self.draw_item(line)
        self.main_window.log(trt("Line added from ({x1}, {y1}) to ({x2}, {y2}).",
                                 x1=round(p1.x, 1), y1=round(p1.y, 1),
                                 x2=round(p2.x, 1), y2=round(p2.y, 1)))
        self.solve_sketch()
        if auto_constrain:
            self._auto_hv(line)
        return line

    def _auto_hv(self, line):
        """FreeCAD auto-constraint: nearly axis-aligned lines get H/V."""
        ang = math.degrees(math.atan2(line.p2.y - line.p1.y,
                                      line.p2.x - line.p1.x)) % 180
        kind = None
        if ang <= 4 or ang >= 176:
            kind = "HORIZONTAL"
        elif abs(ang - 90) <= 4:
            kind = "VERTICAL"
        if kind is not None and not any(
                c["type"] == kind and c["targets"] == [line] for c in self.constraints):
            self.constraints.append({"type": kind, "targets": [line]})
            self.main_window.log(
                tr("Auto-constraint: horizontal") if kind == "HORIZONTAL"
                else tr("Auto-constraint: vertical"))
            self.solve_sketch()

    def add_circle(self, center, radius, construction=None):
        if radius < 0.5:
            self.main_window.log(tr("Circle rejected: radius too small."))
            return None
        self.snapshot()
        circle = SketchCircle(center, radius,
                              self.construction_mode if construction is None
                              else construction)
        self.circles.append(circle)
        self.draw_item(circle)
        self.main_window.log(trt("Circle added: center ({x}, {y}), radius {r}.",
                                 x=round(center.x, 1), y=round(center.y, 1),
                                 r=round(radius, 1)))
        self.solve_sketch()
        return circle

    def add_arc(self, p_start, mid_xy, p_end, construction=None):
        """Three-point arc (FreeCAD G,3)."""
        cc = circumcenter(p_start.x, p_start.y, mid_xy[0], mid_xy[1],
                          p_end.x, p_end.y)
        if cc is None:
            self.main_window.log(tr("Arc rejected: the three points are collinear."))
            return None
        self.snapshot()
        center = SketchPoint(*cc)
        radius = math.hypot(p_start.x - cc[0], p_start.y - cc[1])
        arc = SketchArc(center, radius, p_start, p_end, mid=mid_xy,
                        is_construction=(self.construction_mode
                                         if construction is None else construction))
        self.arcs.append(arc)
        self.draw_item(arc)
        self.main_window.log(
            trt("Arc added: center ({x}, {y}), radius {r}.",
                x=round(center.x, 1), y=round(center.y, 1), r=round(radius, 1)))
        self.solve_sketch()
        return arc

    def add_arc_center(self, center, p1, a2_deg, construction=None):
        """Center-based arc (FreeCAD G,A): center, rim start point, end angle."""
        radius = math.hypot(p1.x - center.x, p1.y - center.y)
        if radius < 0.5:
            self.main_window.log(tr("Arc rejected: radius too small."))
            return None
        a1 = math_angle(center.x, center.y, p1.x, p1.y)
        sweep = (a2_deg - a1) % 360
        am = (a1 + sweep / 2) % 360
        mid = (center.x + radius * math.cos(math.radians(am)),
               center.y - radius * math.sin(math.radians(am)))
        p2 = SketchPoint(center.x + radius * math.cos(math.radians(a2_deg)),
                         center.y - radius * math.sin(math.radians(a2_deg)))
        self.snapshot()
        arc = SketchArc(center, radius, p1, p2, mid=mid,
                        is_construction=(self.construction_mode
                                         if construction is None else construction))
        self.arcs.append(arc)
        self.draw_item(arc)
        self.main_window.log(
            trt("Arc added: center ({x}, {y}), radius {r}.",
                x=round(center.x, 1), y=round(center.y, 1), r=round(radius, 1)))
        self.solve_sketch()
        return arc

    def add_rectangle(self, corner1, corner2, construction=None):
        """FreeCAD-style: 4 lines with shared corners + auto H/V constraints."""
        x1, y1 = corner1
        x2, y2 = corner2
        if abs(x2 - x1) < 0.5 or abs(y2 - y1) < 0.5:
            self.main_window.log(tr("Rectangle rejected: degenerate shape."))
            return None
        bl, br = SketchPoint(x1, y1), SketchPoint(x2, y1)
        tpr, tpl = SketchPoint(x2, y2), SketchPoint(x1, y2)
        bottom = self.add_line(bl, br, construction)
        right = self.add_line(br, tpr, construction)
        top = self.add_line(tpr, tpl, construction)
        left = self.add_line(tpl, bl, construction)
        for line, kind in ((bottom, "HORIZONTAL"), (top, "HORIZONTAL"),
                           (left, "VERTICAL"), (right, "VERTICAL")):
            self.constraints.append({"type": kind, "targets": [line]})
        self.main_window.log(tr("Rectangle created with automatic H/V constraints."))
        self.solve_sketch()
        return (bottom, right, top, left)

    def add_polygon(self, center_xy, vertex_xy, sides, construction=None):
        """FreeCAD-style regular polygon: N chained lines + equal constraints."""
        cx, cy = center_xy
        vx, vy = vertex_xy
        r = math.hypot(vx - cx, vy - cy)
        if r < 0.5:
            self.main_window.log(tr("Polygon rejected: radius too small."))
            return None
        a0 = math.atan2(vy - cy, vx - cx)
        verts = [SketchPoint(cx + r * math.cos(a0 + 2 * math.pi * i / sides),
                             cy + r * math.sin(a0 + 2 * math.pi * i / sides))
                 for i in range(sides)]
        sides_lines = [self.add_line(verts[i], verts[(i + 1) % sides], construction)
                       for i in range(sides)]
        for i in range(sides - 1):
            self.constraints.append(
                {"type": "EQUAL", "targets": [sides_lines[i], sides_lines[i + 1]]})
        self.main_window.log(
            trt("Polygon ({n} sides) created with equal-side constraints.", n=sides))
        self.solve_sketch()
        return sides_lines

    def _arc_path(self, arc):
        cx, cy, r = arc.center.x, arc.center.y, arc.radius
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        a1 = math_angle(cx, cy, arc.p1.x, arc.p1.y)
        am = math_angle(cx, cy, *arc.mid)
        a2 = math_angle(cx, cy, arc.p2.x, arc.p2.y)
        span = (a2 - a1) % 360
        if (am - a1) % 360 > span:
            span -= 360  # sweep the other way so the arc passes through `mid`
        path = QPainterPath()
        path.arcMoveTo(rect, a1)
        path.arcTo(rect, a1, span)
        return path

    # ------------------------------------------------------------------ mouse
    def on_mouse_press(self, button, pos):
        if button == Qt.MouseButton.RightButton:
            if self._pick is not None or self.temp_points or self._poly_last is not None:
                self.cancel_temp()
                return True
            # FreeCAD: right-click a constraint badge deletes the constraint
            badge = self._badge_at(pos)
            if badge is not None:
                self._delete_constraint(badge)
                return True
            return False
        if button != Qt.MouseButton.LeftButton or self.draw_mode == "SELECT":
            if button == Qt.MouseButton.LeftButton and self._pick is not None:
                self._pick_click(pos)
                return True
            return False

        sp, existing = self.snap(pos)
        self.temp_points.append((sp, existing))

        if self.draw_mode == "POINT":
            (s, e), = self.temp_points
            self.add_point_geom(e or SketchPoint(s.x(), s.y()))
            self.temp_points = []
        elif self.draw_mode == "LINE" and len(self.temp_points) == 2:
            (s1, e1), (s2, e2) = self.temp_points
            p1 = e1 or SketchPoint(s1.x(), s1.y())
            p2 = e2 or SketchPoint(s2.x(), s2.y())
            self.add_line(p1, p2, auto_constrain=True)
            self.temp_points = []
        elif self.draw_mode == "POLYLINE":
            # continuous chain: every click after the first emits a segment
            (s, e) = self.temp_points[-1]
            p = e or SketchPoint(s.x(), s.y())
            if self._poly_last is None:
                self._poly_last = p
            else:
                if math.hypot(p.x - self._poly_last.x,
                              p.y - self._poly_last.y) >= 0.5:
                    self.add_line(self._poly_last, p, auto_constrain=True)
                    self._poly_last = p
            self.temp_points = []
        elif self.draw_mode == "CIRCLE" and len(self.temp_points) == 2:
            (s1, e1), (s2, _) = self.temp_points
            center = e1 or SketchPoint(s1.x(), s1.y())
            radius = math.hypot(s2.x() - center.x, s2.y() - center.y)
            self.add_circle(center, radius)
            self.temp_points = []
        elif self.draw_mode == "ARC3" and len(self.temp_points) == 3:
            (s1, e1), (s2, _), (s3, e3) = self.temp_points
            p1 = e1 or SketchPoint(s1.x(), s1.y())
            p2 = e3 or SketchPoint(s3.x(), s3.y())
            self.add_arc(p1, (s2.x(), s2.y()), p2)
            self.temp_points = []
        elif self.draw_mode == "ARC_CENTER" and len(self.temp_points) == 3:
            (s1, e1), (s2, e2), (s3, _) = self.temp_points
            center = e1 or SketchPoint(s1.x(), s1.y())
            p1 = e2 or SketchPoint(s2.x(), s2.y())
            a2 = math_angle(center.x, center.y, s3.x(), s3.y())
            self.add_arc_center(center, p1, a2)
            self.temp_points = []
        elif self.draw_mode == "RECT" and len(self.temp_points) == 2:
            (s1, _), (s2, _) = self.temp_points
            self.add_rectangle((s1.x(), s1.y()), (s2.x(), s2.y()))
            self.temp_points = []
        elif self.draw_mode in ("TRIANGLE", "SQUARE") and len(self.temp_points) == 2:
            (s1, _), (s2, _) = self.temp_points
            self.add_polygon((s1.x(), s1.y()), (s2.x(), s2.y()),
                             3 if self.draw_mode == "TRIANGLE" else 4)
            self.temp_points = []
        return True

    def on_double_click(self, pos):
        """FreeCAD: double-click a dimensional constraint badge to edit it."""
        badge = self._badge_at(pos)
        if badge is None:
            return False
        c = self._badge_of_item.get(badge)
        if c is None or "value" not in c:
            return False
        self._edit_constraint_value(c)
        return True

    # ------------------------------------------------------------------ selection & picking
    def selected_geometry(self):
        return [self.geom_of_item[it] for it in self.scene.selectedItems()
                if it in self.geom_of_item]

    def _resolve_slot(self, kind, pos):
        """Resolve one pick-slot from a click; returns object or None."""
        if kind == "point":
            return self._nearest_point(pos)
        if kind == "line":
            return self._find_geom_at(pos, kinds=(SketchLine,))
        if kind == "round":
            return self._find_geom_at(pos, kinds=(SketchCircle, SketchArc))
        if kind == "curve":
            return self._find_geom_at(pos, kinds=(SketchLine, SketchCircle, SketchArc))
        if kind == "geom":
            return self._find_geom_at(pos)
        if kind == "line_or_point":
            return self._nearest_point(pos) or \
                self._find_geom_at(pos, kinds=(SketchLine,))
        if kind in ("curve_or_point", "point_or_end"):
            return self._nearest_point(pos) or self._find_geom_at(pos)
        return None

    def _request(self, ctype):
        """FreeCAD constraint flow: use scene selection if it already matches
        the slots, otherwise enter click-picking mode. FreeCAD leaves the
        active creation command when a constraint is chosen."""
        self.temp_points = []
        self._poly_last = None
        self.draw_mode = "SELECT"
        kinds = self._SLOTS[ctype]
        pre = self._collect_preselected(kinds)
        if pre is not None:
            self._apply_constraint(ctype, pre)
            return
        self._pick = {"type": ctype, "kinds": list(kinds), "got": []}
        self.main_window.log(trt("Pick: {what}", what=self._pick_prompt(ctype)))

    def _pick_prompt(self, ctype):
        desc = {"point": tr("point"), "line": tr("line"), "round": tr("circle/arc"),
                "curve": tr("curve"), "geom": tr("geometry"),
                "line_or_point": tr("line or center point"),
                "curve_or_point": tr("curve or point"),
                "point_or_end": tr("second point")}
        return trt("Select {what} for the {c} constraint",
                   what=", ".join(desc[k] for k in self._SLOTS[ctype]), c=ctype)

    def _collect_preselected(self, kinds):
        """Map the current scene selection onto the required slots, or None."""
        geoms = self.selected_geometry()
        if not geoms:
            return None
        got = []
        pool = list(geoms)
        for kind in kinds:
            match = None
            for g in pool:
                if self._slot_matches(kind, g):
                    match = g
                    break
            if match is None:
                return None
            got.append(match)
            pool.remove(match)
        return got

    @staticmethod
    def _slot_matches(kind, g):
        if kind in ("point", "line_or_point", "curve_or_point", "point_or_end"):
            return isinstance(g, SketchPoint)
        if kind == "line":
            return isinstance(g, SketchLine)
        if kind == "round":
            return isinstance(g, (SketchCircle, SketchArc))
        if kind == "curve":
            return isinstance(g, (SketchLine, SketchCircle, SketchArc))
        return True  # "geom"

    def _pick_click(self, pos):
        pick = self._pick
        kinds = pick["kinds"]
        kind = kinds[len(pick["got"])] if len(pick["got"]) < len(kinds) else None
        if kind is None:
            return
        obj = self._resolve_slot(kind, pos)
        if obj is None:
            self.main_window.log(tr("Nothing picked - click closer to the target."))
            return
        pick["got"].append(obj)
        # dynamic early-completion: distance on a single line needs no 2nd point
        ctype = pick["type"]
        if ctype in ("DISTANCE", "DISTANCE_X", "DISTANCE_Y") and len(pick["got"]) == 1 \
                and isinstance(pick["got"][0], SketchLine):
            self._apply_constraint(ctype, pick["got"])
            self._pick = None
            return
        if len(pick["got"]) >= len(kinds):
            self._apply_constraint(ctype, pick["got"])
            self._pick = None

    # ------------------------------------------------------------------ constraint builders
    def _apply_constraint(self, ctype, got):
        if ctype == "COINCIDENT":
            self._apply_coincident(got[0], got[1])
            return
        if ctype in ("DISTANCE", "DISTANCE_X", "DISTANCE_Y"):
            self._apply_distance(ctype, got)
            return
        if ctype in ("RADIUS", "DIAMETER"):
            self._apply_radial(ctype, got[0])
            return
        if ctype == "ANGLE":
            self._apply_angle(got[0], got[1])
            return
        if ctype == "POINT_ON":
            self.snapshot()
            self.constraints.append(
                {"type": "POINT_ON", "targets": [got[1]], "point": got[0]})
            self.main_window.log(tr("POINT_ON constraint added."))
            self.solve_sketch()
            return
        if ctype == "SYMMETRIC":
            p1, p2, axis = got
            c = {"type": "SYMMETRIC", "targets": [], "points": [p1, p2]}
            if isinstance(axis, SketchLine):
                c["line"] = axis
            else:
                c["center"] = axis
            self.snapshot()
            self.constraints.append(c)
            self.main_window.log(tr("SYMMETRIC constraint added."))
            self.solve_sketch()
            return
        if ctype in ("LOCK", "BLOCK"):
            self._apply_lock(ctype, got[0])
            return
        # pair / single curve constraints
        self.snapshot()
        self.constraints.append({"type": ctype, "targets": list(got)})
        self.main_window.log(trt("{c} constraint added.", c=ctype))
        self.solve_sketch()

    def _apply_coincident(self, pa, pb):
        """Merge two endpoints into one shared SketchPoint (structural)."""
        if pa is pb:
            self.main_window.log(tr("Endpoints already coincident."))
            return
        self.snapshot()
        for geom in self._all_geometry():
            for attr in ("p1", "p2", "center"):
                if getattr(geom, attr, None) is pb:
                    setattr(geom, attr, pa)
        if pb in self.points:
            self.points.remove(pb)
            item = self.item_of_geom.pop(pb.id, None)
            if item is not None:
                self.geom_of_item.pop(item, None)
                self.scene.removeItem(item)
        for c in self.constraints:
            for key in ("points", "targets"):
                if c.get(key):
                    c[key] = [pa if obj is pb else obj for obj in c[key]]
            if c.get("point") is pb:
                c["point"] = pa
            if c.get("center") is pb:
                c["center"] = pa
        self.main_window.log(trt("COINCIDENT: points merged at ({x}, {y}).",
                                 x=round(pa.x, 1), y=round(pa.y, 1)))
        self.solve_sketch()

    def _apply_distance(self, ctype, got):
        target_line = got[0] if isinstance(got[0], SketchLine) else None
        points = None
        if target_line is None:
            points = [got[0], got[1]]
            cur = (math.hypot(got[1].x - got[0].x, got[1].y - got[0].y)
                   if ctype == "DISTANCE"
                   else (got[1].x - got[0].x if ctype == "DISTANCE_X"
                         else got[1].y - got[0].y))
        else:
            cur = (math.hypot(target_line.p2.x - target_line.p1.x,
                              target_line.p2.y - target_line.p1.y)
                   if ctype == "DISTANCE"
                   else (target_line.p2.x - target_line.p1.x if ctype == "DISTANCE_X"
                         else target_line.p2.y - target_line.p1.y))
        title = {"DISTANCE": tr("Distance Constraint"),
                 "DISTANCE_X": tr("Horizontal Distance Constraint"),
                 "DISTANCE_Y": tr("Vertical Distance Constraint")}[ctype]
        value, ok = QInputDialog.getDouble(self.main_window, title,
                                           tr("Value (mm):"), cur, -1e6, 1e6, 2)
        if not ok:
            return
        self.snapshot()
        c = {"type": ctype, "targets": [target_line] if target_line else [],
             "value": value}
        if points:
            c["points"] = points
        self.constraints.append(c)
        self.main_window.log(trt("{c} = {v} constraint added.",
                                 c=ctype, v=round(value, 2)))
        self.solve_sketch()

    def _apply_radial(self, ctype, geom):
        cur = geom.radius if ctype == "RADIUS" else 2 * geom.radius
        title = tr("Radius Constraint") if ctype == "RADIUS" \
            else tr("Diameter Constraint")
        value, ok = QInputDialog.getDouble(self.main_window, title,
                                           tr("Value (mm):"), cur, 0.01, 1e6, 2)
        if not ok:
            return
        self.snapshot()
        self.constraints.append({"type": ctype, "targets": [geom], "value": value})
        self.main_window.log(trt("{c} = {v} constraint added.",
                                 c=ctype, v=round(value, 2)))
        self.solve_sketch()

    def _apply_angle(self, l1, l2):
        def ang(l):
            return math.degrees(math.atan2(l.p2.y - l.p1.y, l.p2.x - l.p1.x))
        cur = abs(ang(l2) - ang(l1)) % 180
        value, ok = QInputDialog.getDouble(self.main_window, tr("Angle Constraint"),
                                           tr("Angle (deg):"), cur, 0.0, 180.0, 2)
        if not ok:
            return
        self.snapshot()
        self.constraints.append({"type": "ANGLE", "targets": [l1, l2],
                                 "value": value})
        self.main_window.log(trt("ANGLE = {v} deg constraint added.",
                                 v=round(value, 2)))
        self.solve_sketch()

    def _apply_lock(self, ctype, geom):
        points = list(self._geom_points(geom))
        radius = geom.radius if hasattr(geom, "radius") else None
        self.snapshot()
        self.constraints.append({
            "type": ctype, "targets": [geom], "points": points,
            "coords": [(p.x, p.y) for p in points], "radius": radius,
        })
        self.main_window.log(trt("{c} constraint added (geometry fixed in place).",
                                 c=ctype))
        self.solve_sketch()

    # ---- public constraint actions (toolbar / shortcuts) -------------------
    def add_coincident_constraint(self):
        """Merge endpoints: either 2 picked points, or the nearest endpoint
        pair of two selected lines (legacy convenience)."""
        lines = [g for g in self.selected_geometry() if isinstance(g, SketchLine)]
        if len(lines) >= 2:
            l1, l2 = lines[:2]
            pairs = [(l1.p1, l2.p1), (l1.p1, l2.p2), (l1.p2, l2.p1), (l1.p2, l2.p2)]
            pa, pb = min(pairs, key=lambda pr: math.hypot(pr[0].x - pr[1].x,
                                                          pr[0].y - pr[1].y))
            self._apply_coincident(pa, pb)
            return
        self._request("COINCIDENT")

    def add_point_on_constraint(self):
        self._request("POINT_ON")

    def add_horizontal_constraint(self):
        self._request("HORIZONTAL")

    def add_vertical_constraint(self):
        self._request("VERTICAL")

    def add_parallel_constraint(self):
        self._request("PARALLEL")

    def add_perpendicular_constraint(self):
        self._request("PERPENDICULAR")

    def add_tangent_constraint(self):
        self._request("TANGENT")

    def add_equal_constraint(self):
        self._request("EQUAL")

    def add_symmetric_constraint(self):
        self._request("SYMMETRIC")

    def add_length_constraint(self):
        self._request("DISTANCE")

    def add_distance_x_constraint(self):
        self._request("DISTANCE_X")

    def add_distance_y_constraint(self):
        self._request("DISTANCE_Y")

    def add_radius_constraint(self):
        self._request("RADIUS")

    def add_diameter_constraint(self):
        self._request("DIAMETER")

    def add_angle_constraint(self):
        self._request("ANGLE")

    def add_lock_constraint(self):
        self._request("LOCK")

    def add_block_constraint(self):
        self._request("BLOCK")

    def _edit_constraint_value(self, c):
        value, ok = QInputDialog.getDouble(
            self.main_window, tr("Edit Constraint"), tr("Value:"),
            c["value"], -1e6, 1e6, 2)
        if not ok:
            return
        self.snapshot()
        c["value"] = value
        self.main_window.log(trt("{c} changed to {v}.", c=c["type"],
                                 v=round(value, 2)))
        self.solve_sketch()

    def _delete_constraint(self, badge_item):
        c = self._badge_of_item.get(badge_item)
        if c is None:
            return
        self.snapshot()
        self.constraints.remove(c)
        self.main_window.log(trt("{c} constraint removed.", c=c["type"]))
        self.solve_sketch()

    # ------------------------------------------------------------------ solver
    def solve_sketch(self):
        self.dof, residual, self.status, redundant = self.solver.solve(
            self.lines, self.circles, self.arcs, self.constraints, self.points)
        self._restyle()
        self._rebuild_badges()

        if self.status == STATUS_FULL:
            msg = tr("Fully constrained sketch")
        elif self.status == STATUS_OVER:
            msg = tr("Conflicting constraints - sketch could not be solved")
        elif self.status == STATUS_UNDER:
            msg = trt("Under-constrained sketch with {n} degrees of freedom",
                      n=self.dof)
        else:
            msg = tr("Empty sketch")
        if redundant and self.status != STATUS_OVER:
            msg += tr(" (redundant constraints detected)")
        self._update_dof_label()
        self.main_window.log(f"Solver: {msg} (residual {residual:.2e})")
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def _update_dof_label(self):
        self._dof_text = f" {tr('DOF:')} {self.dof} "
        label = getattr(self, "dof_label", None)
        if label is not None:
            label.setText(self._dof_text)

    def _restyle(self):
        for geom in self._all_geometry():
            self.update_item(geom)

    def update_item(self, geom):
        item = self.item_of_geom.get(geom.id)
        if item is None:
            return
        pen = self._pen(geom)
        if item.isSelected():
            pen = QPen(C_SELECTED, 2)
        if isinstance(geom, SketchPoint):
            item.setRect(geom.x - 2.5, geom.y - 2.5, 5, 5)
            item.setPen(QPen(pen.color(), 1.5))
            item.setBrush(QBrush(pen.color()))
        elif isinstance(geom, SketchLine):
            item.setLine(geom.p1.x, geom.p1.y, geom.p2.x, geom.p2.y)
            item.setPen(pen)
        elif isinstance(geom, SketchCircle):
            r = geom.radius
            item.setRect(geom.center.x - r, geom.center.y - r, 2 * r, 2 * r)
            item.setPen(pen)
        else:
            item.setPath(self._arc_path(geom))
            item.setPen(pen)

    # ------------------------------------------------------------------ badges
    def _badge_text_pos(self, c):
        """Badge (text, position, is_dimensional) for one constraint."""
        t = c["type"]
        tg = c.get("targets") or []
        def line_mid(l):
            return QPointF((l.p1.x + l.p2.x) / 2, (l.p1.y + l.p2.y) / 2 - 14)
        def round_pos(g):
            return QPointF(g.center.x + g.radius * 0.7,
                           g.center.y - g.radius * 0.7 - 12)
        geo, dim = C_BADGE_GEO, C_BADGE_DIM
        if t == "HORIZONTAL":
            return "H", line_mid(tg[0]), geo
        if t == "VERTICAL":
            return "V", line_mid(tg[0]), geo
        if t == "PARALLEL":
            return "//", line_mid(tg[0]), geo
        if t == "PERPENDICULAR":
            return "T+", line_mid(tg[0]), geo
        if t == "TANGENT":
            return "T", line_mid(tg[0]) if isinstance(tg[0], SketchLine) \
                else round_pos(tg[0]), geo
        if t == "EQUAL":
            return "=", line_mid(tg[0]) if isinstance(tg[0], SketchLine) \
                else round_pos(tg[0]), geo
        if t == "SYMMETRIC":
            p1, p2 = c["points"]
            return "SYM", QPointF((p1.x + p2.x) / 2, (p1.y + p2.y) / 2 - 14), geo
        if t == "POINT_ON":
            p = c["point"]
            return "ON", QPointF(p.x + 8, p.y - 16), geo
        if t in ("LOCK", "BLOCK"):
            g = tg[0] if tg else None
            if g is None:
                return None
            pts = self._geom_points(g)
            x = sum(p.x for p in pts) / len(pts)
            y = sum(p.y for p in pts) / len(pts)
            return ("LK" if t == "LOCK" else "BLK"), QPointF(x + 8, y - 16), geo
        if t in ("DISTANCE", "LENGTH"):
            if c.get("points"):
                p1, p2 = c["points"]
                pos = QPointF((p1.x + p2.x) / 2, (p1.y + p2.y) / 2 - 14)
            else:
                pos = line_mid(tg[0])
            return f"D {c['value']:.2f}", pos, dim
        if t == "DISTANCE_X":
            if c.get("points"):
                p1, p2 = c["points"]
                pos = QPointF((p1.x + p2.x) / 2, (p1.y + p2.y) / 2 - 14)
            else:
                pos = line_mid(tg[0])
            return f"DX {c['value']:.2f}", pos, dim
        if t == "DISTANCE_Y":
            if c.get("points"):
                p1, p2 = c["points"]
                pos = QPointF((p1.x + p2.x) / 2, (p1.y + p2.y) / 2 - 14)
            else:
                pos = line_mid(tg[0])
            return f"DY {c['value']:.2f}", pos, dim
        if t == "RADIUS":
            return f"R {c['value']:.2f}", round_pos(tg[0]), dim
        if t == "DIAMETER":
            return f"DIA {c['value']:.2f}", round_pos(tg[0]), dim
        if t == "ANGLE":
            return f"{c['value']:.1f} deg", line_mid(tg[0]), dim
        return None

    def _rebuild_badges(self):
        for item in self._badge_items:
            self.scene.removeItem(item)
        self._badge_items = []
        self._badge_of_item = {}
        font = QFont("Arial", 9)
        used = []  # FreeCAD stacks constraint icons side by side
        for c in self.constraints:
            spec = self._badge_text_pos(c)
            if spec is None:
                continue
            text, pos, color = spec
            while any(abs(pos.x() - ux) < 44 and abs(pos.y() - uy) < 14
                      for ux, uy in used):
                pos = QPointF(pos.x() + 44, pos.y())
            used.append((pos.x(), pos.y()))
            item = QGraphicsSimpleTextItem(text)
            item.setFont(font)
            item.setBrush(QBrush(color))
            item.setPos(pos)
            item.setZValue(100)
            self.scene.addItem(item)
            self._badge_items.append(item)
            self._badge_of_item[item] = c

    def _badge_at(self, pos, tol=16):
        best, best_d = None, float(tol)
        for item in self._badge_items:
            d = math.hypot(item.pos().x() - pos.x(), item.pos().y() - pos.y())
            if d < best_d:
                best, best_d = item, d
        return best

    # ------------------------------------------------------------------ undo / redo
    def snapshot(self):
        self._undo.append(copy.deepcopy(
            (self.lines, self.circles, self.arcs, self.points, self.constraints)))
        if len(self._undo) > 50:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self):
        if not self._undo:
            self.main_window.log(tr("Nothing to undo."))
            return
        self._redo.append(copy.deepcopy(
            (self.lines, self.circles, self.arcs, self.points, self.constraints)))
        self._restore(self._undo.pop())
        self.main_window.log(tr("Undo."))

    def redo(self):
        if not self._redo:
            self.main_window.log(tr("Nothing to redo."))
            return
        self._undo.append(copy.deepcopy(
            (self.lines, self.circles, self.arcs, self.points, self.constraints)))
        self._restore(self._redo.pop())
        self.main_window.log(tr("Redo."))

    def _restore(self, snap):
        self.lines, self.circles, self.arcs, self.points, self.constraints = snap
        self.temp_points = []
        self._poly_last = None
        self._pick = None
        self._drag = None
        for item in list(self.item_of_geom.values()):
            self.scene.removeItem(item)
        self.item_of_geom, self.geom_of_item = {}, {}
        for geom in self._all_geometry():
            self.draw_item(geom)
        self.solve_sketch()

    # ------------------------------------------------------------------ editing
    def delete_selected(self):
        geoms = self.selected_geometry()
        if not geoms:
            return
        self.snapshot()
        dead = {id(g) for g in geoms}
        dead_pts = {id(p) for g in geoms for p in self._geom_points(g)}
        for g in geoms:
            for lst in (self.lines, self.circles, self.arcs, self.points):
                if g in lst:
                    lst.remove(g)
            item = self.item_of_geom.pop(g.id, None)
            if item is not None:
                self.geom_of_item.pop(item, None)
                self.scene.removeItem(item)
        self.constraints = [
            c for c in self.constraints
            if all(id(t) not in dead for t in (c.get("targets") or ()))
            and all(id(p) not in dead_pts for p in (c.get("points") or ()))
            and (c.get("point") is None or id(c["point"]) not in dead_pts)
            and (c.get("center") is None or id(c["center"]) not in dead_pts)
        ]
        self.main_window.log(trt("Deleted {n} geometry element(s).", n=len(geoms)))
        self.solve_sketch()

    def clear_sketch(self):
        if not self._all_geometry() and not self.constraints:
            return
        self.snapshot()
        self.lines, self.circles, self.arcs, self.points, self.constraints = \
            [], [], [], [], []
        for item in list(self.item_of_geom.values()):
            self.scene.removeItem(item)
        self.item_of_geom, self.geom_of_item = {}, {}
        self.temp_points = []
        self._poly_last = None
        self.main_window.log(tr("Sketch cleared."))
        self.solve_sketch()

    # ------------------------------------------------------------------ dock / export
    def update_dock_views(self, tree_widget, property_table):
        tree_widget.clear()
        for idx, p in enumerate(self.points, start=1):
            tag = tr(" (construction)") if p.is_construction else ""
            tree_widget.addItem(
                f"{tr('Point')} {idx}{tag} [({p.x:.0f},{p.y:.0f})]")
        for idx, l in enumerate(self.lines, start=1):
            tag = tr(" (construction)") if l.is_construction else ""
            tree_widget.addItem(
                f"{tr('Line')} {idx}{tag} [({l.p1.x:.0f},{l.p1.y:.0f}) -> ({l.p2.x:.0f},{l.p2.y:.0f})]")
        for idx, c in enumerate(self.circles, start=1):
            tag = tr(" (construction)") if c.is_construction else ""
            tree_widget.addItem(
                f"{tr('Circle')} {idx}{tag} [C: ({c.center.x:.0f},{c.center.y:.0f}), R: {c.radius:.0f}]")
        for idx, a in enumerate(self.arcs, start=1):
            tag = tr(" (construction)") if a.is_construction else ""
            tree_widget.addItem(
                f"{tr('Arc')} {idx}{tag} [C: ({a.center.x:.0f},{a.center.y:.0f}), R: {a.radius:.0f}]")

        status_text = {
            STATUS_FULL: tr("Fully constrained"),
            STATUS_OVER: tr("Over-constrained (redundant/conflicting)"),
            STATUS_UNDER: tr("Under-constrained"),
            STATUS_EMPTY: tr("Empty sketch"),
        }[self.status]
        rows = [
            (tr("Solver Status"), status_text),
            (tr("Degrees of Freedom"), str(self.dof)),
            (tr("Points / Lines / Circles / Arcs"),
             f"{len(self.points)} / {len(self.lines)} / {len(self.circles)} / {len(self.arcs)}"),
            (tr("Active Constraints"), str(len(self.constraints))),
            (tr("Snap"), f"{'ON' if self.snap_on else 'OFF'} (grid {self.grid_step})"),
            (tr("Solver Engine"),
             tr("SciPy least-squares") if HAS_SCIPY else tr("DOF fallback (no SciPy)")),
        ]
        property_table.setRowCount(len(rows))
        for i, (key, value) in enumerate(rows):
            property_table.setItem(i, 0, QTableWidgetItem(key))
            property_table.setItem(i, 1, QTableWidgetItem(value))

    def export_data(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, tr("Export Sketch JSON"), "", tr("JSON Files (*.json)"))
        if not file_path:
            return
        data = {
            "points": [{"id": p.id, "x": p.x, "y": p.y} for p in self.points],
            "lines": [
                {"id": l.id, "p1": [l.p1.x, l.p1.y], "p2": [l.p2.x, l.p2.y],
                 "is_construction": l.is_construction}
                for l in self.lines
            ],
            "circles": [
                {"id": c.id, "center": [c.center.x, c.center.y], "radius": c.radius,
                 "is_construction": c.is_construction}
                for c in self.circles
            ],
            "arcs": [
                {"id": a.id, "center": [a.center.x, a.center.y], "radius": a.radius,
                 "p1": [a.p1.x, a.p1.y], "p2": [a.p2.x, a.p2.y],
                 "is_construction": a.is_construction}
                for a in self.arcs
            ],
            "constraints": [
                {"type": c["type"], "targets": [t.id for t in (c.get("targets") or [])],
                 **({"value": c["value"]} if "value" in c else {})}
                for c in self.constraints
            ],
            "dof": self.dof,
            "status": self.status,
        }
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except OSError as e:
            QMessageBox.critical(self.main_window, tr("Export Failed"),
                                 tr("Could not write file:") + f"\n{e}")
            return
        QMessageBox.information(
            self.main_window, tr("Exported"),
            f"Exported {len(self.lines)} lines, {len(self.circles)} circles, "
            f"{len(self.arcs)} arcs\nSaved to: {file_path}")
