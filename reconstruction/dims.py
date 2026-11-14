"""Measured dimensions (millimetres).

Absolute scale is anchored on an assumed 60 mm rim diameter; every other
number is a *ratio* measured on the reference photos (see REPORT.md), so a
different real-world size only changes the global scale, not the shape.

Frame: Y up, origin at the centre of the bucket base, +Z = bear's front,
+X = bear's left (viewer's right in the front photo).
"""
import numpy as np

BUCKET = dict(
    H=60.0,             # rim height at the front (h/D_rim = 1.00, side photo)
    r_bot=22.8,         # outer radius at the base (D_bot/D_rim = 0.76)
    r_top=29.2,         # outer radius just below the rim band
    band_start=55.2,    # rim band (thicker lip) starts here
    band_flare=0.75,    # band stands proud of the wall by this much
    wall=1.15,          # wall thickness
    floor=1.4,          # base thickness
    base_fillet=1.6,
    tab_h=6.8,          # handle tabs rise this far above the rim
    tab_w=7.2,          # half-width of each tab along the rim (arc mm)
    hole_r=1.0,         # handle hole radius
    hole_y=63.4,        # hole centre height
)


def bucket_r_body(y):
    B = BUCKET
    return B["r_bot"] + (B["r_top"] - B["r_bot"]) * (np.asarray(y) / B["band_start"])


def bucket_r_out(y):
    B = BUCKET
    y = np.asarray(y, float)
    t = np.clip((y - (B["band_start"] - 0.5)) / 1.0, 0, 1)
    t = t * t * (3 - 2 * t)
    return bucket_r_body(y) + B["band_flare"] * t


# --- Bear --------------------------------------------------------------------
HEAD_C = np.array([0.6, 97.2, 0.5])
HEAD_R = np.array([21.4, 18.7, 18.9])
HEAD_ROLL_DEG = -4.0            # bear's left side lower (front photo eye line)
BODY_C = np.array([0.0, 60.0, 0.0])
BODY_R = np.array([19.6, 24.5, 17.0])

# hat: crown direction in world space and size
HAT_N = np.array([0.78, 0.40, -0.40])
HAT_R = 22.0          # brim radius   (hat D / rim D = 0.73)
HAT_CROWN_R = 13.0    # crown radius  (0.60 of brim, side photo)
HAT_CROWN_H = 6.2     # crown dome height
HAT_THICK = 0.9
