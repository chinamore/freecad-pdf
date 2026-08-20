"""
Geometry Data Models for 2D Sketcher Workbench
"""
import uuid
from dataclasses import dataclass, field

@dataclass
class SketchPoint:
    x: float
    y: float
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

@dataclass
class SketchLine:
    p1: SketchPoint
    p2: SketchPoint
    is_construction: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

@dataclass
class SketchCircle:
    center: SketchPoint
    radius: float
    is_construction: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

@dataclass
class SketchArc:
    """Three-point arc. `mid` only stores the on-arc click position used
    to determine draw orientation; solver state lives in center/radius/p1/p2."""
    center: SketchPoint
    radius: float
    p1: SketchPoint               # start point (on arc)
    p2: SketchPoint               # end point (on arc)
    mid: tuple = (0.0, 0.0)       # on-arc point for draw orientation
    is_construction: bool = False
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])