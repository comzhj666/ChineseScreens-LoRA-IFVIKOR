"""Analytical and semi-empirical acoustic models for experiment V1."""

from __future__ import annotations

import math

import numpy as np


def miki_rigid_backed_absorption(
    frequency_hz: float | np.ndarray,
    flow_resistivity: float,
    thickness_m: float,
    air_density_kg_m3: float,
    speed_of_sound_m_s: float,
) -> dict[str, np.ndarray]:
    """Return Miki (1990) complex quantities and normal-incidence absorption.

    The implementation follows the exp(+j*omega*t) convention implied by the
    user-frozen negative imaginary terms for Zc and kc and by
    Zs = -j*Zc/tan(kc*d).
    """
    frequency = np.asarray(frequency_hz, dtype=np.float64)
    if np.any(frequency <= 0):
        raise ValueError("frequency_hz must be positive")
    if flow_resistivity <= 0 or thickness_m <= 0:
        raise ValueError("flow_resistivity and thickness_m must be positive")

    rho0 = np.float64(air_density_kg_m3)
    c0 = np.float64(speed_of_sound_m_s)
    x = 1000.0 * frequency / np.float64(flow_resistivity)
    omega = 2.0 * np.pi * frequency

    characteristic_impedance = np.asarray(
        rho0
        * c0
        * (1.0 + 5.50 * x ** (-0.632) - 1j * 8.43 * x ** (-0.632)),
        dtype=np.complex128,
    )
    complex_wavenumber = np.asarray(
        omega
        / c0
        * (1.0 + 7.81 * x ** (-0.618) - 1j * 11.41 * x ** (-0.618)),
        dtype=np.complex128,
    )
    surface_impedance = np.asarray(
        -1j
        * characteristic_impedance
        / np.tan(complex_wavenumber * np.float64(thickness_m)),
        dtype=np.complex128,
    )
    reflection = (surface_impedance - rho0 * c0) / (surface_impedance + rho0 * c0)
    alpha = np.asarray(1.0 - np.abs(reflection) ** 2, dtype=np.float64)

    if np.any(alpha < -1e-6) or np.any(alpha > 1.0 + 1e-6):
        raise ArithmeticError(f"Miki absorption out of physical range: {alpha}")
    # Only correct values that differ from the closed interval by floating error.
    alpha = np.where((alpha < 0.0) & (alpha >= -1e-10), 0.0, alpha)
    alpha = np.where((alpha > 1.0) & (alpha <= 1.0 + 1e-10), 1.0, alpha)

    return {
        "frequency_hz": frequency,
        "characteristic_impedance": characteristic_impedance,
        "complex_wavenumber": complex_wavenumber,
        "surface_impedance": surface_impedance,
        "reflection_coefficient": reflection,
        "alpha": alpha,
    }


def kurze_anderson_insertion_loss(
    path_difference_m: float,
    frequency_hz: float,
    speed_of_sound_m_s: float,
) -> tuple[float, float]:
    """Return Fresnel number and Kurze-Anderson-type insertion loss in dB."""
    delta = float(path_difference_m)
    if delta < -1e-9:
        raise ArithmeticError(f"Significantly negative path difference: {delta}")
    if delta < 0.0:
        delta = 0.0
    if frequency_hz <= 0 or speed_of_sound_m_s <= 0:
        raise ValueError("frequency_hz and speed_of_sound_m_s must be positive")

    fresnel_number = 2.0 * float(frequency_hz) * delta / float(speed_of_sound_m_s)
    if fresnel_number < 0.0:
        raise ArithmeticError(f"Negative Fresnel number: {fresnel_number}")
    if fresnel_number < 1e-12:
        return fresnel_number, 5.0

    u = math.sqrt(2.0 * math.pi * fresnel_number)
    insertion_loss_db = 5.0 + 20.0 * math.log10(u / math.tanh(u))
    return fresnel_number, insertion_loss_db

