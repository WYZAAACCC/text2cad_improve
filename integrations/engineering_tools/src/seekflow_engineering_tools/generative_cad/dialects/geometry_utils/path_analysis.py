"""Path geometry analyzer — classify sweep paths for optimal method selection.

Analyzes 3D path points to determine the best sweep strategy:
- Straight: cylinder (fastest, perfect)
- Gentle bends: polyline or BSpline sweep (smooth, high quality)
- Tight bends: segmented cylinders (guaranteed volume, faceted but correct)
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field


@dataclass
class PathAnalysis:
    """Result of path geometry analysis."""
    point_count: int
    total_length: float
    min_segment_length: float
    max_bend_angle_deg: float = 0.0
    min_bend_radius_mm: float = float("inf")
    is_straight: bool = False
    is_planar: bool = False
    has_tight_bends: bool = False
    recommendation: str = "cylinder"
    details: list[str] = field(default_factory=list)


def analyze_path_geometry(
    path_points: list[tuple[float, float, float]],
    pipe_radius: float = 1.0,
) -> PathAnalysis:
    """Analyze a 3D path and recommend the optimal sweep method.

    Args:
        path_points: List of (x, y, z) tuples defining the sweep path.
        pipe_radius: Radius of the pipe cross-section (for bend radius comparison).

    Returns:
        PathAnalysis with classification and method recommendation.
    """
    n = len(path_points)
    if n < 2:
        raise ValueError("Need at least 2 points for path analysis")

    # Segment lengths and directions
    segments: list[tuple[float, tuple[float, float, float]]] = []
    for i in range(n - 1):
        p0, p1 = path_points[i], path_points[i + 1]
        dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
        length = math.sqrt(dx*dx + dy*dy + dz*dz)
        if length < 1e-9:
            continue
        direction = (dx/length, dy/length, dz/length)
        segments.append((length, direction))

    if not segments:
        raise ValueError("All path segments have zero length")

    total_length = sum(s[0] for s in segments)
    min_seg_len = min(s[0] for s in segments)

    # Bend angles between consecutive segments
    bend_angles: list[float] = []
    for i in range(len(segments) - 1):
        d1 = segments[i][1]
        d2 = segments[i + 1][1]
        dot = d1[0]*d2[0] + d1[1]*d2[1] + d1[2]*d2[2]
        dot = max(-1.0, min(1.0, dot))
        angle = math.degrees(math.acos(dot))
        bend_angles.append(angle)

    max_bend = max(bend_angles) if bend_angles else 0.0

    # Estimate minimum bend radius using chord length and angle
    # R = L / (2*sin(theta/2)) where L is the shorter adjacent segment
    min_bend_radius = float("inf")
    for i, angle in enumerate(bend_angles):
        if angle > 0.1:
            # Use the shorter of the two segments forming the bend
            L = min(segments[i][0], segments[i + 1][0])
            theta_rad = math.radians(angle)
            R = L / (2.0 * math.sin(theta_rad / 2.0)) if theta_rad > 0 else float("inf")
            min_bend_radius = min(min_bend_radius, R)

    # Straightness check: all segments collinear
    is_straight = max_bend < 0.5  # less than 0.5 degrees deviation

    # Planarity check: all points in same plane
    is_planar = True  # default for < 3 points
    if n >= 3:
        # Compute normal from first three non-collinear points
        p0, p1 = path_points[0], path_points[1]
        v1 = (p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2])
        # Find a non-collinear third point
        normal = None
        for i in range(2, n):
            p2 = path_points[i]
            v2 = (p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2])
            nx = v1[1]*v2[2] - v1[2]*v2[1]
            ny = v1[2]*v2[0] - v1[0]*v2[2]
            nz = v1[0]*v2[1] - v1[1]*v2[0]
            norm_len = math.sqrt(nx*nx + ny*ny + nz*nz)
            if norm_len > 1e-9:
                normal = (nx/norm_len, ny/norm_len, nz/norm_len)
                break
        if normal:
            max_deviation = 0.0
            for p in path_points:
                dev = abs((p[0]-p0[0])*normal[0] + (p[1]-p0[1])*normal[1] + (p[2]-p0[2])*normal[2])
                max_deviation = max(max_deviation, dev)
            is_planar = max_deviation < 0.01  # 0.01mm tolerance

    # Tight bend detection: bend radius < 3 * pipe_radius
    has_tight_bends = (
        min_bend_radius != float("inf")
        and min_bend_radius < 3.0 * pipe_radius
    )

    # Recommendation logic
    if n == 2 or is_straight:
        recommendation = "cylinder"
        details = ["Straight path: single cylinder is optimal"]
    elif n == 3 and max_bend < 45.0 and not has_tight_bends:
        recommendation = "polyline_sweep"
        details = [f"Single gentle bend ({max_bend:.0f}deg): polyline MakePipe reliable"]
    elif has_tight_bends:
        recommendation = "segmented"
        details = [
            f"Tight bends detected: min R={min_bend_radius:.0f}mm vs pipe_r={pipe_radius:.0f}mm",
            f"Bend radius/pipe radius ratio = {min_bend_radius/pipe_radius:.1f} (< 3.0)",
            "Segmented cylinders guarantee correct volume for tight bends"
        ]
    else:
        recommendation = "bspline_sweep"
        details = [
            f"Complex path with {n} points, max bend={max_bend:.0f}deg",
            "BSpline sweep produces smooth, high-quality geometry"
        ]

    return PathAnalysis(
        point_count=n,
        total_length=total_length,
        min_segment_length=min_seg_len,
        max_bend_angle_deg=max_bend,
        min_bend_radius_mm=min_bend_radius,
        is_straight=is_straight,
        is_planar=is_planar,
        has_tight_bends=has_tight_bends,
        recommendation=recommendation,
        details=details,
    )
