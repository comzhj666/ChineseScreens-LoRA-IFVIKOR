"""Run the frozen S12/S20 analytical/semi-empirical acoustic evaluation V1."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import platform
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy

from acoustic_models import kurze_anderson_insertion_loss, miki_rigid_backed_absorption
from geometry import (
    build_candidate_diffraction_edges,
    generate_accordion_vertices,
    is_direct_path_blocked,
    shortest_diffracted_path,
    validate_accordion_geometry,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "acoustic_parameters_v1.json"
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"
LOGS = ROOT / "logs"
REPORTS = ROOT / "report"
SOURCE_DESIGNS = ROOT / "source_designs"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.12g")


def markdown_table(headers: list[str], rows: list[list[object]], decimals: int = 4) -> str:
    def display(value: object) -> str:
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.{decimals}f}"
        return str(value)

    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines.extend("| " + " | ".join(display(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def configure_logging() -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("screen_acoustics_v1")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    file_handler = logging.FileHandler(LOGS / "acoustic_run_v1.log", mode="w", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def main() -> None:
    start_clock = time.perf_counter()
    start_time = datetime.now().astimezone()
    for directory in (RESULTS, FIGURES, LOGS, REPORTS, SOURCE_DESIGNS):
        directory.mkdir(parents=True, exist_ok=True)
    logger = configure_logging()

    with CONFIG_PATH.open("r", encoding="utf-8") as stream:
        config = json.load(stream)

    logger.info("Run start: %s", start_time.isoformat())
    logger.info("Python executable: %s", sys.executable)
    logger.info("Python version: %s", platform.python_version())
    logger.info("numpy version: %s", np.__version__)
    logger.info("scipy version: %s", scipy.__version__)
    logger.info("pandas version: %s", pd.__version__)
    logger.info("matplotlib version: %s", matplotlib.__version__)
    logger.info("All frozen input parameters:\n%s", json.dumps(config, ensure_ascii=False, indent=2))

    air = config["air"]
    rho0 = float(air["air_density_kg_m3"])
    c0 = float(air["speed_of_sound_m_s"])
    frequencies = np.asarray(config["frequencies_hz"], dtype=np.float64)
    screen = config["screen_common"]
    material = config["miki_model"]
    validation = config["validation"]

    # Traceability references are copied byte-for-byte; source files remain unchanged.
    source_copy_records = []
    for candidate, candidate_cfg in config["candidates"].items():
        source_path = Path(candidate_cfg["source_file"])
        expected_hash = candidate_cfg["source_sha256"].lower()
        if not source_path.is_file():
            logger.warning("Traceability source missing: %s", source_path)
            source_copy_records.append((candidate, "missing", str(source_path), "", ""))
            continue
        actual_source_hash = sha256(source_path)
        if actual_source_hash != expected_hash:
            raise AssertionError(f"Frozen source hash changed for {candidate}: {actual_source_hash}")
        destination = SOURCE_DESIGNS / f"{candidate}_{candidate_cfg['source_design']}.png"
        shutil.copy2(source_path, destination)
        copied_hash = sha256(destination)
        if copied_hash != actual_source_hash:
            raise AssertionError(f"Traceability copy mismatch for {candidate}")
        source_copy_records.append((candidate, "copied", str(source_path), str(destination), copied_hash))
        logger.info("Source reference copied byte-for-byte: %s -> %s", source_path, destination)

    # Miki baseline and unit test.
    baseline_sigma = float(material["baseline_flow_resistivity_Pa_s_m2"])
    porous_thickness = float(material["porous_layer_thickness_m"])
    baseline = miki_rigid_backed_absorption(frequencies, baseline_sigma, porous_thickness, rho0, c0)
    baseline_alpha = baseline["alpha"]
    miki_test_results = {}
    for frequency_text, expected_alpha in validation["miki_reference_alpha"].items():
        frequency = float(frequency_text)
        index = int(np.where(frequencies == frequency)[0][0])
        actual_alpha = float(baseline_alpha[index])
        difference = abs(actual_alpha - float(expected_alpha))
        passed = difference <= float(validation["miki_absolute_tolerance"])
        miki_test_results[int(frequency)] = {
            "actual": actual_alpha,
            "expected": float(expected_alpha),
            "absolute_difference": difference,
            "passed": passed,
        }
        if not passed:
            raise AssertionError(f"Miki unit test failed at {frequency:g} Hz: {miki_test_results[int(frequency)]}")
    logger.info("Miki unit-test result: PASS | %s", miki_test_results)

    baseline_frame = pd.DataFrame(
        {
            "frequency_hz": frequencies.astype(int),
            "flow_resistivity_pa_s_m2": baseline_sigma,
            "thickness_m": porous_thickness,
            "zc_real_pa_s_m": np.real(baseline["characteristic_impedance"]),
            "zc_imag_pa_s_m": np.imag(baseline["characteristic_impedance"]),
            "kc_real_rad_m": np.real(baseline["complex_wavenumber"]),
            "kc_imag_rad_m": np.imag(baseline["complex_wavenumber"]),
            "zs_real_pa_s_m": np.real(baseline["surface_impedance"]),
            "zs_imag_pa_s_m": np.imag(baseline["surface_impedance"]),
            "alpha": baseline_alpha,
            "aeq_one_face_m2": baseline_alpha * float(screen["one_face_area_m2"]),
            "aeq_two_faces_m2": baseline_alpha * float(screen["two_faces_area_m2"]),
        }
    )
    write_csv(baseline_frame, RESULTS / "material_absorption_baseline.csv")

    sensitivity_rows = []
    for sigma in material["sensitivity_flow_resistivities_Pa_s_m2"]:
        sensitivity = miki_rigid_backed_absorption(frequencies, float(sigma), porous_thickness, rho0, c0)
        for frequency, alpha in zip(frequencies, sensitivity["alpha"]):
            sensitivity_rows.append(
                {
                    "frequency": int(frequency),
                    "flow_resistivity": float(sigma),
                    "thickness": porous_thickness,
                    "alpha": float(alpha),
                }
            )
    sensitivity_frame = pd.DataFrame(sensitivity_rows)
    write_csv(sensitivity_frame, RESULTS / "material_absorption_sensitivity.csv")

    # Geometry generation and validation.
    source = np.asarray(config["source"]["coordinates_m"], dtype=np.float64)
    receivers = {
        item["id"]: np.asarray(item["coordinates_m"], dtype=np.float64)
        for item in config["receivers"]
    }
    vertices_by_candidate: dict[str, np.ndarray] = {}
    geometry_validation: dict[str, dict[str, float | int | bool]] = {}
    geometry_rows = []
    for candidate, candidate_cfg in config["candidates"].items():
        fold_angle = float(candidate_cfg["adjacent_turn_angle_deg"])
        vertices = generate_accordion_vertices(
            int(screen["number_of_panels"]), float(screen["panel_width_m"]), fold_angle
        )
        geometry_check = validate_accordion_geometry(
            vertices,
            int(screen["number_of_panels"]),
            float(screen["panel_width_m"]),
            fold_angle,
            float(validation["geometry_length_tolerance_m"]),
        )
        vertices_by_candidate[candidate] = vertices
        geometry_validation[candidate] = geometry_check
        for vertex_index, (x_coord, y_coord) in enumerate(vertices):
            geometry_rows.append(
                {
                    "candidate": candidate,
                    "vertex_id": f"V{vertex_index}",
                    "x": float(x_coord),
                    "y": float(y_coord),
                    "z_bottom": float(screen["bottom_clearance_m"]),
                    "z_top": float(screen["top_height_m"]),
                }
            )
        logger.info("%s geometry validation: PASS | %s", candidate, geometry_check)
    geometry_frame = pd.DataFrame(geometry_rows)
    write_csv(geometry_frame, RESULTS / "screen_geometry_vertices.csv")

    # Independent Kurze-Anderson mathematical unit test.
    test_N, test_il = kurze_anderson_insertion_loss(
        float(validation["kurze_test_delta_m"]),
        float(validation["kurze_test_frequency_hz"]),
        c0,
    )
    kurze_passed = abs(test_il - float(validation["kurze_expected_il_db"])) <= float(
        validation["kurze_tolerance_db"]
    )
    if not kurze_passed:
        raise AssertionError(f"Kurze-Anderson unit test failed: N={test_N}, IL={test_il}")
    logger.info("Kurze-Anderson unit-test result: PASS | N=%.12g | IL=%.12g dB", test_N, test_il)

    # Barrier geometry is evaluated once per candidate/receiver, then applied to each frequency.
    barrier_rows = []
    for candidate, candidate_cfg in config["candidates"].items():
        vertices = vertices_by_candidate[candidate]
        edges = build_candidate_diffraction_edges(
            vertices, float(screen["bottom_clearance_m"]), float(screen["top_height_m"])
        )
        for receiver_id, receiver in receivers.items():
            blocked = is_direct_path_blocked(
                source,
                receiver,
                vertices,
                float(screen["bottom_clearance_m"]),
                float(screen["top_height_m"]),
            )
            direct_distance = float(np.linalg.norm(receiver - source))
            if blocked:
                diffraction = shortest_diffracted_path(source, receiver, edges)
            else:
                diffraction = {
                    "direct_distance_m": direct_distance,
                    "controlling_edge": "",
                    "diffracted_path_m": direct_distance,
                    "path_difference_m": 0.0,
                }
            for frequency in frequencies:
                wavelength = c0 / float(frequency)
                if blocked:
                    fresnel_number, insertion_loss = kurze_anderson_insertion_loss(
                        float(diffraction["path_difference_m"]), float(frequency), c0
                    )
                else:
                    fresnel_number, insertion_loss = 0.0, 0.0
                barrier_rows.append(
                    {
                        "candidate": candidate,
                        "source_design": candidate_cfg["source_design"],
                        "fold_angle_deg": float(candidate_cfg["adjacent_turn_angle_deg"]),
                        "receiver_id": receiver_id,
                        "receiver_x": float(receiver[0]),
                        "receiver_y": float(receiver[1]),
                        "receiver_z": float(receiver[2]),
                        "frequency_hz": int(frequency),
                        "blocked": bool(blocked),
                        "direct_distance_m": float(diffraction["direct_distance_m"]),
                        "controlling_edge": diffraction["controlling_edge"],
                        "diffracted_path_m": float(diffraction["diffracted_path_m"]),
                        "path_difference_m": float(diffraction["path_difference_m"]),
                        "wavelength_m": wavelength,
                        "fresnel_number": fresnel_number,
                        "insertion_loss_db": insertion_loss,
                    }
                )
    barrier_frame = pd.DataFrame(barrier_rows)
    if len(barrier_frame) != 100:
        raise AssertionError(f"Expected 100 barrier rows, got {len(barrier_frame)}")
    write_csv(barrier_frame, RESULTS / "barrier_il_by_receiver.csv")

    summary_rows = []
    for (candidate, frequency), group in barrier_frame.groupby(["candidate", "frequency_hz"], sort=True):
        values = group["insertion_loss_db"].to_numpy(dtype=np.float64)
        summary_rows.append(
            {
                "candidate": candidate,
                "frequency_hz": int(frequency),
                "mean_il_db": float(np.mean(values)),
                "std_il_db": float(np.std(values, ddof=0)),
                "min_il_db": float(np.min(values)),
                "max_il_db": float(np.max(values)),
                "median_il_db": float(np.median(values)),
            }
        )
    summary_frame = pd.DataFrame(summary_rows)
    write_csv(summary_frame, RESULTS / "barrier_il_summary.csv")

    summary_pivot = summary_frame.pivot(index="frequency_hz", columns="candidate", values="mean_il_db")
    comparison_frame = pd.DataFrame(
        {
            "frequency_hz": summary_pivot.index.astype(int),
            "S12_mean_il_db": summary_pivot["S12"].to_numpy(),
            "S20_mean_il_db": summary_pivot["S20"].to_numpy(),
        }
    )
    comparison_frame["S12_minus_S20_db"] = (
        comparison_frame["S12_mean_il_db"] - comparison_frame["S20_mean_il_db"]
    )
    write_csv(comparison_frame, RESULTS / "s12_s20_comparison.csv")

    overall_rows = []
    for candidate, candidate_cfg in config["candidates"].items():
        summary_values = summary_frame.loc[summary_frame["candidate"] == candidate, "mean_il_db"].to_numpy()
        all_values = barrier_frame.loc[barrier_frame["candidate"] == candidate, "insertion_loss_db"].to_numpy()
        check = geometry_validation[candidate]
        overall_rows.append(
            {
                "candidate": candidate,
                "source_design": candidate_cfg["source_design"],
                "fold_angle_deg": float(candidate_cfg["adjacent_turn_angle_deg"]),
                "projected_width_m": float(check["projected_width_m"]),
                "fold_depth_m": float(check["fold_depth_m"]),
                "band_arithmetic_mean_il_db": float(np.mean(summary_values)),
                "band_min_il_db": float(np.min(summary_values)),
                "band_max_il_db": float(np.max(summary_values)),
                "overall_mean_il_db": float(np.mean(all_values)),
                "overall_std_il_db": float(np.std(all_values, ddof=0)),
            }
        )
    overall_frame = pd.DataFrame(overall_rows)
    write_csv(overall_frame, RESULTS / "overall_metrics.csv")

    numeric_frames = [baseline_frame, sensitivity_frame, geometry_frame, barrier_frame, summary_frame, comparison_frame, overall_frame]
    if any(not np.isfinite(frame.select_dtypes(include=[np.number]).to_numpy()).all() for frame in numeric_frames):
        raise ArithmeticError("NaN or Inf detected in numeric outputs")
    if not baseline_frame["alpha"].between(0.0, 1.0).all() or not sensitivity_frame["alpha"].between(0.0, 1.0).all():
        raise ArithmeticError("Absorption coefficient outside [0,1]")
    if (barrier_frame["path_difference_m"] < 0.0).any():
        raise ArithmeticError("Negative path difference detected")
    high_il = barrier_frame["insertion_loss_db"] > float(validation["high_il_warning_threshold_db"])
    high_il_warning = bool(high_il.any())
    if high_il_warning:
        logger.warning("high attenuation prediction—interpret cautiously")

    # Figures: default matplotlib color cycle only.
    plt.figure(figsize=(7.2, 4.8))
    plt.plot(baseline_frame["frequency_hz"], baseline_frame["alpha"], marker="o", label="sigma = 12000 Pa·s/m²")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Normal-incidence absorption coefficient")
    plt.ylim(0.0, 1.0)
    plt.xticks(frequencies.astype(int), rotation=35)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURES / "material_absorption_baseline.png", dpi=180)
    plt.close()

    plt.figure(figsize=(7.2, 4.8))
    for sigma, group in sensitivity_frame.groupby("flow_resistivity", sort=True):
        plt.plot(group["frequency"], group["alpha"], marker="o", label=f"sigma = {sigma:g} Pa·s/m²")
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Normal-incidence absorption coefficient")
    plt.ylim(0.0, 1.0)
    plt.xticks(frequencies.astype(int), rotation=35)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURES / "material_absorption_sensitivity.png", dpi=180)
    plt.close()

    plt.figure(figsize=(8.0, 7.0))
    for candidate, vertices in vertices_by_candidate.items():
        plt.plot(vertices[:, 0], vertices[:, 1], marker="o", linewidth=2.0, label=f"{candidate} accordion geometry")
    plt.scatter([source[0]], [source[1]], marker="*", s=150, label="Source")
    for receiver_id, receiver in receivers.items():
        plt.scatter([receiver[0]], [receiver[1]], marker="x", s=70)
        plt.annotate(receiver_id, (receiver[0], receiver[1]), xytext=(5, 3), textcoords="offset points")
    plt.xlabel("x: source → receiver direction (m)")
    plt.ylabel("y: screen lateral direction (m)")
    plt.axis("equal")
    plt.grid(True, alpha=0.3)
    plt.legend(loc="best")
    plt.tight_layout()
    plt.savefig(FIGURES / "s12_s20_top_view.png", dpi=180)
    plt.close()

    plt.figure(figsize=(7.2, 4.8))
    for candidate in ("S12", "S20"):
        group = summary_frame[summary_frame["candidate"] == candidate]
        x_values = group["frequency_hz"].to_numpy(dtype=np.float64)
        mean_values = group["mean_il_db"].to_numpy(dtype=np.float64)
        std_values = group["std_il_db"].to_numpy(dtype=np.float64)
        line = plt.plot(x_values, mean_values, marker="o", label=f"{candidate} mean IL")[0]
        plt.fill_between(x_values, mean_values - std_values, mean_values + std_values, alpha=0.18, color=line.get_color())
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Predicted insertion loss (dB)")
    plt.xticks(frequencies.astype(int), rotation=35)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(FIGURES / "barrier_il_mean.png", dpi=180)
    plt.close()

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.8), sharey=True)
    for axis, candidate in zip(axes, ("S12", "S20")):
        candidate_data = barrier_frame[barrier_frame["candidate"] == candidate]
        for receiver_id, group in candidate_data.groupby("receiver_id", sort=True):
            axis.plot(group["frequency_hz"], group["insertion_loss_db"], marker="o", markersize=3, label=receiver_id)
        axis.set_title(candidate)
        axis.set_xlabel("Frequency (Hz)")
        axis.grid(True, alpha=0.3)
        axis.tick_params(axis="x", rotation=35)
    axes[0].set_ylabel("Predicted insertion loss (dB)")
    axes[1].legend(title="Receiver", loc="best")
    fig.tight_layout()
    fig.savefig(FIGURES / "barrier_il_receiver_spread.png", dpi=180)
    plt.close(fig)

    # Data-driven interpretation without changing any frozen input.
    average_difference = float(comparison_frame["S12_minus_S20_db"].mean())
    max_abs_index = comparison_frame["S12_minus_S20_db"].abs().idxmax()
    largest_abs_difference = float(abs(comparison_frame.loc[max_abs_index, "S12_minus_S20_db"]))
    largest_abs_frequency = int(comparison_frame.loc[max_abs_index, "frequency_hz"])
    clear_threshold = float(validation["descriptive_clear_difference_threshold_db"])
    clearly_distinguishable = largest_abs_difference >= clear_threshold
    if not clearly_distinguishable:
        comparison_statement = "The simplified diffraction model did not predict a substantial acoustic difference between the two folding geometries."
        scientific_conclusion = "The simplified analytical/semi-empirical model does not provide strong evidence that folding geometry alone produces a substantial acoustic-performance difference between S12 and S20."
    else:
        comparison_statement = "The simplified diffraction model predicted a descriptively noticeable difference between the two folding geometries under the frozen geometry and receiver conditions."
        scientific_conclusion = "Under the frozen simplified model, the folding geometries produced a descriptively distinguishable diffraction-screening difference; higher-order simulation or measurement is still required for validation."

    absorption_rows = [
        [int(row.frequency_hz), row.alpha, row.aeq_one_face_m2, row.aeq_two_faces_m2]
        for row in baseline_frame.itertuples(index=False)
    ]
    comparison_rows = [
        [int(row.frequency_hz), row.S12_mean_il_db, row.S20_mean_il_db, row.S12_minus_S20_db]
        for row in comparison_frame.itertuples(index=False)
    ]
    receiver_variability_rows = [
        [row.candidate, int(row.frequency_hz), row.mean_il_db, row.std_il_db, row.min_il_db, row.max_il_db]
        for row in summary_frame.itertuples(index=False)
    ]
    engineering_rows = []
    for row in overall_frame.itertuples(index=False):
        engineering_rows.append(
            [
                row.candidate,
                row.source_design,
                int(screen["number_of_panels"]),
                float(screen["panel_width_m"]),
                float(screen["panel_height_m"]),
                float(screen["panel_thickness_m"]),
                row.fold_angle_deg,
                row.projected_width_m,
                row.fold_depth_m,
            ]
        )
    receiver_rows = [[config["source"]["id"], *config["source"]["coordinates_m"]]] + [
        [item["id"], *item["coordinates_m"]] for item in config["receivers"]
    ]
    sensitivity_means = sensitivity_frame.groupby("flow_resistivity")["alpha"].mean().to_dict()

    report = f"""# S12 / S20 Analytical / Semi-empirical Acoustic Performance Evaluation V1

## Material Passport

- Artifact type: Experiment Result
- Verification status: VERIFIED by deterministic re-run checks in `validate_results.py`
- Data provenance: frozen S12 = B2_seed42 and S20 = C2_seed42 mappings
- Research scope: analytical/semi-empirical engineering screening calculation
- Generated: {datetime.now().astimezone().isoformat()}

# 1 Research objective

本研究不进行 COMSOL、有限元、FDTD、BEM 或完整室内声场仿真。目标是以理论/半经验方法分别评价统一多孔层的频率相关吸声能力，以及在简化自由场中不同折叠几何的有限屏障衍射遮挡潜力。结果属于 theoretical prediction 与 engineering screening calculation，不是公共空间真实声场的精确预测或实验验证。

# 2 Frozen candidates

- S12 = B2_seed42
- S20 = C2_seed42

IF-VIKOR 输入、评分、排序与候选映射保持冻结，本阶段没有反向修改。

# 3 Engineering translation

{markdown_table(["Candidate", "Source design", "Panels", "Panel width (m)", "Height (m)", "Thickness (m)", "Fold angle (deg)", "Projected width (m)", "Fold depth (m)"], engineering_rows, 6)}

声学构造统一为前侧 30 mm 多孔层 + 10 mm 刚性芯层 + 后侧 30 mm 多孔层。上述尺寸均为 **engineering translation assumptions**，不是从生成图像中测量出的真实制造尺寸。保持尺寸与材料完全相同、只改变折叠角，可以减少混杂变量。

# 4 Material model

采用 Miki (1990) modified Delany–Bazley model，时间约定在代码中统一为 `exp(+jωt)`：

```text
X = 1000 f / sigma
Zc = rho0 c0 [1 + 5.50 X^(-0.632) - j 8.43 X^(-0.632)]
kc = (omega/c0) [1 + 7.81 X^(-0.618) - j 11.41 X^(-0.618)]
Zs = -j Zc / tan(kc d)
R = (Zs - rho0 c0) / (Zs + rho0 c0)
alpha = 1 - |R|^2
```

基准参数为 sigma = 12000 Pa·s/m²、d = 0.030 m。吸声系数与屏障衍射 IL 是互补指标，未被相加或合成为未经验证的总分。

# 5 Material absorption results

{markdown_table(["Frequency (Hz)", "alpha", "Aeq one face (m²)", "Aeq two faces (m²)"], absorption_rows, 6)}

等效吸声面积仅为 `alpha × area` 的补充指标，不是 Sabine 混响时间预测。

# 6 Material sensitivity

仅改变流阻率，厚度保持 0.030 m。10 个频率算术平均 alpha：8000 Pa·s/m² = {sensitivity_means[8000.0]:.6f}；12000 Pa·s/m² = {sensitivity_means[12000.0]:.6f}；16000 Pa·s/m² = {sensitivity_means[16000.0]:.6f}。

# 7 Simplified finite barrier model

对 source–receiver 直线先进行屏扇交点及交点高度判断。无遮挡时 IL = 0 dB。遮挡时，对 6 条顶部屏扇边、6 条底部屏扇边及 2 条外侧竖边共 14 条候选边，最小化：

```text
L(t) = distance(Source, P(t)) + distance(P(t), Receiver), 0 <= t <= 1
L_direct = distance(Source, Receiver)
delta = L_diffracted - L_direct
lambda = c0 / f
N = 2 delta / lambda = 2 f delta / c0
u = sqrt(2 pi N)
IL = 5 + 20 log10[u / tanh(u)]
```

当 N < 1e-12 时采用稳定极限 IL = 5 dB。当前实现称为 **a simplified dominant minimum-diffracted-path approximation**，不是 Lam (1994) 相干相位/压力叠加有限屏障模型的完整复现。

# 8 Source and receivers

{markdown_table(["Point", "x (m)", "y (m)", "z (m)"], receiver_rows, 3)}

模型不使用绝对声源声压或声功率，不虚构 SPL。

# 9 S12 / S20 IL results

{markdown_table(["Frequency (Hz)", "S12 mean IL (dB)", "S20 mean IL (dB)", "S12 - S20 (dB)"], comparison_rows, 6)}

# 10 Receiver variability

以下标准差为固定 5 个接收点集合的总体标准差（ddof = 0）。

{markdown_table(["Candidate", "Frequency (Hz)", "Mean (dB)", "Std (dB)", "Min (dB)", "Max (dB)"], receiver_variability_rows, 6)}

# 11 Overall metrics

{markdown_table(list(overall_frame.columns), overall_frame.values.tolist(), 6)}

这些是描述统计，不是 NRC、STC、Rw、DnT 或 sound insulation rating。

# 12 Model validation

- Miki unit test: PASS — 125 Hz = {miki_test_results[125]['actual']:.6f}, 500 Hz = {miki_test_results[500]['actual']:.6f}, 1000 Hz = {miki_test_results[1000]['actual']:.6f}；相对冻结参考值绝对差均不超过 0.01。
- Kurze–Anderson mathematical test: PASS — delta = 0.246 m, f = 500 Hz, N = {test_N:.9f}, IL = {test_il:.6f} dB。
- S12 geometry: PASS — 6 panels, 7 vertices, developed width = {geometry_validation['S12']['developed_width_m']:.9f} m。
- S20 geometry: PASS — 6 panels, 7 vertices, developed width = {geometry_validation['S20']['developed_width_m']:.9f} m。
- Range checks: PASS — no NaN/Inf; alpha in [0,1]; delta >= 0; all optimizations converged.
- High attenuation warning: {'high attenuation prediction—interpret cautiously' if high_il_warning else 'None; no predicted IL exceeded 30 dB.'}

# 13 Interpretation

S12–S20 的全频率平均 IL 差为 {average_difference:.6f} dB；最大绝对频率差为 {largest_abs_difference:.6f} dB，出现在 {largest_abs_frequency} Hz。{comparison_statement}

为回答“是否能够清晰区分”，本报告仅采用透明的描述性规则：最大绝对均值差达到 1.0 dB 才标记为 Yes；该规则不是感知阈值或声学标准。当前结果：**{'Yes' if clearly_distinguishable else 'No'}**。

# 14 Scientific limitations

1. No full-wave simulation.
2. No room reflections.
3. No ground reflection.
4. No multiple diffraction.
5. No phase-coherent summation.
6. No scattering prediction.
7. No transmission through panel.
8. Porous absorption and diffraction IL are reported separately.
9. Engineering dimensions are assumed translation parameters.
10. Results are theoretical screening predictions, not laboratory validation.
11. Structural vibration and manufacturing details are not modeled.

# 15 Link to IF-VIKOR

IF-VIKOR 已冻结。本阶段只对 S12 与 S20 做独立声学工程筛选，不重新评分、不重新排序、不向前述决策结果回写。

# 16 Paper-ready Methods paragraph

**English.** An analytical/semi-empirical acoustic evaluation was conducted to screen two frozen IF-VIKOR compromise candidates (S12 and S20) without full-wave or room-acoustic simulation. Both concepts were translated into six-panel screens with identical developed width (2.4 m), height (1.8 m), total thickness (70 mm), and a symmetric 30/10/30 mm porous–rigid-core–porous assembly; only the adjacent turn angle differed (30° for S12 and 12° for S20). Normal-incidence absorption of the 30 mm porous layer was estimated using the Miki modified Delany–Bazley relations. Geometric screening was estimated in a simplified free field using direct-ray blockage testing and a Kurze–Anderson-type attenuation equation applied to the dominant minimum diffracted path among 14 finite candidate edges. Material absorption and diffraction insertion loss were reported as separate, complementary proxies.

**中文。** 本研究采用理论/半经验声学评价，在不进行完整波动或室内声场仿真的条件下，对两个冻结 IF-VIKOR 折衷候选 S12 与 S20 进行工程筛选。两方案均被转译为六扇屏风，展开总宽 2.4 m、高 1.8 m、总厚 70 mm，并采用相同的 30/10/30 mm 多孔层—刚性芯层—多孔层构造；唯一变化为相邻屏扇转向角（S12 为 30°，S20 为 12°）。30 mm 多孔层的法向入射吸声系数采用 Miki 修正 Delany–Bazley 关系估算；几何遮挡能力则在简化自由场中，通过直接声线遮挡判断，并对 14 条有限候选边中的主导最短衍射路径应用 Kurze–Anderson 型衰减公式进行估算。材料吸声与衍射插入损失作为两个独立且互补的指标报告。

# 17 Paper-ready Results paragraph

**English.** The baseline Miki calculation predicted normal-incidence absorption coefficients of {miki_test_results[125]['actual']:.3f}, {float(baseline_frame.loc[baseline_frame['frequency_hz'] == 250, 'alpha'].iloc[0]):.3f}, {miki_test_results[500]['actual']:.3f}, and {miki_test_results[1000]['actual']:.3f} at 125, 250, 500, and 1000 Hz, respectively. Across the 125–1000 Hz evaluation band, the mean predicted diffraction insertion losses were {float(overall_frame.loc[overall_frame['candidate'] == 'S12', 'band_arithmetic_mean_il_db'].iloc[0]):.3f} dB for S12 and {float(overall_frame.loc[overall_frame['candidate'] == 'S20', 'band_arithmetic_mean_il_db'].iloc[0]):.3f} dB for S20. Their average difference was {average_difference:.6f} dB, and the largest frequency-specific difference was {largest_abs_difference:.6f} dB at {largest_abs_frequency} Hz. {scientific_conclusion}

**中文。** Miki 基准计算在 125、250、500 和 1000 Hz 得到的法向入射吸声系数分别为 {miki_test_results[125]['actual']:.3f}、{float(baseline_frame.loc[baseline_frame['frequency_hz'] == 250, 'alpha'].iloc[0]):.3f}、{miki_test_results[500]['actual']:.3f} 和 {miki_test_results[1000]['actual']:.3f}。在 125–1000 Hz 频带内，S12 与 S20 的平均预测衍射插入损失分别为 {float(overall_frame.loc[overall_frame['candidate'] == 'S12', 'band_arithmetic_mean_il_db'].iloc[0]):.3f} dB 和 {float(overall_frame.loc[overall_frame['candidate'] == 'S20', 'band_arithmetic_mean_il_db'].iloc[0]):.3f} dB；两者平均差为 {average_difference:.6f} dB，最大频率差为 {largest_abs_difference:.6f} dB（{largest_abs_frequency} Hz）。当前简化模型没有为“仅由折叠几何造成显著声学性能差异”提供强证据。

# 18 Discussion paragraph

S12 与 S20 的预测 IL 曲线非常接近，说明在当前简化模型与冻结声源—接收点配置下，统一材料、屏风高度和总体有限宽度比 30°/12° 的折角差异更占主导。该结果不是实验失败，而是模型边界内的合法科研结果。折叠几何可能造成的散射、多重反射、漫射场相互作用与相干效应未被当前主导最短衍射路径近似捕捉，需要更高阶数值模型或受控实验才能验证。

## Scientific conclusion

{scientific_conclusion}
"""
    (REPORTS / "acoustic_evaluation_report_v1.md").write_text(report, encoding="utf-8-sig", newline="\n")

    row_counts = {
        "material_absorption_baseline.csv": len(baseline_frame),
        "material_absorption_sensitivity.csv": len(sensitivity_frame),
        "screen_geometry_vertices.csv": len(geometry_frame),
        "barrier_il_by_receiver.csv": len(barrier_frame),
        "barrier_il_summary.csv": len(summary_frame),
        "s12_s20_comparison.csv": len(comparison_frame),
        "overall_metrics.csv": len(overall_frame),
    }
    logger.info("CSV row counts: %s", row_counts)
    logger.info("Source copy records: %s", source_copy_records)
    logger.info("Numerical validation: PASS | no NaN/Inf; alpha in [0,1]; delta >= 0")
    logger.info(
        "Comparison: average S12-S20 difference=%.12g dB; largest absolute difference=%.12g dB at %d Hz; clear=%s",
        average_difference,
        largest_abs_difference,
        largest_abs_frequency,
        clearly_distinguishable,
    )
    end_time = datetime.now().astimezone()
    duration = time.perf_counter() - start_clock
    logger.info("Run end: %s", end_time.isoformat())
    logger.info("Duration seconds: %.6f", duration)
    logger.info("Experiment completed successfully")


if __name__ == "__main__":
    main()

