"""
Geometric Constraint Solver Engine (SciPy least-squares bridge),
modelled on FreeCAD's Sketcher solver semantics.

Variables: shared point coordinates (2 per unique point, deduplicated by
point id) + radii (1 per circle / arc). Arcs contribute 2 internal equations
(their endpoints must lie on the circle) which are solved but do NOT count
against the sketch's degrees of freedom.

Supported user constraints (FreeCAD parity):
  Coincident        - structural: endpoints are merged to a shared SketchPoint
  HORIZONTAL        - line endpoints share Y
  VERTICAL          - line endpoints share X
  PARALLEL          - two lines, equal direction (cross == 0)
  PERPENDICULAR     - two lines, dot == 0
  TANGENT           - line/line (collinear), line/circle, circle/circle
  EQUAL             - line/line (length), circle|arc/circle|arc (radius)
  SYMMETRIC         - two points mirrored about a line or a center point
  POINT_ON          - a point lies on a line / circle / arc
  BLOCK / LOCK      - geometry fixed at captured coordinates
  DISTANCE / LENGTH - line length or point-to-point distance
  DISTANCE_X        - signed X distance of a line's endpoints (or 2 points)
  DISTANCE_Y        - signed Y distance of a line's endpoints (or 2 points)
  RADIUS            - circle / arc radius
  DIAMETER          - circle diameter (2R)
  ANGLE             - angle between two lines (degrees)
"""
import math

import numpy as np

try:
    from scipy.optimize import least_squares
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

STATUS_EMPTY = "empty"
STATUS_UNDER = "under"
STATUS_FULL = "full"
STATUS_OVER = "over"

_SOLVE_TOL = 1e-6
_EPS = 1e-12


def _numeric_jacobian(f, x, eps=1e-7):
    """Central-difference Jacobian of a residual vector function."""
    x = np.asarray(x, dtype=float)
    f0 = f(x)
    jac = np.empty((f0.size, x.size))
    for j in range(x.size):
        h = eps * max(1.0, abs(x[j]))
        xp, xm = x.copy(), x.copy()
        xp[j] += h
        xm[j] -= h
        jac[:, j] = (f(xp) - f(xm)) / (2 * h)
    return jac


class SketchSolver:
    def solve(self, lines, circles, arcs, constraints, points=()):
        """
        Solve the constraint system, writing solved coordinates / radii back
        into the geometry models.
        Returns: (remaining_dof, residual_error, status, redundant)
        """
        geometry = list(lines) + list(circles) + list(arcs) + list(points)
        if not geometry:
            return 0, 0.0, STATUS_EMPTY, False

        # --- index shared variables -------------------------------------
        pt_index, pts = {}, []
        rad_index, rad_objs = {}, []

        def reg_pt(p):
            if p.id not in pt_index:
                pt_index[p.id] = len(pts)
                pts.append(p)

        def reg_rad(o):
            if o.id not in rad_index:
                rad_index[o.id] = len(rad_objs)
                rad_objs.append(o)

        for p in points:
            reg_pt(p)
        for l in lines:
            reg_pt(l.p1)
            reg_pt(l.p2)
        for c in circles:
            reg_pt(c.center)
            reg_rad(c)
        for a in arcs:
            reg_pt(a.center)
            reg_pt(a.p1)
            reg_pt(a.p2)
            reg_rad(a)
        # constraint-referenced points not attached to any geometry
        for c in constraints:
            for p in c.get("points") or ():
                reg_pt(p)
            if c.get("point") is not None:
                reg_pt(c["point"])

        npts = len(pts)
        nvars = 2 * npts + len(rad_objs)

        x0 = np.empty(nvars)
        for p in pts:
            i = pt_index[p.id]
            x0[2 * i], x0[2 * i + 1] = p.x, p.y
        for j, o in enumerate(rad_objs):
            x0[2 * npts + j] = o.radius

        def P(v, p):
            i = pt_index[p.id]
            return v[2 * i], v[2 * i + 1]

        def R(v, o):
            return v[2 * npts + rad_index[o.id]]

        def dvec(v, l):
            x1, y1 = P(v, l.p1)
            x2, y2 = P(v, l.p2)
            return x2 - x1, y2 - y1

        def uvec(v, l):
            dx, dy = dvec(v, l)
            n = math.hypot(dx, dy) or _EPS
            return dx / n, dy / n

        def line_len(v, l):
            dx, dy = dvec(v, l)
            return math.hypot(dx, dy)

        def sdist_point_line(v, pt, line):
            """Signed distance from point to (infinite) line."""
            dx, dy = dvec(v, line)
            n = math.hypot(dx, dy) or _EPS
            px, py = P(v, pt)
            ax, ay = P(v, line.p1)
            return ((px - ax) * dy - (py - ay) * dx) / n

        def is_round(o):
            return hasattr(o, "radius")

        # --- residuals ---------------------------------------------------
        def user_residuals(v):
            res = []
            for c in constraints:
                t = c["type"]
                tg = c["targets"]
                if t == "HORIZONTAL":
                    _, y1 = P(v, tg[0].p1)
                    _, y2 = P(v, tg[0].p2)
                    res.append(y1 - y2)
                elif t == "VERTICAL":
                    x1, _ = P(v, tg[0].p1)
                    x2, _ = P(v, tg[0].p2)
                    res.append(x1 - x2)
                elif t == "PARALLEL":
                    ux1, uy1 = uvec(v, tg[0])
                    ux2, uy2 = uvec(v, tg[1])
                    res.append(ux1 * uy2 - uy1 * ux2)
                elif t == "PERPENDICULAR":
                    ux1, uy1 = uvec(v, tg[0])
                    ux2, uy2 = uvec(v, tg[1])
                    res.append(ux1 * ux2 + uy1 * uy2)
                elif t == "TANGENT":
                    g1, g2 = tg
                    if not is_round(g1) and not is_round(g2):
                        # line/line tangent == collinear (2 equations)
                        ux1, uy1 = uvec(v, g1)
                        ux2, uy2 = uvec(v, g2)
                        res.append(ux1 * uy2 - uy1 * ux2)
                        res.append(sdist_point_line(v, g2.p1, g1))
                    elif is_round(g1) and is_round(g2):
                        cx1, cy1 = P(v, g1.center)
                        cx2, cy2 = P(v, g2.center)
                        d = math.hypot(cx2 - cx1, cy2 - cy1)
                        r1, r2 = R(v, g1), R(v, g2)
                        target = (r1 + r2) if d >= max(r1, r2) else abs(r1 - r2)
                        res.append(d - target)
                    else:
                        line = g1 if not is_round(g1) else g2
                        circ = g2 if not is_round(g1) else g1
                        sd = sdist_point_line(v, circ.center, line)
                        res.append(sd - math.copysign(R(v, circ), sd or 1.0))
                elif t == "EQUAL":
                    if is_round(tg[0]) and is_round(tg[1]):
                        res.append(R(v, tg[0]) - R(v, tg[1]))
                    else:
                        res.append(line_len(v, tg[0]) - line_len(v, tg[1]))
                elif t == "SYMMETRIC":
                    p1, p2 = c["points"]
                    p1x, p1y = P(v, p1)
                    p2x, p2y = P(v, p2)
                    if c.get("line") is not None:
                        ax, ay = P(v, c["line"].p1)
                        ux, uy = uvec(v, c["line"])
                        proj = (p1x - ax) * ux + (p1y - ay) * uy
                        fx, fy = ax + proj * ux, ay + proj * uy  # foot of p1
                        res += [p2x - (2 * fx - p1x), p2y - (2 * fy - p1y)]
                    else:
                        cx, cy = P(v, c["center"])
                        res += [p2x + p1x - 2 * cx, p2y + p1y - 2 * cy]
                elif t == "POINT_ON":
                    g = tg[0]
                    p = c["point"]
                    if is_round(g):
                        px, py = P(v, p)
                        cx, cy = P(v, g.center)
                        res.append(math.hypot(px - cx, py - cy) - R(v, g))
                    else:
                        res.append(sdist_point_line(v, p, g))
                elif t in ("DISTANCE", "LENGTH"):
                    if c.get("points"):
                        p1, p2 = c["points"]
                        x1, y1 = P(v, p1)
                        x2, y2 = P(v, p2)
                        res.append(math.hypot(x2 - x1, y2 - y1) - c["value"])
                    else:
                        res.append(line_len(v, tg[0]) - c["value"])
                elif t == "DISTANCE_X":
                    pts2 = c.get("points") or (tg[0].p1, tg[0].p2)
                    x1, _ = P(v, pts2[0])
                    x2, _ = P(v, pts2[1])
                    res.append((x2 - x1) - c["value"])
                elif t == "DISTANCE_Y":
                    pts2 = c.get("points") or (tg[0].p1, tg[0].p2)
                    _, y1 = P(v, pts2[0])
                    _, y2 = P(v, pts2[1])
                    res.append((y2 - y1) - c["value"])
                elif t == "RADIUS":
                    res.append(R(v, tg[0]) - c["value"])
                elif t == "DIAMETER":
                    res.append(2 * R(v, tg[0]) - c["value"])
                elif t == "ANGLE":
                    ux1, uy1 = uvec(v, tg[0])
                    ux2, uy2 = uvec(v, tg[1])
                    dot = max(-1.0, min(1.0, ux1 * ux2 + uy1 * uy2))
                    # scaled to ~length units for the least-squares balance
                    res.append((math.acos(dot) - math.radians(c["value"])) * 10.0)
                elif t in ("LOCK", "BLOCK"):
                    for pt, (fx, fy) in zip(c["points"], c["coords"]):
                        x, y = P(v, pt)
                        res += [x - fx, y - fy]
                    if c.get("radius") is not None:
                        res.append(R(v, tg[0]) - c["radius"])
            return res

        def all_residuals(v):
            res = user_residuals(v)
            for a in arcs:  # internal equations, not user DOF
                cx, cy = P(v, a.center)
                for p in (a.p1, a.p2):
                    px, py = P(v, p)
                    res.append(math.hypot(px - cx, py - cy) - R(v, a))
            return res

        def user_dof_cost():
            n = 0
            for c in constraints:
                t = c["type"]
                if t in ("LOCK", "BLOCK"):
                    n += 2 * len(c["points"]) + (1 if c.get("radius") is not None else 0)
                elif t == "SYMMETRIC":
                    n += 2
                elif t == "TANGENT" and not is_round(c["targets"][0]) \
                        and not is_round(c["targets"][1]):
                    n += 2
                else:
                    n += 1
            return n

        n_user = user_dof_cost()
        n_internal = 2 * len(arcs)

        # --- solve -------------------------------------------------------
        if HAS_SCIPY and (n_user + n_internal) > 0:
            # NOTE: tr_solver="exact" (the trf default) mishandles
            # underdetermined systems (fewer residuals than variables) and
            # can stop far from the solution; lsmr converges correctly.
            result = least_squares(lambda v: np.asarray(all_residuals(v), dtype=float),
                                   x0, method="trf", tr_solver="lsmr")
            solved = result.x
            residual = float(np.sum(result.fun ** 2))
            # DOF and redundancy come from the Jacobian rank at the solution:
            # dependent constraints (e.g. translation-invariant systems) must
            # not consume DOF, and every equation beyond the rank is redundant.
            # result.jac is None with lsmr, so recompute numerically.
            jac = _numeric_jacobian(
                lambda v: np.asarray(all_residuals(v), dtype=float), solved)
            sv = np.linalg.svd(jac, compute_uv=False) if jac.size else np.zeros(0)
            rank = int((sv > sv[0] * 1e-6).sum()) if sv.size else 0
            dof = max(0, nvars - rank)
            redundant = (n_user + n_internal) > rank
        else:
            solved = x0
            residual = float(np.sum(np.asarray(all_residuals(x0), dtype=float) ** 2))
            rank = 0
            dof = max(0, nvars - n_user - n_internal)
            redundant = (n_user + n_internal) > nvars

        # --- write back --------------------------------------------------
        for p in pts:
            i = pt_index[p.id]
            p.x, p.y = float(solved[2 * i]), float(solved[2 * i + 1])
        for j, o in enumerate(rad_objs):
            o.radius = abs(float(solved[2 * npts + j]))

        # FreeCAD semantics: redundancy is a warning, not an error state;
        # OVER means the system could not be satisfied (conflicting constraints)
        if residual > _SOLVE_TOL and (n_user + n_internal) > 0:
            status = STATUS_OVER
        elif dof == 0:
            status = STATUS_FULL
        else:
            status = STATUS_UNDER
        return dof, residual, status, redundant
