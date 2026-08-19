"""
Geometric Constraint Solver Bridge using SciPy Optimization
"""
import numpy as np
try:
    from scipy.optimize import least_squares
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

class SketchSolver:
    def __init__(self):
        pass

    def solve(self, points, lines, constraints):
        """
        Solves geometric constraints with a Levenberg-Marquardt least-squares
        pass over the line endpoint coordinates, writing the solved positions
        back into the line models.
        Returns: (remaining_dof, residual_error)
        """
        dof = max(0, len(lines) * 4 - len(constraints))

        if not lines or not constraints:
            return dof, 0.0

        x0 = np.array(
            [coord for line in lines
             for coord in (line.p1.x, line.p1.y, line.p2.x, line.p2.y)],
            dtype=float,
        )
        line_index = {id(line): i for i, line in enumerate(lines)}

        def residuals(vars_flat):
            res = []
            for c in constraints:
                i = line_index.get(id(c["target"]))
                if i is None:
                    continue
                x1, y1, x2, y2 = vars_flat[i * 4: i * 4 + 4]
                if c["type"] == "HORIZONTAL":
                    res.append(y1 - y2)
                elif c["type"] == "VERTICAL":
                    res.append(x1 - x2)
            return np.asarray(res, dtype=float)

        if not HAS_SCIPY:
            return dof, float(np.sum(residuals(x0) ** 2))

        # 'trf' also works when constraints (residuals) are fewer than variables
        result = least_squares(residuals, x0, method="trf")

        for line in lines:
            i = line_index[id(line)] * 4
            line.p1.x, line.p1.y, line.p2.x, line.p2.y = result.x[i: i + 4]

        return dof, float(np.sum(result.fun ** 2))
