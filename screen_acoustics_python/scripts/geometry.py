"""Geometry utilities for the six-panel folding-screen experiment."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize_scalar


@dataclass(frozen=True)
class DiffractionEdge:
    name: str
    p0: np.ndarray
    p1: np.ndarray


def generate_accordion_vertices(
    number_of_panels: int,
    panel_width_m: float,
    adjacent_turn_angle_deg: float,
) -> np.ndarray:
    """Generate centered hinge vertices using alternating +/- theta/2 headings.

    Angles are measured from +y toward +x in the xy plane. The arithmetic mean
    of vertex x coordinates is centered at zero; the y extent midpoint is zero.
    """
    if number_of_panels <= 0 or panel_width_m <= 0:
        raise ValueError("panel count and panel width must be positive")
    half_angle = math.radians(adjacent_turn_angle_deg / 2.0)
    headings = [half_angle if i % 2 == 0 else -half_angle for i in range(number_of_panels)]
    vertices = [np.array([0.0, 0.0], dtype=np.float64)]
    for heading in headings:
        step = panel_width_m * np.array([math.sin(heading), math.cos(heading)], dtype=np.float64)
        vertices.append(vertices[-1] + step)
    result = np.asarray(vertices, dtype=np.float64)
    result[:, 0] -= np.mean(result[:, 0])
    result[:, 1] -= 0.5 * (np.min(result[:, 1]) + np.max(result[:, 1]))
    return result


def validate_accordion_geometry(
    vertices_xy: np.ndarray,
    number_of_panels: int,
    panel_width_m: float,
    adjacent_turn_angle_deg: float,
    tolerance: float = 1e-9,
) -> dict[str, float | int | bool]:
    vertices = np.asarray(vertices_xy, dtype=np.float64)
    if vertices.shape != (number_of_panels + 1, 2):
        raise AssertionError(f"Expected {(number_of_panels + 1, 2)}, got {vertices.shape}")
    segments = np.diff(vertices, axis=0)
    lengths = np.linalg.norm(segments, axis=1)
    if not np.all(np.abs(lengths - panel_width_m) <= tolerance):
        raise AssertionError(f"Panel lengths failed tolerance: {lengths}")

    headings = np.unwrap(np.arctan2(segments[:, 0], segments[:, 1]))
    turn_angles = np.abs(np.diff(headings)) * 180.0 / math.pi
    if not np.all(np.abs(turn_angles - adjacent_turn_angle_deg) <= 1e-9):
        raise AssertionError(f"Turn angles failed tolerance: {turn_angles}")

    developed_width = float(np.sum(lengths))
    expected_developed_width = number_of_panels * panel_width_m
    if abs(developed_width - expected_developed_width) > tolerance:
        raise AssertionError("Developed width validation failed")
    if abs(float(np.mean(vertices[:, 0]))) > tolerance:
        raise AssertionError("Mean x is not centered")
    if abs(float(np.min(vertices[:, 1]) + np.max(vertices[:, 1]))) > 2.0 * tolerance:
        raise AssertionError("Y extent midpoint is not centered")

    return {
        "panel_count": number_of_panels,
        "vertex_count": len(vertices),
        "max_segment_length_error_m": float(np.max(np.abs(lengths - panel_width_m))),
        "max_turn_angle_error_deg": float(np.max(np.abs(turn_angles - adjacent_turn_angle_deg))),
        "developed_width_m": developed_width,
        "projected_width_m": float(np.ptp(vertices[:, 1])),
        "fold_depth_m": float(np.ptp(vertices[:, 0])),
        "mean_x_m": float(np.mean(vertices[:, 0])),
        "mid_y_m": float(0.5 * (np.min(vertices[:, 1]) + np.max(vertices[:, 1]))),
        "valid": True,
    }


def _cross_2d(a: np.ndarray, b: np.ndarray) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def segment_intersection_parameters(
    a0: np.ndarray,
    a1: np.ndarray,
    b0: np.ndarray,
    b1: np.ndarray,
    tolerance: float = 1e-12,
) -> tuple[float, float] | None:
    """Return parameters t,u for the unique 2D segment intersection, if any."""
    p = np.asarray(a0, dtype=np.float64)
    r = np.asarray(a1, dtype=np.float64) - p
    q = np.asarray(b0, dtype=np.float64)
    s = np.asarray(b1, dtype=np.float64) - q
    denominator = _cross_2d(r, s)
    if abs(denominator) <= tolerance:
        return None
    q_minus_p = q - p
    t = _cross_2d(q_minus_p, s) / denominator
    u = _cross_2d(q_minus_p, r) / denominator
    if -tolerance <= t <= 1.0 + tolerance and -tolerance <= u <= 1.0 + tolerance:
        return min(max(t, 0.0), 1.0), min(max(u, 0.0), 1.0)
    return None


def is_direct_path_blocked(
    source_xyz: np.ndarray,
    receiver_xyz: np.ndarray,
    vertices_xy: np.ndarray,
    z_bottom_m: float,
    z_top_m: float,
) -> bool:
    """Test xy panel intersection and interpolate the 3D ray height at crossing."""
    source = np.asarray(source_xyz, dtype=np.float64)
    receiver = np.asarray(receiver_xyz, dtype=np.float64)
    vertices = np.asarray(vertices_xy, dtype=np.float64)
    for index in range(len(vertices) - 1):
        intersection = segment_intersection_parameters(
            source[:2], receiver[:2], vertices[index], vertices[index + 1]
        )
        if intersection is None:
            continue
        ray_parameter, _ = intersection
        intersection_z = source[2] + ray_parameter * (receiver[2] - source[2])
        if z_bottom_m - 1e-12 <= intersection_z <= z_top_m + 1e-12:
            return True
    return False


def build_candidate_diffraction_edges(
    vertices_xy: np.ndarray,
    z_bottom_m: float,
    z_top_m: float,
) -> list[DiffractionEdge]:
    vertices = np.asarray(vertices_xy, dtype=np.float64)
    edges: list[DiffractionEdge] = []
    for index in range(len(vertices) - 1):
        start, end = vertices[index], vertices[index + 1]
        edges.append(
            DiffractionEdge(
                f"top_panel_{index + 1}",
                np.array([start[0], start[1], z_top_m], dtype=np.float64),
                np.array([end[0], end[1], z_top_m], dtype=np.float64),
            )
        )
        edges.append(
            DiffractionEdge(
                f"bottom_panel_{index + 1}",
                np.array([start[0], start[1], z_bottom_m], dtype=np.float64),
                np.array([end[0], end[1], z_bottom_m], dtype=np.float64),
            )
        )
    edges.extend(
        [
            DiffractionEdge(
                "left_outer_vertical",
                np.array([vertices[0, 0], vertices[0, 1], z_bottom_m], dtype=np.float64),
                np.array([vertices[0, 0], vertices[0, 1], z_top_m], dtype=np.float64),
            ),
            DiffractionEdge(
                "right_outer_vertical",
                np.array([vertices[-1, 0], vertices[-1, 1], z_bottom_m], dtype=np.float64),
                np.array([vertices[-1, 0], vertices[-1, 1], z_top_m], dtype=np.float64),
            ),
        ]
    )
    if len(edges) != 14:
        raise AssertionError(f"Expected 14 candidate edges, got {len(edges)}")
    return edges


def shortest_diffracted_path(
    source_xyz: np.ndarray,
    receiver_xyz: np.ndarray,
    edges: list[DiffractionEdge],
) -> dict[str, float | str]:
    source = np.asarray(source_xyz, dtype=np.float64)
    receiver = np.asarray(receiver_xyz, dtype=np.float64)
    direct_distance = float(np.linalg.norm(receiver - source))
    candidates: list[tuple[float, str, float, float]] = []
    for edge in edges:
        direction = edge.p1 - edge.p0

        def path_length(parameter: float) -> float:
            point = edge.p0 + parameter * direction
            return float(np.linalg.norm(source - point) + np.linalg.norm(receiver - point))

        optimized = minimize_scalar(
            path_length,
            bounds=(0.0, 1.0),
            method="bounded",
            options={"xatol": 1e-12, "maxiter": 1000},
        )
        if not optimized.success or not np.isfinite(optimized.fun):
            raise ArithmeticError(f"Edge optimization failed for {edge.name}: {optimized}")
        path_difference = float(optimized.fun - direct_distance)
        if path_difference < -1e-9:
            raise ArithmeticError(f"Negative path difference for {edge.name}: {path_difference}")
        if path_difference < 0.0:
            path_difference = 0.0
        candidates.append((path_difference, edge.name, float(optimized.fun), float(optimized.x)))

    positive = [item for item in candidates if item[0] > 0.0]
    if not positive:
        raise ArithmeticError("No positive candidate diffraction path difference")
    delta, edge_name, diffracted_path, edge_parameter = min(positive, key=lambda item: item[0])
    return {
        "direct_distance_m": direct_distance,
        "controlling_edge": edge_name,
        "diffracted_path_m": diffracted_path,
        "path_difference_m": delta,
        "edge_parameter": edge_parameter,
    }

