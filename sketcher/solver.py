"""
Geometric Constraint Solver Engine (SciPy least-squares bridge).

Variables: shared point coordinates (2 per unique point, deduplicated by
point id) + radii (1 per circle / arc). Arcs contribute 2 internal equations
(their endpoints must lie on the circle) which are solved but do NOT count
against the sketch's degrees of freedom.

Supported user constraints:
  HORIZONTAL, VERTICAL, PARALLEL, PERPENDICULAR, EQUAL, LENGTH, RADIUS, LOCK
(Coincident is structural: endpoints are merged to a shared SketchPoint.)
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


class SketchSolver:
    def solve(self, lines, circles, arcs, constraints):
        """
        Solve the constraint system, writing solved coordinates / radii back
        into the geometry models.
        Returns: (remaining_dof, residual_error, status, redundant)
        """
        geometry = list(lines) + list(circles) + list(arcs)
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
            n = math.hypot(dx, dy) or 1e-12
            return dx / n, dy / n

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
                elif t == "EQUAL":
                    dx1, dy1 = dvec(v, tg[0])
                    dx2, dy2 = dvec(v, tg[1])
                    res.append(math.hypot(dx1, dy1) - math.hypot(dx2, dy2))
                elif t == "LENGTH":
                    dx, dy = dvec(v, tg[0])
                    res.append(math.hypot(dx, dy) - c["value"])
                elif t == "RADIUS":
                    res.append(R(v, tg[0]) - c["value"])
                elif t == "LOCK":
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
                if c["type"] == "LOCK":
                    n += 2 * len(c["points"]) + (1 if c.get("radius") is not None else 0)
                else:
                    n += 1
            return n

        n_user = user_dof_cost()
        n_internal = 2 * len(arcs)

        # --- solve -------------------------------------------------------
        if HAS_SCIPY and (n_user + n_internal) > 0:
            result = least_squares(lambda v: np.asarray(all_residuals(v), dtype=float),
                                   x0, method="trf")
            solved = result.x
            residual = float(np.sum(result.fun ** 2))
            # DOF and redundancy come from the Jacobian rank at the solution:
            # dependent constraints (e.g. translation-invariant systems) must
            # not consume DOF, and every equation beyond the rank is redundant.
            jac = np.asarray(result.jac, dtype=float)
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
