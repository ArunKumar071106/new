"""Geometry of every physical component.

Organic / moulded parts are defined as signed distance fields (exact
zero-level surfaces, smooth blends where the real object has fillets) and
polygonised later; thin fabric parts (ribbon bow, hat) are built as
parametric surfaces with real thickness.
"""
import numpy as np
from geom import (nrm, smin, smax, sd_ellipsoid, sd_capsule, sd_sphere, rot_axis,
                  smoothstep, sdf_normals)
from dims import (BUCKET, bucket_r_body, bucket_r_out, HEAD_C, HEAD_R, HEAD_ROLL_DEG,
                  BODY_C, BODY_R, HAT_N, HAT_R, HAT_CROWN_R, HAT_CROWN_H, HAT_THICK)

# =============================================================================
# Bucket
# =============================================================================
_B = BUCKET
_SLOPE = (_B["r_top"] - _B["r_bot"]) / _B["band_start"]
_COSA = 1.0 / np.sqrt(1 + _SLOPE ** 2)
_RIM_R = _B["r_top"] + _B["band_flare"]

# rim-top height as a function of arc length from a tab centre (lookup table)
_S_TAB = np.linspace(-40, 40, 8001)
def _rim_profile(s):
    arch = _B["H"] + _B["tab_h"] * np.sqrt(np.clip(1 - (s / _B["tab_w"]) ** 2, 0, 1))
    return smax(np.full_like(s, _B["H"]), arch, 1.7)
_TOP_TAB = _rim_profile(_S_TAB)
_DTOP_TAB = np.clip(np.gradient(_TOP_TAB, _S_TAB), -12, 12)


def bucket_top(phi):
    """Rim top height and slope for polar angle phi (tabs at +X and -X)."""
    d0 = np.angle(np.exp(1j * phi))                # distance to +X tab
    d1 = np.angle(np.exp(1j * (phi - np.pi)))      # distance to -X tab
    d = np.where(np.abs(d0) < np.abs(d1), d0, d1)
    s = d * _RIM_R
    return np.interp(s, _S_TAB, _TOP_TAB), np.interp(s, _S_TAB, _DTOP_TAB)


def bucket_sdf(p):
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    rho = np.sqrt(x * x + z * z)
    outer = smax((rho - bucket_r_out(y)) * _COSA, -y, _B["base_fillet"])
    cav = smax((rho - (bucket_r_body(y) - _B["wall"])) * _COSA, _B["floor"] - y, 1.0)
    shell = smax(outer, -cav, 0.2)
    top, dtop = bucket_top(np.arctan2(z, x))
    d_top = (y - top) / np.sqrt(1 + dtop ** 2)
    shell = smax(shell, d_top, 0.42)
    for side in (1.0, -1.0):
        dh = np.sqrt((y - _B["hole_y"]) ** 2 + z * z) - _B["hole_r"]
        dh = np.where(side * x > 0, dh, 1e3)
        shell = smax(shell, -dh, 0.18)
    return shell


BUCKET_BOX = (np.array([-31.6, -0.4, -31.6]), np.array([31.6, 68.2, 31.6]))

# =============================================================================
# Bear (flocked figure)
# =============================================================================
R_HEAD = rot_axis([0, 0, 1], np.radians(HEAD_ROLL_DEG))


def head_local(p):
    return (p - HEAD_C) @ R_HEAD


def head_world(q):
    return q @ R_HEAD.T + HEAD_C


MUZZLE = (np.array([-1.0, -8.3, 11.3]), np.array([9.3, 6.9, 8.8]))
EAR_R = (np.array([-13.9, 14.8, -1.0]), np.array([5.6, 5.4, 3.5]))   # bear's right ear
ARMS = [((s * 14.0, 74.5, 3.0), (s * 21.3, 63.8, 7.0), 5.4) for s in (-1.0, 1.0)]


def bear_parts(p):
    q = head_local(p)
    head = sd_ellipsoid(q, np.zeros(3), HEAD_R)
    muzzle = sd_ellipsoid(q, *MUZZLE)
    ear = sd_ellipsoid(q, *EAR_R)
    body = sd_ellipsoid(p, BODY_C, BODY_R)
    arms = [sd_capsule(p, a, b, r) for a, b, r in ARMS]
    return head, muzzle, ear, body, arms


def bear_sdf(p):
    head, muzzle, ear, body, arms = bear_parts(p)
    d = smin(head, muzzle, 3.0)
    d = smin(d, ear, 1.6)
    d = smin(d, body, 6.0)
    for a in arms:
        d = smin(d, a, 2.5)
    return d


BEAR_BOX = (np.array([-28.5, 34.0, -20.5]), np.array([28.5, 120.5, 23.0]))


def surface_point_local(x, y, sdf=bear_sdf, z0=40.0):
    """March from the front (+Z in head space) to the bear surface."""
    z = z0
    for _ in range(200):
        pw = head_world(np.array([[x, y, z]]))
        d = sdf(pw)[0]
        if abs(d) < 1e-4:
            break
        z -= d * 0.8
    pw = head_world(np.array([[x, y, z]]))
    return pw[0], sdf_normals(sdf, pw)[0]


# eye / nose beads: (head-local x, y), radius, embed depth
BEADS = {
    "eye_right": ((-11.1, 2.9), 3.8, 1.55),
    "eye_left": ((13.5, 2.6), 3.8, 1.55),
    "nose": ((-2.2, -8.6), 3.5, 1.45),
}


def bead_placements():
    out = {}
    for name, ((x, y), r, emb) in BEADS.items():
        ps, n = surface_point_local(x, y)
        out[name] = (ps - n * emb, n, r)
    return out


# =============================================================================
# Hat (parametric, revolved)
# =============================================================================
def hat_profile(nseg_top=72):
    """(r, z) polyline from the crown centre over the top surface, around the
    bound edge and back under the brim to the centre, plus the index where the
    top (printed) surface ends."""
    R, Rc, Hc, T = HAT_R, HAT_CROWN_R, HAT_CROWN_H, HAT_THICK
    droop = 1.1
    def brim_drop(r):
        t = np.clip((r - Rc) / (R - Rc), 0, 1)
        return -droop * t ** 2
    def top_z(r):
        crown = T + Hc * np.clip(1 - (r / Rc) ** 2.3, 0, 1) ** 0.55
        brim = T + brim_drop(r)
        # stitched seam: shallow groove on the brim
        brim = brim - 0.16 * np.exp(-((r - 0.875 * R) / 0.35) ** 2)
        return smax(brim, crown, 0.9)
    # dense sampling near the crown edge
    r_top = np.unique(np.concatenate([np.linspace(0, R - T / 2, nseg_top),
                                      np.linspace(Rc - 2.2, Rc + 1.5, 16)]))
    top = np.stack([r_top, top_z(r_top)], 1)
    # bound edge: half round from top to bottom
    zc_top = top[-1, 1]
    zc_bot = brim_drop(r_top[-1])
    zc = 0.5 * (zc_top + zc_bot)
    rad = 0.5 * (zc_top - zc_bot)
    ang = np.linspace(np.pi / 2, -np.pi / 2, 15)[1:-1]
    edge = np.stack([r_top[-1] + (rad + 0.12) * np.cos(ang), zc + rad * np.sin(ang)], 1)
    r_bot = np.unique(np.concatenate([np.linspace(0, r_top[-1], 26), [Rc]]))[::-1]
    bot = np.stack([r_bot, brim_drop(r_bot)], 1)
    prof = np.concatenate([top, edge, bot], 0)
    n_top = len(top) + len(edge) // 2
    return prof, n_top


def revolve(prof, nseg):
    """Revolve a (r,z) polyline around +z. First/last points must have r=0."""
    ang = np.linspace(0, 2 * np.pi, nseg, endpoint=False)
    V, ring_idx = [], []
    for i, (r, z) in enumerate(prof):
        if r < 1e-9:
            ring_idx.append([len(V)])
            V.append([0, 0, z])
        else:
            ring_idx.append(list(range(len(V), len(V) + nseg)))
            V.extend(np.stack([r * np.cos(ang), r * np.sin(ang), np.full(nseg, z)], 1).tolist())
    V = np.array(V)
    F, Fseg = [], []
    for i in range(len(prof) - 1):
        a, b = ring_idx[i], ring_idx[i + 1]
        for j in range(nseg):
            j1 = (j + 1) % nseg
            if len(a) == 1:
                F.append([a[0], b[j], b[j1]])
            elif len(b) == 1:
                F.append([a[j], b[0], a[j1]])
            else:
                F.append([a[j], b[j], b[j1]])
                F.append([a[j], b[j1], a[j1]])
                Fseg.append(i)
                Fseg.append(i)
                continue
            Fseg.append(i)
    return V, np.array(F, np.int64), np.array(Fseg), ring_idx


def hat_frame():
    n = nrm(HAT_N)
    up = np.array([0.0, 1.0, 0.0])
    yl = nrm(up - n * (n @ up))
    xl = np.cross(yl, n)
    return xl, yl, n


# =============================================================================
# Ribbon bow (parametric strips with thickness)
# =============================================================================
RIBBON_T = 0.32
BOW_TILE_MM = 24.0      # texture tile length along the ribbon
BOW_WIDTH_MM = 20.0     # texture tile width (full ribbon width)


def _strip_solid(S, U, thickness, closed_u=True):
    """S: (nu, ns, 3) mid-surface of a ribbon; returns closed solid mesh with
    UVs (outer face, inner face and the two selvedge edges)."""
    nu, ns, _ = S.shape
    du = np.roll(S, -1, 0) - np.roll(S, 1, 0)
    dv = np.gradient(S, axis=1)
    N = nrm(np.cross(du, dv))
    top = S + N * thickness / 2
    bot = S - N * thickness / 2
    Vs, UVs, Fs = [], [], []
    def grid(P, uv, flip):
        base = sum(len(v) for v in Vs)
        Vs.append(P.reshape(-1, 3))
        UVs.append(uv.reshape(-1, 2))
        f = []
        jj = nu if closed_u else nu - 1
        for i in range(jj):
            i1 = (i + 1) % nu
            for k in range(P.shape[1] - 1):
                a, b, c, d = i * P.shape[1] + k, i1 * P.shape[1] + k, i1 * P.shape[1] + k + 1, i * P.shape[1] + k + 1
                f += [[a, b, c], [a, c, d]] if not flip else [[a, c, b], [a, d, c]]
        Fs.append(np.array(f) + base)
    grid(top, U, False)
    grid(bot, U, True)
    # selvedges
    for k, flip in ((0, True), (ns - 1, False)):
        P = np.stack([top[:, k], bot[:, k]], 1)
        uv = np.stack([U[:, k], U[:, k]], 1)
        grid(P, uv, flip)
    V = np.concatenate(Vs)
    UV = np.concatenate(UVs)
    F = np.concatenate(Fs)
    return V, UV, F


def bow_geometry(knot_center, push=None):
    """Two looped wings + a gathered centre knot."""
    parts = []
    nth, ns = 120, 18
    th = np.linspace(0, 2 * np.pi, nth, endpoint=False)
    s = np.linspace(-1, 1, ns)
    TH, Sg = np.meshgrid(th, s, indexing="ij")
    wings = {-1: dict(L=18.0, wt=19.0, tilt=9.0), 1: dict(L=16.5, wt=16.5, tilt=7.0)}
    for side, w in wings.items():
        L, wt = w["L"], w["wt"]
        xi = (1 - np.cos(TH)) / 2
        x = 2.4 + (L - 2.4) * xi
        D = 2.5
        z = D * np.sin(TH)
        width = 7.0 + (wt - 7.0) * xi ** 0.55
        y = Sg * width / 2
        # puff: the loop bulges away from its own centre line
        bulge = 0.9 * (1 - Sg ** 2) * np.sin(np.pi * xi) ** 0.8
        z = z + np.sign(np.sin(TH)) * bulge * np.abs(np.sin(TH)) ** 0.3
        P = np.stack([x, y, z], -1)
        # raise wings slightly, mirror to the side, and wrap round the neck
        Rz = rot_axis([0, 0, 1], np.radians(w["tilt"]))
        P = P @ Rz.T
        P[..., 0] *= side
        P[..., 2] -= 0.017 * P[..., 0] ** 2
        P = P + knot_center
        # UVs: arc length along the loop at the mid line / tile size
        mid = P[:, ns // 2]
        seg = np.linalg.norm(np.diff(np.concatenate([mid, mid[:1]]), axis=0), axis=1)
        arc = np.concatenate([[0], np.cumsum(seg)[:-1]])
        U = np.stack([np.repeat(arc[:, None], ns, 1) / BOW_TILE_MM + (0.31 if side > 0 else 0.0),
                      (Sg + 1) / 2], -1)
        parts.append(("wing_" + ("left" if side > 0 else "right"), P, U))
    # knot: band around the gathered centre (loop in the YZ plane)
    nk, nsk = 72, 12
    ph = np.linspace(0, 2 * np.pi, nk, endpoint=False)
    sk = np.linspace(-1, 1, nsk)
    PH, SK = np.meshgrid(ph, sk, indexing="ij")
    barrel = 1 + 0.14 * (1 - SK ** 2)
    yk = 4.7 * np.cos(PH) * barrel
    zk = 3.3 * np.sin(PH) * barrel
    xk = SK * 4.4
    P = np.stack([xk, yk, zk], -1) + knot_center
    mid = P[:, nsk // 2]
    seg = np.linalg.norm(np.diff(np.concatenate([mid, mid[:1]]), axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)[:-1]])
    U = np.stack([np.repeat(arc[:, None], nsk, 1) / BOW_TILE_MM,
                  0.5 + SK * (8.8 / BOW_WIDTH_MM) / 2], -1)
    parts.append(("knot", P, U))
    out = []
    for name, P, U in parts:
        if push is not None:
            P = push(P.reshape(-1, 3)).reshape(P.shape)
        V, UV, F = _strip_solid(P, U, RIBBON_T)
        out.append((name, V, UV, F))
    return out


# =============================================================================
# Flower + leaves (moulded plastic, SDF)
# =============================================================================
class Flower:
    def __init__(self, base, axis, length=10.5):
        self.base = np.asarray(base, float)
        self.a = nrm(np.asarray(axis, float))
        up = np.array([0, 1.0, 0])
        self.e1 = nrm(np.cross(up, self.a))
        self.e2 = np.cross(self.a, self.e1)
        self.L = length
        self.t = 0.45
        # leaves: (base offset (world), direction, normal-ish, length, half-width)
        b = self.base + self.a * 1.2
        self.leaves = [
            (b + np.array([-1.2, -1.5, 0.6]), nrm([-0.75, -0.55, 0.35]), nrm([0.2, -0.3, 1.0]), 9.5, 2.6),
            (b + np.array([1.4, -1.8, 0.2]), nrm([0.55, -0.75, 0.25]), nrm([-0.1, -0.2, 1.0]), 9.0, 2.7),
        ]
        self.stem = (self.base - self.a * 4.5, self.base + self.a * 0.5, 0.75)

    def local(self, p):
        d = p - self.base
        w = d @ self.a
        u = d @ self.e1
        v = d @ self.e2
        return w, np.sqrt(u * u + v * v), np.arctan2(v, u)

    def prof(self, w):
        L = self.L
        t = np.clip(w / L, 0, 1.2)
        r = 1.6 + 3.9 * t ** 1.45 + 1.15 * smoothstep(0.70, 1.05, t) ** 1.6
        return r

    def petal_len(self, th):
        c = np.abs(np.cos(3 * th))
        return self.L * (0.80 + 0.20 * c ** 0.45)

    def parts(self, p):
        w, rho, th = self.local(p)
        eps = 0.02
        rp = self.prof(w)
        dr = (self.prof(w + eps) - self.prof(w - eps)) / (2 * eps)
        shell = np.abs(rho - rp) / np.sqrt(1 + dr * dr) - self.t / 2
        cap = (w - self.petal_len(th)) / np.sqrt(1 + 0.0)
        corolla = smax(smax(shell, cap, 0.25), -w - 0.2, 0.3)
        recept = sd_ellipsoid(p, self.base + self.a * 0.3, np.array([2.0, 2.0, 2.0]))
        stamen = smin(sd_capsule(p, self.base, self.base + self.a * 5.2, 0.5),
                      sd_sphere(p, self.base + self.a * 5.4, 0.85), 0.4)
        stem = sd_capsule(p, *self.stem)
        leaves = [self.leaf_sdf(p, *lf) for lf in self.leaves]
        return corolla, recept, stamen, stem, leaves

    def leaf_sdf(self, p, b, d, nrm_hint, L, hw):
        d = nrm(d)
        n = nrm(nrm_hint - d * (nrm_hint @ d))
        side = np.cross(n, d)
        q = p - b
        u = q @ d
        v = q @ side
        h = q @ n
        uc = np.clip(u / L, 0, 1)
        width = hw * np.sin(np.pi * np.clip(uc, 0.0, 1.0)) ** 0.75
        saw = (u * 1.45) % 1.0
        width = width * (1 + 0.20 * (saw - 0.5))
        bend = 0.07 * v * v - 0.035 * u * u * 0.3
        d_thick = np.abs(h - bend) - 0.2
        d_out = np.abs(v) - width
        d_len = np.maximum(-u, u - L)
        return smax(smax(d_thick, d_out, 0.15), d_len, 0.15)

    def sdf(self, p):
        corolla, recept, stamen, stem, leaves = self.parts(p)
        d = smin(corolla, recept, 0.6)
        d = np.minimum(d, stamen)
        d = smin(d, stem, 0.5)
        for lf in leaves:
            d = smin(d, lf, 0.35)
        return d

    def region(self, p):
        corolla, recept, stamen, stem, leaves = self.parts(p)
        ds = np.stack([np.minimum(corolla, recept), stamen, stem, leaves[0], leaves[1]], 1)
        return np.argmin(ds, 1)

    def box(self):
        c = self.base + self.a * 4
        return c - 14.0, c + 14.0
