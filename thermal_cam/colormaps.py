# SPDX-License-Identifier: GPL-3.0-or-later
"""colormaps.py -- Thermal colormaps as 256x3 uint8 numpy arrays."""

import numpy as np


def _interp_lut(stops):
    """Build 256-entry RGB LUT from a list of (R,G,B) stops."""
    stops = np.array(stops, dtype=np.float32)
    lut   = np.zeros((256, 3), dtype=np.uint8)
    n     = len(stops)
    for i in range(256):
        t  = i / 255.0 * (n - 1)
        lo = int(t)
        hi = min(lo + 1, n - 1)
        f  = t - lo
        lut[i] = np.clip(stops[lo] + (stops[hi] - stops[lo]) * f, 0, 255).astype(np.uint8)
    return lut


INFERNO = _interp_lut([
    [0,0,4],[20,11,53],[58,9,99],[96,19,110],[133,33,107],
    [169,46,94],[203,65,73],[229,89,52],[247,121,24],[252,165,10],
    [246,215,70],[252,255,164],
])

TURBO = _interp_lut([
    [48,18,59],[86,67,170],[71,131,220],[45,185,164],
    [99,222,105],[195,244,79],[254,196,56],[249,140,33],
    [222,73,12],[163,14,2],
])

IRONBOW = _interp_lut([
    [0,0,0],[60,0,80],[120,0,80],[180,40,0],
    [220,100,0],[240,180,0],[255,240,120],[255,255,220],
])

GRAYSCALE = _interp_lut([[i,i,i] for i in np.linspace(0, 255, 12)])

COLORMAPS = {
    "Inferno":   INFERNO,
    "Turbo":     TURBO,
    "Ironbow":   IRONBOW,
    "Grayscale": GRAYSCALE,
}
