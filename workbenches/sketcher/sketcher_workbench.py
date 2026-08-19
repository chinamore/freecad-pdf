"""
Workbench 2: 2D Sketcher Workbench
FreeCAD-style Parametric Sketcher with Snapping, Geometry, & Scipy Constraint Solver Engine.
"""
import json
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsLineItem, QGraphicsEllipseItem,
    QTableWidgetItem, QFileDialog, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPen, QColor, QAction

from workbenches.base_workbench import BaseWorkbench
from sketcher.models import SketchPoint, SketchLine, SketchCircle
from sketcher.solver import SketchSolver

class SketcherWorkbench(BaseWorkbench):
    def __init__(self, main_window):
        super().__init__(main_window)

        self.scene = QGraphicsScene()
        self.scene.setSceneRect(-1000, -1000, 2000, 2000)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints())

        self.draw_mode = "SELECT"  # SELECT, LINE, CIRCLE
        self.temp_start_point = None

        # Data Models
        self.points = []
        self.lines = []
        self.line_items = []  # QGraphicsLineItem mirroring self.lines
        self.circles = []
        self.constraints = []
        
        self.solver = SketchSolver()

        # Grid background
        self._draw_grid()

        # Mouse Events
        self.view.mousePressEvent = self.on_mouse_press

    def _draw_grid(self):
        grid_pen = QPen(QColor(230, 230, 230), 1, Qt.PenStyle.DotLine)
        axis_pen = QPen(QColor(180, 180, 180), 1.5)
        
        for x in range(-1000, 1000, 50):
            self.scene.addLine(x, -1000, x, 1000, grid_pen)
        for y in range(-1000, 1000, 50):
            self.scene.addLine(-1000, y, 1000, y, grid_pen)

        # Origin Axis
        self.scene.addLine(-1000, 0, 1000, 0, axis_pen)
        self.scene.addLine(0, -1000, 0, 1000, axis_pen)

    def get_central_widget(self):
        return self.view

    def setup_toolbar(self, toolbar):
        line_act = QAction("Draw Line", self.main_window)
        line_act.setCheckable(True)
        line_act.triggered.connect(lambda checked: self.set_draw_mode("LINE" if checked else "SELECT"))
        toolbar.addAction(line_act)

        circle_act = QAction("Draw Circle", self.main_window)
        circle_act.setCheckable(True)
        circle_act.triggered.connect(lambda checked: self.set_draw_mode("CIRCLE" if checked else "SELECT"))
        toolbar.addAction(circle_act)

        toolbar.addSeparator()

        h_const_act = QAction("Horizontal Constraint", self.main_window)
        h_const_act.triggered.connect(self.add_horizontal_constraint)
        toolbar.addAction(h_const_act)

        v_const_act = QAction("Vertical Constraint", self.main_window)
        v_const_act.triggered.connect(self.add_vertical_constraint)
        toolbar.addAction(v_const_act)

        solve_act = QAction("Solve Sketch (DOF)", self.main_window)
        solve_act.triggered.connect(self.solve_sketch)
        toolbar.addAction(solve_act)

    def set_draw_mode(self, mode):
        self.draw_mode = mode
        self.temp_start_point = None
        self.main_window.log(f"Sketcher Tool Mode: {mode}")

    def on_mouse_press(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            QGraphicsView.mousePressEvent(self.view, event)
            return

        pos = self.view.mapToScene(event.pos())

        if self.draw_mode == "LINE":
            if self.temp_start_point is None:
                self.temp_start_point = pos
                self.main_window.log(f"Line Start: ({pos.x():.1f}, {pos.y():.1f})")
            else:
                p1 = SketchPoint(self.temp_start_point.x(), self.temp_start_point.y())
                p2 = SketchPoint(pos.x(), pos.y())
                line = SketchLine(p1, p2)
                
                self.lines.append(line)
                item = self.scene.addLine(p1.x, p1.y, p2.x, p2.y, QPen(QColor(37, 99, 235), 2))
                self.line_items.append(item)
                
                self.main_window.log(f"Line Created: ({p1.x:.1f},{p1.y:.1f}) -> ({p2.x:.1f},{p2.y:.1f})")
                self.temp_start_point = None
                self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

        elif self.draw_mode == "CIRCLE":
            if self.temp_start_point is None:
                self.temp_start_point = pos
            else:
                center = SketchPoint(self.temp_start_point.x(), self.temp_start_point.y())
                radius = ((pos.x() - center.x)**2 + (pos.y() - center.y)**2)**0.5
                circle = SketchCircle(center, radius)
                
                self.circles.append(circle)
                self.scene.addEllipse(
                    center.x - radius, center.y - radius, radius * 2, radius * 2,
                    QPen(QColor(16, 185, 129), 2)
                )
                self.main_window.log(f"Circle Created: Center ({center.x:.1f},{center.y:.1f}), R={radius:.1f}")
                self.temp_start_point = None
                self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

        else:
            QGraphicsView.mousePressEvent(self.view, event)

    def add_horizontal_constraint(self):
        if self.lines:
            last_line = self.lines[-1]
            self.constraints.append({"type": "HORIZONTAL", "target": last_line})
            self.main_window.log(f"Added HORIZONTAL constraint to Line #{len(self.lines)}")
            self.solve_sketch()

    def add_vertical_constraint(self):
        if self.lines:
            last_line = self.lines[-1]
            self.constraints.append({"type": "VERTICAL", "target": last_line})
            self.main_window.log(f"Added VERTICAL constraint to Line #{len(self.lines)}")
            self.solve_sketch()

    def solve_sketch(self):
        dof, res = self.solver.solve(self.points, self.lines, self.constraints)
        # Sync the scene with the solved geometry
        for line, item in zip(self.lines, self.line_items):
            item.setLine(line.p1.x, line.p1.y, line.p2.x, line.p2.y)
        self.main_window.log(f"Solver result: Residual = {res:.6f}, Remaining Degrees of Freedom (DOF) = {dof}")
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def update_dock_views(self, tree_widget, property_table):
        tree_widget.clear()
        for idx, l in enumerate(self.lines, start=1):
            tree_widget.addItem(f"Line #{idx} [({l.p1.x:.0f},{l.p1.y:.0f}) -> ({l.p2.x:.0f},{l.p2.y:.0f})]")
        for idx, c in enumerate(self.circles, start=1):
            tree_widget.addItem(f"Circle #{idx} [Center: ({c.center.x:.0f},{c.center.y:.0f}), R: {c.radius:.0f}]")

        property_table.setRowCount(4)
        property_table.setItem(0, 0, QTableWidgetItem("Total Lines"))
        property_table.setItem(0, 1, QTableWidgetItem(str(len(self.lines))))
        
        property_table.setItem(1, 0, QTableWidgetItem("Total Circles"))
        property_table.setItem(1, 1, QTableWidgetItem(str(len(self.circles))))

        property_table.setItem(2, 0, QTableWidgetItem("Active Constraints"))
        property_table.setItem(2, 1, QTableWidgetItem(str(len(self.constraints))))

        property_table.setItem(3, 0, QTableWidgetItem("Solver Engine"))
        property_table.setItem(3, 1, QTableWidgetItem("SciPy Optimization (LM)"))

    def export_data(self):
        file_path, _ = QFileDialog.getSaveFileName(self.main_window, "Export Sketch DXF/JSON", "", "JSON Files (*.json)")
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
            "constraints": [
                {"type": c["type"], "target": c["target"].id}
                for c in self.constraints
            ],
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
            f"{len(self.constraints)} constraints."
        )