#!/usr/bin/env python3
"""
Exact IF-VIKOR reproduction for the Chinese folding-screen study.

Reproduces the frozen analysis from the five anonymized evaluator CSV files:
- predefined 1–5 -> intuitionistic fuzzy mapping
- IFWA group aggregation
- equal-expert/equal-criterion primary IF-VIKOR, v=0.50
- classical compromise conditions
- intuitionistic-fuzzy entropy sensitivity weights
- four expert/criterion weighting combinations
- v sensitivity (0.25, 0.50, 0.75)
- three-component (mu, nu, pi) distance sensitivity
- ICC(2,k), absolute agreement, average measures, k=5,
  with 20,000 candidate-level bootstrap resamples, seed=42

This script does not alter any input ratings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr


EVALUATORS = ["E01", "E02", "E03", "E04", "E05"]
CRITERIA = ["C1", "C2", "C3", "C4", "C5"]
CANDIDATES = [f"S{i:02d}" for i in range(1, 31)]

RATING_TO_IFN = {
    1: (0.15, 0.80),
    2: (0.25, 0.65),
    3: (0.50, 0.40),
    4: (0.75, 0.15),
    5: (0.85, 0.10),
}

EXPECTED_SHA256 = {
    "E01_scores.csv": "7b17258aaf435c93159d0968ffc1cf464b9a9f2758109972436449941576c6b1",
    "E02_scores.csv": "d3317e97e9331de0576ff54db2d730b85f01c9bdf98bc3c6becc55499577c508",
    "E03_scores.csv": "6e051d104de7514400abeaa3c9df02e82cca954d878e9577d83ac09903525c08",
    "E04_scores.csv": "4b4953db151694337542d27d7c58cd8fcc55f3b330e567ba1047c953d2851e60",
    "E05_scores.csv": "18325d9e4c8554e07c378bf1bd3e57c10b5bf41f26bf3c690edb460b3c3f9584",
}

EXPECTED_PRIMARY_TOP = [
    ("S12", 0.135856, 0.092949, 0.067789),
    ("S20", 0.252250, 0.076159, 0.096224),
    ("S28", 0.261728, 0.111107, 0.245159),
    ("S07", 0.394066, 0.117178, 0.379076),
    ("S01", 0.204599, 0.159744, 0.394301),
]

EXPECTED_ENTROPY_CRITERION_WEIGHTS = np.array(
    [0.310928, 0.223869, 0.155124, 0.183984, 0.126095], dtype=float
)
EXPECTED_ENTROPY_EXPERT_WEIGHTS = np.array(
    [0.200550, 0.168673, 0.240675, 0.159859, 0.230243], dtype=float
)
EXPECTED_ICC = np.array([0.578, 0.556, 0.499, 0.617, 0.255], dtype=float)
EXPECTED_ICC_CI = np.array([
    [0.193, 0.738],
    [0.240, 0.700],
    [0.259, 0.646],
    [0.278, 0.758],
    [-0.049, 0.445],
], dtype=float)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_inputs(data_dir: Path, strict_hash: bool = False):
    frames = []
    hash_rows = []

    for evaluator in EVALUATORS:
        path = data_dir / f"{evaluator}_scores.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing input: {path}")

        digest = sha256_file(path)
        expected = EXPECTED_SHA256[path.name]
        hash_match = digest == expected
        hash_rows.append({
            "evaluator": evaluator,
            "file": path.name,
            "sha256": digest,
            "expected_sha256": expected,
            "match": hash_match,
        })
        if strict_hash and not hash_match:
            raise ValueError(
                f"SHA256 mismatch for {path.name}. "
                "Use the frozen source CSV bytes or omit --strict-hash."
            )

        df = pd.read_csv(path)
        required = ["candidate_id", *CRITERIA]
        if list(df.columns) != required:
            raise ValueError(f"{path.name}: expected columns {required}, got {list(df.columns)}")
        if df["candidate_id"].duplicated().any():
            raise ValueError(f"{path.name}: duplicate candidate_id")
        if set(df["candidate_id"]) != set(CANDIDATES):
            raise ValueError(f"{path.name}: candidate IDs must be S01-S30 exactly")

        df = df.set_index("candidate_id").loc[CANDIDATES].reset_index()
        for c in CRITERIA:
            if df[c].isna().any():
                raise ValueError(f"{path.name}: missing value in {c}")
            vals = df[c].to_numpy()
            if not np.all(np.equal(vals, np.round(vals))):
                raise ValueError(f"{path.name}: non-integer rating in {c}")
            if not np.all((vals >= 1) & (vals <= 5)):
                raise ValueError(f"{path.name}: rating outside 1-5 in {c}")
        frames.append(df)

    scores = np.stack([df[CRITERIA].to_numpy(dtype=int) for df in frames], axis=0)  # K x m x n

    mapping_path = data_dir / "candidate_mapping.csv"
    mapping = pd.read_csv(mapping_path) if mapping_path.exists() else pd.DataFrame({
        "candidate_id": CANDIDATES,
        "original_id": [""] * len(CANDIDATES),
    })
    if set(mapping["candidate_id"]) != set(CANDIDATES):
        raise ValueError("candidate_mapping.csv must contain S01-S30 exactly")
    mapping = mapping.set_index("candidate_id").loc[CANDIDATES].reset_index()

    return scores, pd.DataFrame(hash_rows), mapping


def ratings_to_ifn(scores: np.ndarray):
    mu_lut = np.array([np.nan, 0.15, 0.25, 0.50, 0.75, 0.85])
    nu_lut = np.array([np.nan, 0.80, 0.65, 0.40, 0.15, 0.10])
    mu = mu_lut[scores]
    nu = nu_lut[scores]
    hesitation = 1.0 - mu - nu
    return mu, nu, hesitation


def ifwa(mu: np.ndarray, nu: np.ndarray, evaluator_weights: np.ndarray):
    evaluator_weights = np.asarray(evaluator_weights, dtype=float)
    if evaluator_weights.shape != (len(EVALUATORS),):
        raise ValueError("Evaluator weights must have length 5")
    if not np.isclose(evaluator_weights.sum(), 1.0):
        raise ValueError("Evaluator weights must sum to 1")

    w = evaluator_weights[:, None, None]
    group_mu = 1.0 - np.prod((1.0 - mu) ** w, axis=0)
    group_nu = np.prod(nu ** w, axis=0)
    group_pi = 1.0 - group_mu - group_nu
    return group_mu, group_nu, group_pi


def distance_two_component(mu1, nu1, mu2, nu2):
    return np.sqrt(((mu1 - mu2) ** 2 + (nu1 - nu2) ** 2) / 2.0)


def distance_three_component(mu1, nu1, pi1, mu2, nu2, pi2):
    # Frozen sensitivity definition intentionally divides by 2, matching the frozen report.
    return np.sqrt(
        ((mu1 - mu2) ** 2 + (nu1 - nu2) ** 2 + (pi1 - pi2) ** 2) / 2.0
    )


def normalized_distances(group_mu, group_nu, distance_mode="two"):
    group_pi = 1.0 - group_mu - group_nu

    # All five criteria are benefit criteria.
    pos_mu = group_mu.max(axis=0)
    pos_nu = group_nu.min(axis=0)
    pos_pi = 1.0 - pos_mu - pos_nu

    neg_mu = group_mu.min(axis=0)
    neg_nu = group_nu.max(axis=0)
    neg_pi = 1.0 - neg_mu - neg_nu

    if distance_mode == "two":
        denom = distance_two_component(pos_mu, pos_nu, neg_mu, neg_nu)
        numer = distance_two_component(
            pos_mu[None, :], pos_nu[None, :], group_mu, group_nu
        )
    elif distance_mode == "three":
        denom = distance_three_component(
            pos_mu, pos_nu, pos_pi, neg_mu, neg_nu, neg_pi
        )
        numer = distance_three_component(
            pos_mu[None, :], pos_nu[None, :], pos_pi[None, :],
            group_mu, group_nu, group_pi
        )
    else:
        raise ValueError("distance_mode must be 'two' or 'three'")

    if np.any(denom <= 0):
        raise ValueError("At least one criterion has zero ideal-solution distance")

    D = numer / denom[None, :]
    ideals = {
        "positive": (pos_mu, pos_nu, pos_pi),
        "negative": (neg_mu, neg_nu, neg_pi),
    }
    return D, ideals


def vikor(D: np.ndarray, criterion_weights: np.ndarray, v: float):
    criterion_weights = np.asarray(criterion_weights, dtype=float)
    if criterion_weights.shape != (len(CRITERIA),):
        raise ValueError("Criterion weights must have length 5")
    if not np.isclose(criterion_weights.sum(), 1.0):
        raise ValueError("Criterion weights must sum to 1")
    if not (0.0 <= v <= 1.0):
        raise ValueError("v must be in [0,1]")

    weighted = D * criterion_weights[None, :]
    S = weighted.sum(axis=1)
    R = weighted.max(axis=1)

    S_star, S_minus = S.min(), S.max()
    R_star, R_minus = R.min(), R.max()

    if np.isclose(S_minus, S_star) or np.isclose(R_minus, R_star):
        raise ValueError("Degenerate VIKOR normalization")

    A = (S - S_star) / (S_minus - S_star)
    B = (R - R_star) / (R_minus - R_star)
    Q = v * A + (1.0 - v) * B

    # Stable sort preserves S01..S30 order for exact ties.
    order = np.argsort(Q, kind="stable")
    rank = np.empty(len(Q), dtype=int)
    rank[order] = np.arange(1, len(Q) + 1)

    return {
        "S": S,
        "R": R,
        "Q": Q,
        "A": A,
        "B": B,
        "order": order,
        "rank": rank,
        "S_star": S_star,
        "S_minus": S_minus,
        "R_star": R_star,
        "R_minus": R_minus,
    }


def compromise_conditions(vres):
    Q, S, R, order = vres["Q"], vres["S"], vres["R"], vres["order"]
    m = len(Q)
    dq = 1.0 / (m - 1)
    first, second = order[0], order[1]

    advantage_gap = Q[second] - Q[first]
    acceptable_advantage = bool(advantage_gap >= dq)
    stability = bool(first == np.argmin(S) or first == np.argmin(R))

    if acceptable_advantage and stability:
        compromise = [first]
    elif not acceptable_advantage:
        compromise = [
            idx for idx in order
            if (Q[idx] - Q[first]) <= dq + 1e-15
        ]
    else:
        # Standard fallback when the leading Q alternative lacks decision stability.
        compromise = [first, second]

    return {
        "DQ": dq,
        "Q_gap_first_second": advantage_gap,
        "acceptable_advantage": acceptable_advantage,
        "decision_stability": stability,
        "compromise_indices": compromise,
    }


def entropy_weights(mu: np.ndarray, nu: np.ndarray):
    """
    Frozen intuitionistic-fuzzy entropy sensitivity.

    mu, nu shapes: K x m x n
    E_j^(k) = mean_i cos[ pi * (mu-nu) * (1-hesitation) / 2 ]
    w_j^(k) = (1-E_j^(k)) / (n - sum_j E_j^(k))
    comprehensive criterion weights = arithmetic mean over evaluators
    G^(k) = sum_j w_j^(k) E_j^(k)
    lambda_k = (1-G^(k)) / (K - sum_k G^(k))
    """
    hesitation = 1.0 - mu - nu
    E = np.mean(
        np.cos(np.pi * (mu - nu) * (1.0 - hesitation) / 2.0),
        axis=1,
    )  # K x n

    per_evaluator_criterion_weights = (
        (1.0 - E) / (len(CRITERIA) - E.sum(axis=1, keepdims=True))
    )
    comprehensive_criterion_weights = per_evaluator_criterion_weights.mean(axis=0)

    G = np.sum(per_evaluator_criterion_weights * E, axis=1)
    evaluator_entropy_weights = (1.0 - G) / (len(EVALUATORS) - G.sum())

    return {
        "E": E,
        "per_evaluator_criterion_weights": per_evaluator_criterion_weights,
        "criterion_weights": comprehensive_criterion_weights,
        "G": G,
        "evaluator_weights": evaluator_entropy_weights,
    }


def rank_correlations(base_rank, alt_rank):
    return (
        float(spearmanr(base_rank, alt_rank).statistic),
        float(kendalltau(base_rank, alt_rank).statistic),
    )


def icc2k_absolute_average(X: np.ndarray):
    """
    ICC(2,k): two-way random-effects, absolute-agreement, average-measures.

    Rows = targets/candidates; columns = raters/evaluators.
    """
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    grand = X.mean()
    row_means = X.mean(axis=1)
    col_means = X.mean(axis=0)

    ss_rows = k * np.sum((row_means - grand) ** 2)
    ss_cols = n * np.sum((col_means - grand) ** 2)
    residual = X - row_means[:, None] - col_means[None, :] + grand
    ss_error = np.sum(residual ** 2)

    ms_rows = ss_rows / (n - 1)
    ms_cols = ss_cols / (k - 1)
    ms_error = ss_error / ((n - 1) * (k - 1))

    denom = ms_rows + (ms_cols - ms_error) / n
    if np.isclose(denom, 0.0):
        return np.nan
    return (ms_rows - ms_error) / denom


def bootstrap_icc(scores: np.ndarray, n_boot=20_000, seed=42):
    """
    Candidate-level nonparametric bootstrap.

    A single NumPy Generator initialized with seed=42 is used sequentially across
    C1..C5. This reproduces the frozen confidence intervals.
    """
    rng = np.random.default_rng(seed)
    rows = []

    for j, criterion in enumerate(CRITERIA):
        X = scores[:, :, j].T  # candidates x evaluators
        point = icc2k_absolute_average(X)

        vals = np.empty(n_boot, dtype=float)
        n = X.shape[0]
        for b in range(n_boot):
            idx = rng.integers(0, n, size=n)
            vals[b] = icc2k_absolute_average(X[idx, :])

        vals = vals[np.isfinite(vals)]
        lo, hi = np.percentile(vals, [2.5, 97.5])
        rows.append({
            "criterion": criterion,
            "ICC_2_k": point,
            "bootstrap_ci_low": lo,
            "bootstrap_ci_high": hi,
            "bootstrap_resamples": n_boot,
            "bootstrap_seed": seed,
        })

    return pd.DataFrame(rows)


def make_group_matrix_df(group_mu, group_nu, mapping):
    group_pi = 1.0 - group_mu - group_nu
    rows = []
    original_lookup = dict(zip(mapping["candidate_id"], mapping["original_id"]))
    for i, candidate in enumerate(CANDIDATES):
        row = {
            "candidate_id": candidate,
            "original_id": original_lookup.get(candidate, ""),
        }
        for j, c in enumerate(CRITERIA):
            row[f"{c}_mu"] = group_mu[i, j]
            row[f"{c}_nu"] = group_nu[i, j]
            row[f"{c}_pi"] = group_pi[i, j]
        rows.append(row)
    return pd.DataFrame(rows)


def make_ideals_df(ideals):
    rows = []
    for j, c in enumerate(CRITERIA):
        pm, pn, pp = ideals["positive"][0][j], ideals["positive"][1][j], ideals["positive"][2][j]
        nm, nn, np_ = ideals["negative"][0][j], ideals["negative"][1][j], ideals["negative"][2][j]
        rows.append({
            "criterion": c,
            "positive_mu": pm,
            "positive_nu": pn,
            "positive_pi": pp,
            "negative_mu": nm,
            "negative_nu": nn,
            "negative_pi": np_,
        })
    return pd.DataFrame(rows)


def make_ranking_df(vres, mapping):
    original_lookup = dict(zip(mapping["candidate_id"], mapping["original_id"]))
    rows = []
    for position, idx in enumerate(vres["order"], start=1):
        rows.append({
            "rank": position,
            "candidate_id": CANDIDATES[idx],
            "original_id": original_lookup.get(CANDIDATES[idx], ""),
            "S": vres["S"][idx],
            "R": vres["R"][idx],
            "Q": vres["Q"][idx],
        })
    return pd.DataFrame(rows)


def crossing_v(vres, idx_a, idx_b):
    # Q_i(v) = B_i + v*(A_i-B_i)
    A, B = vres["A"], vres["B"]
    numerator = B[idx_b] - B[idx_a]
    denominator = (A[idx_a] - B[idx_a]) - (A[idx_b] - B[idx_b])
    if np.isclose(denominator, 0.0):
        return np.nan
    return numerator / denominator


def verify_frozen_results(primary_df, compromise, entropy, icc_df):
    checks = []

    for rank_expected, (candidate, S, R, Q) in enumerate(EXPECTED_PRIMARY_TOP, start=1):
        row = primary_df.iloc[rank_expected - 1]
        checks.append((
            f"primary rank {rank_expected} candidate",
            row["candidate_id"] == candidate,
            row["candidate_id"],
            candidate,
        ))
        for name, actual, expected in [
            ("S", row["S"], S),
            ("R", row["R"], R),
            ("Q", row["Q"], Q),
        ]:
            checks.append((
                f"{candidate} {name}",
                np.isclose(actual, expected, atol=5e-7),
                float(actual),
                expected,
            ))

    compromise_candidates = [CANDIDATES[i] for i in compromise["compromise_indices"]]
    checks.extend([
        ("Q gap", np.isclose(compromise["Q_gap_first_second"], 0.028435, atol=5e-7),
         float(compromise["Q_gap_first_second"]), 0.028435),
        ("DQ", np.isclose(compromise["DQ"], 0.034483, atol=5e-7),
         float(compromise["DQ"]), 0.034483),
        ("acceptable advantage", compromise["acceptable_advantage"] is False,
         compromise["acceptable_advantage"], False),
        ("decision stability", compromise["decision_stability"] is True,
         compromise["decision_stability"], True),
        ("compromise set", compromise_candidates == ["S12", "S20"],
         compromise_candidates, ["S12", "S20"]),
    ])

    checks.append((
        "entropy criterion weights",
        np.allclose(entropy["criterion_weights"], EXPECTED_ENTROPY_CRITERION_WEIGHTS, atol=5e-7),
        entropy["criterion_weights"].tolist(),
        EXPECTED_ENTROPY_CRITERION_WEIGHTS.tolist(),
    ))
    checks.append((
        "entropy evaluator weights",
        np.allclose(entropy["evaluator_weights"], EXPECTED_ENTROPY_EXPERT_WEIGHTS, atol=5e-7),
        entropy["evaluator_weights"].tolist(),
        EXPECTED_ENTROPY_EXPERT_WEIGHTS.tolist(),
    ))

    checks.append((
        "ICC point estimates (3 d.p.)",
        np.allclose(np.round(icc_df["ICC_2_k"].to_numpy(), 3), EXPECTED_ICC, atol=1e-12),
        np.round(icc_df["ICC_2_k"].to_numpy(), 3).tolist(),
        EXPECTED_ICC.tolist(),
    ))
    ci_round = np.column_stack([
        np.round(icc_df["bootstrap_ci_low"].to_numpy(), 3),
        np.round(icc_df["bootstrap_ci_high"].to_numpy(), 3),
    ])
    checks.append((
        "ICC bootstrap CIs (3 d.p.)",
        np.allclose(ci_round, EXPECTED_ICC_CI, atol=1e-12),
        ci_round.tolist(),
        EXPECTED_ICC_CI.tolist(),
    ))

    failed = [c for c in checks if not c[1]]
    return checks, failed


def main():
    parser = argparse.ArgumentParser(description="Reproduce the frozen IF-VIKOR analysis.")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--strict-hash",
        action="store_true",
        help="Fail if rating CSV byte-level SHA256 differs from the frozen source files.",
    )
    parser.add_argument("--bootstrap-resamples", type=int, default=20_000)
    parser.add_argument("--bootstrap-seed", type=int, default=42)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    scores, hash_df, mapping = load_inputs(args.data_dir, strict_hash=args.strict_hash)
    mu, nu, hesitation = ratings_to_ifn(scores)

    # Descriptive statistics across 150 ratings per criterion; sample SD (ddof=1).
    flat = scores.transpose(1, 0, 2).reshape(-1, len(CRITERIA))
    desc = pd.DataFrame({
        "criterion": CRITERIA,
        "mean": flat.mean(axis=0),
        "sample_sd": flat.std(axis=0, ddof=1),
        "median": np.median(flat, axis=0),
        "min": flat.min(axis=0),
        "max": flat.max(axis=0),
    })

    # Primary IF-VIKOR.
    equal_evaluator_weights = np.full(len(EVALUATORS), 1.0 / len(EVALUATORS))
    equal_criterion_weights = np.full(len(CRITERIA), 1.0 / len(CRITERIA))

    group_mu, group_nu, group_pi = ifwa(mu, nu, equal_evaluator_weights)
    D2, ideals2 = normalized_distances(group_mu, group_nu, distance_mode="two")
    primary = vikor(D2, equal_criterion_weights, v=0.50)
    compromise = compromise_conditions(primary)

    group_df = make_group_matrix_df(group_mu, group_nu, mapping)
    ideals_df = make_ideals_df(ideals2)
    distance_df = pd.DataFrame(D2, columns=CRITERIA)
    distance_df.insert(0, "candidate_id", CANDIDATES)
    primary_df = make_ranking_df(primary, mapping)

    # Entropy sensitivity.
    ent = entropy_weights(mu, nu)

    entropy_by_eval = pd.DataFrame(ent["E"], columns=[f"{c}_entropy" for c in CRITERIA])
    entropy_by_eval.insert(0, "evaluator", EVALUATORS)
    for j, c in enumerate(CRITERIA):
        entropy_by_eval[f"{c}_criterion_weight"] = ent["per_evaluator_criterion_weights"][:, j]
    entropy_by_eval["G"] = ent["G"]
    entropy_by_eval["evaluator_weight"] = ent["evaluator_weights"]

    entropy_criterion_df = pd.DataFrame({
        "criterion": CRITERIA,
        "comprehensive_entropy_weight": ent["criterion_weights"],
    })
    entropy_expert_df = pd.DataFrame({
        "evaluator": EVALUATORS,
        "G": ent["G"],
        "entropy_weight": ent["evaluator_weights"],
    })

    # Four expert/criterion weighting combinations.
    schemes = [
        ("equal_experts_equal_criteria", equal_evaluator_weights, equal_criterion_weights),
        ("equal_experts_entropy_criteria", equal_evaluator_weights, ent["criterion_weights"]),
        ("entropy_experts_equal_criteria", ent["evaluator_weights"], equal_criterion_weights),
        ("entropy_experts_entropy_criteria", ent["evaluator_weights"], ent["criterion_weights"]),
    ]
    base_rank = primary["rank"]
    weight_summary_rows = []
    weight_ranking_rows = []
    for scheme_name, ew, cw in schemes:
        gm, gn, gp = ifwa(mu, nu, ew)
        D, _ = normalized_distances(gm, gn, distance_mode="two")
        res = vikor(D, cw, v=0.50)
        rho, tau = rank_correlations(base_rank, res["rank"])
        top5 = [CANDIDATES[i] for i in res["order"][:5]]
        weight_summary_rows.append({
            "scheme": scheme_name,
            "top5": ",".join(top5),
            "spearman_rho_vs_primary": rho,
            "kendall_tau_vs_primary": tau,
        })
        rdf = make_ranking_df(res, mapping)
        rdf.insert(0, "scheme", scheme_name)
        weight_ranking_rows.extend(rdf.to_dict("records"))

    weight_summary_df = pd.DataFrame(weight_summary_rows)
    weight_rankings_df = pd.DataFrame(weight_ranking_rows)

    # v sensitivity using the primary D, S and R structure.
    v_summary_rows = []
    v_ranking_rows = []
    v_results = {}
    for vv in [0.25, 0.50, 0.75]:
        res = vikor(D2, equal_criterion_weights, v=vv)
        v_results[vv] = res
        top5 = [CANDIDATES[i] for i in res["order"][:5]]
        v_summary_rows.append({
            "v": vv,
            "top5": ",".join(top5),
            "first_candidate": CANDIDATES[res["order"][0]],
            "first_Q": res["Q"][res["order"][0]],
            "second_candidate": CANDIDATES[res["order"][1]],
            "second_Q": res["Q"][res["order"][1]],
        })
        rdf = make_ranking_df(res, mapping)
        rdf.insert(0, "v", vv)
        v_ranking_rows.extend(rdf.to_dict("records"))

    s12_idx = CANDIDATES.index("S12")
    s20_idx = CANDIDATES.index("S20")
    cross = crossing_v(primary, s12_idx, s20_idx)

    v_summary_df = pd.DataFrame(v_summary_rows)
    v_rankings_df = pd.DataFrame(v_ranking_rows)

    # Three-component distance sensitivity.
    D3, ideals3 = normalized_distances(group_mu, group_nu, distance_mode="three")
    res3 = vikor(D3, equal_criterion_weights, v=0.50)
    rho3, tau3 = rank_correlations(base_rank, res3["rank"])
    three_df = make_ranking_df(res3, mapping)
    three_summary = {
        "distance_definition": "sqrt(((dmu)^2+(dnu)^2+(dpi)^2)/2)",
        "top5": [CANDIDATES[i] for i in res3["order"][:5]],
        "spearman_rho_vs_primary": rho3,
        "kendall_tau_vs_primary": tau3,
    }

    # ICC diagnostic.
    icc_df = bootstrap_icc(
        scores,
        n_boot=args.bootstrap_resamples,
        seed=args.bootstrap_seed,
    )

    # Frozen result verification.
    checks, failed = verify_frozen_results(primary_df, compromise, ent, icc_df)
    check_df = pd.DataFrame([
        {
            "check": name,
            "passed": bool(passed),
            "actual": json.dumps(actual, ensure_ascii=False) if isinstance(actual, (list, dict)) else str(actual),
            "expected": json.dumps(expected, ensure_ascii=False) if isinstance(expected, (list, dict)) else str(expected),
        }
        for name, passed, actual, expected in checks
    ])

    compromise_candidates = [CANDIDATES[i] for i in compromise["compromise_indices"]]
    summary = {
        "primary": {
            "expert_weights": equal_evaluator_weights.tolist(),
            "criterion_weights": equal_criterion_weights.tolist(),
            "v": 0.50,
            "distance": "two-component Euclidean",
            "rank_1": primary_df.iloc[0]["candidate_id"],
            "rank_2": primary_df.iloc[1]["candidate_id"],
            "Q_gap_first_second": float(compromise["Q_gap_first_second"]),
            "DQ": float(compromise["DQ"]),
            "acceptable_advantage": compromise["acceptable_advantage"],
            "decision_stability": compromise["decision_stability"],
            "compromise_set": compromise_candidates,
        },
        "v_sensitivity_crossing_S12_S20": float(cross),
        "three_component_sensitivity": three_summary,
        "bootstrap": {
            "resamples": args.bootstrap_resamples,
            "seed": args.bootstrap_seed,
        },
        "frozen_reproduction_pass": len(failed) == 0,
    }

    # Outputs.
    hash_df.to_csv(args.output_dir / "input_hashes.csv", index=False)
    desc.to_csv(args.output_dir / "descriptive_criteria.csv", index=False)
    group_df.to_csv(args.output_dir / "group_if_matrix.csv", index=False)
    ideals_df.to_csv(args.output_dir / "ideal_solutions_primary.csv", index=False)
    distance_df.to_csv(args.output_dir / "normalized_distances_primary.csv", index=False)
    primary_df.to_csv(args.output_dir / "primary_vikor_ranking.csv", index=False)

    entropy_by_eval.to_csv(args.output_dir / "entropy_details_by_evaluator.csv", index=False)
    entropy_criterion_df.to_csv(args.output_dir / "entropy_criterion_weights.csv", index=False)
    entropy_expert_df.to_csv(args.output_dir / "entropy_evaluator_weights.csv", index=False)

    weight_summary_df.to_csv(args.output_dir / "weight_sensitivity_summary.csv", index=False)
    weight_rankings_df.to_csv(args.output_dir / "weight_sensitivity_rankings.csv", index=False)
    v_summary_df.to_csv(args.output_dir / "v_sensitivity_summary.csv", index=False)
    v_rankings_df.to_csv(args.output_dir / "v_sensitivity_rankings.csv", index=False)

    three_df.to_csv(args.output_dir / "three_component_ranking.csv", index=False)
    icc_df.to_csv(args.output_dir / "icc_summary.csv", index=False)
    check_df.to_csv(args.output_dir / "frozen_reproduction_checks.csv", index=False)

    with (args.output_dir / "reproduction_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n=== Frozen IF-VIKOR reproduction ===")
    print(primary_df.head(10).to_string(index=False))
    print()
    print(f"Q2-Q1 = {compromise['Q_gap_first_second']:.6f}")
    print(f"DQ      = {compromise['DQ']:.6f}")
    print(f"Acceptable advantage: {compromise['acceptable_advantage']}")
    print(f"Decision stability:   {compromise['decision_stability']}")
    print(f"Compromise set:       {', '.join(compromise_candidates)}")
    print(f"S12/S20 v crossing:   {cross:.6f}")
    print()
    print("Entropy criterion weights:", np.round(ent["criterion_weights"], 6))
    print("Entropy evaluator weights:", np.round(ent["evaluator_weights"], 6))
    print()
    print(icc_df.to_string(index=False))
    print()

    if failed:
        print("REPRODUCTION CHECK: FAIL")
        for name, _, actual, expected in failed:
            print(f" - {name}: actual={actual}, expected={expected}")
        raise SystemExit(2)

    print("REPRODUCTION CHECK: PASS")
    print(f"Outputs written to: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
