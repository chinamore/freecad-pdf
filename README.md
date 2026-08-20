# PDFBubbleAnnotator & 2D Sketcher Workbench

FreeCAD-style dual-workbench desktop application built with **PyQt6**. Designed for mechanical engineering quality inspection (FAI / PPAP ballooning) and 2D parametric geometry drafting.

## 🌟 Key Features

1. **FreeCAD-Style GUI Architecture**:
   - Integrated Workbench Switcher Toolbar (`QComboBox`).
   - Dockable Tree View & Property Inspector (`QDockWidget`).
   - Integrated Python Console & Logging output.
   - **Multilingual UI**: runtime switch between English and 简体中文 (Language menu; the choice is persisted via QSettings).
   - Application icon (window + Windows EXE) from `assets/icon.ico`.

2. **Workbench 1: PDF Bubble Annotator** (PyMuPDF rendering engine):
   - True PDF page rendering with page navigation, zoom (Ctrl+Wheel), and fit-to-view.
   - Click-to-add draggable balloons with auto-incrementing sequence numbers.
   - Per-balloon styling: diameter, border width, font size, outline / fill / text colors, transparent fill.
   - Right-click / Delete key removal, per-page auto-renumbering, Undo / Redo (50 steps).
   - Vector PDF export (balloons drawn into a copy of the source PDF), current-page PNG, batch PNG, and printing.
   - Export balloon coordinates & metadata to JSON for FAI inspection reports.

3. **Workbench 2: 2D Sketcher Workbench** (FreeCAD Sketcher parity, full 2D CAD):
   - **FreeCAD-style red tool icons** on the toolbar (text lives in the tooltip / status tip).
   - Geometry tools (single-shot: they return to Select after one shape): Point `G,P`,
     Line `G,L`, Polyline `G,M` (continuous chain until Esc), Circle `G,C`,
     Arc by center `G,A`, Arc by 3 points `G,3`, Rectangle `G,R`, Triangle `G,T`,
     Square `G,S`, Reference line `G,X` (dashed construction line).
   - **Type-in dimensions while drawing**: after a line/circle/rectangle is placed, a
     small dialog offers the exact length / radius / width+height (mm, pre-filled with the
     dragged value); typing a value applies it, Esc keeps the dragged size.
   - **Selection & editing**: rubber-band box select (drag on empty canvas), Ctrl+A select
     all, Del deletes the picked line/circle/arcs only, and **Ctrl+click multi-selects
     vertices and geometry** (needed to pick two endpoints for a point-to-point distance
     or a symmetry axis).
   - **Safe dimension entry**: every typed dimension is solved immediately; if it conflicts
     with the existing constraints the user is warned and the conflicting value is rolled
     back (instead of silently failing).
   - File menu: **New 2D Sketch** (Ctrl+N), **Open 2D Sketch…**, **Import 2D CAD (DXF)…**,
     **Save 2D Sketch (JSON)** (Ctrl+S) — round-trippable, **Save as 2D CAD (DXF)…**,
     **Save as 2D Vector (SVG)…**.
   - Canvas shows the FreeCAD-style origin marker and red X / green Y reference axes.
   - **Red vertex handles** at every endpoint / center (line ends, rectangle corners, ...),
     moving with the geometry.
   - Constraints: Coincident `C`, Point-on-object `O`, Horizontal `H`, Vertical `V`,
     Parallel `P`, Perpendicular `N`, Tangent `T`, Equal `E`, Symmetric `S`, Block `B`,
     Lock `K`, Distance `D`, Distance X `L`, Distance Y `I`, Radius `R`, Diameter, Angle `A`.
   - FreeCAD interaction: press the shortcut then click the targets (pick workflow), or
     pre-select then apply; constraint command leaves the active tool like FreeCAD.
   - **Drag & drop with LIVE solve**: grab a vertex or a whole curve; constraints follow
     in real time and are re-imposed on release.
   - **Auto-constraints** on creation (nearly axis-aligned lines get H/V; snapped endpoints
     become structural coincidence = shared points).
   - **Constraint badges** on the canvas (H, V, //, T+, =, TAN, SYM, ON, LK, BLK, D/DX/DY/R/DIA/deg
     values), stacked side-by-side like FreeCAD; **double-click a dimensional badge to edit
     its value**, right-click a badge to remove the constraint.
   - Colour semantics: normal black / construction blue / selected yellow / preselection
     light blue / fully-constrained green / conflicting red.
   - Undo/redo (`Ctrl+Z` / `Ctrl+Shift+Z` / `Ctrl+Y`) covering geometry, constraints, drags.
   - `G,N` toggles construction geometry of the selection; grid & endpoint snapping;
     continuous creation mode; Esc / right-click cancels.
   - SciPy least-squares solver (LSMR trust-region solver, numerically stable for
     underdetermined sketches) with shared-variable deduplication, DOF analysis,
     over-constraint detection, and fully-constrained highlighting.
   - Coordinate Transformer (Mapping PDF Page Points to Physical Sketch mm space).

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
├── assets/
│   └── icon.png / icon.ico     # Application icon (window + EXE)
├── ui/
│   └── main_window.py          # FreeCAD MainWindow, Docks, Workbench Switcher, i18n hooks
├── utils/
│   ├── coordinate_transform.py # PDF to Sketch Matrix Transformer
│   └── i18n.py                 # English / 简体中文 translation dictionary
├── workbenches/
│   ├── base_workbench.py       # Abstract Workbench Interface
│   ├── pdf_annotator/          # [Workbench 1] FAI Bubble Annotator
│   └── sketcher/               # [Workbench 2] 2D Parametric Sketcher
└── sketcher/
    ├── models.py               # GeoElement Data Models
    └── solver.py               # Constraint Solver Engine (SciPy Bridge)
```