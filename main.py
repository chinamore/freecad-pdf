"""
PDFBubbleAnnotator Main Entry Point
FreeCAD-style Workbench Architecture for PDF Bubble Annotation & 2D Sketching
"""
import sys
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    window = MainWindow()
    window.showMaximized()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()