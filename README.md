# PDFBubbleAnnotator & 2D Sketcher Workbench

FreeCAD-style dual-workbench desktop application built with **PyQt6**. Designed for mechanical engineering quality inspection (FAI / PPAP ballooning) and 2D parametric geometry drafting.

## 🌟 Key Features

1. **FreeCAD-Style GUI Architecture**:
   - Integrated Workbench Switcher Toolbar (`QComboBox`).
   - Dockable Tree View & Property Inspector (`QDockWidget`).
   - Integrated Python Console & Logging output.

2. **Workbench 1: PDF Bubble Annotator** (PyMuPDF rendering engine):
   - True PDF page rendering with page navigation, zoom (Ctrl+Wheel), and fit-to-view.
   - Click-to-add draggable balloons with auto-incrementing sequence numbers.
   - Per-balloon styling: diameter, border width, font size, outline / fill / text colors, transparent fill.
   - Right-click / Delete key removal, per-page auto-renumbering, Undo / Redo (50 steps).
   - Vector PDF export (balloons drawn into a copy of the source PDF), current-page PNG, batch PNG, and printing.
   - Export balloon coordinates & metadata to JSON for FAI inspection reports.

3. **Workbench 2: 2D Sketcher Workbench**:
   - Parametric geometry drafting (Lines, Circles, Origin Grid).
   - Coordinate Transformer (Mapping PDF Page Points to Physical Sketch mm space).
   - Geometric Constraint Solver integration (`SciPy` Levenberg-Marquardt optimizer bridge).

---

## 🚀 Quick Start & Running Instructions

### 1. Installation
Ensure Python 3.9+ is installed, then install dependencies:

```bash
pip install -r requirements.txt
```

### 2. Run Application
Launch the application:

```bash
python main.py
```

---

## 🛠 Project Structure

```
PDFBubbleAnnotator/
├── main.py                     # Entry point
├── requirements.txt            # Python dependencies
├── ui/
│   ├── main_window.py          # FreeCAD MainWindow, Docks, Workbench Switcher
├── utils/
│   └── coordinate_transform.py # PDF to Sketch Matrix Transformer
├── workbenches/
│   ├── base_workbench.py       # Abstract Workbench Interface
│   ├── pdf_annotator/          # [Workbench 1] FAI Bubble Annotator
│   └── sketcher/               # [Workbench 2] 2D Parametric Sketcher
└── sketcher/
    ├── models.py               # GeoElement Data Models
    └── solver.py               # Constraint Solver Engine (SciPy Bridge)
```