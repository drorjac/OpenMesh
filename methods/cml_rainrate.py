"""
methods/cml_rainrate.py
=======================
ITU-R P.838-3 power-law rain-rate retrieval from CML specific attenuation.

The specific (per-km) rain attenuation is

    gamma_R = k * R**alpha            [dB/km],   R in mm/h

so total path attenuation A = gamma_R * L = k * R**alpha * L  (L in km), and the
inverse retrieval of rain rate from a measured attenuation A on a path of length
L is

    R = ( A / (k * L) ) ** (1/alpha)         [mm/h]

k and alpha are frequency- and polarisation-dependent. They are computed from
the ITU-R P.838-3 Gaussian-sum model (valid 1-1000 GHz):

    log10(k) = sum_j a_j * exp(-((log10 f - b_j)/c_j)**2) + m_k*log10 f + c_k
    alpha    = sum_j a_j * exp(-((log10 f - b_j)/c_j)**2) + m_a*log10 f + c_a

with separate coefficient sets for horizontal (H) and vertical (V) polarisation
(Rec. ITU-R P.838-3, Tables 1-4). f is in GHz.

CAVEAT for this dataset: the rain power law is a *rain-only* retrieval. Applying
it to snow/mixed hours is expected to mis-estimate rate (dry snow is far more
transparent than rain at the same dB), and at V-band (~60-70 GHz) gaseous/oxygen
absorption and wet-antenna effects are not modelled here. Those failures are the
point of the phase-coloured scatter in Part 2.4.
"""
from __future__ import annotations

import numpy as np

# --- ITU-R P.838-3 coefficient tables ---------------------------------------
# kH, kV: model for log10(k);  aH, aV: model for alpha.
_KH = dict(a=[-5.33980, -0.35351, -0.23789, -0.94158],
           b=[-0.10008,  1.26970,  0.86036,  0.64552],
           c=[ 1.13098,  0.45400,  0.15354,  0.16817], m=-0.18961, k=0.71147)
_KV = dict(a=[-3.80595, -3.44965, -0.39902,  0.50167],
           b=[ 0.56934, -0.22911,  0.73042,  1.07319],
           c=[ 0.81061,  0.51059,  0.11899,  0.27195], m=-0.16398, k=0.63297)
_AH = dict(a=[-0.14318,  0.29591,  0.32177, -5.37610, 16.1721],
           b=[ 1.82442,  0.77564,  0.63773, -0.96230, -3.29980],
           c=[-0.55187,  0.19822,  0.13164,  1.47828,  3.43990], m=0.67849, k=-1.95537)
_AV = dict(a=[-0.07771,  0.56727, -0.20238, -48.2991, 48.5833],
           b=[ 2.33840,  0.95545,  1.14520,  0.791669, 0.791459],
           c=[-0.76284,  0.54039,  0.26809,  0.116226, 0.116479], m=-0.053739, k=0.83433)


def _gauss_sum(logf, t):
    s = np.zeros_like(logf, dtype=float)
    for a, b, c in zip(t['a'], t['b'], t['c']):
        s += a * np.exp(-(((logf - b) / c) ** 2))
    return s + t['m'] * logf + t['k']


def itu_k_alpha(freq_ghz, pol: str = 'V'):
    """Return (k, alpha) per ITU-R P.838-3 for frequency `freq_ghz` (scalar or
    array) and polarisation 'H' or 'V'. Vertical is the NYC Mesh default."""
    f = np.asarray(freq_ghz, dtype=float)
    logf = np.log10(f)
    pol = (pol or 'V').upper()[0]
    if pol == 'H':
        kt, at = _KH, _AH
    else:
        kt, at = _KV, _AV
    k = 10.0 ** _gauss_sum(logf, kt)
    alpha = _gauss_sum(logf, at)
    return k, alpha


def rain_rate_from_attenuation(att_db, length_km, freq_ghz, pol: str = 'V',
                               clip_negative: bool = True):
    """Invert A = k*R**alpha*L to rain rate R (mm/h).

    att_db    : path attenuation (dB), scalar/array
    length_km : path length (km), scalar/array (broadcast with att_db)
    freq_ghz  : carrier frequency (GHz)
    Negative/zero attenuation -> 0 mm/h when clip_negative (no physical rain).
    """
    att = np.asarray(att_db, dtype=float)
    L = np.asarray(length_km, dtype=float)
    k, alpha = itu_k_alpha(freq_ghz, pol)
    spec = att / (k * L)                      # = R**alpha
    with np.errstate(invalid='ignore'):
        R = np.where(spec > 0, spec ** (1.0 / alpha), 0.0 if clip_negative else np.nan)
    if clip_negative:
        R = np.where(np.isfinite(R), np.maximum(R, 0.0), 0.0)
    return R


if __name__ == "__main__":
    # Quick coefficient sanity check against the published recommendation.
    for f in [5.5, 23.0, 38.0, 60.0, 68.0]:
        kH, aH = itu_k_alpha(f, 'H')
        kV, aV = itu_k_alpha(f, 'V')
        print(f"f={f:5.1f} GHz  kH={kH:.5f} aH={aH:.4f}  kV={kV:.5f} aV={aV:.4f}")
    # Forward/inverse round-trip: 10 mm/h on a 1.3 km 68 GHz V link.
    k, a = itu_k_alpha(68.0, 'V')
    A = k * 10.0 ** a * 1.3
    R = rain_rate_from_attenuation(A, 1.3, 68.0, 'V')
    print(f"\nround-trip 68GHz V, L=1.3km: R=10 -> A={A:.2f} dB -> R={R:.2f} mm/h")
