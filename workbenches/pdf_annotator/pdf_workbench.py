"""
Workbench 1: PDF Bubble Annotator
Used for Quality Inspection, FAI / PPAP Ballooning, and Feature Measurement.
"""
import json
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsTextItem, QGraphicsItemGroup, QFileDialog, QTableWidgetItem, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPen, QBrush, QFont, QAction

from workbenches.base_workbench import BaseWorkbench

class BubbleItem(QGraphicsItemGroup):
    def __init__(self, number, x, y, radius=14):
        super().__init__()
        self.number = number
        self.radius = radius

        # Outer Circle
        self.circle = QGraphicsEllipseItem(-radius, -radius, radius * 2, radius * 2)
        self.circle.setPen(QPen(QColor(220, 38, 38), 2))  # Engineering Red
        self.circle.setBrush(QBrush(QColor(254, 226, 226, 200)))
        self.addToGroup(self.circle)

        # Number Text
        self.text = QGraphicsTextItem(str(number))
        self.text.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.text.setDefaultTextColor(QColor(185, 28, 28))
        
        # Center Text
        bounds = self.text.boundingRect()
        self.text.setPos(-bounds.width() / 2, -bounds.height() / 2)
        self.addToGroup(self.text)

        self.setPos(x, y)
        self.setFlags(
            QGraphicsItemGroup.GraphicsItemFlag.ItemIsMovable |
            QGraphicsItemGroup.GraphicsItemFlag.ItemIsSelectable
        )

class PDFAnnotatorWorkbench(BaseWorkbench):
    def __init__(self, main_window):
        super().__init__(main_window)
        
        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHints(self.view.renderHints())

        self.bubbles = []
        self.current_balloon_index = 1
        self.add_mode = True

        # Click to Add Bubble Event
        self.view.mousePressEvent = self.on_canvas_click

    def get_central_widget(self):
        return self.view

    def setup_toolbar(self, toolbar):
        add_bubble_act = QAction("Add Balloon", self.main_window)
        add_bubble_act.setCheckable(True)
        add_bubble_act.setChecked(self.add_mode)
        add_bubble_act.triggered.connect(self.toggle_add_mode)
        toolbar.addAction(add_bubble_act)

        clear_act = QAction("Clear All Balloons", self.main_window)
        clear_act.triggered.connect(self.clear_balloons)
        toolbar.addAction(clear_act)

        renumber_act = QAction("Auto Renumber", self.main_window)
        renumber_act.triggered.connect(self.renumber_balloons)
        toolbar.addAction(renumber_act)

    def toggle_add_mode(self, checked):
        self.add_mode = checked
        self.main_window.log(f"Balloon placement mode: {self.add_mode}")

    def on_canvas_click(self, event):
        if self.add_mode and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.view.mapToScene(event.pos())
            self.add_balloon(scene_pos.x(), scene_pos.y())
        else:
            QGraphicsView.mousePressEvent(self.view, event)

    def add_balloon(self, x, y):
        bubble = BubbleItem(self.current_balloon_index, x, y)
        self.scene.addItem(bubble)
        self.bubbles.append(bubble)
        self.main_window.log(f"Added Balloon #{self.current_balloon_index} at ({x:.1f}, {y:.1f})")
        self.current_balloon_index += 1
        
        # Refresh Dock
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)

    def clear_balloons(self):
        for b in self.bubbles:
            self.scene.removeItem(b)
        self.bubbles.clear()
        self.current_balloon_index = 1
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)
        self.main_window.log("Cleared all balloons.")

    def renumber_balloons(self):
        for idx, b in enumerate(self.bubbles, start=1):
            b.number = idx
            b.text.setPlainText(str(idx))
            bounds = b.text.boundingRect()
            b.text.setPos(-bounds.width() / 2, -bounds.height() / 2)
        self.current_balloon_index = len(self.bubbles) + 1
        self.update_dock_views(self.main_window.tree_list, self.main_window.property_table)
        self.main_window.log("Auto-renumbered balloons sequentially.")

    def load_pdf(self, file_path):
        # Placeholder rendering using background scene rect / image mapping
        self.scene.clear()
        self.bubbles.clear()
        self.current_balloon_index = 1

        # Add background placeholder
        text_item = self.scene.addText(f"Loaded Drawing: {file_path}")
        text_item.setFont(QFont("Arial", 16))
        text_item.setPos(50, 20)
        
        self.scene.addRect(50, 60, 800, 1100, QPen(QColor(100, 100, 100), 2, Qt.PenStyle.DashLine))

    def update_dock_views(self, tree_widget, property_table):
        tree_widget.clear()
        for b in self.bubbles:
            tree_widget.addItem(f"Balloon #{b.number} - Pos: ({b.pos().x():.1f}, {b.pos().y():.1f})")

        property_table.setRowCount(3)
        property_table.setItem(0, 0, QTableWidgetItem("Total Balloons"))
        property_table.setItem(0, 1, QTableWidgetItem(str(len(self.bubbles))))
        
        property_table.setItem(1, 0, QTableWidgetItem("Inspection Standard"))
        property_table.setItem(1, 1, QTableWidgetItem("ISO 2859-1 / FAI"))

        property_table.setItem(2, 0, QTableWidgetItem("Default Bubble Radius"))
        property_table.setItem(2, 1, QTableWidgetItem("14 px"))

    def export_data(self):
        file_path, _ = QFileDialog.getSaveFileName(self.main_window, "Export Balloons JSON", "", "JSON Files (*.json)")
        if not file_path:
            return
        data = [
            {"balloon_id": b.number, "x": b.pos().x(), "y": b.pos().y()}
            for b in self.bubbles
        ]
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except OSError as e:
            QMessageBox.critical(self.main_window, "Export Failed", f"Could not write file:\n{e}")
            return
        QMessageBox.information(self.main_window, "Success", f"Exported {len(data)} balloons to JSON!")