"""
Workbench 2: 2D Sketcher Workbench
FreeCAD-style parametric sketcher: geometry tools (line / circle / arc /
rectangle), grid & endpoint snapping, construction geometry, geometric
constraints driven by a SciPy least-squares solver, DOF analysis and
fully-constrained highlighting (green), mirroring the FreeCAD Sketcher UX.
"""
import json
import math

from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPathItem, QLabel, QSpinBox,
    QFileDialog, QMessageBox, QInputDialog, QTableWidgetItem,
)
from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QPen, QColor, QAction, QPainter, QPainterPath

from workbenches.base_workbench import BaseWorkbench
from sketcher.models import SketchPoint, SketchLine, SketchCircle, SketchArc
from sketcher.solver import (
    SketchSolver, HAS_SCIPY, STATUS_EMPTY, STATUS_UNDER, STATUS_FULL, STATUS_OVER,
)

COLOR_NORMAL = "#2563eb"        # normal geometry (blue)
COLOR_CONSTRUCTION = "#7aa7d9"  # construction geometry (dashed light blue)
COLOR_FULL = "#16a34a"          # fully constrained (FreeCAD green)


def circumcenter(ax, ay, bx, by, cx, cy):
    """Circle center through 3 points, or None if they are collinear."""
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy)
          + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx)
          + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy


class SketcherView(QGraphicsView):
    """Canvas view delegating clicks / keys to the workbench state machine."""

    def __init__(self, workbench):
        super().__init__(workbench.scene)
        self.wb = workbench
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setMouseTracking(True)

    def mousePressEvent(self, event):
        if not self.wb.on_mouse_press(event.button(), self.mapToScene(event.pos())):
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.wb.delete_selected()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.wb.cancel_temp()
            return
        super().keyPressEvent(event)


class SketcherWorkbench(BaseWorkbench):
    def __init__(self, main_window):
        super().__init__(main_window)

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(-1000, -1000, 2000, 2000)
        self.view = SketcherView(self)

        # State machine
        self.draw_mode = "SELECT"      # SELECT, LINE, CIRCLE, ARC, RECT
        self.temp_points = []          # in-progress clicks [(QPointF, SketchPoint|None)]
        self.construction_mode = False

        # Snapping
        self.snap_on = True
        self.grid_step = 5
        self.snap_px = 12

        # Data models
        self.lines = []
        self.circles = []
        self.arcs = []
        self.constraints = []

        # Graphics bookkeeping
        self.item_of_geom = {}         # geom.id -> QGraphicsItem
        self.geom_of_item = {}         # QGraphicsItem -> geom

        self.solver = SketchSolver()
        self.dof = 0
        self.status = STATUS_EMPTY

        self._draw_grid()

        # Persistent toolbar widgets
        self.grid_spin = QSpinBox(minimum=1, maximum=100, value=self.grid_step)
        self.grid_spin.setFixedWidth(52)
        self.grid_spin.valueChanged.connect(lambda v: setattr(self, "grid_step", v))
        self.dof_label = QLabel(" DOF: — ")

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
        for label, mode in (("Line", "LINE"), ("Circle", "CIRCLE"),
                            ("Arc", "ARC"), ("Rect", "RECT")):
            act = QAction(label, self.main_window)
            act.setCheckable(True)
            act.setChecked(self.draw_mode == mode)
            act.triggered.connect(
                lambda checked, m=mode: self.set_draw_mode(m if checked else "SELECT"))
            toolbar.addAction(act)

        constr_act = QAction("Construction", self.main_window)
        constr_act.setCheckable(True)
        constr_act.setChecked(self.construction_mode)
        constr_act.triggered.connect(self._toggle_construction)
        toolbar.addAction(constr_act)

        toolbar.addSeparator()

        snap_act = QAction("Snap", self.main_window)
        snap_act.setCheckable(True)
        snap_act.setChecked(self.snap_on)
        snap_act.triggered.connect(lambda checked: setattr(self, "snap_on", checked))
        toolbar.addAction(snap_act)
        toolbar.addWidget(QLabel(" Grid "))
        toolbar.addWidget(self.grid_spin)

        toolbar.addSeparator()

        for label, handler in (
            ("Coincident", self.add_coincident_constraint),
            ("H", self.add_horizontal_constraint),
            ("V", self.add_vertical_constraint),
            ("Parallel", self.add_parallel_constraint),
            ("Perp", self.add_perpendicular_constraint),
            ("Equal", self.add_equal_constraint),
            ("Length", self.add_length_constraint),
            ("Radius", self.add_radius_constraint),
            ("Lock", self.add_lock_constraint),
        ):
            act = QAction(label, self.main_window)
            act.triggered.connect(handler)
            toolbar.addAction(act)

        toolbar.addSeparator()

        solve_act = QAction("Solve", self.main_window)
        solve_act.triggered.connect(self.solve_sketch)
        toolbar.addAction(solve_act)
        delete_act = QAction("Delete", self.main_window)
        delete_act.triggered.connect(self.delete_selected)
        toolbar.addAction(delete_act)
        clear_act = QAction("Clear", self.main_window)
        clear_act.triggered.connect(self.clear_sketch)
        toolbar.addAction(clear_act)

        toolbar.addWidget(self.dof_label)

    def _toggle_construction(self, checked):
        self.construction_mode = checked
        self.main_window.log(f"Construction geometry mode: {checked}")

    def set_draw_mode(self, mode):
        self.draw_mode = mode
        self.temp_points = []
        self.main_window.log(f"Sketcher tool: {mode}")

    def cancel_temp(self):
        if self.temp_points:
            self.temp_points = []
            self.main_window.log("In-progress geometry cancelled.")

    # ------------------------------------------------------------------ snap
    def all_points(self):
        seen, out = set(), []
        for geom in self.lines + self.circles + self.arcs:
            pts = (geom.p1, geom.p2) if isinstance(geom, SketchLine) else \
                  (geom.center,) if isinstance(geom, SketchCircle) else \
                  (geom.center, geom.p1, geom.p2)
            for p in pts:
                if p.id not in seen:
                    seen.add(p.id)
                    out.append(p)
        return out

    def snap(self, pos):
        """Snap to the nearest existing endpoint, else to the grid."""
        best, best_d = None, float(self.snap_px)
        for p in self.all_points():
            d = math.hypot(p.x - pos.x(), p.y - pos.y())
            if d < best_d:
                best, best_d = p, d
        if best is not None:
            return QPointF(best.x, best.y), best
        if self.snap_on:
            s = self.grid_step
            return QPointF(round(pos.x() / s) * s, round(pos.y() / s) * s), None
        return pos, None

    # ------------------------------------------------------------------ geometry
    def _pen(self, geom):
        if geom.is_construction:
            return QPen(QColor(COLOR_CONSTRUCTION), 2, Qt.PenStyle.DashLine)
        color = COLOR_FULL if self.status == STATUS_FULL else COLOR_NORMAL
        return QPen(QColor(color), 2)

    def _register_item(self, geom, item):
        item.setPen(self._pen(geom))
        item.setFlags(item.GraphicsItemFlag.ItemIsSelectable)
        self.item_of_geom[geom.id] = item
        self.geom_of_item[item] = geom

    def add_line(self, p1, p2, construction=None):
        line = SketchLine(
            p1, p2,
            is_construction=self.construction_mode if construction is None else construction)
        self.lines.append(line)
        self._register_item(line, self.scene.addLine(p1.x, p1.y, p2.x, p2.y))
        self.main_window.log(
            f"Line: ({p1.x:.1f},{p1.y:.1f}) -> ({p2.x:.1f},{p2.y:.1f})")
        self.solve_sketch()
        return line

    def add_circle(self, center, radius, construction=None):
        if radius < 0.5:
            self.main_window.log("Circle rejected: radius too small.")
            return None
        circle = SketchCircle(
            center, radius,
            is_construction=self.construction_mode if construction is None else construction)
        self.circles.append(circle)
        self._register_item(circle, self.scene.addEllipse(
            center.x - radius, center.y - radius, radius * 2, radius * 2))
        self.main_window.log(
            f"Circle: center ({center.x:.1f},{center.y:.1f}), R={radius:.1f}")
        self.solve_sketch()
        return circle

    def add_arc(self, p_start, mid_xy, p_end, construction=None):
        cc = circumcenter(p_start.x, p_start.y, mid_xy[0], mid_xy[1], p_end.x, p_end.y)
        if cc is None:
            self.main_window.log("Arc rejected: the three points are collinear.")
            return None
        center = SketchPoint(*cc)
        radius = math.hypot(p_start.x - cc[0], p_start.y - cc[1])
        arc = SketchArc(
            center, radius, p_start, p_end, mid=tuple(mid_xy),
            is_construction=self.construction_mode if construction is None else construction)
        self.arcs.append(arc)
        item = QGraphicsPathItem(self._arc_path(arc))
        self.scene.addItem(item)
        self._register_item(arc, item)
        self.main_window.log(
            f"Arc: center ({cc[0]:.1f},{cc[1]:.1f}), R={radius:.1f}")
        self.solve_sketch()
        return arc

    def add_rectangle(self, corner1, corner2, construction=None):
        """FreeCAD-style: 4 lines with shared corners + auto H/V constraints."""
        x1, y1 = corner1
        x2, y2 = corner2
        if abs(x2 - x1) < 0.5 or abs(y2 - y1) < 0.5:
            self.main_window.log("Rectangle rejected: degenerate shape.")
            return None
        bl, br = SketchPoint(x1, y1), SketchPoint(x2, y1)
        tr, tl = SketchPoint(x2, y2), SketchPoint(x1, y2)
        bottom = self.add_line(bl, br, construction)
        right = self.add_line(br, tr, construction)
        top = self.add_line(tr, tl, construction)
        left = self.add_line(tl, bl, construction)
        for line, kind in ((bottom, "HORIZONTAL"), (top, "HORIZONTAL"),
                           (left, "VERTICAL"), (right, "VERTICAL")):
            self.constraints.append({"type": kind, "targets": [line]})
        self.main_window.log("Rectangle created with automatic H/V constraints.")
        self.solve_sketch()
        return (bottom, right, top, left)

    def _arc_path(self, arc):
        cx, cy, r = arc.center.x, arc.center.y, arc.radius
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)

        def angle(px, py):  # math angle (y-up) == Qt arc angle
            return math.degrees(math.atan2(-(py - cy), px - cx))

        a1 = angle(arc.p1.x, arc.p1.y)
        am = angle(*arc.mid)
        a2 = angle(arc.p2.x, arc.p2.y)
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
            if self.temp_points:
                self.cancel_temp()
                return True
            return False
        if button != Qt.MouseButton.LeftButton or self.draw_mode == "SELECT":
            return False

        sp, existing = self.snap(pos)
        self.temp_points.append((sp, existing))

        if self.draw_mode == "LINE" and len(self.temp_points) == 2:
            (s1, e1), (s2, e2) = self.temp_points
            p1 = e1 or SketchPoint(s1.x(), s1.y())
            p2 = e2 or SketchPoint(s2.x(), s2.y())
            self.add_line(p1, p2)
            self.temp_points = []
        elif self.draw_mode == "CIRCLE" and len(self.temp_points) == 2:
            (s1, e1), (s2, _) = self.temp_points
            center = e1 or SketchPoint(s1.x(), s1.y())
            radius = math.hypot(s2.x() - center.x, s2.y() - center.y)
            self.add_circle(center, radius)
            self.temp_points = []
        elif self.draw_mode == "ARC" and len(self.temp_points) == 3:
            (s1, e1), (s2, _), (s3, e3) = self.temp_points
            p1 = e1 or SketchPoint(s1.x(), s1.y())
            p2 = e3 or SketchPoint(s3.x(), s3.y())
            self.add_arc(p1, (s2.x(), s2.y()), p2)
            self.temp_points = []
        elif self.draw_mode == "RECT" and len(self.temp_points) == 2:
            (s1, _), (s2, _) = self.temp_points
            self.add_rectangle((s1.x(), s1.y()), (s2.x(), s2.y()))
            self.temp_points = []
        return True

    # ------------------------------------------------------------------ constraints
    def selected_geometry(self):
        return [self.geom_of_item[it] for it in self.scene.selectedItems()
                if it in self.geom_of_item]

    def _pick_lines(self, n):
        sel = [g for g in self.selected_geometry() if isinstance(g, SketchLine)]
        if len(sel) >= n:
            return sel[:n]
        if not sel and len(self.lines) >= n:
            return self.lines[-n:]
        self.main_window.log(f"Select {n} line(s) first (or draw {n}).")
        return None

    def add_horizontal_constraint(self):
        lines = self._pick_lines(1)
        if not lines:
            return
        for line in lines:
            self.constraints.append({"type": "HORIZONTAL", "targets": [line]})
        self.main_window.log(f"HORIZONTAL constraint on {len(lines)} line(s).")
        self.solve_sketch()

    def add_vertical_constraint(self):
        lines = self._pick_lines(1)
        if not lines:
            return
        for line in lines:
            self.constraints.append({"type": "VERTICAL", "targets": [line]})
        self.main_window.log(f"VERTICAL constraint on {len(lines)} line(s).")
        self.solve_sketch()

    def _add_pair_constraint(self, kind):
        lines = self._pick_lines(2)
        if not lines:
            return
        self.constraints.append({"type": kind, "targets": lines})
        self.main_window.log(f"{kind} constraint between two lines.")
        self.solve_sketch()

    def add_parallel_constraint(self):
        self._add_pair_constraint("PARALLEL")

    def add_perpendicular_constraint(self):
        self._add_pair_constraint("PERPENDICULAR")

    def add_equal_constraint(self):
        self._add_pair_constraint("EQUAL")

    def add_length_constraint(self):
        lines = self._pick_lines(1)
        if not lines:
            return
        line = lines[0]
        current = math.hypot(line.p2.x - line.p1.x, line.p2.y - line.p1.y)
        value, ok = QInputDialog.getDouble(
            self.main_window, "Length Constraint", "Length (mm):", current, 0.01, 1e6, 2)
        if not ok:
            return
        self.constraints.append({"type": "LENGTH", "targets": [line], "value": value})
        self.main_window.log(f"LENGTH = {value:.2f} constraint added.")
        self.solve_sketch()

    def add_radius_constraint(self):
        sel = [g for g in self.selected_geometry()
               if isinstance(g, (SketchCircle, SketchArc))]
        if not sel:
            sel = (self.circles + self.arcs)[-1:] if (self.circles or self.arcs) else []
        if not sel:
            self.main_window.log("Select a circle or arc first.")
            return
        geom = sel[0]
        value, ok = QInputDialog.getDouble(
            self.main_window, "Radius Constraint", "Radius (mm):", geom.radius, 0.01, 1e6, 2)
        if not ok:
            return
        self.constraints.append({"type": "RADIUS", "targets": [geom], "value": value})
        self.main_window.log(f"RADIUS = {value:.2f} constraint added.")
        self.solve_sketch()

    def add_lock_constraint(self):
        sel = self.selected_geometry() or (self.lines + self.circles + self.arcs)[-1:]
        if not sel:
            self.main_window.log("Nothing to lock.")
            return
        geom = sel[0]
        if isinstance(geom, SketchLine):
            points = [geom.p1, geom.p2]
            radius = None
        elif isinstance(geom, SketchCircle):
            points = [geom.center]
            radius = geom.radius
        else:
            points = [geom.center, geom.p1, geom.p2]
            radius = geom.radius
        self.constraints.append({
            "type": "LOCK", "targets": [geom], "points": points,
            "coords": [(p.x, p.y) for p in points], "radius": radius,
        })
        self.main_window.log("LOCK constraint added (geometry fixed in place).")
        self.solve_sketch()

    def add_coincident_constraint(self):
        """Merge the nearest endpoint pair of two lines into a shared point."""
        lines = self._pick_lines(2)
        if not lines:
            return
        l1, l2 = lines
        pairs = [(l1.p1, l2.p1), (l1.p1, l2.p2), (l1.p2, l2.p1), (l1.p2, l2.p2)]
        pa, pb = min(pairs, key=lambda pr: math.hypot(pr[0].x - pr[1].x,
                                                      pr[0].y - pr[1].y))
        if pa is pb:
            self.main_window.log("Endpoints already coincident.")
            return
        if l2.p1 is pb:
            l2.p1 = pa
        else:
            l2.p2 = pa
        self.main_window.log(
            f"COINCIDENT: endpoints merged at ({pa.x:.1f},{pa.y:.1f}).")
        self.solve_sketch()

    # ------------------------------------------------------------------ solver
    def solve_sketch(self):
        self.dof, residual, self.status, redundant = self.solver.solve(
            self.lines, self.circles, self.arcs, self.constraints)
        self._restyle()

        if self.status == STATUS_FULL:
            msg = "Fully constrained sketch"
        elif self.status == STATUS_OVER:
            msg = "Conflicting constraints - sketch could not be solved"
        elif self.status == STATUS_UNDER:
            msg = f"Under-constrained sketch with {self.dof} degrees of freedom"
        else:
            msg = "Empty sketch"
        if redundant and self.status != STATUS_OVER:
            msg += " (redundant constraints detected)"
        self.dof_label.setText(f" DOF: {self.dof} ")
        self.main_window.log(f"Solver: {msg} (residual {residual:.2e})")
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def _restyle(self):
        for geom in self.lines + self.circles + self.arcs:
            self.update_item(geom)

    def update_item(self, geom):
        item = self.item_of_geom.get(geom.id)
        if item is None:
            return
        if isinstance(geom, SketchLine):
            item.setLine(geom.p1.x, geom.p1.y, geom.p2.x, geom.p2.y)
        elif isinstance(geom, SketchCircle):
            r = geom.radius
            item.setRect(geom.center.x - r, geom.center.y - r, 2 * r, 2 * r)
        else:
            item.setPath(self._arc_path(geom))
        item.setPen(self._pen(geom))

    # ------------------------------------------------------------------ editing
    def delete_selected(self):
        geoms = self.selected_geometry()
        if not geoms:
            return
        dead = {id(g) for g in geoms}
        for g in geoms:
            for lst in (self.lines, self.circles, self.arcs):
                if g in lst:
                    lst.remove(g)
            item = self.item_of_geom.pop(g.id, None)
            if item is not None:
                self.geom_of_item.pop(item, None)
                self.scene.removeItem(item)
        self.constraints = [c for c in self.constraints
                            if all(id(t) not in dead for t in c["targets"])]
        self.main_window.log(f"Deleted {len(geoms)} geometry element(s).")
        self.solve_sketch()

    def clear_sketch(self):
        self.lines, self.circles, self.arcs, self.constraints = [], [], [], []
        for item in list(self.item_of_geom.values()):
            self.scene.removeItem(item)
        self.item_of_geom, self.geom_of_item = {}, {}
        self.temp_points = []
        self.main_window.log("Sketch cleared.")
        self.solve_sketch()

    # ------------------------------------------------------------------ dock / export
    def update_dock_views(self, tree_widget, property_table):
        tree_widget.clear()
        for idx, l in enumerate(self.lines, start=1):
            tag = " (construction)" if l.is_construction else ""
            tree_widget.addItem(
                f"Line {idx}{tag} [({l.p1.x:.0f},{l.p1.y:.0f}) -> ({l.p2.x:.0f},{l.p2.y:.0f})]")
        for idx, c in enumerate(self.circles, start=1):
            tag = " (construction)" if c.is_construction else ""
            tree_widget.addItem(
                f"Circle {idx}{tag} [C: ({c.center.x:.0f},{c.center.y:.0f}), R: {c.radius:.0f}]")
        for idx, a in enumerate(self.arcs, start=1):
            tag = " (construction)" if a.is_construction else ""
            tree_widget.addItem(
                f"Arc {idx}{tag} [C: ({a.center.x:.0f},{a.center.y:.0f}), R: {a.radius:.0f}]")

        status_text = {
            STATUS_FULL: "Fully constrained",
            STATUS_OVER: "Over-constrained (redundant/conflicting)",
            STATUS_UNDER: "Under-constrained",
            STATUS_EMPTY: "Empty sketch",
        }[self.status]
        rows = [
            ("Solver Status", status_text),
            ("Degrees of Freedom", str(self.dof)),
            ("Lines / Circles / Arcs",
             f"{len(self.lines)} / {len(self.circles)} / {len(self.arcs)}"),
            ("Active Constraints", str(len(self.constraints))),
            ("Snap", f"{'ON' if self.snap_on else 'OFF'} (grid {self.grid_step})"),
            ("Solver Engine", "SciPy least-squares" if HAS_SCIPY else "DOF fallback (no SciPy)"),
        ]
        property_table.setRowCount(len(rows))
        for i, (key, value) in enumerate(rows):
            property_table.setItem(i, 0, QTableWidgetItem(key))
            property_table.setItem(i, 1, QTableWidgetItem(value))

    def export_data(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self.main_window, "Export Sketch JSON", "", "JSON Files (*.json)")
        if not file_path:
            return
        data = {
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
                {"type": c["type"], "targets": [t.id for t in c["targets"]],
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
            QMessageBox.critical(self.main_window, "Export Failed", f"Could not write file:\n{e}")
            return
        QMessageBox.information(
            self.main_window, "Exported",
            f"Exported {len(self.lines)} lines, {len(self.circles)} circles, "
            f"{len(self.arcs)} arcs, {len(self.constraints)} constraints."
        )
