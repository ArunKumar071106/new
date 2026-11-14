"""Textures extracted directly from the reference photographs.

* Heart sticker: un-wrapped from the curved bucket wall in the front photo
  (cylindrical back-projection), white-balanced against the surrounding
  bucket plastic so the lighting gradient of the photo is removed.
* Hat crown fabric: rectified from the left-side photo where the hat faces
  the camera, then de-lit by normalising against a robust low-pass of the
  photo so only the printed glitter pattern and weave remain.
"""
import os
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.morphology import convex_hull_image

from dims import BUCKET, bucket_r_out

REF = os.path.join(os.path.dirname(__file__), "..", "reference")


def _load(name):
    return np.asarray(Image.open(os.path.join(REF, name)).convert("RGB")).astype(np.float64) / 255.0


def _srgb_to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def _bilinear(img, x, y):
    return np.stack([ndimage.map_coordinates(img[..., c], [y, x], order=1, mode="nearest")
                     for c in range(img.shape[2])], -1)


# ----------------------------------------------------------------------------
# Sticker
# ----------------------------------------------------------------------------
# Measurements taken on the front photo (4080x3060):
STK = dict(
    y_bottom=2995.0,         # image row of the base front edge (h = 0)
    y_rim=1835.0,            # image row of the rim top at the front (h = 60)
    # bucket silhouette edges at two rows (left, right)
    edge_rows=((2100.0, 1530.0, 2745.0), (2950.0, 1620.0, 2620.0)),
    sin_elev=0.17,           # camera elevation from rim-ellipse aspect ratio
    s_range=(-24.0, 24.0),   # sticker texture covers this arc length (mm)
    h_range=(6.0, 54.0),     # and this height range (mm)
)


def sticker_texture(size=1024, bucket_albedo_srgb=(0.902, 0.627, 0.753)):
    img = _load("01_front.webp")
    s0, s1 = STK["s_range"]
    h0, h1 = STK["h_range"]
    S, Hh = np.meshgrid(np.linspace(s0, s1, size), np.linspace(h1, h0, size))  # row0 = top
    R_mm = bucket_r_out(Hh)
    phi = S / R_mm
    kv = (STK["y_bottom"] - STK["y_rim"]) / BUCKET["H"]
    yf = STK["y_bottom"] - Hh * kv
    (ya, la, ra), (yb, lb, rb) = STK["edge_rows"]
    def edges(y):
        t = (y - ya) / (yb - ya)
        return la + t * (lb - la), ra + t * (rb - ra)
    l, r = edges(yf)
    Rpx = (r - l) / 2
    y = yf - Rpx * STK["sin_elev"] * (1 - np.cos(phi))
    l, r = edges(y)
    xc, Rpx = (l + r) / 2, (r - l) / 2
    x = xc + Rpx * np.sin(phi)
    rect = _bilinear(img, x, y)

    # --- heart mask: sticker is much darker / more violet than the plastic
    lin = _srgb_to_lin(rect)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722])
    m = rect[..., 0] < 0.53          # sticker red channel ~0.35-0.47, plastic ~0.63-0.72
    m = ndimage.binary_opening(m, iterations=6)
    lab, n = ndimage.label(m)
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    m = lab == (1 + int(np.argmax(sizes)))
    m = ndimage.binary_closing(m, iterations=10)
    m = ndimage.binary_fill_holes(m)
    m = ndimage.binary_opening(m, iterations=12)
    # A heart outline is convex everywhere below its top notch: fill the
    # light bouquet print (which touches the edge) with the convex hull.
    rows = np.nonzero(m.any(1))[0]
    top_third = rows[0] + (rows[-1] - rows[0]) // 3
    runs = [np.count_nonzero(np.diff(np.r_[0, row.astype(np.int8), 0]) == 1) for row in m[:top_third]]
    notch = max([i for i, r in enumerate(runs) if r >= 2] or [0])
    lower = m.copy()
    lower[:notch + 1] = False
    hull = convex_hull_image(lower)
    m = m | hull
    # smooth outline (die-cut edge) and keep it anti-aliased
    soft = ndimage.gaussian_filter(m.astype(np.float64), 2.0)
    alpha = np.clip((soft - 0.5) * 6 + 0.5, 0, 1)

    # --- white balance / de-light against the surrounding bucket plastic
    ring = ndimage.binary_dilation(m, iterations=10) & ~ndimage.binary_dilation(m, iterations=3)
    ring &= (lum > 0.12)
    yy, xx = np.nonzero(ring)
    target = _srgb_to_lin(np.array(bucket_albedo_srgb))
    # fit a smooth (quadratic) illumination field per channel over the ring
    A = np.stack([np.ones_like(xx), xx, yy, xx * xx, yy * yy, xx * yy], 1).astype(np.float64) / \
        np.array([1, size, size, size ** 2, size ** 2, size ** 2])
    Yg, Xg = np.mgrid[0:size, 0:size]
    Ag = np.stack([np.ones_like(Xg), Xg, Yg, Xg * Xg, Yg * Yg, Xg * Yg], -1).astype(np.float64) / \
        np.array([1, size, size, size ** 2, size ** 2, size ** 2])
    illum = np.zeros_like(lin)
    for c in range(3):
        coef, *_ = np.linalg.lstsq(A, lin[yy, xx, c], rcond=None)
        illum[..., c] = np.maximum(Ag @ coef, 1e-3)
    albedo = _lin_to_srgb(lin / illum * target)
    # outside the heart the colour is irrelevant (alpha masked); bleed edge
    out = np.concatenate([albedo, alpha[..., None]], -1)
    info = {"arc_width_mm": float(np.ptp(S[m])), "height_mm": float(np.ptp(Hh[m])),
            "h_min": float(Hh[m].min()), "h_max": float(Hh[m].max()),
            "s_min": float(S[m].min()), "s_max": float(S[m].max())}
    return out, info


# ----------------------------------------------------------------------------
# Hat crown fabric
# ----------------------------------------------------------------------------
HAT = dict(
    # brim ellipse in 02_left_side, least-squares conic fit to the clean
    # part of the segmented outline (px)
    center=(2407.3, 524.0),
    minor=(446.0, (0.927, -0.374)),   # semi-axis length, image direction
    major=(529.0, (-0.374, -0.927)),
    usable=0.985,
)


def hat_texture(size=2048, base_srgb=(0.80, 0.70, 0.86)):
    img = _load("02_left_side.webp")
    cx, cy = HAT["center"]
    (am, em), (aM, eM) = HAT["minor"], HAT["major"]
    em, eM = np.array(em), np.array(eM)
    # pure (symmetric) affine un-foreshortening: keeps image-up as hat-up
    E = np.stack([em, eM], 1)
    A = E @ np.diag([am, aM]) @ E.T
    u, v = np.meshgrid(np.linspace(-1, 1, size), np.linspace(1, -1, size))  # row0 = +y (top)
    rr = np.sqrt(u * u + v * v)
    k = np.minimum(1.0, HAT["usable"] / np.maximum(rr, 1e-9))
    q = np.stack([u * k, -v * k], -1)            # image orientation (y down)
    p = q @ A.T
    x = cx + p[..., 0]
    y = cy + p[..., 1]
    rect = _bilinear(img, x, y)
    lin = _srgb_to_lin(rect)
    # robust low-pass (illumination + base colour) : median on a small copy
    small = lin[::8, ::8]
    lp = np.stack([ndimage.median_filter(small[..., c], size=21) for c in range(3)], -1)
    lp = np.stack([ndimage.gaussian_filter(lp[..., c], 4) for c in range(3)], -1)
    lp = np.stack([ndimage.zoom(lp[..., c], size / lp.shape[0], order=1) for c in range(3)], -1)
    lp = lp[:size, :size]
    ratio = lin / np.maximum(lp, 1e-3)
    # glitter print mask: strongly magenta relative to the lavender satin
    target = _srgb_to_lin(np.array(base_srgb))
    a0 = _lin_to_srgb(np.clip(ratio * target, 0, 1))
    sat = a0[..., 0] + a0[..., 2] - 2 * a0[..., 1]
    gl = np.clip((sat - 0.33) / 0.10, 0, 1)
    gl = ndimage.gaussian_filter(gl, 0.8)
    # Remaining mid-frequency shading (dome highlights, the dark side of the
    # crown) measured on satin-only pixels with normalised convolution.
    w = np.clip(1 - gl, 0, 1)
    lum = ratio @ np.array([0.2126, 0.7152, 0.0722])
    sig = size / 40
    mid = ndimage.gaussian_filter(lum * w, sig) / np.maximum(ndimage.gaussian_filter(w, sig), 1e-3)
    mid = np.maximum(mid, 1e-3)
    ratio = ratio / mid[..., None] * mid[..., None] ** 0.25
    albedo_lin = np.clip(ratio * target, 0, 1)
    albedo = _lin_to_srgb(albedo_lin)
    return albedo, np.clip(gl, 0, 1), rr
