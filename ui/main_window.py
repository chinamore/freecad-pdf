"""
FreeCAD-Style Main Window with Workbench Switcher & Dockable Panels
"""
import os
from PyQt6.QtWidgets import (
    QMainWindow, QComboBox, QToolBar, QDockWidget, QListWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit, QVBoxLayout,
    QWidget, QLabel, QStackedWidget, QMessageBox, QFileDialog, QSplitter
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon, QAction

from workbenches.pdf_annotator.pdf_workbench import PDFAnnotatorWorkbench
from workbenches.sketcher.sketcher_workbench import SketcherWorkbench

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Bubble Annotator & 2D Sketcher (FreeCAD Style)")
        self.resize(1400, 900)

        # Active central container (Stacked Widget for Workbenches)
        self.central_stack = QStackedWidget()
        self.setCentralWidget(self.central_stack)

        # Workbenches Registry
        self.workbenches = {}
        
        # Init UI Framework
        self._create_menu_bar()
        self._create_dock_panels()
        self._create_workbench_switcher()

        # Register Workbenches
        self.register_workbench("PDF Bubble Annotator", PDFAnnotatorWorkbench(self))
        self.register_workbench("2D Sketcher Workbench", SketcherWorkbench(self))

        # Set default workbench
        self.workbench_combo.setCurrentText("PDF Bubble Annotator")
        self.on_workbench_changed("PDF Bubble Annotator")

    def _create_menu_bar(self):
        menu = self.menuBar()
        
        # File Menu
        file_menu = menu.addMenu("&File")
        
        open_action = QAction("&Open PDF...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_pdf)
        file_menu.addAction(open_action)

        export_action = QAction("&Export Annotations / JSON...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_data)
        file_menu.addAction(export_action)

        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # View Menu
        view_menu = menu.addMenu("&View")
        # Added dynamically based on docks

        # Help Menu
        help_menu = menu.addMenu("&Help")
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _create_dock_panels(self):
        # 1. Left Dock: Tree & Properties Panel
        self.left_dock = QDockWidget("Model / Properties", self)
        self.left_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)

        left_layout.addWidget(QLabel("<b>Elements Tree / Inspector:</b>"))
        self.tree_list = QListWidget()
        left_layout.addWidget(self.tree_list, 1)

        left_layout.addWidget(QLabel("<b>Property View:</b>"))
        self.property_table = QTableWidget(0, 2)
        self.property_table.setHorizontalHeaderLabels(["Property", "Value"])
        self.property_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.property_table, 1)

        self.left_dock.setWidget(left_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

        # 2. Bottom Dock: Python Console & Output Log
        self.bottom_dock = QDockWidget("Python Console & Logs", self)
        self.bottom_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.append(">>> FreeCAD-Style Environment Initialized.")
        self.console_output.append(">>> Ready for PDF Inspection & 2D Sketching.")
        
        self.bottom_dock.setWidget(self.console_output)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)

    def _create_workbench_switcher(self):
        # Workbench Selector Toolbar
        self.wb_toolbar = QToolBar("Workbench Switcher", self)
        self.wb_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.wb_toolbar)

        self.wb_toolbar.addWidget(QLabel("  <b>Workbench: </b> "))
        self.workbench_combo = QComboBox()
        self.workbench_combo.setMinimumWidth(200)
        self.workbench_combo.currentTextChanged.connect(self.on_workbench_changed)
        self.wb_toolbar.addWidget(self.workbench_combo)

        # Dynamic Toolbar Container for Active Workbench Tools
        self.active_wb_toolbar = QToolBar("Active Workbench Tools", self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.active_wb_toolbar)

    def register_workbench(self, name, workbench_instance):
        self.workbenches[name] = workbench_instance
        self.workbench_combo.addItem(name)
        self.central_stack.addWidget(workbench_instance.get_central_widget())

    def on_workbench_changed(self, name):
        if name not in self.workbenches:
            return

        # Deactivate previous workbench tools
        self.active_wb_toolbar.clear()

        # Activate selected workbench
        wb = self.workbenches[name]
        self.central_stack.setCurrentWidget(wb.get_central_widget())

        # Populate active workbench toolbar
        wb.setup_toolbar(self.active_wb_toolbar)
        
        # Refresh tree / properties
        wb.update_dock_views(self.tree_list, self.property_table)
        
        self.log(f"Switched to Workbench: [{name}]")

    def log(self, text):
        self.console_output.append(f">>> {text}")

    def open_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open PDF File", "", "PDF Files (*.pdf)")
        if file_path:
            pdf_wb = self.workbenches.get("PDF Bubble Annotator")
            if pdf_wb:
                pdf_wb.load_pdf(file_path)
                self.workbench_combo.setCurrentText("PDF Bubble Annotator")
                self.log(f"Loaded PDF: {file_path}")

    def export_data(self):
        current_wb_name = self.workbench_combo.currentText()
        wb = self.workbenches.get(current_wb_name)
        if wb:
            wb.export_data()

    def show_about(self):
        QMessageBox.about(
            self,
            "About PDFBubbleAnnotator",
            "<b>PDFBubbleAnnotator & 2D Sketcher</b><br>"
            "FreeCAD-Style Architecture in PyQt6.<br><br>"
            "Features:<br>"
            "1. PDF Inspection Balloon Annotations (FAI/PPAP Workflow)<br>"
            "2. 2D Parametric Geometry Sketcher & Coordinate Transformation"
        )