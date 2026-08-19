"""
Coordinate Transformation Utility
Maps between PDF Page Coordinates (Points), Screen Canvas Pixels, and Sketcher Physics (mm).
"""
from PyQt6.QtGui import QTransform, QPointF

class CoordinateTransform:
    def __init__(self, scale=1.0, rotation=0, offset_x=0.0, offset_y=0.0):
        self.scale = scale
        self.rotation = rotation
        self.offset_x = offset_x
        self.offset_y = offset_y

    def get_pdf_to_sketch_transform(self) -> QTransform:
        """
        Transform from PDF Page Space (0,0 top-left, 72 dpi)
        to Sketcher Physical Space (0,0 origin, mm, Y-axis flipped up).
        """
        transform = QTransform()
        transform.translate(self.offset_x, self.offset_y)
        transform.rotate(self.rotation)
        transform.scale(self.scale, -self.scale)  # Y-flip for standard engineering coordinate system
        return transform

    def pdf_to_sketch(self, point: QPointF) -> QPointF:
        matrix = self.get_pdf_to_sketch_transform()
        return matrix.map(point)

    def sketch_to_pdf(self, point: QPointF) -> QPointF:
        matrix, inverted = self.get_pdf_to_sketch_transform().inverted()
        if inverted:
            return matrix.map(point)
        return point