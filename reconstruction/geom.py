"""Geometry, meshing, UV and texture-baking utilities.

All modelling is done in millimetres in a Y-up, right-handed frame whose
origin is the centre of the bucket's base. +Z is the bear's front, +X is the
bear's left (viewer's right when looking at the face).
"""
import numpy as np
from scipy import ndimage
from skimage import measure
import fast_simplification
import xatlas


# --------------------------------------------------------------------------
# small vector helpers
# --------------------------------------------------------------------------
def nrm(v, axis=-1):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v, axis=axis, keepdims=True)
    return v / np.maximum(n, 1e-12)


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def rot_axis(axis, ang):
    """Rotation matrix (Rodrigues) for angle in radians."""
    a = nrm(np.asarray(axis, float))
    c, s = np.cos(ang), np.sin(ang)
    x, y, z = a
    return np.array([
        [c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
        [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
        [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)],
    ])


# --------------------------------------------------------------------------
# signed distance primitives (p: (N,3))
# --------------------------------------------------------------------------
def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def sd_ellipsoid(p, c, r):
    r = np.asarray(r, float)
    q = (p - c) / r
    k0 = np.linalg.norm(q, axis=-1)
    k1 = np.linalg.norm(q / r, axis=-1)
    return k0 * (k0 - 1.0) / np.maximum(k1, 1e-9)


def sd_capsule(p, a, b, r):
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    pa = p - a
    ba = b - a
    h = np.clip(pa @ ba / (ba @ ba), 0.0, 1.0)
    return np.linalg.norm(pa - h[:, None] * ba, axis=-1) - r


def sd_sphere(p, c, r):
    return np.linalg.norm(p - c, axis=-1) - r


# --------------------------------------------------------------------------
# 3D gradient noise
# --------------------------------------------------------------------------
class Noise3:
    def __init__(self, seed=0):
        rng = np.random.default_rng(seed)
        perm = rng.permutation(256)
        self.perm = np.concatenate([perm, perm]).astype(np.int64)
        g = rng.normal(size=(256, 3))
        self.grad = g / np.linalg.norm(g, axis=1, keepdims=True)

    def __call__(self, p):
        p = np.asarray(p, np.float64)
        pi = np.floor(p).astype(np.int64)
        pf = p - pi
        pi &= 255
        u = pf * pf * pf * (pf * (pf * 6 - 15) + 10)
        P = self.perm
        out = 0.0
        res = np.zeros(len(p))
        corners = []
        for dx in (0, 1):
            for dy in (0, 1):
                for dz in (0, 1):
                    h = P[P[P[pi[:, 0] + dx] + pi[:, 1] + dy] + pi[:, 2] + dz]
                    g = self.grad[h]
                    d = pf - np.array([dx, dy, dz])
                    corners.append(((dx, dy, dz), np.einsum("ij,ij->i", g, d)))
        vals = {c: v for c, v in corners}
        ux, uy, uz = u[:, 0], u[:, 1], u[:, 2]
        def L(a, b, t):
            return a + (b - a) * t
        x00 = L(vals[(0, 0, 0)], vals[(1, 0, 0)], ux)
        x10 = L(vals[(0, 1, 0)], vals[(1, 1, 0)], ux)
        x01 = L(vals[(0, 0, 1)], vals[(1, 0, 1)], ux)
        x11 = L(vals[(0, 1, 1)], vals[(1, 1, 1)], ux)
        y0 = L(x00, x10, uy)
        y1 = L(x01, x11, uy)
        res = L(y0, y1, uz)
        return res * 1.8  # roughly [-1,1]

    def fbm(self, p, octaves=4, lac=2.03, gain=0.5):
        amp, s, tot, norm = 1.0, 1.0, 0.0, 0.0
        for o in range(octaves):
            tot = tot + amp * self(p * s + o * 17.31)
            norm += amp
            amp *= gain
            s *= lac
        return tot / norm


# --------------------------------------------------------------------------
# meshing
# --------------------------------------------------------------------------
def eval_grid(sdf, lo, hi, h, slab=16):
    xs = np.arange(lo[0], hi[0] + h * 0.5, h)
    ys = np.arange(lo[1], hi[1] + h * 0.5, h)
    zs = np.arange(lo[2], hi[2] + h * 0.5, h)
    vol = np.empty((len(xs), len(ys), len(zs)), np.float32)
    Y, Z = np.meshgrid(ys, zs, indexing="ij")
    for i0 in range(0, len(xs), slab):
        xi = xs[i0:i0 + slab]
        X = np.broadcast_to(xi[:, None, None], (len(xi),) + Y.shape)
        pts = np.stack([X.ravel(),
                        np.broadcast_to(Y, X.shape).ravel(),
                        np.broadcast_to(Z, X.shape).ravel()], 1)
        vol[i0:i0 + slab] = sdf(pts).reshape(len(xi), len(ys), len(zs))
    return vol, np.array([xs[0], ys[0], zs[0]])


def sdf_normals(sdf, V, eps=0.01):
    g = np.zeros_like(V)
    for k in range(3):
        d = np.zeros(3)
        d[k] = eps
        g[:, k] = sdf(V + d) - sdf(V - d)
    return nrm(g)


def mc_mesh(sdf, lo, hi, h, target_tris, project_iters=2):
    """Polygonise an SDF, decimate it, then project vertices back onto the
    exact zero level set so the simplified mesh keeps the true surface."""
    vol, origin = eval_grid(sdf, lo, hi, h)
    V, F, _, _ = measure.marching_cubes(vol, 0.0, spacing=(h, h, h),
                                        gradient_direction="ascent")
    V = V + origin
    F = F.astype(np.int64)
    if len(F) > target_tris:
        V, F = fast_simplification.simplify(V.astype(np.float32), F.astype(np.int32),
                                            target_reduction=1.0 - target_tris / len(F),
                                            agg=5)
        V = V.astype(np.float64)
        F = F.astype(np.int64)
    for _ in range(project_iters):  # Newton projection onto the surface
        d = sdf(V)
        n = sdf_normals(sdf, V)
        V = V - n * d[:, None]
    F = fix_orientation(V, F)
    V, F = clean(V, F)
    return drop_fragments(V, F)


def drop_fragments(V, F, min_faces=50):
    """Topology repair after decimation: weld, drop tiny (edge-connected)
    slivers, and close small boundary loops with a centroid fan."""
    import trimesh
    m = trimesh.Trimesh(V, F, process=True)
    parts = m.split(only_watertight=False)
    m = trimesh.util.concatenate([p for p in parts if len(p.faces) >= min_faces])
    m.merge_vertices()
    V, F = np.asarray(m.vertices, float), np.asarray(m.faces, np.int64)
    V, F = fill_small_holes(V, F)
    return clean(V, F)


def fill_small_holes(V, F, max_edges=64):
    # directed half-edges whose twin is missing form the boundary
    he = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    key = {(a, b) for a, b in he.tolist()}
    border = [(a, b) for a, b in he.tolist() if (b, a) not in key]
    if not border:
        return V, F
    nxt = {}
    for a, b in border:
        nxt.setdefault(a, []).append(b)
    used = set()
    newV, newF = [V], [F]
    nv = len(V)
    for a, b in border:
        if (a, b) in used:
            continue
        loop = [a]
        cur, ok = b, True
        used.add((a, b))
        while cur != a:
            loop.append(cur)
            if len(loop) > max_edges or cur not in nxt:
                ok = False
                break
            n2 = nxt[cur][0]
            used.add((cur, n2))
            cur = n2
        if not ok or len(loop) < 3:
            continue
        c = V[loop].mean(0)
        newV.append(c[None])
        # boundary half-edge (a->b) has its face on the left; the cap uses (b->a)
        tris = [[loop[(i + 1) % len(loop)], loop[i], nv] for i in range(len(loop))]
        newF.append(np.array(tris, np.int64))
        nv += 1
    return np.concatenate(newV), np.concatenate(newF)


def fix_orientation(V, F):
    vol = signed_volume(V, F)
    if vol < 0:
        F = F[:, ::-1].copy()
    return F


def signed_volume(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    return np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6.0


def clean(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    area = np.linalg.norm(np.cross(b - a, c - a), axis=1)
    F = F[(area > 1e-10) & (F[:, 0] != F[:, 1]) & (F[:, 1] != F[:, 2]) & (F[:, 0] != F[:, 2])]
    used = np.unique(F)
    remap = -np.ones(len(V), np.int64)
    remap[used] = np.arange(len(used))
    return V[used], remap[F]


def vertex_normals(V, F):
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    fn = np.cross(b - a, c - a)
    N = np.zeros_like(V)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    return nrm(N)


def weld(V, F, tol=1e-6):
    key = np.round(V / tol).astype(np.int64)
    _, idx, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return V[idx], inv.ravel()[F]


# --------------------------------------------------------------------------
# UVs + tangents
# --------------------------------------------------------------------------
def unwrap(V, F, resolution, padding=4):
    atlas = xatlas.Atlas()
    atlas.add_mesh(V.astype(np.float32), F.astype(np.uint32))
    co = xatlas.ChartOptions()
    co.max_iterations = 2
    po = xatlas.PackOptions()
    po.resolution = resolution
    po.padding = padding
    po.bilinear = True
    po.bruteForce = False
    atlas.generate(co, po)
    vmap, idx, uv = atlas[0]
    return vmap.astype(np.int64), idx.astype(np.int64), uv.astype(np.float64)


def tangents(V, N, UV, F):
    """Per-vertex tangents (xyz,w) following the glTF convention
    (bitangent = cross(N, T) * w points towards decreasing v)."""
    p0, p1, p2 = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    t0, t1, t2 = UV[F[:, 0]], UV[F[:, 1]], UV[F[:, 2]]
    e1, e2 = p1 - p0, p2 - p0
    d1, d2 = t1 - t0, t2 - t0
    r = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    r = np.where(np.abs(r) < 1e-14, 1e-14, r)
    sdir = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / r[:, None]   # dP/du
    tdir = (e2 * d1[:, 0:1] - e1 * d2[:, 0:1]) / r[:, None]   # dP/dv
    T = np.zeros_like(V)
    Bv = np.zeros_like(V)
    for k in range(3):
        np.add.at(T, F[:, k], sdir)
        np.add.at(Bv, F[:, k], tdir)
    T = T - N * np.einsum("ij,ij->i", N, T)[:, None]
    bad = np.linalg.norm(T, axis=1) < 1e-12
    if bad.any():
        alt = np.where(np.abs(N[bad, 0:1]) < 0.9, [[1, 0, 0]], [[0, 1, 0]])
        T[bad] = np.cross(N[bad], alt)
    T = nrm(T)
    w = np.where(np.einsum("ij,ij->i", np.cross(N, T), -Bv) < 0, -1.0, 1.0)
    return np.concatenate([T, w[:, None]], 1)


# --------------------------------------------------------------------------
# rasterise a UV layout -> per-texel triangle id + barycentrics
# --------------------------------------------------------------------------
def raster_uv(UV, F, W, H):
    tri = -np.ones((H, W), np.int64)
    bary = np.zeros((H, W, 3), np.float32)
    P = UV * np.array([W, H]) - 0.5
    A, B, C = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]
    xmin = np.clip(np.floor(np.minimum(np.minimum(A[:, 0], B[:, 0]), C[:, 0])).astype(int), 0, W - 1)
    xmax = np.clip(np.ceil(np.maximum(np.maximum(A[:, 0], B[:, 0]), C[:, 0])).astype(int), 0, W - 1)
    ymin = np.clip(np.floor(np.minimum(np.minimum(A[:, 1], B[:, 1]), C[:, 1])).astype(int), 0, H - 1)
    ymax = np.clip(np.ceil(np.maximum(np.maximum(A[:, 1], B[:, 1]), C[:, 1])).astype(int), 0, H - 1)
    for t in range(len(F)):
        x0, x1, y0, y1 = xmin[t], xmax[t], ymin[t], ymax[t]
        xs = np.arange(x0, x1 + 1)
        ys = np.arange(y0, y1 + 1)
        X, Y = np.meshgrid(xs, ys)
        a, b, c = A[t], B[t], C[t]
        den = (b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1])
        if abs(den) < 1e-12:
            continue
        l0 = ((b[1] - c[1]) * (X - c[0]) + (c[0] - b[0]) * (Y - c[1])) / den
        l1 = ((c[1] - a[1]) * (X - c[0]) + (a[0] - c[0]) * (Y - c[1])) / den
        l2 = 1 - l0 - l1
        m = (l0 >= -1e-4) & (l1 >= -1e-4) & (l2 >= -1e-4)
        if not m.any():
            continue
        yy, xx = Y[m], X[m]
        tri[yy, xx] = t
        bary[yy, xx] = np.stack([l0[m], l1[m], l2[m]], 1)
    return tri, bary


def dilate(img, mask, iters=24):
    """Push texels outward into the empty gutter so mip-maps/bilinear
    filtering never sample the background colour across UV seams."""
    img = img.astype(np.float32).copy()
    m = mask.astype(np.float32)
    if img.ndim == 2:
        img = img[..., None]
    for _ in range(iters):
        if m.min() > 0:
            break
        acc = np.stack([ndimage.uniform_filter(img[..., c] * m, 3) for c in range(img.shape[2])], -1)
        cnt = ndimage.uniform_filter(m, 3)
        fill = (m == 0) & (cnt > 1e-6)
        img[fill] = acc[fill] / cnt[fill][:, None]
        m = np.where(fill, 1.0, m)
    if (m == 0).any():
        img[m == 0] = img[m > 0].mean(0)
    return img.squeeze()


class Baker:
    """Surface-space texture baking for an unwrapped mesh: every texel gets
    its exact 3D position, interpolated normal and tangent frame, so
    procedural materials can be evaluated as *solid* (3D) textures with no
    seams across UV chart boundaries."""

    def __init__(self, V, N, TAN, UV, F, size):
        self.size = size
        tri, bary = raster_uv(UV, F, size, size)
        self.mask = tri >= 0
        t = tri[self.mask]
        b = bary[self.mask].astype(np.float64)
        f = F[t]
        def interp(A):
            return (A[f[:, 0]] * b[:, 0:1] + A[f[:, 1]] * b[:, 1:2] + A[f[:, 2]] * b[:, 2:3])
        self.P = interp(V)
        self.N = nrm(interp(N))
        T = interp(TAN[:, :3])
        T = nrm(T - self.N * np.einsum("ij,ij->i", self.N, T)[:, None])
        self.T = T
        w = np.sign(interp(TAN[:, 3:4]))
        w[w == 0] = 1
        self.B = np.cross(self.N, self.T) * w

    def to_image(self, vals, fill=None):
        vals = np.asarray(vals, np.float32)
        ch = 1 if vals.ndim == 1 else vals.shape[1]
        img = np.zeros((self.size, self.size, ch), np.float32)
        img[self.mask] = vals.reshape(-1, ch)
        return dilate(img, self.mask)

    def normal_from_height(self, hfn, strength=1.0, eps=0.01):
        """Bake a tangent-space normal map from a 3D height function."""
        P, N = self.P, self.N
        g = np.zeros_like(P)
        for k in range(3):
            d = np.zeros(3)
            d[k] = eps
            g[:, k] = (hfn(P + d) - hfn(P - d)) / (2 * eps)
        gs = g - N * np.einsum("ij,ij->i", N, g)[:, None]
        n = nrm(N - strength * gs)
        ts = np.stack([np.einsum("ij,ij->i", n, self.T),
                       np.einsum("ij,ij->i", n, self.B),
                       np.einsum("ij,ij->i", n, N)], 1)
        ts = nrm(ts)
        img = self.to_image(ts)
        img = nrm(img)
        return img * 0.5 + 0.5


def ao_from_sdf(scene_sdf, P, N, steps=(0.6, 1.4, 2.8, 5.0, 8.0, 12.0), k=1.15):
    """Ambient occlusion estimated from the scene distance field along the
    surface normal (standard SDF AO)."""
    occ = np.zeros(len(P))
    wsum = 0.0
    for i, d in enumerate(steps):
        w = 1.0 / (1.0 + i * 0.6)
        s = scene_sdf(P + N * d)
        occ += w * np.clip((d - s) / d, 0, 1)
        wsum += w
    return np.clip(1.0 - k * occ / wsum, 0.0, 1.0)


def normal_map_from_height_image(h, strength):
    """Tangent-space normal map from an image-space height map (rows go
    down = +v). Green encodes the image-up direction (glTF convention)."""
    gy, gx = np.gradient(h.astype(np.float64))
    n = np.stack([-gx * strength, gy * strength, np.ones_like(h)], -1)
    n = nrm(n)
    return n * 0.5 + 0.5
