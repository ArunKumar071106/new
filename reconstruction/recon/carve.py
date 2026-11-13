"""Voxel visual-hull carving and silhouette re-projection."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .cameras import Camera


@dataclass
class Grid:
    lo: np.ndarray  # (3,) min corner
    hi: np.ndarray  # (3,) max corner
    res: tuple[int, int, int]

    @property
    def voxel(self) -> np.ndarray:
        return (self.hi - self.lo) / (np.array(self.res) - 1)

    def points(self) -> np.ndarray:
        axes = [np.linspace(self.lo[i], self.hi[i], self.res[i], dtype=np.float32) for i in range(3)]
        g = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
        return g.reshape(-1, 3)


def grid_for_box(lo, hi, max_res: int, pad: float = 0.08) -> Grid:
    lo, hi = np.asarray(lo, float), np.asarray(hi, float)
    ext = hi - lo
    lo, hi = lo - ext * pad, hi + ext * pad
    ext = hi - lo
    vox = ext.max() / (max_res - 1)
    res = tuple(int(np.ceil(e / vox)) + 1 for e in ext)
    hi = lo + vox * (np.array(res) - 1)
    return Grid(lo, hi, res)


def inside_mask(cam: Camera, mask: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Silhouette test. Points projecting outside the frame take the value of the nearest
    border pixel: if the object runs off the edge of the photo (cut off), the frame edge
    must not slice the object; if it does not touch the edge, those points are carved."""
    uv, z = cam.project(pts)
    h, w = mask.shape
    u = np.clip(np.round(uv[:, 0]), 0, w - 1).astype(np.int64)
    v = np.clip(np.round(uv[:, 1]), 0, h - 1).astype(np.int64)
    return (z > 0) & (mask[v, u] > 0)


def carve(pts: np.ndarray, cams: list[Camera], masks: list[np.ndarray]) -> np.ndarray:
    occ = np.ones(len(pts), bool)
    for cam, m in zip(cams, masks):
        idx = np.nonzero(occ)[0]
        occ[idx] = inside_mask(cam, m, pts[idx])
    return occ


def splat(cam: Camera, pts: np.ndarray, shape: tuple[int, int], voxel_size: float) -> np.ndarray:
    """Approximate silhouette of a voxel set: project centres, close gaps of one voxel footprint."""
    h, w = shape
    img = np.zeros((h, w), np.uint8)
    if len(pts) == 0:
        return img
    uv, z = cam.project(pts)
    ok = z > 0
    u = np.round(uv[ok, 0]).astype(np.int64)
    v = np.round(uv[ok, 1]).astype(np.int64)
    inb = (u >= 0) & (u < w) & (v >= 0) & (v < h)
    img[v[inb], u[inb]] = 1
    rad = cam.f * voxel_size / max(np.median(z[ok]), 1e-6)
    k = int(np.clip(np.ceil(rad), 1, 25)) | 1
    if k > 1:
        img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k + 2, k + 2)))
        img = cv2.dilate(img, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (max(1, k // 2) | 1,) * 2))
    return img


def iou(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a > 0, b > 0
    u = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / u) if u else 0.0
