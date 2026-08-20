"""
STEP (AP203/AP214) loader + orthographic projection for the Drawing workbench.

Loads a STEP file via CadQuery/OCP, tessellates each edge into polyline
samples, and projects them to 2D from a chosen view direction
(FRONT / TOP / RIGHT / ISO). Projection is wireframe (all edges drawn);
first-angle vs third-angle placement is handled by the workbench.
"""
import math

HAS_CQ = False
_CQ_ERROR = None
try:
    import os as _os
    import sys as _sys
    # PyInstaller: make the bundled OCC dlls discoverable on Windows
    _meipass = getattr(_sys, "_MEIPASS", None)
    if _meipass:
        for _cand in ("cadquery_ocp.libs", "OCP"):
            _p = _os.path.join(_meipass, _cand)
            if _os.path.isdir(_p) and _p not in _os.environ.get("PATH", ""):
                _os.environ["PATH"] = _p + _os.pathsep + _os.environ.get("PATH", "")
    from cadquery import importers
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_UniformAbscissa
    HAS_CQ = True
except Exception as _e:  # pragma: no cover - environment specific
    _CQ_ERROR = _e


def load_step(path):
    """Return (solid, samples_per_edge) or raise."""
    if not HAS_CQ:
        raise RuntimeError(f"cadquery import failed: {_CQ_ERROR!r}")
    wp = importers.importStep(path)
    solid = wp.val().wrapped
    BRepMesh_IncrementalMesh(solid, 0.2, True)
    return solid


def _sample_edges(solid, n_samples=40):
    """Return list of polylines: [[(x,y,z), ...], ...]."""
    lines = []
    exp = TopExp_Explorer(solid, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        curve = BRepAdaptor_Curve(edge)
        first, last = curve.FirstParameter(), curve.LastParameter()
        disc = GCPnts_UniformAbscissa(curve, n_samples, first, last)
        pts = []
        for i in range(1, disc.NbPoints() + 1):
            p = curve.Value(disc.Parameter(i))
            pts.append((p.X(), p.Y(), p.Z()))
        if len(pts) > 1:
            lines.append(pts)
        exp.Next()
    return lines


_VIEWS = {
    # name: (project(x,y,z) -> (u,v))
    "FRONT": lambda x, y, z: (x, -z),
    "TOP": lambda x, y, z: (x, y),
    "RIGHT": lambda x, y, z: (y, -z),
    "LEFT": lambda x, y, z: (-y, -z),
    "ISO": lambda x, y, z: (x * 0.866 - y * 0.866,
                            -(x * 0.5 + y * 0.5 - z * 0.707)),
}


def project_2d(solid, view="FRONT"):
    """Return list of 2D polylines [[(u,v), ...], ...] for the view."""
    proj = _VIEWS.get(view.upper(), _VIEWS["FRONT"])
    return [[proj(*p) for p in line] for line in _sample_edges(solid)]
