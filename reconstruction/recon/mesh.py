"""Occupancy grid -> watertight, smoothed, decimated triangle mesh."""
from __future__ import annotations

import numpy as np
import trimesh
from scipy import ndimage
from skimage import measure

from .carve import Grid


def infer_base(occ: np.ndarray, grid: Grid, max_slope: float = 0.6) -> dict:
    """Find the support plane of an object photographed only from above the table.

    Cameras that look down leave a cone-shaped "skirt" under the true base in the visual
    hull: there the equivalent radius r(y) = sqrt(area/pi) of horizontal slices shrinks
    quickly going down (|dr/dy| ~ 1/tan(elevation)). Real side walls - even tapered ones -
    are much steeper (small |dr/dy|). Walking up from the lowest slice, the base is the
    first slice where the wall slope drops below `max_slope`.
    """
    vox = float(grid.voxel[1])
    area = occ.sum(axis=(0, 2)).astype(float)
    r = np.sqrt(area / np.pi)
    ys = np.nonzero(area)[0]
    y0, y1 = int(ys.min()), int(ys.max())
    rs = ndimage.uniform_filter1d(r, 5)
    slope = np.gradient(rs)  # voxels of radius per voxel of height
    base = y0
    limit = y0 + int(0.4 * (y1 - y0))
    for y in range(y0 + 2, limit):
        if slope[y] < max_slope and rs[y] > 0.5 * rs[y0:limit].max():
            base = y
            break
    prof = [round(float(r[y] * vox * 1000), 2) for y in range(y0, min(limit, y0 + 60))]
    return {"base_index": int(base), "raw_bottom_index": y0,
            "skirt_height_m": float((base - y0) * vox),
            "radius_profile_mm_from_bottom": prof}


def occupancy_to_mesh(occ: np.ndarray, grid: Grid, smooth_sigma: float = 1.0, target_faces: int = 40000,
                      taubin_iters: int = 10) -> trimesh.Trimesh:
    field = ndimage.gaussian_filter(occ.astype(np.float32), smooth_sigma)
    field = np.pad(field, 1)  # guarantees a closed surface
    verts, faces, _, _ = measure.marching_cubes(field, 0.5, spacing=tuple(grid.voxel))
    verts = verts - grid.voxel + grid.lo
    m = trimesh.Trimesh(verts, faces[:, ::-1], process=True)  # outward normals
    parts = m.split(only_watertight=False)
    if len(parts) > 1:
        m = max(parts, key=lambda p: p.area)
    trimesh.smoothing.filter_taubin(m, lamb=0.5, nu=-0.53, iterations=taubin_iters)
    if len(m.faces) > target_faces:
        import fast_simplification

        v, f = fast_simplification.simplify(np.asarray(m.vertices, np.float32), np.asarray(m.faces),
                                            target_reduction=1 - target_faces / len(m.faces))
        m = trimesh.Trimesh(v, f, process=True)
    m.fix_normals()
    return m
