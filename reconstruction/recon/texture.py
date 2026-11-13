"""UV unwrapping and multi-view texture baking.

Each texel's 3D position is projected into every photograph; colours are blended with
weights favouring views that see the surface head-on, are not occluded, and are not
near a silhouette edge (where background bleeds in). Surfaces no photograph sees (the
underside) are filled by diffusing colour from neighbouring observed surface and are
reported as inferred.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import scipy.sparse as sp
import xatlas
from scipy import ndimage

from .cameras import Camera
from .photo import sample_bilinear


@dataclass
class TexturedMesh:
    vertices: np.ndarray  # (V,3) after UV seam splitting
    normals: np.ndarray
    faces: np.ndarray
    uvs: np.ndarray  # OpenGL convention (v up)
    texture: np.ndarray  # RGB uint8
    stats: dict


def unwrap(vertices: np.ndarray, faces: np.ndarray, resolution: int):
    # xatlas uses absolute epsilons: metre-scale meshes (areas ~1e-7) get shattered into
    # thousands of one-triangle charts. UVs are scale-invariant, so unwrap a normalised copy.
    v = vertices - vertices.mean(0)
    v = v * (100.0 / max(np.ptp(v, axis=0).max(), 1e-12))
    atlas = xatlas.Atlas()
    atlas.add_mesh(v.astype(np.float32), faces.astype(np.uint32))
    po = xatlas.PackOptions()
    po.resolution = resolution
    po.padding = 4
    po.bilinear = True
    co = xatlas.ChartOptions()
    atlas.generate(chart_options=co, pack_options=po)
    vmap, idx, uvs = atlas[0]
    return vmap, idx.astype(np.int64), uvs


def rasterize_uv(faces: np.ndarray, uvs: np.ndarray, res: int):
    """Return per-texel face id (-1 = empty) and barycentric coordinates."""
    fid = np.full((res, res), -1, np.int32)
    pix = np.stack([uvs[:, 0] * res - 0.5, (1 - uvs[:, 1]) * res - 0.5], 1)
    tri = pix[faces]
    fixed = np.round(tri * 16).astype(np.int32)  # 4 bits sub-pixel precision
    for i in range(len(faces)):
        cv2.fillConvexPoly(fid, fixed[i], int(i), lineType=cv2.LINE_8, shift=4)
    ys, xs = np.nonzero(fid >= 0)
    f = fid[ys, xs]
    a, b, c = tri[f, 0], tri[f, 1], tri[f, 2]
    p = np.stack([xs, ys], 1).astype(np.float64)
    v0, v1, v2 = b - a, c - a, p - a
    d00 = (v0 * v0).sum(1); d01 = (v0 * v1).sum(1); d11 = (v1 * v1).sum(1)
    d20 = (v2 * v0).sum(1); d21 = (v2 * v1).sum(1)
    den = d00 * d11 - d01 * d01
    den[np.abs(den) < 1e-12] = 1e-12
    w1 = (d11 * d20 - d01 * d21) / den
    w2 = (d00 * d21 - d01 * d20) / den
    bary = np.clip(np.stack([1 - w1 - w2, w1, w2], 1), 0, 1)
    bary /= bary.sum(1, keepdims=True)
    return fid, ys, xs, f, bary


def vertex_visibility(V: np.ndarray, N: np.ndarray, cam: Camera, field: np.ndarray, lo: np.ndarray,
                      voxel: float) -> np.ndarray:
    """Ray-march from each vertex towards the camera through the smoothed occupancy field."""
    d = cam.C[None] - V
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    vis = (N * d).sum(1) > 0.0
    ids = np.nonzero(vis)[0]
    start = V[ids] + N[ids] * 1.5 * voxel
    shape = np.array(field.shape)
    for k in range(int(np.linalg.norm(shape)) + 2):
        q = (start + d[ids] * (k * 0.75 * voxel) - lo) / voxel
        inside = np.all((q >= 0) & (q <= shape - 1), 1)
        if not inside.any():
            break
        val = np.zeros(len(ids), np.float32)
        val[inside] = ndimage.map_coordinates(field, q[inside].T, order=1)
        hit = val > 0.5
        vis[ids[hit]] = False
        ids, start = ids[~hit], start[~hit]
        if len(ids) == 0:
            break
    return vis


def diffuse_vertex_colours(colours: np.ndarray, known: np.ndarray, faces: np.ndarray, n_vert: int,
                           iters: int = 400) -> np.ndarray:
    """Fill unknown vertex colours by repeated neighbour averaging (harmonic-like fill)."""
    e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    A = sp.coo_matrix((np.ones(len(e) * 2), (np.r_[e[:, 0], e[:, 1]], np.r_[e[:, 1], e[:, 0]])),
                      shape=(n_vert, n_vert)).tocsr()
    A.data[:] = 1
    deg = np.asarray(A.sum(1)).ravel()
    deg[deg == 0] = 1
    c = colours.copy()
    c[~known] = colours[known].mean(0) if known.any() else 128
    for _ in range(iters):
        nc = (A @ c) / deg[:, None]
        c[~known] = nc[~known]
    return c


def bake(mesh_v: np.ndarray, mesh_f: np.ndarray, mesh_n: np.ndarray, cams: dict[str, Camera],
         images: dict[str, np.ndarray], masks: dict[str, np.ndarray], confidence: dict[str, float],
         field: np.ndarray, lo: np.ndarray, voxel: float, resolution: int = 2048,
         sharpness: float = 4.0, log=print) -> TexturedMesh:
    vmap, faces, uvs = unwrap(mesh_v, mesh_f, resolution)
    V, N = mesh_v[vmap], mesh_n[vmap]
    log(f"  UV atlas: {len(V)} vertices after seam split, {resolution}px")

    fid, ys, xs, f, bary = rasterize_uv(faces, uvs, resolution)
    P = (V[faces[f]] * bary[:, :, None]).sum(1)
    Nt = (N[faces[f]] * bary[:, :, None]).sum(1)
    Nt /= np.maximum(np.linalg.norm(Nt, axis=1, keepdims=True), 1e-9)

    acc = np.zeros((len(P), 3))
    wsum = np.zeros(len(P))
    best_view = np.full(len(P), -1, np.int8)
    best_w = np.zeros(len(P))
    vert_acc = np.zeros((len(V), 3))
    vert_w = np.zeros(len(V))
    names = list(cams)
    for vi, n in enumerate(names):
        cam, img, msk = cams[n], images[n], masks[n]
        vis_v = vertex_visibility(V, N, cam, field, lo, voxel).astype(np.float32)
        vis_t = (vis_v[faces[f]] * bary).sum(1)
        to_cam = cam.C[None] - P
        to_cam /= np.linalg.norm(to_cam, axis=1, keepdims=True)
        cos = np.clip((Nt * to_cam).sum(1), 0, 1)
        uv, _ = cam.project(P)
        dt = cv2.distanceTransform((msk > 0).astype(np.uint8), cv2.DIST_L2, 5)
        edge = sample_bilinear(dt[..., None].astype(np.float32), uv)[:, 0]
        edge = np.clip(np.nan_to_num(edge, nan=0.0) / (0.012 * max(msk.shape)), 0, 1)
        col = sample_bilinear(img.astype(np.float32), uv)
        ok = ~np.isnan(col).any(1)
        w = np.where(ok, (vis_t ** 2) * (cos ** sharpness) * edge * confidence.get(n, 1.0), 0.0)
        w = np.where(vis_t > 0.5, w, 0.0)
        acc[ok] += col[ok] * w[ok, None]
        wsum += w
        upd = w > best_w
        best_w[upd], best_view[upd] = w[upd], vi
        # per-vertex colours (used to fill unobserved surface)
        uvv, _ = cam.project(V)
        cv_ = sample_bilinear(img.astype(np.float32), uvv)
        tv = cam.C[None] - V
        tv /= np.linalg.norm(tv, axis=1, keepdims=True)
        wv = vis_v * np.clip((N * tv).sum(1), 0, 1) ** sharpness
        okv = ~np.isnan(cv_).any(1)
        vert_acc[okv] += cv_[okv] * wv[okv, None]
        vert_w += np.where(okv, wv, 0)
        log(f"  baked {n}: covers {100 * (w > 1e-3).mean():.1f}% of texels")

    observed = wsum > 1e-4
    colours = np.zeros((len(P), 3))
    colours[observed] = acc[observed] / wsum[observed, None]
    known_v = vert_w > 1e-3
    vcol = np.zeros((len(V), 3))
    vcol[known_v] = vert_acc[known_v] / vert_w[known_v, None]
    vcol = diffuse_vertex_colours(vcol, known_v, faces, len(V))
    fill = (vcol[faces[f[~observed]]] * bary[~observed, :, None]).sum(1)
    colours[~observed] = fill

    tex = np.zeros((resolution, resolution, 3), np.uint8)
    tex[ys, xs] = np.clip(colours, 0, 255).astype(np.uint8)[:, ::-1]  # BGR -> RGB
    # pad islands so bilinear/mipmap sampling never reads empty texels
    empty = (fid < 0).astype(np.uint8)
    tex = cv2.inpaint(tex, empty, 3, cv2.INPAINT_TELEA) if empty.any() else tex
    # area statistics
    tri_area = np.linalg.norm(np.cross(V[faces[:, 1]] - V[faces[:, 0]], V[faces[:, 2]] - V[faces[:, 0]]), axis=1) / 2
    face_obs = np.zeros(len(faces))
    np.add.at(face_obs, f, observed.astype(float))
    face_cnt = np.bincount(f, minlength=len(faces)).astype(float)
    frac = np.divide(face_obs, face_cnt, out=np.ones(len(faces)), where=face_cnt > 0)
    stats = {
        "texels_used": int(len(P)),
        "observed_surface_fraction": float((tri_area * frac).sum() / tri_area.sum()),
        "inferred_surface_fraction": float((tri_area * (1 - frac)).sum() / tri_area.sum()),
        "dominant_view_share": {n: float((best_view == i).mean()) for i, n in enumerate(names)},
    }
    return TexturedMesh(V, N, faces, uvs, tex, stats)
