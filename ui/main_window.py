"""
FreeCAD-Style Main Window with Workbench Switcher & Dockable Panels
Supports English / Simplified Chinese with a runtime language switch.
"""
import os
import sys

from PyQt6.QtWidgets import (
    QMainWindow, QComboBox, QToolBar, QDockWidget, QListWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit, QVBoxLayout,
    QWidget, QLabel, QStackedWidget, QMessageBox, QFileDialog,
    QFrame, QFormLayout, QDoubleSpinBox, QSpinBox
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QIcon

from utils import i18n
from utils.i18n import tr, available_languages

from workbenches.pdf_annotator.pdf_workbench import PDFAnnotatorWorkbench
from workbenches.sketcher.sketcher_workbench import SketcherWorkbench
from workbenches.techdraw.techdraw_workbench import TechDrawWorkbench

WINDOW_TITLE = "PDF Bubble Annotator & 2D Sketcher (FreeCAD Style)"
WB_PDF = "PDF Bubble Annotator"
WB_SKETCH = "2D Sketcher Workbench"
WB_DRAWING = "Drawing Page (TechDraw)"


def resource_path(relative):
    """Resolve bundled assets both in dev runs and PyInstaller builds."""
    base = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    return os.path.join(base, relative)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("freecad-pdf", "ui")
        i18n.set_language(self.settings.value("language", "en"))

        self.setWindowTitle(tr(WINDOW_TITLE))
        self.setWindowIcon(QIcon(resource_path("assets/icon.png")))
        self.resize(1400, 900)

        # Active central container (Stacked Widget for Workbenches)
        self.central_stack = QStackedWidget()
        self.setCentralWidget(self.central_stack)

        # Workbenches Registry
        self.workbenches = {}
        self._current_wb_key = None

        # Init UI Framework
        self._create_menu_bar()
        self._create_dock_panels()
        self._create_workbench_switcher()

        # Register Workbenches
        self.register_workbench(WB_PDF, PDFAnnotatorWorkbench(self))
        self.register_workbench(WB_SKETCH, SketcherWorkbench(self))
        self.register_workbench(WB_DRAWING, TechDrawWorkbench(self))

        # Set default workbench
        self._select_workbench(WB_PDF)

    def _create_menu_bar(self):
        menu = self.menuBar()

        # File Menu
        file_menu = menu.addMenu(tr("&File"))

        new2d_action = QAction(tr("&New 2D Sketch"), self)
        new2d_action.setShortcut("Ctrl+N")
        new2d_action.triggered.connect(self.new_2d_sketch)
        file_menu.addAction(new2d_action)

        open_sketch_action = QAction(tr("&Open 2D Sketch..."), self)
        open_sketch_action.triggered.connect(self.open_2d_sketch)
        file_menu.addAction(open_sketch_action)

        import_dxf_action = QAction(tr("&Import 2D CAD (DXF)..."), self)
        import_dxf_action.triggered.connect(self.import_2d_dxf)
        file_menu.addAction(import_dxf_action)

        file_menu.addSeparator()

        open_action = QAction(tr("&Open PDF..."), self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_pdf)
        file_menu.addAction(open_action)

        export_action = QAction(tr("&Export Annotations / JSON..."), self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_data)
        file_menu.addAction(export_action)

        file_menu.addSeparator()

        save_json_action = QAction(tr("&Save 2D Sketch (JSON)..."), self)
        save_json_action.setShortcut("Ctrl+S")
        save_json_action.triggered.connect(self.save_2d_sketch)
        file_menu.addAction(save_json_action)

        dxf_action = QAction(tr("Save as 2D CAD (DXF)..."), self)
        dxf_action.triggered.connect(self.save_2d_dxf)
        file_menu.addAction(dxf_action)
        svg_action = QAction(tr("Save as 2D Vector (SVG)..."), self)
        svg_action.triggered.connect(self.save_2d_svg)
        file_menu.addAction(svg_action)

        file_menu.addSeparator()
        exit_action = QAction(tr("E&xit"), self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Language Menu
        lang_menu = menu.addMenu(tr("Language"))
        for code, label in available_languages():
            act = QAction(label, self)
            act.setCheckable(True)
            act.setChecked(i18n.language() == code)
            act.triggered.connect(lambda checked, c=code: self._switch_language(c))
            lang_menu.addAction(act)

        # Help Menu
        help_menu = menu.addMenu(tr("&Help"))
        about_action = QAction(tr("&About"), self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _switch_language(self, code):
        i18n.set_language(code)
        self.settings.setValue("language", code)
        self.retranslate()

    def retranslate(self):
        self.menuBar().clear()
        self._create_menu_bar()
        self.setWindowTitle(tr(WINDOW_TITLE))

        # Dock titles / headers
        self.left_dock.setWindowTitle(tr("Model / Tree View"))
        self.bottom_dock.setWindowTitle(tr("Python Console & Logs"))
        self.tree_title_label.setText(tr("<b>Elements Tree / Inspector:</b>"))
        self.property_title_label.setText(tr("<b>Property View:</b>"))
        self.property_table.setHorizontalHeaderLabels([tr("Property"), tr("Value")])
        self.wb_label.setText(tr("  <b>Workbench: </b> "))

        # Workbench combo: localized display text, stable English keys via userData
        self.workbench_combo.blockSignals(True)
        self.workbench_combo.clear()
        for key in self.workbenches:
            self.workbench_combo.addItem(tr(key), userData=key)
        idx = self.workbench_combo.findData(self._current_wb_key)
        self.workbench_combo.setCurrentIndex(max(idx, 0))
        self.workbench_combo.blockSignals(False)

        # Let workbenches refresh their cached label state first
        for wb in self.workbenches.values():
            hook = getattr(wb, "retranslate", None)
            if hook:
                hook()

        # Rebuild active workbench toolbar + dock views in the new language
        self.on_workbench_changed(self._current_wb_key)

    def _create_dock_panels(self):
        # 1. Left Dock: Tree & Properties Panel
        self.left_dock = QDockWidget(tr("Model / Tree View"), self)
        self.left_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(5, 5, 5, 5)

        self.tree_title_label = QLabel(tr("<b>Elements Tree / Inspector:</b>"))
        left_layout.addWidget(self.tree_title_label)
        self.tree_list = QListWidget()
        left_layout.addWidget(self.tree_list, 1)

        self.property_title_label = QLabel(tr("<b>Property View:</b>"))
        left_layout.addWidget(self.property_title_label)
        self.property_table = QTableWidget(0, 2)
        self.property_table.setHorizontalHeaderLabels([tr("Property"), tr("Value")])
        self.property_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        left_layout.addWidget(self.property_table, 1)

        # TechDraw-style tolerance editor
        self.tol_title_label = QLabel(tr("<b>Dimension Tolerance:</b>"))
        left_layout.addWidget(self.tol_title_label)
        self.tolerance_frame = QFrame()
        tol_layout = QFormLayout(self.tolerance_frame)
        self.tol_nominal = QLabel("-")
        tol_layout.addRow(tr("Nominal:"), self.tol_nominal)
        self.tol_over = QDoubleSpinBox(minimum=-1e6, maximum=1e6, decimals=4)
        self.tol_over.setSingleStep(0.01)
        tol_layout.addRow(tr("+Tol:"), self.tol_over)
        self.tol_under = QDoubleSpinBox(minimum=-1e6, maximum=1e6, decimals=4)
        self.tol_under.setSingleStep(0.01)
        tol_layout.addRow(tr("-Tol:"), self.tol_under)
        self.tol_decimals = QSpinBox(minimum=0, maximum=6, value=2)
        tol_layout.addRow(tr("Decimals:"), self.tol_decimals)
        self.tol_hint = QLabel(tr("(double-click a dimension badge on the canvas)"))
        self.tol_hint.setStyleSheet("color: gray; font-size: 10px;")
        tol_layout.addRow(self.tol_hint)
        self.tolerance_frame.setVisible(True)  # always visible with a hint
        left_layout.addWidget(self.tolerance_frame)

        self.left_dock.setWidget(left_widget)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.left_dock)

        # 2. Bottom Dock: Python Console & Output Log
        self.bottom_dock = QDockWidget(tr("Python Console & Logs"), self)
        self.bottom_dock.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)

        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        self.console_output.append(tr(">>> FreeCAD-Style Environment Initialized."))
        self.console_output.append(tr(">>> Ready for PDF Inspection & 2D Sketching."))

        self.bottom_dock.setWidget(self.console_output)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.bottom_dock)

    def _create_workbench_switcher(self):
        # Workbench Selector Toolbar
        self.wb_toolbar = QToolBar("Workbench Switcher", self)
        self.wb_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.wb_toolbar)

        self.wb_label = QLabel(tr("  <b>Workbench: </b> "))
        self.wb_toolbar.addWidget(self.wb_label)
        self.workbench_combo = QComboBox()
        self.workbench_combo.setMinimumWidth(200)
        self.workbench_combo.currentIndexChanged.connect(self._on_combo_index)
        self.wb_toolbar.addWidget(self.workbench_combo)

        # Dynamic Toolbar Container for Active Workbench Tools
        self.active_wb_toolbar = QToolBar("Active Workbench Tools", self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.active_wb_toolbar)

    def _on_combo_index(self, index):
        key = self.workbench_combo.itemData(index)
        if key is not None:
            self.on_workbench_changed(key)

    def _select_workbench(self, key):
        combo = self.workbench_combo
        combo.blockSignals(True)
        idx = combo.findData(key)
        combo.setCurrentIndex(max(idx, 0))
        combo.blockSignals(False)
        self.on_workbench_changed(key)

    def register_workbench(self, name, workbench_instance):
        self.workbenches[name] = workbench_instance
        # Add to the stack before the combo so any fired index signal is safe
        self.central_stack.addWidget(workbench_instance.get_central_widget())
        self.workbench_combo.addItem(tr(name), userData=name)

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

        self._current_wb_key = name
        self.log(f"Switched to Workbench: [{name}]")

    def log(self, text):
        self.console_output.append(f">>> {text}")

    def open_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, tr("Open PDF File"), "", tr("PDF Files (*.pdf)"))
        if file_path:
            pdf_wb = self.workbenches.get(WB_PDF)
            if pdf_wb:
                pdf_wb.load_pdf(file_path)
                self._select_workbench(WB_PDF)
                self.log(f"Loaded PDF: {file_path}")

    def export_data(self):
        wb = self.workbenches.get(self._current_wb_key)
        if wb:
            wb.export_data()

    def _sketcher_wb(self):
        wb = self.workbenches.get(WB_SKETCH)
        if wb is None:
            return None
        if self._current_wb_key != WB_SKETCH:
            self._select_workbench(WB_SKETCH)
        return wb

    def new_2d_sketch(self):
        """Ctrl+N: switch to the Sketcher and start a blank sketch."""
        wb = self._sketcher_wb()
        if wb is not None:
            wb.clear_sketch()
            self.log(tr("New 2D sketch created."))

    def open_2d_sketch(self):
        wb = self._sketcher_wb()
        if wb is not None:
            wb.open_sketch()

    def import_2d_dxf(self):
        wb = self._sketcher_wb()
        if wb is not None:
            wb.import_dxf()

    def save_2d_sketch(self):
        wb = self._sketcher_wb()
        if wb is not None:
            wb.export_data()

    def save_2d_dxf(self):
        wb = self._sketcher_wb()
        if wb is not None:
            wb.export_dxf()

    def save_2d_svg(self):
        wb = self._sketcher_wb()
        if wb is not None:
            wb.export_svg()

    def show_about(self):
        QMessageBox.about(
            self,
            tr("About") + " PDFBubbleAnnotator",
            tr("<h3>FreeCAD-Style Modularity Demo</h3>"
               "<p>A dual-workbench architecture:<br>"
               "1. PDF Inspection (FAI ballooning)<br>"
               "2. Parametric 2D Sketcher</p>")
        )
