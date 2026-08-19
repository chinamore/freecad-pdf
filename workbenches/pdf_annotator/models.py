"""
Data models for the PDF Bubble Annotator workbench.

Balloon positions are stored normalized (nx, ny in 0..1, origin top-left)
relative to their PDF page, so they survive zooming and map losslessly to
both screen pixels and PDF points on export.
"""
import uuid
from dataclasses import dataclass, field, asdict


@dataclass
class Bubble:
    page: int                 # 1-based PDF page number
    nx: float                 # normalized x (0..1, left -> right)
    ny: float                 # normalized y (0..1, top -> bottom)
    text: str                 # balloon number / label
    size: int = 28            # circle diameter in px at 100 % zoom
    border: int = 2           # outline width in px at 100 % zoom
    font: int = 13            # label font size in px at 100 % zoom
    outer_color: str = "#ef3340"
    fill_color: str = "transparent"   # "transparent" or "#rrggbb"
    font_color: str = "#ef3340"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        known = set(Bubble.__dataclass_fields__)
        return Bubble(**{k: v for k, v in d.items() if k in known})
