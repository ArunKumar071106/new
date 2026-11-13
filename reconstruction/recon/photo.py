"""Colour normalisation and photo-consistency.

Photo-consistency resolves what silhouettes cannot: for a near-symmetric outline (a
round bucket) several rotation angles give the same silhouette, but only the correct
one makes surface colours (stickers, eyes, bow) agree across views.
"""
from __future__ import annotations

import cv2
import numpy as np
from scipy import ndimage

from .cameras import Camera


def white_reference(img_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Mean colour of the brightest, least saturated object pixels (a neutral reference)."""
    px = img_bgr[mask > 0].astype(np.float32)
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)[mask > 0].astype(np.float32)
    lum = px.mean(1)
    score = lum - 0.5 * hsv[:, 1]
    sel = score >= np.percentile(score, 80)
    return px[sel].mean(0)


def colour_gains(views: dict, ref_name: str) -> dict[str, np.ndarray]:
    """Per-view per-channel gains mapping each view's neutral reference to the reference view's."""
    refs = {n: white_reference(v.work, v.mask) for n, v in views.items()}
    target = refs[ref_name]
    return {n: np.clip(target / np.maximum(r, 1.0), 0.5, 2.5) for n, r in refs.items()}


def apply_gain(img_bgr: np.ndarray, gain: np.ndarray) -> np.ndarray:
    return np.clip(img_bgr.astype(np.float32) * gain[None, None, :], 0, 255).astype(np.uint8)


def sample_bilinear(img: np.ndarray, uv: np.ndarray) -> np.ndarray:
    """Bilinear sample an HxWxC float image at uv (N,2); out-of-bounds -> nan."""
    h, w = img.shape[:2]
    n = len(uv)
    cols = 1024
    rows = max(1, -(-n // cols))
    pad = rows * cols - n
    mx = np.pad(uv[:, 0].astype(np.float32), (0, pad), constant_values=-1).reshape(rows, cols)
    my = np.pad(uv[:, 1].astype(np.float32), (0, pad), constant_values=-1).reshape(rows, cols)
    out = np.empty((rows * cols, img.shape[2] if img.ndim == 3 else 1), np.float32)
    step = 30000  # cv2.remap needs map dims < 32767
    for r0 in range(0, rows, step):
        o = cv2.remap(img, mx[r0:r0 + step], my[r0:r0 + step], cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REPLICATE)
        out[r0 * cols:(r0 + step) * cols] = o.reshape(-1, out.shape[1])
    out = out[:n]
    bad = (uv[:, 0] < 0) | (uv[:, 0] > w - 1) | (uv[:, 1] < 0) | (uv[:, 1] > h - 1)
    out[bad] = np.nan
    return out


class SurfaceProbe:
    """Surface points + normals of an occupancy grid, with ray-marched visibility."""

    def __init__(self, occ3d: np.ndarray, lo: np.ndarray, voxel: float, max_points: int = 12000, seed: int = 0):
        self.lo, self.voxel = lo, voxel
        self.field = ndimage.gaussian_filter(occ3d.astype(np.float32), 1.0)
        surf = occ3d & ~ndimage.binary_erosion(occ3d)
        idx = np.argwhere(surf)
        if len(idx) > max_points:
            idx = idx[np.random.default_rng(seed).choice(len(idx), max_points, replace=False)]
        g = np.stack(np.gradient(self.field), -1)[tuple(idx.T)]
        n = -g / np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
        self.idx = idx
        self.P = lo + idx * voxel
        self.N = n

    def visible(self, cam: Camera, min_cos: float = 0.25) -> np.ndarray:
        to_cam = cam.C[None] - self.P
        dist = np.linalg.norm(to_cam, axis=1, keepdims=True)
        d = to_cam / dist
        facing = (self.N * d).sum(1) > min_cos
        vis = facing.copy()
        ids = np.nonzero(facing)[0]
        if len(ids) == 0:
            return vis
        start = self.P[ids] + self.N[ids] * 2.0 * self.voxel
        shape = np.array(self.field.shape)
        nsteps = int(np.ceil(np.linalg.norm(shape))) + 2
        for k in range(nsteps):
            q = (start + d[ids] * (k * self.voxel) - self.lo) / self.voxel
            inside = np.all((q >= 0) & (q <= shape - 1), axis=1)
            if not inside.any():
                break
            val = np.zeros(len(ids), np.float32)
            val[inside] = ndimage.map_coordinates(self.field, q[inside].T, order=1)
            vis[ids[val > 0.5]] = False
            keep = val <= 0.5
            ids, start = ids[keep], start[keep]
            if len(ids) == 0:
                break
        return vis


def to_lab(img_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img_bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)


def photo_error(probe: SurfaceProbe, cams: dict[str, Camera], labs: dict[str, np.ndarray],
                involve: str | None = None, clip: float = 40.0) -> float:
    """Mean Lab colour disagreement between pairs of views over mutually visible surface points."""
    cols, viss = {}, {}
    for n, cam in cams.items():
        uv, _ = cam.project(probe.P)
        c = sample_bilinear(labs[n], uv)
        v = probe.visible(cam) & ~np.isnan(c).any(1)
        cols[n], viss[n] = c, v
    names = list(cams)
    tot, cnt = 0.0, 0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if involve and involve not in (a, b):
                continue
            both = viss[a] & viss[b]
            if both.sum() < 30:
                continue
            diff = np.linalg.norm((cols[a][both] - cols[b][both]) * np.array([0.5, 1, 1]), axis=1)
            tot += np.minimum(diff, clip).sum()
            cnt += both.sum()
    return tot / cnt if cnt else clip
