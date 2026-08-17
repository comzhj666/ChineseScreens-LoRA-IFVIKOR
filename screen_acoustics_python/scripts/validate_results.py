"""Independent validation of the S12/S20 acoustic evaluation V1 outputs."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import matplotlib.image as mpimg
import numpy as np
import pandas as pd

from acoustic_models import kurze_anderson_insertion_loss, miki_rigid_backed_absorption
from geometry import generate_accordion_vertices, validate_accordion_geometry


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "acoustic_parameters_v1.json"
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def assert_close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
        raise AssertionError(f"{label}: actual={actual}, expected={expected}, tolerance={tolerance}")


def main() -> None:
    with CONFIG.open("r", encoding="utf-8") as stream:
        config = json.load(stream)

    expected_csv_rows = {
        "material_absorption_baseline.csv": 10,
        "material_absorption_sensitivity.csv": 30,
        "screen_geometry_vertices.csv": 14,
        "barrier_il_by_receiver.csv": 100,
        "barrier_il_summary.csv": 20,
        "s12_s20_comparison.csv": 10,
        "overall_metrics.csv": 2,
    }
    frames = {}
    for filename, expected_rows in expected_csv_rows.items():
        path = RESULTS / filename
        if not path.is_file() or not path.read_bytes().startswith(b"\xef\xbb\xbf"):
            raise AssertionError(f"Missing or non-UTF-8-SIG CSV: {path}")
        frame = pd.read_csv(path, encoding="utf-8-sig")
        if len(frame) != expected_rows:
            raise AssertionError(f"{filename}: {len(frame)} rows, expected {expected_rows}")
        frames[filename] = frame

    baseline = frames["material_absorption_baseline.csv"]
    sensitivity = frames["material_absorption_sensitivity.csv"]
    geometry = frames["screen_geometry_vertices.csv"]
    barrier = frames["barrier_il_by_receiver.csv"]
    summary = frames["barrier_il_summary.csv"]
    comparison = frames["s12_s20_comparison.csv"]
    overall = frames["overall_metrics.csv"]

    numeric_frames = [baseline, sensitivity, geometry, barrier, summary, comparison, overall]
    if any(not np.isfinite(frame.select_dtypes(include=[np.number]).to_numpy()).all() for frame in numeric_frames):
        raise AssertionError("NaN or Inf found")
    if not baseline["alpha"].between(0.0, 1.0).all() or not sensitivity["alpha"].between(0.0, 1.0).all():
        raise AssertionError("alpha outside [0,1]")
    if (barrier["path_difference_m"] < 0.0).any():
        raise AssertionError("negative path difference found")

    air = config["air"]
    material = config["miki_model"]
    validation = config["validation"]
    frequencies = np.asarray(config["frequencies_hz"], dtype=np.float64)
    independent_miki = miki_rigid_backed_absorption(
        frequencies,
        float(material["baseline_flow_resistivity_Pa_s_m2"]),
        float(material["porous_layer_thickness_m"]),
        float(air["air_density_kg_m3"]),
        float(air["speed_of_sound_m_s"]),
    )
    if not np.allclose(independent_miki["alpha"], baseline["alpha"], rtol=0.0, atol=1e-10):
        raise AssertionError("Baseline alpha does not reproduce")
    for frequency_text, expected in validation["miki_reference_alpha"].items():
        actual = float(baseline.loc[baseline["frequency_hz"] == int(frequency_text), "alpha"].iloc[0])
        assert_close(actual, float(expected), float(validation["miki_absolute_tolerance"]), f"Miki {frequency_text} Hz")

    test_N, test_il = kurze_anderson_insertion_loss(
        float(validation["kurze_test_delta_m"]),
        float(validation["kurze_test_frequency_hz"]),
        float(air["speed_of_sound_m_s"]),
    )
    assert_close(test_il, float(validation["kurze_expected_il_db"]), float(validation["kurze_tolerance_db"]), "Kurze test")

    screen = config["screen_common"]
    geometry_checks = {}
    for candidate, candidate_cfg in config["candidates"].items():
        candidate_geometry = geometry[geometry["candidate"] == candidate]
        if len(candidate_geometry) != 7:
            raise AssertionError(f"{candidate} does not have exactly 7 vertices")
        vertices_from_csv = candidate_geometry.sort_values("vertex_id")[["x", "y"]].to_numpy(dtype=np.float64)
        generated_vertices = generate_accordion_vertices(
            int(screen["number_of_panels"]),
            float(screen["panel_width_m"]),
            float(candidate_cfg["adjacent_turn_angle_deg"]),
        )
        if not np.allclose(vertices_from_csv, generated_vertices, rtol=0.0, atol=1e-10):
            raise AssertionError(f"{candidate} geometry CSV does not reproduce")
        geometry_checks[candidate] = validate_accordion_geometry(
            vertices_from_csv,
            int(screen["number_of_panels"]),
            float(screen["panel_width_m"]),
            float(candidate_cfg["adjacent_turn_angle_deg"]),
            float(validation["geometry_length_tolerance_m"]),
        )

    expected_frequencies = set(config["frequencies_hz"])
    expected_receivers = {receiver["id"] for receiver in config["receivers"]}
    for candidate in ("S12", "S20"):
        candidate_rows = barrier[barrier["candidate"] == candidate]
        if len(candidate_rows) != 50:
            raise AssertionError(f"{candidate} barrier row count is not 50")
        if set(candidate_rows["frequency_hz"]) != expected_frequencies:
            raise AssertionError(f"{candidate} frequency set mismatch")
        if set(candidate_rows["receiver_id"]) != expected_receivers:
            raise AssertionError(f"{candidate} receiver set mismatch")
        if not all(len(group) == 5 for _, group in candidate_rows.groupby("frequency_hz")):
            raise AssertionError(f"{candidate} does not have 5 receivers per frequency")

    # Recalculate every stored IL value from delta and the frozen formula.
    for row in barrier.itertuples(index=False):
        if bool(row.blocked):
            expected_N, expected_il = kurze_anderson_insertion_loss(
                float(row.path_difference_m), float(row.frequency_hz), float(air["speed_of_sound_m_s"])
            )
        else:
            expected_N, expected_il = 0.0, 0.0
        assert_close(float(row.fresnel_number), expected_N, 1e-9, "stored Fresnel number")
        assert_close(float(row.insertion_loss_db), expected_il, 1e-9, "stored IL")

    # Reconcile all summary statistics with the receiver-level table.
    for row in summary.itertuples(index=False):
        values = barrier[
            (barrier["candidate"] == row.candidate) & (barrier["frequency_hz"] == row.frequency_hz)
        ]["insertion_loss_db"].to_numpy(dtype=np.float64)
        expected_values = [np.mean(values), np.std(values, ddof=0), np.min(values), np.max(values), np.median(values)]
        actual_values = [row.mean_il_db, row.std_il_db, row.min_il_db, row.max_il_db, row.median_il_db]
        if not np.allclose(actual_values, expected_values, rtol=0.0, atol=1e-9):
            raise AssertionError(f"Summary mismatch for {row.candidate} {row.frequency_hz} Hz")

    for row in comparison.itertuples(index=False):
        assert_close(row.S12_minus_S20_db, row.S12_mean_il_db - row.S20_mean_il_db, 1e-9, "comparison difference")

    required_figures = [
        "material_absorption_baseline.png",
        "material_absorption_sensitivity.png",
        "s12_s20_top_view.png",
        "barrier_il_mean.png",
        "barrier_il_receiver_spread.png",
    ]
    figure_shapes = {}
    for filename in required_figures:
        path = FIGURES / filename
        if not path.is_file() or path.stat().st_size == 0:
            raise AssertionError(f"Missing figure: {path}")
        image = mpimg.imread(path)
        if image.size == 0:
            raise AssertionError(f"Unreadable figure: {path}")
        figure_shapes[filename] = list(image.shape)

    report_path = ROOT / "report" / "acoustic_evaluation_report_v1.md"
    report_text = report_path.read_text(encoding="utf-8-sig")
    required_report_terms = [
        "Analytical / Semi-empirical Acoustic Performance Evaluation",
        "a simplified dominant minimum-diffracted-path approximation",
        "No full-wave simulation",
        "Porous absorption and diffraction IL are reported separately",
        "# 16 Paper-ready Methods paragraph",
        "# 17 Paper-ready Results paragraph",
        "# 18 Discussion paragraph",
    ]
    if not all(term in report_text for term in required_report_terms):
        raise AssertionError("Report is missing one or more required sections/statements")

    source_checks = {}
    for candidate, candidate_cfg in config["candidates"].items():
        source = Path(candidate_cfg["source_file"])
        copy = ROOT / "source_designs" / f"{candidate}_{candidate_cfg['source_design']}.png"
        expected_hash = candidate_cfg["source_sha256"].lower()
        source_hash = sha256(source)
        copy_hash = sha256(copy)
        if source_hash != expected_hash or copy_hash != expected_hash:
            raise AssertionError(f"Source/copy protection check failed for {candidate}")
        source_checks[candidate] = {"source_sha256": source_hash, "copy_sha256": copy_hash}

    required_files = [
        ROOT / "config" / "engineering_translation_v1.md",
        ROOT / "config" / "method_references_v1.md",
        ROOT / "logs" / "acoustic_run_v1.log",
        report_path,
    ]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required_files):
        raise AssertionError("One or more required non-tabular artifacts are missing")

    result = {
        "status": "PASS",
        "csv_row_counts": expected_csv_rows,
        "miki_unit_test": {
            "125_hz_alpha": float(baseline.loc[baseline["frequency_hz"] == 125, "alpha"].iloc[0]),
            "500_hz_alpha": float(baseline.loc[baseline["frequency_hz"] == 500, "alpha"].iloc[0]),
            "1000_hz_alpha": float(baseline.loc[baseline["frequency_hz"] == 1000, "alpha"].iloc[0]),
        },
        "kurze_unit_test": {"fresnel_number": test_N, "insertion_loss_db": test_il},
        "geometry": geometry_checks,
        "nan_or_inf": False,
        "alpha_range": [float(sensitivity["alpha"].min()), float(sensitivity["alpha"].max())],
        "minimum_path_difference_m": float(barrier["path_difference_m"].min()),
        "figure_shapes": figure_shapes,
        "source_protection": source_checks,
        "all_outputs_verified": True,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

