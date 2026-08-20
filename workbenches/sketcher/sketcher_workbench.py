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
                             QMenu, QMessageBox, QSpinBox, QTableWidgetItem)

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


# ---------------------------------------------------------------- FreeCAD-style icons
_ICON_RED = QColor(220, 30, 30)
_ICON_TEXT = QColor(30, 30, 30)


def _icon_dots(p, pts, r=2.2):
    p.setPen(QPen(_ICON_RED, 1.2))
    p.setBrush(QBrush(_ICON_RED))
    for x, y in pts:
        p.drawEllipse(QPointF(x, y), r, r)


def _draw_dim_icon(p, kind):
    """FreeCAD-style dimensional-constraint glyph (24x24 painter)."""
    pen = QPen(_ICON_RED, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "DIM":  # ruler with arrowheads, used for the dimension group
        p.drawLine(4, 12, 20, 12)
        p.drawLine(4, 12, 8, 8)
        p.drawLine(4, 12, 8, 16)
        p.drawLine(20, 12, 16, 8)
        p.drawLine(20, 12, 16, 16)
        for x in (7, 12, 17):
            p.drawLine(x, 9, x, 15)
    elif kind == "DIST_X":  # H: two vertical bars joined by an arrowed line
        p.drawLine(5, 5, 5, 19)
        p.drawLine(19, 5, 19, 19)
        p.drawLine(5, 12, 19, 12)
        p.drawLine(5, 12, 9, 9)
        p.drawLine(5, 12, 9, 15)
        p.drawLine(19, 12, 15, 9)
        p.drawLine(19, 12, 15, 15)
    elif kind == "DIST_Y":  # I: two horizontal bars joined by an arrowed line
        p.drawLine(5, 5, 19, 5)
        p.drawLine(5, 19, 19, 19)
        p.drawLine(12, 5, 12, 19)
        p.drawLine(12, 5, 9, 9)
        p.drawLine(12, 5, 15, 9)
        p.drawLine(12, 19, 9, 15)
        p.drawLine(12, 19, 15, 15)
    elif kind == "DIST":  # diagonal double-arrow (point-to-point)
        p.drawLine(5, 19, 19, 5)
        p.drawLine(5, 19, 10, 19)
        p.drawLine(5, 19, 5, 14)
        p.drawLine(19, 5, 14, 5)
        p.drawLine(19, 5, 19, 10)
    elif kind == "RADIUS":  # circle with a radius spoke
        p.drawEllipse(QPointF(13, 11), 8, 8)
        p.drawLine(13, 11, 19, 5)
        _icon_dots(p, [(13, 11)], r=1.8)
    elif kind == "DIAMETER":  # circle with a diagonal slash through it
        p.drawEllipse(QPointF(12, 12), 8, 8)
        p.drawLine(6, 18, 18, 6)
    elif kind == "ANGLE":  # wedge with a small arc
        p.drawLine(4, 18, 20, 18)
        p.drawLine(4, 18, 16, 6)
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 10, 16, 16), 0)
        path.arcTo(QRectF(4, 10, 16, 16), 0, 45)
        p.drawPath(path)
    elif kind == "LOCK":  # padlock
        p.drawRect(7, 11, 10, 9)
        path = QPainterPath()
        path.arcMoveTo(QRectF(8, 3, 8, 10), 0)
        path.arcTo(QRectF(8, 3, 8, 10), 0, 180)
        p.drawPath(path)
        _icon_dots(p, [(12, 15)], r=1.6)
    elif kind == "BLOCK":  # circle with a crossed prohibition slash
        p.drawEllipse(QPointF(12, 12), 8, 8)
        p.drawLine(6, 6, 18, 18)


def make_dim_icon(kind):
    from PyQt6.QtGui import QPixmap, QIcon
    pm = QPixmap(24, 24)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_dim_icon(p, kind)
    p.end()
    return QIcon(pm)


def _draw_icon_shape(p, kind):
    """FreeCAD-style red glyph on a transparent canvas (24x24 painter)."""
    pen = QPen(_ICON_RED, 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "POINT":
        _icon_dots(p, [(12, 12)], r=3.0)
    elif kind == "LINE":
        p.drawLine(5, 19, 19, 5)
        _icon_dots(p, [(5, 19), (19, 5)])
    elif kind == "POLYLINE":
        path = QPainterPath(QPointF(4, 18))
        path.lineTo(10, 9)
        path.lineTo(15, 14)
        path.lineTo(20, 5)
        p.drawPath(path)
        _icon_dots(p, [(4, 18), (10, 9), (15, 14), (20, 5)])
    elif kind == "CIRCLE":
        p.drawEllipse(QPointF(12, 12), 8, 8)
        _icon_dots(p, [(12, 12), (12, 4)])
    elif kind == "ARC_CENTER":
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 4, 16, 16), 0)
        path.arcTo(QRectF(4, 4, 16, 16), 0, 120)
        p.drawPath(path)
        _icon_dots(p, [(12, 12), (20, 12), (8, 5.1)])
    elif kind == "ARC3":
        path = QPainterPath()
        path.arcMoveTo(QRectF(4, 4, 16, 16), 20)
        path.arcTo(QRectF(4, 4, 16, 16), 20, 140)
        p.drawPath(path)
        _icon_dots(p, [(19.5, 9.5), (12, 3.2), (4.8, 14.2)])
    elif kind == "RECT":
        p.drawRect(5, 7, 14, 10)
        _icon_dots(p, [(5, 7), (19, 7), (19, 17), (5, 17)])
    elif kind == "TRIANGLE":
        path = QPainterPath(QPointF(12, 5))
        path.lineTo(20, 18)
        path.lineTo(4, 18)
        path.closeSubpath()
        p.drawPath(path)
        _icon_dots(p, [(12, 5), (20, 18), (4, 18)])
    elif kind == "SQUARE":
        p.drawRect(6, 6, 12, 12)
        _icon_dots(p, [(6, 6), (18, 6), (18, 18), (6, 18)])
    elif kind == "CONSTRUCTION":
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setColor(QColor(70, 130, 220))
        p.setPen(pen)
        p.drawRect(5, 7, 14, 10)
    elif kind == "SNAP":
        _icon_dots(p, [(12, 12)], r=2.5)
        p.drawLine(12, 3, 12, 7)
        p.drawLine(12, 17, 12, 21)
        p.drawLine(3, 12, 7, 12)
        p.drawLine(17, 12, 21, 12)
    elif kind == "REFLINE":  # dashed infinite-ish reference line
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setColor(QColor(70, 130, 220))
        p.setPen(pen)
        p.drawLine(3, 18, 21, 6)
    # ---- geometric constraints (FreeCAD photo style) --------------------
    elif kind == "COINCIDENT":  # two endpoints merging into one
        p.drawLine(4, 8, 12, 12)
        p.drawLine(20, 8, 12, 12)
        _icon_dots(p, [(4, 8), (20, 8)], r=2.0)
        _icon_dots(p, [(12, 12)], r=3.0)
    elif kind == "POINT_ON":  # point sitting on a curve
        path = QPainterPath(QPointF(4, 16))
        path.quadTo(12, 4, 20, 16)
        p.drawPath(path)
        _icon_dots(p, [(12, 9.5)], r=3.0)
    elif kind == "H_CONSTR":  # bold H
        p.drawLine(6, 5, 6, 19)
        p.drawLine(18, 5, 18, 19)
        p.drawLine(6, 12, 18, 12)
    elif kind == "V_CONSTR":  # perpendicular mark
        p.drawLine(5, 17, 19, 17)
        p.drawLine(12, 17, 12, 5)
        p.drawRect(8, 13, 4, 4)
    elif kind == "PARALLEL_CON":  # //
        p.drawLine(8, 19, 13, 5)
        p.drawLine(13, 19, 18, 5)
    elif kind == "PERP_CON":  # < rotated (perpendicular glyph)
        p.drawLine(5, 12, 13, 20)
        p.drawLine(5, 12, 13, 4)
    elif kind == "TANGENT_CON":  # circle with tangent line
        p.drawEllipse(QPointF(12, 13), 6, 6)
        p.drawLine(4, 19, 20, 19)
    elif kind == "EQUAL_CON":  # =
        p.drawLine(5, 10, 19, 10)
        p.drawLine(5, 15, 19, 15)
    elif kind == "SYMM_CON":  # two triangles mirrored about a dashed axis
        pen.setStyle(Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawLine(12, 3, 12, 21)
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.drawLine(4, 8, 8, 12)
        p.drawLine(4, 16, 8, 12)
        p.drawLine(20, 8, 16, 12)
        p.drawLine(20, 16, 16, 12)


def make_tool_icon(kind, label=""):
    """FreeCAD-style red tool icon; optional 1-3 letter overlay like FreeCAD."""
    from PyQt6.QtGui import QPixmap
    pm = QPixmap(24, 24)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    _draw_icon_shape(p, kind)
    if label:
        f = QFont("Arial", 8, QFont.Weight.Bold)
        p.setFont(f)
        p.setPen(QPen(_ICON_TEXT))
        p.drawText(pm.rect(), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight,
                   label)
    p.end()
    from PyQt6.QtGui import QIcon
    return QIcon(pm)


def make_constraint_icon(text):
    """FreeCAD-style red constraint badge icon (letters only)."""
    from PyQt6.QtGui import QPixmap, QIcon
    pm = QPixmap(24, 24)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont("Arial", 10 if len(text) <= 2 else 8, QFont.Weight.Bold)
    p.setFont(f)
    p.setPen(QPen(_ICON_RED))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return QIcon(pm)


class SketcherView(QGraphicsView):
    """Canvas view delegating clicks / drags / keys to the workbench."""

    def __init__(self, workbench):
        super().__init__(workbench.scene)
        self.wb = workbench
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMouseTracking(True)
        # rubber-band box select in Select mode
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)

    def mousePressEvent(self, event):
        pos = self.mapToScene(event.pos())
        if event.button() == Qt.MouseButton.LeftButton and \
                event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if self.wb.ctrl_click(pos):
                return  # ctrl+click multi-select handled
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
        ("REFLINE", 2, "Reference line", "G, X"),
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

        # FreeCAD model geometry: origin point + X/Y reference axes.
        # These are REAL geometry (can be referenced by constraints) but are
        # locked in place and not user-deletable.
        self._origin = SketchPoint(0.0, 0.0)
        self._x_axis = SketchLine(SketchPoint(-1000, 0), SketchPoint(1000, 0),
                                  is_construction=True)
        self._y_axis = SketchLine(SketchPoint(0, -1000), SketchPoint(0, 1000),
                                  is_construction=True)
        self._fixed_ids = {self._origin.id, self._x_axis.id, self._y_axis.id}

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
        # register selectable scene items for origin/axes (constraint targets)
        for geom, color, width in (
                (self._x_axis, QColor(200, 40, 40), 0),
                (self._y_axis, QColor(40, 160, 40), 0)):
            it = QGraphicsLineItem(geom.p1.x, geom.p1.y, geom.p2.x, geom.p2.y)
            it.setPen(QPen(color, width))
            it.setFlag(it.GraphicsItemFlag.ItemIsSelectable, True)
            self.scene.addItem(it)
            self.item_of_geom[geom.id] = it
            self.geom_of_item[it] = geom
        self._hover_geom = None        # preselection highlight
        self._badge_items = []         # constraint badge items
        self._badge_of_item = {}       # badge item -> constraint dict
        self._vertex_items = {}        # SketchPoint.id -> red vertex handle item
        self._vertex_size = 7.0        # handle edge length (scene units)
        self._preview = None           # rubber-band item while creating

        self.solver = SketchSolver()
        self.dof = 0
        self.status = STATUS_EMPTY

        # Interaction state
        self._drag = None              # {"points": [...], "last": QPointF}
        self._composing = False        # inside a composite shape (rect/polygon)
        self._key_prefix = ""          # "G" arms FreeCAD-style create-tool keys
        self._sel_points = []          # ctrl+click multi-selected SketchPoints
        self._constr_action = None     # toolbar action kept for sync
        self._pick = None              # {"type", "kinds", "got"}

        # Undo / redo (deep snapshots; shared points keep identity via memo)
        self._undo = []
        self._redo = []

        self._draw_grid()

        # Toolbar label state (the QLabel itself is rebuilt on every
        # workbench switch; see PDF workbench for the rationale)
        self._dof_text = f" {tr('DOF:')} — "
        # lock origin + axes permanently
        self.constraints.append({
            "type": "LOCK",
            "targets": [self._origin],
            "points": [self._origin], "coords": [(0.0, 0.0)], "radius": None,
            "builtin": True})
        self.constraints.append({
            "type": "LOCK",
            "targets": [self._x_axis],
            "points": list(self._geom_points(self._x_axis)),
            "coords": [(-1000.0, 0.0), (1000.0, 0.0)], "radius": None,
            "builtin": True})
        self.constraints.append({
            "type": "LOCK",
            "targets": [self._y_axis],
            "points": list(self._geom_points(self._y_axis)),
            "coords": [(0.0, -1000.0), (0.0, 1000.0)], "radius": None,
            "builtin": True})

    # ------------------------------------------------------------------ UI
    def _draw_grid(self):
        # draw with zero-width (cosmetic) pens so the grid is always 1px on
        # screen regardless of zoom, and stays visible in the default view
        grid_pen = QPen(QColor(225, 225, 225), 0, Qt.PenStyle.DotLine)
        for x in range(-1000, 1000, 50):
            self.scene.addLine(x, -1000, x, 1000, grid_pen)
        for y in range(-1000, 1000, 50):
            self.scene.addLine(-1000, y, 1000, y, grid_pen)
        # FreeCAD default XY reference lines: X axis red, Y axis green
        x_pen = QPen(QColor(200, 40, 40), 0)
        y_pen = QPen(QColor(40, 160, 40), 0)
        self.scene.addLine(-1000, 0, 1000, 0, x_pen)
        self.scene.addLine(0, -1000, 0, 1000, y_pen)
        label_font = QFont("Arial", 10, QFont.Weight.Bold)
        x_label = QGraphicsSimpleTextItem("X")
        x_label.setFont(label_font)
        x_label.setBrush(QBrush(QColor(200, 40, 40)))
        x_label.setPos(985, -22)
        self.scene.addItem(x_label)
        y_label = QGraphicsSimpleTextItem("Y")
        y_label.setFont(label_font)
        y_label.setBrush(QBrush(QColor(40, 160, 40)))
        y_label.setPos(6, -995)
        self.scene.addItem(y_label)
        # FreeCAD red origin marker at (0,0)
        origin = self.scene.addEllipse(-4, -4, 8, 8,
                                       QPen(QColor(200, 0, 0), 2),
                                       QBrush(QColor(220, 40, 40)))
        origin.setZValue(40)
        # default view centred on the origin (like FreeCAD's sketch view)
        self.view.centerOn(0, 0)

    def get_central_widget(self):
        return self.view

    def setup_toolbar(self, toolbar):
        # FreeCAD-style red icons; text lives in the tooltip (and status tip)
        for mode, _, label_key, sc in self.TOOLS:
            label = tr(label_key)
            act = QAction(make_tool_icon(mode), "", self.main_window)
            act.setCheckable(True)
            act.setChecked(self.draw_mode == mode)
            act.setToolTip(f"{label} ({sc})")
            act.setStatusTip(f"{label} ({sc})")
            act.triggered.connect(
                lambda checked, m=mode: self.set_draw_mode(m if checked else "SELECT"))
            toolbar.addAction(act)

        constr_act = QAction(make_tool_icon("CONSTRUCTION"), "", self.main_window)
        constr_act.setCheckable(True)
        constr_act.setChecked(self.construction_mode)
        constr_act.setToolTip(f"{tr('Construction')} (G, N " + tr("toggles selection") + ")")
        constr_act.triggered.connect(self._toggle_construction)
        toolbar.addAction(constr_act)
        self._constr_action = constr_act

        toolbar.addSeparator()

        snap_act = QAction(make_tool_icon("SNAP"), "", self.main_window)
        snap_act.setCheckable(True)
        snap_act.setChecked(self.snap_on)
        snap_act.setToolTip(tr("Snap"))
        snap_act.triggered.connect(lambda checked: setattr(self, "snap_on", checked))
        toolbar.addAction(snap_act)
        grid_spin = QSpinBox(minimum=1, maximum=100, value=self.grid_step)
        grid_spin.setFixedWidth(52)
        grid_spin.valueChanged.connect(lambda v: setattr(self, "grid_step", v))
        toolbar.addWidget(QLabel(tr(" Grid ")))
        toolbar.addWidget(grid_spin)

        toolbar.addSeparator()

        # ---- geometric constraints (FreeCAD glyphs) -------------------------
        for kind, label, sc, handler in (
            ("COINCIDENT", tr("Coincident"), "C", self.add_coincident_constraint),
            ("POINT_ON", tr("Point-on"), "O", self.add_point_on_constraint),
            ("H_CONSTR", "H", "H", self.add_horizontal_constraint),
            ("V_CONSTR", "V", "V", self.add_vertical_constraint),
            ("PARALLEL_CON", tr("Parallel"), "P", self.add_parallel_constraint),
            ("PERP_CON", tr("Perp"), "N", self.add_perpendicular_constraint),
            ("TANGENT_CON", tr("Tangent"), "T", self.add_tangent_constraint),
            ("EQUAL_CON", tr("Equal"), "E", self.add_equal_constraint),
            ("SYMM_CON", tr("Symmetric"), "S", self.add_symmetric_constraint),
        ):
            act = QAction(make_tool_icon(kind), "", self.main_window)
            tip = f"{label} ({sc})"
            act.setToolTip(tip)
            act.setStatusTip(tip)
            act.triggered.connect(handler)
            toolbar.addAction(act)

        # ---- dimension group: one dropdown button, like FreeCAD -------------
        dim_act = QAction(make_dim_icon("DIM"), "", self.main_window)
        dim_act.setToolTip(tr("Dimension constraints"))
        dim_act.setStatusTip(tr("Dimension constraints"))
        dim_menu = QMenu(self.main_window)
        dim_items = (
            ("DIM", tr("Dimension"), "D", self.add_length_constraint),
            ("DIST_X", tr("Horizontal distance constraint"), "L",
             self.add_distance_x_constraint),
            ("DIST_Y", tr("Vertical distance constraint"), "I",
             self.add_distance_y_constraint),
            ("DIST", tr("Distance constraint"), "K, D", self.add_length_constraint),
            ("RADIUS", tr("Radius constraint"), "K, R", self.add_radius_constraint),
            ("DIAMETER", tr("Diameter constraint"), "K, O",
             self.add_diameter_constraint),
            ("ANGLE", tr("Angle constraint"), "K, A", self.add_angle_constraint),
            ("LOCK", tr("Lock constraint"), "K, L", self.add_lock_constraint),
        )
        for kind, label, sc, handler in dim_items:
            act = dim_menu.addAction(make_dim_icon(kind), f"{label}\t{sc}")
            act.triggered.connect(handler)
        dim_act.setMenu(dim_menu)
        toolbar.addAction(dim_act)
        dim_btn = toolbar.widgetForAction(dim_act)
        if dim_btn is not None:
            dim_btn.setPopupMode(dim_btn.ToolButtonPopupMode.MenuButtonPopup)
            dim_btn.clicked.connect(self.add_length_constraint)

        # block stays standalone (not in FreeCAD's dimension menu)
        blk_act = QAction(make_dim_icon("BLOCK"), "", self.main_window)
        blk_act.setToolTip(f"{tr('Block')} (B)")
        blk_act.setStatusTip(f"{tr('Block')} (B)")
        blk_act.triggered.connect(self.add_block_constraint)
        toolbar.addAction(blk_act)

        toolbar.addSeparator()

        undo_act = QAction(make_constraint_icon("<<"), "", self.main_window)
        undo_act.setToolTip(f"{tr('Undo')} (Ctrl+Z)")
        undo_act.triggered.connect(self.undo)
        toolbar.addAction(undo_act)
        redo_act = QAction(make_constraint_icon(">>"), "", self.main_window)
        redo_act.setToolTip(f"{tr('Redo')} (Ctrl+Shift+Z)")
        redo_act.triggered.connect(self.redo)
        toolbar.addAction(redo_act)
        delete_act = QAction(make_constraint_icon("X"), "", self.main_window)
        delete_act.setToolTip(f"{tr('Delete')} (Del)")
        delete_act.triggered.connect(self.delete_selected)
        toolbar.addAction(delete_act)
        clear_act = QAction(make_constraint_icon("CLR"), "", self.main_window)
        clear_act.setToolTip(tr("Clear"))
        clear_act.triggered.connect(self.clear_sketch)
        toolbar.addAction(clear_act)

        dxf_act = QAction(make_constraint_icon("DXF"), "", self.main_window)
        dxf_act.setToolTip(tr("Save as 2D CAD (DXF)"))
        dxf_act.triggered.connect(self.export_dxf)
        toolbar.addAction(dxf_act)

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
        self._clear_preview()
        self.main_window.log(trt("Sketcher tool: {v}", v=mode))

    def cancel_temp(self):
        if self._pick is not None:
            self._pick = None
            self.main_window.log(tr("Constraint picking cancelled."))
            return
        if self.temp_points or self._poly_last is not None:
            self.temp_points = []
            self._poly_last = None
            self._clear_preview()
            self.main_window.log(tr("In-progress geometry cancelled."))

    # ------------------------------------------------------------------ models
    def _all_geometry(self, include_axes=True):
        g = self.lines + self.circles + self.arcs + self.points
        if include_axes:
            g = g + [self._x_axis, self._y_axis]
        return g

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
            locked = {"mode": "point"}
        else:
            geom = self._find_geom_at(pos)
            if geom is None:
                return False
            points, seen = [], set()
            for p in self._geom_points(geom):  # dedup by id (unhashable dataclass)
                if p.id not in seen:
                    seen.add(p.id)
                    points.append(p)
            locked = {"mode": "body", "geom": geom, "shape": self._shape_of(geom)}
        self.snapshot()  # one undo step per drag
        self._drag = {"points": points, "last": QPointF(pos), **locked}
        return True

    def _shape_of(self, geom):
        """Rigid relative offsets of a geometry's points (for body drag)."""
        if isinstance(geom, SketchPoint):
            return {}
        base = self._geom_points(geom)[0]
        return {p.id: (p.x - base.x, p.y - base.y) for p in self._geom_points(geom)}

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
        # FreeCAD live-solve: constraints move along in real time; a whole
        # body is translated RIGIDLY (shape preserved), points follow freely
        self._live_solve()
        if self._drag.get("mode") == "body":
            geom = self._drag["geom"]
            base = self._geom_points(geom)[0]
            for p in self._geom_points(geom):
                rx, ry = self._drag["shape"][p.id]
                p.x, p.y = base.x + rx, base.y + ry
                moved.add(p.id)
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
        """Solve without log noise (used while dragging). The dragged
        points are pinned at the mouse so the geometry follows exactly."""
        pin = self._drag["points"] if self._drag else None
        try:
            self.dof, _, self.status, _ = self.solver.solve(
                self.lines + [self._x_axis, self._y_axis], self.circles,
                self.arcs, self.constraints,
                self.points + [self._origin], pin=pin)
        except Exception:
            return
        for geom in self._all_geometry():
            self.update_item(geom)
        self._update_dof_label()
        self._update_vertex_positions()

    # ------------------------------------------------------------------ hover
    # ------------------------------------------------------------------ vertices
    def _rebuild_vertices(self):
        """FreeCAD-style red vertex handles at every endpoint / center."""
        for item in self._vertex_items.values():
            self.scene.removeItem(item)
        self._vertex_items = {}
        for p in self.all_points():
            self._vertex_items[p.id] = self._make_vertex(p)

    def _make_vertex(self, p):
        s = self._vertex_size / 2
        item = self.scene.addRect(p.x - s, p.y - s, self._vertex_size,
                                  self._vertex_size,
                                  QPen(QColor(200, 0, 0), 1.5), QBrush(QColor(255, 60, 60)))
        item.setZValue(50)
        return item

    def _update_vertex_positions(self):
        for p in self.all_points():
            item = self._vertex_items.get(p.id)
            if item is not None:
                s = self._vertex_size / 2
                item.setRect(p.x - s, p.y - s, self._vertex_size, self._vertex_size)

    def ctrl_click(self, pos):
        """Ctrl+click: toggle-select a vertex/geometry without clearing the
        rest (needed to multi-select two endpoints for distance/symmetry)."""
        if self.draw_mode != "SELECT":
            return False
        p = self._nearest_point(pos, tol=max(6.0, float(self.snap_px)))
        if p is not None:
            if p in self._sel_points:
                self._sel_points.remove(p)
            else:
                self._sel_points.append(p)
            self._refresh_point_selection()
            return True
        geom = self._find_geom_at(pos)
        if geom is not None:
            item = self.item_of_geom.get(geom.id)
            if item is not None:
                item.setSelected(not item.isSelected())
                self.update_item(geom)
                return True
        return False

    def _refresh_point_selection(self):
        for pid, item in self._vertex_items.items():
            p = self._point_by_id(pid)
            if p is not None:
                sel = p in self._sel_points
                item.setBrush(QBrush(QColor(255, 200, 0) if sel
                                         else QColor(255, 60, 60)))

    def _point_by_id(self, pid):
        for p in self.all_points():
            if p.id == pid:
                return p
        return None

    def selected_points(self):
        """Multi-selected SketchPoints (ctrl+click), in click order."""
        return list(self._sel_points)

    def on_hover(self, pos):
        """FreeCAD-style preselection highlight (light blue)."""
        self._update_preview(pos)
        if self.draw_mode != "SELECT" or self._drag is not None:
            self._set_hover(None)
            return
        geom = self._find_geom_at(pos)
        self._set_hover(geom)

    # ------------------------------------------------------------------ rubber-band preview
    def _clear_preview(self):
        if self._preview is not None:
            self.scene.removeItem(self._preview)
            self._preview = None

    def _update_preview(self, pos):
        """Rubber-band the shape being created so it follows the mouse."""
        mode = self.draw_mode
        n = len(self.temp_points)
        if mode == "SELECT" or (n == 0 and mode != "POLYLINE"):
            self._clear_preview()
            return
        sp, _ = self.snap(pos)
        pen = QPen(C_PRESEL, 1.5, Qt.PenStyle.DashLine)
        path = QPainterPath()
        valid = False
        anchor = None
        if mode == "POLYLINE" and self._poly_last is not None:
            anchor = QPointF(self._poly_last.x, self._poly_last.y)
        elif n >= 1:
            anchor = self.temp_points[-1][0]
        if mode in ("LINE", "POLYLINE") and anchor is not None:
            path.moveTo(anchor)
            path.lineTo(sp)
            valid = True
        elif mode == "RECT" and anchor is not None:
            path.addRect(QRectF(anchor, sp).normalized())
            valid = True
        elif mode == "CIRCLE" and anchor is not None:
            r = math.hypot(sp.x() - anchor.x(), sp.y() - anchor.y())
            path.addEllipse(anchor.x() - r, anchor.y() - r, 2 * r, 2 * r)
            valid = True
        elif mode in ("TRIANGLE", "SQUARE") and anchor is not None:
            sides = 3 if mode == "TRIANGLE" else 4
            cx, cy = anchor.x(), anchor.y()
            r = math.hypot(sp.x() - cx, sp.y() - cy)
            a0 = math.atan2(sp.y() - cy, sp.x() - cx)
            pts = [(cx + r * math.cos(a0 + 2 * math.pi * i / sides),
                    cy + r * math.sin(a0 + 2 * math.pi * i / sides))
                   for i in range(sides)]
            path.moveTo(*pts[0])
            for q in pts[1:]:
                path.lineTo(*q)
            path.closeSubpath()
            valid = True
        elif mode == "ARC3" and n == 1 and anchor is not None:
            path.moveTo(anchor)
            path.lineTo(sp)
            valid = True
        elif mode == "ARC3" and n == 2:
            (s1, _), (s2, _) = self.temp_points
            cc = circumcenter(s1.x(), s1.y(), s2.x(), s2.y(), sp.x(), sp.y())
            if cc is not None:
                r = math.hypot(s1.x() - cc[0], s1.y() - cc[1])
                rect = QRectF(cc[0] - r, cc[1] - r, 2 * r, 2 * r)
                a1 = math_angle(cc[0], cc[1], s1.x(), s1.y())
                am = math_angle(cc[0], cc[1], s2.x(), s2.y())
                a2 = math_angle(cc[0], cc[1], sp.x(), sp.y())
                span = (a2 - a1) % 360
                if (am - a1) % 360 > span:
                    span -= 360
                path.arcMoveTo(rect, a1)
                path.arcTo(rect, a1, span)
                valid = True
        elif mode == "ARC_CENTER" and n == 1 and anchor is not None:
            r = math.hypot(sp.x() - anchor.x(), sp.y() - anchor.y())
            path.addEllipse(anchor.x() - r, anchor.y() - r, 2 * r, 2 * r)
            valid = True
        elif mode == "ARC_CENTER" and n == 2:
            (sc, _), (sr, _) = self.temp_points
            r = math.hypot(sr.x() - sc.x(), sr.y() - sc.y())
            if r > 0.5:
                rect = QRectF(sc.x() - r, sc.y() - r, 2 * r, 2 * r)
                a1 = math_angle(sc.x(), sc.y(), sr.x(), sr.y())
                a2 = math_angle(sc.x(), sc.y(), sp.x(), sp.y())
                path.arcMoveTo(rect, a1)
                path.arcTo(rect, a1, (a2 - a1) % 360)
                valid = True
        if not valid:
            self._clear_preview()
            return
        if self._preview is None:
            self._preview = QGraphicsPathItem()
            self._preview.setZValue(60)
            self.scene.addItem(self._preview)
        self._preview.setPath(path)
        self._preview.setPen(pen)

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
                    "T": "TRIANGLE", "S": "SQUARE", "X": "REFLINE"}

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
        if key == Qt.Key.Key_A and mods & Qt.KeyboardModifier.ControlModifier:
            self.select_all()
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
        add(self._origin)  # FreeCAD origin can be referenced by constraints
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
        if not self._composing:
            self._offer_length_input(line)
        return line

    # ------------------------------------------------------------------ on-create value input
    def _offer_length_input(self, line):
        """FreeCAD-style: after drawing a line, offer to type its exact length
        (pre-filled with the dragged value, mm). Esc keeps the dragged length."""
        cur = math.hypot(line.p2.x - line.p1.x, line.p2.y - line.p1.y)
        value, ok = QInputDialog.getDouble(
            self.main_window, tr("Line Length"), tr("Length (mm):"),
            cur, 0.01, 1e6, 2)
        if not ok or abs(value - cur) < 1e-9:
            return
        self.snapshot()
        c = {"type": "DISTANCE", "targets": [line], "value": value}
        self.constraints.append(c)
        self._solve_checked(c)

    def _offer_radius_input(self, geom):
        cur = geom.radius
        value, ok = QInputDialog.getDouble(
            self.main_window, tr("Radius"), tr("Radius (mm):"),
            cur, 0.01, 1e6, 2)
        if not ok or abs(value - cur) < 1e-9:
            return
        self.snapshot()
        c = {"type": "RADIUS", "targets": [geom], "value": value}
        self.constraints.append(c)
        self._solve_checked(c)

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
        self._offer_radius_input(circle)
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
        self._composing = True
        try:
            bottom = self.add_line(bl, br, construction)
            right = self.add_line(br, tpr, construction)
            top = self.add_line(tpr, tpl, construction)
            left = self.add_line(tpl, bl, construction)
        finally:
            self._composing = False
        for line, kind in ((bottom, "HORIZONTAL"), (top, "HORIZONTAL"),
                           (left, "VERTICAL"), (right, "VERTICAL")):
            self.constraints.append({"type": kind, "targets": [line]})
        self.main_window.log(tr("Rectangle created with automatic H/V constraints."))
        self.solve_sketch()
        self._offer_rect_size(bottom, left)
        return (bottom, right, top, left)

    def _offer_rect_size(self, bottom, left):
        """Offer width/height (mm) after drawing a rectangle."""
        w = math.hypot(bottom.p2.x - bottom.p1.x, bottom.p2.y - bottom.p1.y)
        h = math.hypot(left.p2.x - left.p1.x, left.p2.y - left.p1.y)
        w2, ok = QInputDialog.getDouble(self.main_window, tr("Rectangle Width"),
                                        tr("Width (mm):"), w, 0.01, 1e6, 2)
        if ok and abs(w2 - w) > 1e-9:
            self.constraints.append({"type": "DISTANCE_X", "targets": [bottom],
                                     "value": w2})
        h2, ok2 = QInputDialog.getDouble(self.main_window, tr("Rectangle Height"),
                                         tr("Height (mm):"), h, 0.01, 1e6, 2)
        if ok2 and abs(h2 - h) > 1e-9:
            self.constraints.append({"type": "DISTANCE_Y", "targets": [left],
                                     "value": h2})
        if (ok and abs(w2 - w) > 1e-9) or (ok2 and abs(h2 - h) > 1e-9):
            self.solve_sketch()
            if self.status == STATUS_OVER:
                self.main_window.log(
                    tr("Rectangle size conflicts with existing constraints."))

    def add_reference_line(self, p1, p2):
        """FreeCAD-style construction/reference line: drawn as an infinite
        dashed line through the two points, flagged as construction geometry."""
        if math.hypot(p2.x - p1.x, p2.y - p1.y) < 0.5:
            self.main_window.log(tr("Reference line rejected: zero length."))
            return None
        self.snapshot()
        line = SketchLine(p1, p2, is_construction=True)
        self.lines.append(line)
        self.draw_item(line)
        item = self.item_of_geom[line.id]
        pen = QPen(C_CONSTRUCTION, 1.5, Qt.PenStyle.DashLine)
        item.setPen(pen)
        self.main_window.log(trt("Reference line added from ({x1}, {y1}) to ({x2}, {y2}).",
                                 x1=round(p1.x, 1), y1=round(p1.y, 1),
                                 x2=round(p2.x, 1), y2=round(p2.y, 1)))
        self.solve_sketch()
        return line

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
        self._composing = True
        try:
            sides_lines = [self.add_line(verts[i], verts[(i + 1) % sides], construction)
                           for i in range(sides)]
        finally:
            self._composing = False
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
        if button == Qt.MouseButton.LeftButton:
            if self._pick is not None:
                self._pick_click(pos)  # pick mode routes ALL clicks to picking
                return True
            if self.draw_mode == "SELECT":
                # click a vertex handle (point) directly in Select mode
                p = self._nearest_point(pos, tol=max(6.0, float(self.snap_px)))
                if p is not None:
                    if p in self._sel_points:
                        self._sel_points.remove(p)
                    else:
                        self._sel_points.append(p)
                    self._refresh_point_selection()
                    return True
                return False  # empty area: let Qt rubber-band / deselect run
            # creation mode: fall through to the click sequencer below
        elif button != Qt.MouseButton.RightButton:
            return False
        else:
            return False

        sp, existing = self.snap(pos)
        self.temp_points.append((sp, existing))

        if self.draw_mode == "POINT":
            (s, e), = self.temp_points
            self.add_point_geom(e or SketchPoint(s.x(), s.y()))
            self.set_draw_mode("SELECT")  # single-shot tool
        elif self.draw_mode == "LINE" and len(self.temp_points) == 2:
            (s1, e1), (s2, e2) = self.temp_points
            p1 = e1 or SketchPoint(s1.x(), s1.y())
            p2 = e2 or SketchPoint(s2.x(), s2.y())
            self.add_line(p1, p2, auto_constrain=True)
            self.set_draw_mode("SELECT")  # single-shot tool
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
            self.set_draw_mode("SELECT")  # single-shot tool
        elif self.draw_mode == "ARC3" and len(self.temp_points) == 3:
            (s1, e1), (s2, _), (s3, e3) = self.temp_points
            p1 = e1 or SketchPoint(s1.x(), s1.y())
            p2 = e3 or SketchPoint(s3.x(), s3.y())
            self.add_arc(p1, (s2.x(), s2.y()), p2)
            self.set_draw_mode("SELECT")  # single-shot tool
        elif self.draw_mode == "ARC_CENTER" and len(self.temp_points) == 3:
            (s1, e1), (s2, e2), (s3, _) = self.temp_points
            center = e1 or SketchPoint(s1.x(), s1.y())
            p1 = e2 or SketchPoint(s2.x(), s2.y())
            a2 = math_angle(center.x, center.y, s3.x(), s3.y())
            self.add_arc_center(center, p1, a2)
            self.set_draw_mode("SELECT")  # single-shot tool
        elif self.draw_mode == "RECT" and len(self.temp_points) == 2:
            (s1, _), (s2, _) = self.temp_points
            self.add_rectangle((s1.x(), s1.y()), (s2.x(), s2.y()))
            self.set_draw_mode("SELECT")  # single-shot tool
        elif self.draw_mode == "REFLINE" and len(self.temp_points) == 2:
            (s1, e1), (s2, e2) = self.temp_points
            p1 = e1 or SketchPoint(s1.x(), s1.y())
            p2 = e2 or SketchPoint(s2.x(), s2.y())
            self.add_reference_line(p1, p2)
            self.set_draw_mode("SELECT")  # single-shot tool
        elif self.draw_mode in ("TRIANGLE", "SQUARE") and len(self.temp_points) == 2:
            (s1, _), (s2, _) = self.temp_points
            self.add_polygon((s1.x(), s1.y()), (s2.x(), s2.y()),
                             3 if self.draw_mode == "TRIANGLE" else 4)
            self.set_draw_mode("SELECT")  # single-shot tool
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

    def _picked_points(self):
        """SketchPoints collected via pick-clicks (used for point constraints)."""
        return [obj for obj in (self._pick["got"] if self._pick else [])
                if isinstance(obj, SketchPoint)]

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
            # for an axis slot prefer a line; only fall back to a point
            return self._find_geom_at(pos, kinds=(SketchLine,)) or \
                self._nearest_point(pos)
        if kind in ("curve_or_point", "point_or_end"):
            return self._nearest_point(pos) or self._find_geom_at(pos)
        return None

    def _request(self, ctype):
        """FreeCAD constraint flow: use scene selection if it already matches
        the slots, otherwise enter click-picking mode. Preselected items fill
        as many leading slots as they match; the user clicks the rest."""
        self.temp_points = []
        self._poly_last = None
        self.draw_mode = "SELECT"
        kinds = list(self._SLOTS[ctype])
        # consume preselection greedily per slot
        pool = list(self._sel_points) + [
            g for g in (self.lines + self.circles + self.arcs + self.points)
            if self.item_of_geom.get(g.id) is not None
            and self.item_of_geom[g.id].isSelected()]
        got = []
        remaining = list(kinds)
        for kind in list(kinds):
            match = None
            for g in pool:
                if self._slot_matches(kind, g):
                    match = g
                    break
            if match is None:
                break
            got.append(match)
            pool.remove(match)
            remaining.pop(0)
        if len(got) == len(kinds):
            self._sel_points = [p for p in self._sel_points if p not in got]
            self._apply_constraint(ctype, got)
            self._refresh_point_selection()
            return
        if got:
            self._sel_points = [p for p in self._sel_points if p not in got]
            self._refresh_point_selection()
        # store the full slot map with the partial got; _pick_click appends
        self._pick = {"type": ctype, "kinds": remaining, "got": [],
                      "pre": got, "all_kinds": kinds}
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
        """FreeCAD-style: match the current selection against the required
        slots. Geometry click-selected on the canvas plus ctrl+click
        multi-selected vertices all count."""
        sel_points = list(self._sel_points)
        geoms = [g for g in (self.lines + self.circles + self.arcs + self.points)
                 if self.item_of_geom.get(g.id) is not None
                 and self.item_of_geom[g.id].isSelected()]
        pool = list(sel_points) + geoms
        if not pool:
            return None
        got = []
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
        if kind == "point":
            return isinstance(g, SketchPoint)
        if kind == "line_or_point":
            return isinstance(g, (SketchPoint, SketchLine))
        if kind in ("curve_or_point", "point_or_end"):
            return True  # resolved by _resolve_slot either way
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
        pre = pick.get("pre", [])
        all_got = pre + pick["got"]
        all_kinds = pick.get("all_kinds", kinds)
        ctype = pick["type"]
        # dynamic early-completion for distance on a line (first slot)
        if ctype in ("DISTANCE", "DISTANCE_X", "DISTANCE_Y") and len(all_got) == 1 \
                and isinstance(all_got[0], SketchLine):
            self._apply_constraint(ctype, all_got)
            self._pick = None
            return
        if len(all_got) >= len(all_kinds):
            self._apply_constraint(ctype, all_got)
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
            # FreeCAD semantics: symmetric is between TWO DISTINCT points
            # (e.g. two corners of a rectangle). If the two picked points are
            # the endpoints of the SAME line the user almost certainly wants
            # to mirror that whole line, which is a degenerate/ambiguous case
            # - guard against collapsing it to a point.
            parents1 = [g for g in self._all_geometry()
                        if p1 in self._geom_points(g)]
            parents2 = [g for g in self._all_geometry()
                        if p2 in self._geom_points(g)]
            shared = [g for g in parents1 if g in parents2]
            # endpoints of the SAME line would be driven to the same place by
            # symmetry - reject so it never collapses to a point
            if any(isinstance(g, SketchLine) for g in shared):
                self.main_window.log(
                    tr("Symmetric needs two DIFFERENT points (e.g. two "
                       "corners). For a single line, mirror its endpoints "
                       "about the axis instead."))
                return
            c = {"type": "SYMMETRIC", "targets": [], "points": [p1, p2]}
            if isinstance(axis, SketchLine):
                c["line"] = axis
            else:
                c["center"] = axis
            self.snapshot()
            self.constraints.append(c)
            # FreeCAD keeps the length of a mirrored object by making the
            # symmetry the driving relation; pair the picked points and let
            # the solver keep distances. If it conflicts, _solve_checked
            # warns and rolls back instead of collapsing geometry.
            self.main_window.log(tr("SYMMETRIC constraint added."))
            self._solve_checked(c)
            return

    def add_mirror_line_about_axis(self):
        """FreeCAD-style: mirror a whole line about an axis line (keeps the
        original length by construction)."""
        self.main_window.log(tr("Mirror: select the line, then the axis line."))
        self._pick = {"type": "_MIRROR", "kinds": ["line", "line"], "got": []}

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
        vitem = self._vertex_items.pop(pb.id, None)  # merged point handle
        if vitem is not None:
            self.scene.removeItem(vitem)
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
        self._solve_checked(c)

    def _apply_radial(self, ctype, geom):
        cur = geom.radius if ctype == "RADIUS" else 2 * geom.radius
        title = tr("Radius Constraint") if ctype == "RADIUS" \
            else tr("Diameter Constraint")
        value, ok = QInputDialog.getDouble(self.main_window, title,
                                           tr("Value (mm):"), cur, 0.01, 1e6, 2)
        if not ok:
            return
        self.snapshot()
        c = {"type": ctype, "targets": [geom], "value": value}
        self.constraints.append(c)
        self.main_window.log(trt("{c} = {v} constraint added.",
                                 c=ctype, v=round(value, 2)))
        self._solve_checked(c)

    def _solve_checked(self, new_constraint):
        """Solve, and if the new constraint conflicts with the existing system
        (user perceives this as 'the value did not take effect'), warn and roll
        it back so the sketch stays consistent."""
        self.solve_sketch()
        if self.status == STATUS_OVER:
            self.constraints.remove(new_constraint)
            self.solve_sketch()
            QMessageBox.warning(
                self.main_window, tr("Conflicting Constraint"),
                tr("This value conflicts with the existing constraints and "
                   "was not applied. Remove or change the conflicting "
                   "constraint first."))

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
            self.lines + [self._x_axis, self._y_axis], self.circles,
            self.arcs, self.constraints, self.points + [self._origin])
        self._restyle()
        self._rebuild_badges()
        self._rebuild_vertices()

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
            pts = c["points"]
            x = sum(p.x for p in pts) / len(pts)
            y = sum(p.y for p in pts) / len(pts)
            return "SYM", QPointF(x, y - 14), geo
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
            if c.get("builtin"):  # no badges for origin/axis locks
                continue
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
        self._clear_preview()
        for item in list(self.item_of_geom.values()):
            self.scene.removeItem(item)
        self.item_of_geom, self.geom_of_item = {}, {}
        for geom in self._all_geometry():
            self.draw_item(geom)
        self.solve_sketch()
        self._rebuild_vertices()

    # ------------------------------------------------------------------ editing
    def select_all(self):
        for item in self.item_of_geom.values():
            item.setSelected(True)
        self.main_window.log(trt("Selected {n} element(s).",
                                 n=len(self.item_of_geom)))

    def delete_selected(self):
        geoms = [g for g in self.selected_geometry()
                 if g.id not in self._fixed_ids]  # origin/axes are not deletable
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
            for p in self._geom_points(g):
                vitem = self._vertex_items.pop(p.id, None)
                if vitem is not None:
                    self.scene.removeItem(vitem)
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
        user_geom = self._all_geometry(include_axes=False)
        if not user_geom and not [c for c in self.constraints
                                  if not c.get("builtin")]:
            return
        self.snapshot()
        self.lines, self.circles, self.arcs, self.points = [], [], [], []
        self.constraints = [c for c in self.constraints if c.get("builtin")]
        self._sel_points = []
        for item in list(self.item_of_geom.values()):
            self.scene.removeItem(item)
        for item in list(self._vertex_items.values()):
            self.scene.removeItem(item)
        self._vertex_items = {}
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

    def _arc_sweep(self, arc):
        """(start_angle, end_angle) in math y-up degrees, respecting `mid`."""
        a1 = math_angle(arc.center.x, arc.center.y, arc.p1.x, arc.p1.y)
        am = math_angle(arc.center.x, arc.center.y, *arc.mid)
        a2 = math_angle(arc.center.x, arc.center.y, arc.p2.x, arc.p2.y)
        span = (a2 - a1) % 360
        if (am - a1) % 360 > span:
            # clockwise sweep: exchange so DXF CCW covers the same points
            return a2, a1
        return a1, a2

    # ------------------------------------------------------------------ import / export
    def export_dxf(self, file_path=None):
        """FreeCAD-style 'Save as 2D CAD': export the sketch as a DXF file."""
        if not self._all_geometry():
            QMessageBox.information(self.main_window, tr("Export 2D CAD"),
                                    tr("The sketch is empty."))
            return
        if file_path is None:
            file_path, _ = QFileDialog.getSaveFileName(
                self.main_window, tr("Save as 2D CAD (DXF)"), "",
                tr("DXF Files (*.dxf)"))
        if not file_path:
            return
        if not file_path.lower().endswith(".dxf"):
            file_path += ".dxf"
        # Qt scene y-down -> DXF math y-up
        out = ["0", "SECTION", "2", "ENTITIES"]

        def add_line(x1, y1, x2, y2):
            out.extend(["0", "LINE", "8", "0",
                        "10", f"{x1}", "20", f"{-y1}",
                        "11", f"{x2}", "21", f"{-y2}"])

        for l in self.lines:
            if l.id in self._fixed_ids:  # don't export the reference axes
                continue
            add_line(l.p1.x, l.p1.y, l.p2.x, l.p2.y)
        for c in self.circles:
            out += ["0", "CIRCLE", "8", "0",
                    "10", f"{c.center.x}", "20", f"{-c.center.y}",
                    "40", f"{c.radius}"]
        for a in self.arcs:
            a1, a2 = self._arc_sweep(a)
            out += ["0", "ARC", "8", "0",
                    "10", f"{a.center.x}", "20", f"{-a.center.y}",
                    "40", f"{a.radius}", "50", f"{a1}", "51", f"{a2}"]
        for p in self.points:
            out += ["0", "POINT", "8", "0",
                    "10", f"{p.x}", "20", f"{-p.y}"]
        out += ["0", "ENDSEC", "0", "EOF"]
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write("\n".join(out) + "\n")
        except OSError as e:
            QMessageBox.critical(self.main_window, tr("Export Failed"),
                                 tr("Could not write file:") + f"\n{e}")
            return
        self.main_window.log(trt("2D CAD (DXF) saved to {v}", v=file_path))

    def export_svg(self):
        """FreeCAD-style 'Save as SVG': render the sketch to an SVG vector file."""
        if not self._all_geometry():
            QMessageBox.information(self.main_window, tr("Export SVG"),
                                    tr("The sketch is empty."))
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, tr("Save as 2D Vector (SVG)"), "",
            tr("SVG Files (*.svg)"))
        if not file_path:
            return
        if not file_path.lower().endswith(".svg"):
            file_path += ".svg"
        from PyQt6.QtSvg import QSvgGenerator
        rect = self.scene.itemsBoundingRect().adjusted(-20, -20, 20, 20)
        gen = QSvgGenerator()
        gen.setFileName(file_path)
        gen.setSize(rect.size().toSize())
        gen.setViewBox(rect)
        gen.setTitle("2D Sketch")
        painter = QPainter(gen)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        hidden = []
        for item in self.scene.items():
            if item in self._badge_items or item in self._vertex_items.values() \
                    or item is self._preview:
                item.hide()
                hidden.append(item)
        self.scene.render(painter, rect, rect)
        painter.end()
        for item in hidden:
            item.show()
        self.main_window.log(trt("2D vector (SVG) saved to {v}", v=file_path))

    # ------------------------------------------------------------------ native JSON
    def export_data(self, file_path=None):
        if file_path is None:
            file_path, _ = QFileDialog.getSaveFileName(
                self.main_window, tr("Save 2D Sketch (JSON)"), "",
                tr("Sketch Files (*.sketch.json);;JSON Files (*.json)"))
        if not file_path:
            return
        data = {
            "points": [{"id": p.id, "x": p.x, "y": p.y,
                        "is_construction": p.is_construction} for p in self.points],
            "lines": [
                {"id": l.id, "p1": [l.p1.x, l.p1.y], "p2": [l.p2.x, l.p2.y],
                 "is_construction": l.is_construction}
                for l in self.lines if l.id not in self._fixed_ids
            ],
            "circles": [
                {"id": c.id, "center": [c.center.x, c.center.y], "radius": c.radius,
                 "is_construction": c.is_construction}
                for c in self.circles
            ],
            "arcs": [
                {"id": a.id, "center": [a.center.x, a.center.y], "radius": a.radius,
                 "p1": [a.p1.x, a.p1.y], "p2": [a.p2.x, a.p2.y], "mid": list(a.mid),
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
        self.main_window.log(trt("2D sketch saved to {v}", v=file_path))

    def open_sketch(self, file_path=None):
        """Open a native .sketch.json (exported by 'Save 2D Sketch')."""
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
                self.main_window, tr("Open 2D Sketch"), "",
                tr("Sketch Files (*.sketch.json);;JSON Files (*.json)"))
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            QMessageBox.critical(self.main_window, tr("Open Failed"), str(e))
            return
        self.clear_sketch()
        for pd in data.get("points", []):
            p = SketchPoint(pd["x"], pd["y"])
            p.is_construction = pd.get("is_construction", False)
            self.points.append(p)
            self.draw_item(p)
        for ld in data.get("lines", []):
            l = SketchLine(SketchPoint(*ld["p1"]), SketchPoint(*ld["p2"]),
                           ld.get("is_construction", False))
            self.lines.append(l)
            self.draw_item(l)
        for cd in data.get("circles", []):
            c = SketchCircle(SketchPoint(*cd["center"]), cd["radius"],
                             cd.get("is_construction", False))
            self.circles.append(c)
            self.draw_item(c)
        for ad in data.get("arcs", []):
            a = SketchArc(SketchPoint(*ad["center"]), ad["radius"],
                          SketchPoint(*ad["p1"]), SketchPoint(*ad["p2"]),
                          mid=tuple(ad.get("mid", (0, 0))),
                          is_construction=ad.get("is_construction", False))
            self.arcs.append(a)
            self.draw_item(a)
        # constraints reference geometry by id -> rebuild against the new objects
        id_of = {g.id: g for g in self._all_geometry()}
        for cd in data.get("constraints", []):
            targets = [id_of[t] for t in cd.get("targets", []) if t in id_of]
            if targets or cd.get("points"):
                c = {"type": cd["type"], "targets": targets}
                if "value" in cd:
                    c["value"] = cd["value"]
                self.constraints.append(c)
        self.solve_sketch()
        self._rebuild_vertices()
        self.main_window.log(trt("Opened 2D sketch {v}", v=file_path))

    # ------------------------------------------------------------------ DXF import
    def import_dxf(self, file_path=None):
        """Import a DXF (LINE / CIRCLE / ARC / POINT entities) into the sketch."""
        if file_path is None:
            file_path, _ = QFileDialog.getOpenFileName(
                self.main_window, tr("Import 2D CAD (DXF)"), "",
                tr("DXF Files (*.dxf)"))
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError as e:
            QMessageBox.critical(self.main_window, tr("Import Failed"), str(e))
            return
        entities = self._parse_dxf_entities(text)
        if not entities:
            QMessageBox.information(self.main_window, tr("Import 2D CAD"),
                                    tr("No supported entities (LINE/CIRCLE/ARC/POINT) found."))
            return
        self.snapshot()
        imported = 0
        for kind, d in entities:
            try:
                if kind == "LINE":
                    self.add_line(SketchPoint(d[10], -d[20]), SketchPoint(d[11], -d[21]))
                elif kind == "CIRCLE":
                    self.add_circle(SketchPoint(d[10], -d[20]), d[40])
                elif kind == "ARC":
                    cx, cy, r = d[10], -d[20], d[40]
                    a1, a2 = math.radians(d[50]), math.radians(d[51])
                    p1 = SketchPoint(cx + r * math.cos(a1), cy - r * math.sin(a1))
                    p2 = SketchPoint(cx + r * math.cos(a2), cy - r * math.sin(a2))
                    am = (d[50] + ((d[51] - d[50]) % 360) / 2) % 360
                    mid = (cx + r * math.cos(math.radians(am)),
                           cy - r * math.sin(math.radians(am)))
                    self.add_arc(p1, mid, p2)
                elif kind == "POINT":
                    self.add_point_geom(SketchPoint(d[10], -d[20]))
                imported += 1
            except Exception:
                continue
        self.main_window.log(trt("Imported {n} entities from {v}", n=imported, v=file_path))
        self._rebuild_vertices()

    @staticmethod
    def _parse_dxf_entities(text):
        """Minimal DXF ENTITIES parser: LINE, CIRCLE, ARC, POINT (group-code pairs)."""
        lines = [ln.rstrip("\r") for ln in text.splitlines()]
        # isolate the ENTITIES section
        try:
            start = next(i for i, ln in enumerate(lines) if ln.strip() == "ENTITIES")
        except StopIteration:
            return []
        try:
            end = next(i for i in range(start + 1, len(lines))
                       if lines[i].strip() == "ENDSEC")
        except StopIteration:
            end = len(lines)
        ents = []
        i = start + 1
        current = None
        while i < end:
            code = lines[i].strip()
            value = lines[i + 1].strip() if i + 1 < end else ""
            i += 2
            if code == "0":
                if current and current[0] in ("LINE", "CIRCLE", "ARC", "POINT"):
                    ents.append(current)
                current = (value, {})
                continue
            if current is None:
                continue
            try:
                current[1][int(code)] = float(value)
            except ValueError:
                pass
        if current and current[0] in ("LINE", "CIRCLE", "ARC", "POINT"):
            ents.append(current)
        return ents
