"""Build the textured GLB reconstruction of the flocked teddy bear in the
pink "Lover Grass" gift bucket.

usage:  python build.py [--quick] [--out ../output/teddy_bear_bucket.glb]
"""
import argparse
import json
import os
import time
import numpy as np
from scipy import ndimage

import geom as G
from geom import nrm, Noise3, smoothstep
import parts as PT
from dims import BUCKET, bucket_r_out, HAT_R
from photo_textures import sticker_texture, hat_texture
from gltf_writer import GLBWriter

HERE = os.path.dirname(os.path.abspath(__file__))
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


def s2l(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def l2s(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


NOISE = Noise3(11)
NOISE2 = Noise3(23)

# ----------------------------------------------------------------- colours (sRGB, from photos)
C_BUCKET = np.array([0.925, 0.680, 0.795])
C_BEAR = np.array([0.950, 0.936, 0.910])
C_HAT = np.array([0.80, 0.70, 0.86])
C_HAT_UNDER = np.array([0.935, 0.905, 0.945])
C_RIBBON = np.array([0.72, 0.655, 0.875])
C_DOT = np.array([0.935, 0.895, 0.845])
C_PETAL = np.array([0.86, 0.12, 0.50])
C_PETAL_IN = np.array([0.74, 0.10, 0.37])
C_PETAL_EDGE = np.array([0.96, 0.62, 0.80])
C_STAMEN = np.array([0.98, 0.72, 0.18])
C_STEM = np.array([0.62, 0.70, 0.20])
C_LEAF1 = np.array([0.90, 0.85, 0.18])
C_LEAF2 = np.array([0.88, 0.66, 0.16])


def pack_orm(ao, rough, metal):
    return np.stack([ao, rough, metal], -1)


def sdf_part(name, sdf, box, h, target, texsize, shader, scene_sdf, normal_strength):
    log(f"{name}: meshing (voxel {h} mm)")
    V, F = G.mc_mesh(sdf, box[0], box[1], h, target)
    N = G.sdf_normals(sdf, V)
    log(f"{name}: {len(F)} tris, unwrapping")
    vmap, F2, UV = G.unwrap(V, F, texsize)
    V2, N2 = V[vmap], N[vmap]
    TAN = G.tangents(V2, N2, UV, F2)
    log(f"{name}: baking {texsize}^2 textures")
    bk = G.Baker(V2, N2, TAN, UV, F2, texsize)
    ao = G.ao_from_sdf(scene_sdf, bk.P, bk.N) if scene_sdf is not None else np.ones(len(bk.P))
    bk.ao = ao
    out = shader(bk)
    alb = bk.to_image(out["albedo"])
    orm = bk.to_image(pack_orm(ao, out["rough"], out["metal"]))
    nmap = bk.normal_from_height(out["height"], normal_strength) if out.get("height") else None
    return dict(V=V2, N=N2, UV=UV, TAN=TAN, F=F2), dict(albedo=alb, orm=orm, normal=nmap)


def push_out(sdf, clearance):
    def f(P):
        P = P.copy()
        for _ in range(4):
            d = sdf(P)
            m = d < clearance
            if not m.any():
                break
            n = G.sdf_normals(sdf, P[m])
            P[m] += n * (clearance - d[m])[:, None]
        return P
    return f


def uv_sphere(c, r, n_axis, squash=0.9, nu=48, nv=24):
    th = np.linspace(0, np.pi, nv + 1)
    ph = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    V = [[0, 0, 1]]
    for t in th[1:-1]:
        for p in ph:
            V.append([np.sin(t) * np.cos(p), np.sin(t) * np.sin(p), np.cos(t)])
    V.append([0, 0, -1])
    V = np.array(V)
    F = []
    for j in range(nu):
        F.append([0, 1 + j, 1 + (j + 1) % nu])
    for i in range(nv - 2):
        a0, b0 = 1 + i * nu, 1 + (i + 1) * nu
        for j in range(nu):
            j1 = (j + 1) % nu
            F += [[a0 + j, b0 + j, b0 + j1], [a0 + j, b0 + j1, a0 + j1]]
    last = len(V) - 1
    base = 1 + (nv - 2) * nu
    for j in range(nu):
        F.append([base + j, last, base + (j + 1) % nu])
    F = np.array(F)
    # local z -> n_axis, squash along it (dome-shaped bead)
    z = nrm(n_axis)
    x = nrm(np.cross([0, 1, 0], z) if abs(z[1]) < 0.95 else np.cross([1, 0, 0], z))
    y = np.cross(z, x)
    Vl = V * np.array([r, r, r * squash])
    Nl = nrm(V / np.array([r, r, r * squash]) * r)
    M = np.stack([x, y, z], 1)
    return Vl @ M.T + c, Nl @ M.T, F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "output", "teddy_bear_bucket.glb"))
    args = ap.parse_args()
    q = args.quick
    TEX = 512 if q else 2048
    TEX_S = 512 if q else 1024
    stats = {"parts": {}}

    # ------------------------------------------------------------ placements
    beads = PT.bead_placements()
    # hat: crown direction n, in-plane offset, then slide along n until the
    # underside just beds 0.7 mm into the flock (it is glued on)
    xl, yl, n = PT.hat_frame()
    prof, n_top = PT.hat_profile()
    HV, HF, Hseg, _ = PT.revolve(prof, 72 if q else 128)
    _r = np.linalg.norm(HV[:, :2], axis=1)
    _a = np.arctan2(HV[:, 1], HV[:, 0])
    _t = np.clip((_r - PT.HAT_CROWN_R) / (HAT_R - PT.HAT_CROWN_R), 0, 1) ** 1.6
    HV[:, 2] += _t * (0.55 * np.sin(2 * _a + 0.7) + 0.30 * np.sin(3 * _a + 2.1) + 0.15 * np.sin(5 * _a + 0.4))
    e_out = nrm(np.array([1.0, 0, 0]) - n * n[0])
    def hat_world(t):
        O = PT.HEAD_C + n * t + e_out * 5.0
        return O + HV[:, :1] * xl + HV[:, 1:2] * yl + HV[:, 2:3] * n, O
    under = np.nonzero(Hseg >= n_top)[0]
    under_v = np.unique(HF[under])
    lo, hi = 5.0, 40.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        W, _ = hat_world(mid)
        if PT.bear_sdf(W[under_v]).min() < -0.7:
            lo = mid
        else:
            hi = mid
    HW, HAT_O = hat_world(hi)
    log("hat origin", HAT_O.round(2), "offset along n", round(hi, 2))

    def hat_sdf(p):
        d = p - HAT_O
        z = d @ n
        rr = np.linalg.norm(d - np.outer(z, n), axis=1)
        brim = np.maximum(np.abs(z - 0.2) - 0.9, rr - HAT_R)
        crown = G.sd_ellipsoid(np.stack([d @ xl, d @ yl, z], 1), np.array([0, 0, 0.9]),
                               np.array([PT.HAT_CROWN_R, PT.HAT_CROWN_R, PT.HAT_CROWN_H]))
        return np.minimum(brim, crown)

    # bow knot sits on the neck front
    ps, _ = PT.surface_point_local(-0.4, -24.6)   # head-local point below the chin
    knot_c = np.array([-0.3, ps[1], 0.0])
    zz = 40.0
    for _ in range(100):
        d = PT.bear_sdf(np.array([[knot_c[0], knot_c[1], zz]]))[0]
        zz -= d * 0.8
    knot_c[2] = zz + 3.3 * 1.14 * 0.55
    log("bow knot", knot_c.round(2))

    # flower: trumpet opening seen at the chest just above the rim
    a = nrm(np.array([-0.25, 0.30, 1.0]))
    open_c = np.array([-1.0, 64.6, 25.8])
    flower = PT.Flower(open_c - a * 9.5, a, length=10.5)
    # keep it clear of the bucket wall
    fb = flower.box()
    for _ in range(30):
        g = np.stack(np.meshgrid(*[np.linspace(fb[0][k], fb[1][k], 40) for k in range(3)], indexing="ij"), -1).reshape(-1, 3)
        dfl = flower.sdf(g)
        pts = g[dfl < 0]
        clr = PT.bucket_sdf(pts).min() if len(pts) else 9
        if clr > 0.4:
            break
        flower.base = flower.base + np.array([0, 0.3, -0.15])
        flower.leaves = [(lb + np.array([0, 0.3, -0.15]),) + lf[1:] for lb, lf in ((l[0], l) for l in flower.leaves)]
        flower.stem = (flower.stem[0] + np.array([0, 0.3, -0.15]), flower.stem[1] + np.array([0, 0.3, -0.15]), flower.stem[2])
        fb = flower.box()
    log("flower base", flower.base.round(2), "bucket clearance", round(float(clr), 2))

    bow_c = knot_c
    def bow_sdf_approx(p):
        d = G.sd_ellipsoid(p, bow_c, np.array([20.0, 9.5, 3.6]))
        return d

    def scene_sdf(p):
        d = np.minimum(PT.bucket_sdf(p), PT.bear_sdf(p))
        d = np.minimum(d, hat_sdf(p))
        d = np.minimum(d, bow_sdf_approx(p))
        d = np.minimum(d, G.sd_sphere(p, open_c - a * 4, 6.0))
        for (c, nn, r) in beads.values():
            d = np.minimum(d, G.sd_sphere(p, c, r))
        return d

    W = GLBWriter()
    nodes = []

    # ------------------------------------------------------------ bucket
    def bucket_shader(bk):
        P, ao = bk.P, bk.ao
        n1 = NOISE.fbm(P / 9.0, 3)
        alb = C_BUCKET * (1 + 0.014 * n1[:, None])
        alb = alb * (1 - 0.06 * np.clip(1 - ao, 0, 1)[:, None] * np.array([0.9, 1.0, 1.1]))
        # fingerprints / smudges: soft blotches of duller gloss
        smudge = smoothstep(0.12, 0.5, NOISE.fbm(P / 3.2, 4)) * smoothstep(-0.1, 0.45, NOISE2.fbm(P / 14.0, 2))
        # fine handling scratches: thin, long, mostly horizontal lines
        ridge = 1 - np.abs(NOISE2(P * np.array([1 / 0.45, 1 / 9.0, 1 / 0.45]) + 3.1))
        scratch = smoothstep(0.965, 0.995, ridge) * smoothstep(0.1, 0.5, NOISE(P / 6.0 + 7.7))
        rough = 0.24 + 0.04 * NOISE.fbm(P / 2.5, 2) + 0.16 * smudge + 0.22 * scratch
        alb = alb * (1 + 0.025 * scratch[:, None])
        def height(Q):
            r = 1 - np.abs(NOISE2(Q * np.array([1 / 0.45, 1 / 9.0, 1 / 0.45]) + 3.1))
            s = smoothstep(0.965, 0.995, r) * smoothstep(0.1, 0.5, NOISE(Q / 6.0 + 7.7))
            return 0.008 * NOISE(Q / 0.35) + 0.004 * NOISE2(Q / 0.12) - 0.006 * s
        return dict(albedo=np.clip(alb, 0, 1), rough=np.clip(rough, 0.18, 0.7), metal=np.zeros(len(P)), height=height)
    prim, tex = sdf_part("bucket", PT.bucket_sdf, PT.BUCKET_BOX, 0.5 if q else 0.2,
                         8000 if q else 46000, TEX_S, bucket_shader, scene_sdf, 1.0)
    m_bucket = W.material("Bucket_PinkPlastic",
                          base=W.texture(tex["albedo"], quality=93),
                          normal=W.texture(tex["normal"], quality=88),
                          orm=W.texture(tex["orm"], quality=93), occl_strength=0.9)
    prim["material"] = m_bucket
    nodes.append(W.mesh("Bucket", [prim]))
    stats["parts"]["Bucket"] = len(prim["F"])

    # ------------------------------------------------------------ sticker
    st, sinfo = sticker_texture(TEX_S, bucket_albedo_srgb=tuple(C_BUCKET))
    s0, s1 = -24.0, 24.0
    h0, h1 = 6.0, 54.0
    ns = 96 if not q else 48
    Sg, Hg = np.meshgrid(np.linspace(s0, s1, ns + 1), np.linspace(h1, h0, ns + 1))
    rho = bucket_r_out(Hg) + 0.09
    phi = np.pi / 2 - Sg / rho
    SV = np.stack([rho * np.cos(phi), Hg, rho * np.sin(phi)], -1).reshape(-1, 3)
    SUV = np.stack([(Sg - s0) / (s1 - s0), (h1 - Hg) / (h1 - h0)], -1).reshape(-1, 2)
    alpha_small = ndimage.zoom(st[..., 3], (ns + 1) / st.shape[0], order=1)
    SF = []
    keep = ndimage.binary_dilation(alpha_small > 0.02, iterations=2)
    for i in range(ns):
        for j in range(ns):
            if keep[i:i + 2, j:j + 2].any():
                a0, b0 = i * (ns + 1) + j, (i + 1) * (ns + 1) + j
                SF += [[a0, b0, b0 + 1], [a0, b0 + 1, a0 + 1]]
    SF = np.array(SF)
    used = np.unique(SF)
    remap = -np.ones(len(SV), int)
    remap[used] = np.arange(len(used))
    SV, SUV, SF = SV[used], SUV[used], remap[SF]
    slope = (BUCKET["r_top"] - BUCKET["r_bot"]) / BUCKET["band_start"]
    SN = nrm(np.stack([SV[:, 0], -slope * np.linalg.norm(SV[:, [0, 2]], axis=1), SV[:, 2]], 1))
    # orientation: make faces point outward
    fa = np.cross(SV[SF[:, 1]] - SV[SF[:, 0]], SV[SF[:, 2]] - SV[SF[:, 0]])
    if np.einsum("ij,ij->i", fa, SN[SF[:, 0]]).mean() < 0:
        SF = SF[:, ::-1]
    STAN = G.tangents(SV, SN, SUV, SF)
    # paper-like matte print with a tiny grain in the normal map
    gx_, gy_ = np.meshgrid(np.arange(TEX_S) / 6.0, np.arange(TEX_S) / 6.0)
    gy = NOISE(np.stack([gx_, gy_, np.zeros_like(gx_)], -1).reshape(-1, 3)).reshape(TEX_S, TEX_S)
    s_norm = G.normal_map_from_height_image(gy * 0.6, 0.25)
    st8 = (np.clip(st, 0, 1) * 255 + 0.5).astype(np.uint8)
    m_st = W.material("Sticker_LoverGrass", base=W.texture(st8, kind="png", clamp=True),
                      normal=W.texture(s_norm, quality=92, clamp=True), rough=0.62,
                      alpha_mode="MASK", alpha_cutoff=0.5)
    nodes.append(W.mesh("Sticker_Heart", [dict(V=SV, N=SN, UV=SUV, TAN=STAN, F=SF, material=m_st)]))
    stats["parts"]["Sticker_Heart"] = len(SF)
    stats["sticker"] = sinfo

    # ------------------------------------------------------------ bear
    def bear_shader(bk):
        P, ao = bk.P, bk.ao
        blotch = NOISE.fbm(P / 4.5, 3)            # uneven flock density
        speck = NOISE2(P / 0.33)                  # fibre clumps
        alb = C_BEAR * (1 + 0.022 * blotch[:, None] + 0.012 * speck[:, None])
        # handled toy: faint grey-brown dust in the creases (neck, under arms)
        dust = np.clip(1 - ao, 0, 1) ** 1.4
        alb = alb * (1 - dust[:, None] * np.array([0.085, 0.095, 0.120]))
        alb = alb * (1 - 0.025 * smoothstep(72, 46, P[:, 1]))[:, None] * np.array([1, 0.994, 0.982])
        rough = 0.95 + 0.04 * NOISE(P / 1.1)
        def height(Q):
            # short dense fibres: soft grain with no plaster-like pits
            return (0.016 * NOISE(Q / 0.11) + 0.012 * NOISE2(Q / 0.24) +
                    0.025 * NOISE.fbm(Q / 0.9, 2))
        return dict(albedo=np.clip(alb, 0, 1), rough=np.clip(rough, 0.85, 1), metal=np.zeros(len(P)), height=height)
    prim, tex = sdf_part("bear", PT.bear_sdf, PT.BEAR_BOX, 0.55 if q else 0.24,
                         10000 if q else 72000, TEX, bear_shader, scene_sdf, 1.0)
    m_bear = W.material("Bear_WhiteFlocking", base=W.texture(tex["albedo"], quality=92),
                        normal=W.texture(tex["normal"], quality=80),
                        orm=W.texture(tex["orm"], quality=90),
                        sheen={"sheenColorFactor": [1.0, 0.985, 0.96], "sheenRoughnessFactor": 0.36})
    prim["material"] = m_bear
    nodes.append(W.mesh("Bear_Body", [prim]))
    stats["parts"]["Bear_Body"] = len(prim["F"])

    # ------------------------------------------------------------ beads
    m_bead = W.material("Bead_BlackGloss", base_factor=(0.016, 0.011, 0.009, 1.0), rough=0.11, metal=0.0)
    for name, (c, nn, r) in beads.items():
        BV, BN, BF = uv_sphere(c, r, nn, squash=0.92, nu=24 if q else 48, nv=12 if q else 24)
        nodes.append(W.mesh("Bead_" + name, [dict(V=BV, N=BN, F=BF, material=m_bead)]))
        stats["parts"]["Bead_" + name] = len(BF)

    # ------------------------------------------------------------ hat
    halb, hgl, hrr = hat_texture(TEX)
    lum = halb @ np.array([0.2126, 0.7152, 0.0722])
    weave = lum - ndimage.gaussian_filter(lum, 1.6 * TEX / 1024)
    rng = np.random.default_rng(5)
    spark = ndimage.gaussian_filter(rng.normal(size=lum.shape), 0.7) * hgl
    hh = np.clip(weave, -0.08, 0.08) * 1.0 + spark * 0.5
    hnorm = G.normal_map_from_height_image(hh, 2.2 * TEX / 1024)
    rough = 0.40 - 0.18 * hgl
    metal = 0.85 * hgl
    horm = pack_orm(np.ones_like(lum), rough, metal)
    m_hat = W.material("Hat_SatinGlitter", base=W.texture(halb, quality=92, clamp=True),
                       normal=W.texture(hnorm, quality=93, clamp=True),
                       orm=W.texture(horm, quality=93, clamp=True))
    # underside felt with the binding's running stitch near the edge
    yy, xx = np.mgrid[0:TEX_S, 0:TEX_S] / TEX_S * 2 * HAT_R
    Q = np.stack([xx, yy, np.zeros_like(xx)], -1).reshape(-1, 3)
    fel = (0.6 * NOISE(Q / 0.16) + 0.4 * NOISE2(Q / 0.06)).reshape(TEX_S, TEX_S)
    rr_ = np.hypot(xx - HAT_R, yy - HAT_R)
    ang_ = np.arctan2(yy - HAT_R, xx - HAT_R)
    rs = 0.925 * HAT_R
    stitch = smoothstep(0.16, 0.06, np.abs(rr_ - rs)) * smoothstep(0.15, 0.45, np.sin(ang_ * rs / 0.55 * np.pi))
    blot = NOISE.fbm(Q / 3.5, 3).reshape(TEX_S, TEX_S)
    ualb = C_HAT_UNDER * (1 + 0.025 * blot[..., None] + 0.02 * fel[..., None])
    ualb = ualb * (1 - stitch[..., None]) + np.array([0.80, 0.74, 0.88]) * stitch[..., None]
    ualb = np.clip(ualb, 0, 1)
    fel = fel + 2.5 * stitch
    m_hatu = W.material("Hat_UndersideFelt", base=W.texture(ualb, quality=90),
                        normal=W.texture(G.normal_map_from_height_image(fel, 0.7), quality=90),
                        rough=0.95, sheen={"sheenColorFactor": [0.95, 0.93, 0.98], "sheenRoughnessFactor": 0.4})
    HN = G.vertex_normals(HW, HF)
    hl = HW - HAT_O
    HUV = np.stack([0.5 + (hl @ xl) / (2 * HAT_R * 1.0), 0.5 - (hl @ yl) / (2 * HAT_R * 1.0)], 1)
    prims = []
    for sel, mat in ((Hseg < n_top, m_hat), (Hseg >= n_top, m_hatu)):
        f = HF[sel]
        u = np.unique(f)
        rm = -np.ones(len(HW), int)
        rm[u] = np.arange(len(u))
        V_, N_, UV_, F_ = HW[u], HN[u], HUV[u], rm[f]
        prims.append(dict(V=V_, N=N_, UV=UV_, TAN=G.tangents(V_, N_, UV_, F_), F=F_, material=mat))
    nodes.append(W.mesh("Hat", prims))
    stats["parts"]["Hat"] = int(len(HF))

    # ------------------------------------------------------------ bow
    T = TEX_S
    uu, vv = np.meshgrid((np.arange(T) + 0.5) / T, (np.arange(T) + 0.5) / T)
    xm, ym = uu * PT.BOW_TILE_MM, vv * PT.BOW_WIDTH_MM
    ribs = 0.5 + 0.5 * np.cos(2 * np.pi * xm / (PT.BOW_TILE_MM / 40))
    ribs = ribs ** 0.6
    selv = smoothstep(0.7, 0.0, np.minimum(ym, PT.BOW_WIDTH_MM - ym))
    dots = np.zeros_like(xm)
    rng_d = np.random.default_rng(17)
    wob = NOISE(np.stack([np.sin(2 * np.pi * uu) * 6, np.cos(2 * np.pi * uu) * 6, ym / 0.35], -1).reshape(-1, 3)).reshape(T, T)
    for row, yc in enumerate(np.arange(2.5, PT.BOW_WIDTH_MM, 5.0)):
        off = 3.0 if row % 2 else 0.0
        for xc in np.arange(off, PT.BOW_TILE_MM, 6.0):
            jx, jy, jr = rng_d.normal(0, 0.22), rng_d.normal(0, 0.18), rng_d.normal(0, 0.07)
            op = rng_d.uniform(0.75, 1.0)
            for xw in (xc - PT.BOW_TILE_MM, xc, xc + PT.BOW_TILE_MM):
                r = np.sqrt((xm - xw - jx) ** 2 + (ym - yc - jy) ** 2) * (1 + 0.07 * wob)
                dots = np.maximum(dots, op * smoothstep(1.02 + jr, 0.70 + jr, r))
    tile_noise = NOISE(np.stack([np.sin(2 * np.pi * uu) * 3, np.cos(2 * np.pi * uu) * 3, ym / 0.6], -1).reshape(-1, 3)).reshape(T, T)
    balb = C_RIBBON * (0.94 + 0.08 * ribs)[..., None] * (1 + 0.03 * tile_noise[..., None] + 0.02 * wob[..., None])
    dots = dots * 0.62 * (0.9 + 0.1 * ribs)
    balb = balb * (1 - dots[..., None]) + C_DOT * (0.96 + 0.05 * ribs)[..., None] * dots[..., None]
    bh = ribs * 1.0 + selv * 0.6 + 0.15 * tile_noise
    bnorm = G.normal_map_from_height_image(bh, 1.4)
    borm = pack_orm(0.85 + 0.15 * ribs, 0.58 + 0.12 * (1 - ribs), np.zeros_like(ribs))
    m_bow = W.material("Bow_GrosgrainRibbon", base=W.texture(np.clip(balb, 0, 1), quality=92),
                       normal=W.texture(bnorm, quality=93), orm=W.texture(borm, quality=92),
                       sheen={"sheenColorFactor": [0.85, 0.80, 0.98], "sheenRoughnessFactor": 0.38})
    bow = PT.bow_geometry(knot_c, push=push_out(PT.bear_sdf, PT.RIBBON_T / 2 + 0.12))
    bprims = []
    for name, V_, UV_, F_ in bow:
        N_ = G.vertex_normals(V_, F_)
        bprims.append(dict(V=V_, N=N_, UV=UV_, TAN=G.tangents(V_, N_, UV_, F_), F=F_, material=m_bow))
        stats["parts"]["Bow_" + name] = len(F_)
    nodes.append(W.mesh("Bow", bprims))

    # ------------------------------------------------------------ flower
    def flower_shader(bk):
        P = bk.P
        reg = flower.region(P)
        w, rho, th = flower.local(flower.warp(P))
        rp = flower.prof(w)
        inner = rho < rp
        L = flower.petal_len(th)
        tip = smoothstep(L - 1.8, L - 0.1, w)
        throat = smoothstep(1.0, 7.5, w)
        vein = 0.5 + 0.5 * np.cos(th * 22 + 0.6 * NOISE(P / 0.8))
        c_out = C_PETAL * (0.93 + 0.07 * throat)[:, None] * (1 - 0.06 * vein * (1 - tip))[:, None]
        c_in = C_PETAL_IN + (C_PETAL - C_PETAL_IN) * throat[:, None]
        c = np.where(inner[:, None], c_in, c_out)
        c = c * (1 - tip[:, None] * 0.7) + C_PETAL_EDGE * tip[:, None] * 0.7
        cols = [c, np.broadcast_to(C_STAMEN, c.shape), np.broadcast_to(C_STEM, c.shape),
                np.broadcast_to(C_LEAF1, c.shape), np.broadcast_to(C_LEAF2, c.shape)]
        alb = np.choose(reg[:, None], cols)
        alb = alb * (1 + 0.035 * NOISE(P / 0.6) + 0.02 * NOISE2(P / 2.5))[:, None]
        rough = np.where(reg == 0, 0.34 + 0.18 * tip, 0.45) + 0.05 * NOISE2(P / 0.4)
        def height(Q):
            return 0.006 * NOISE(Q / 0.15) + 0.004 * NOISE2(Q / 0.05)
        return dict(albedo=np.clip(alb, 0, 1), rough=rough, metal=np.zeros(len(P)), height=height)
    prim, tex = sdf_part("flower", flower.sdf, flower.box(), 0.16 if q else 0.075,
                         6000 if q else 17000, TEX_S, flower_shader, scene_sdf, 1.0)
    m_fl = W.material("Flower_PlasticMagentaYellow", base=W.texture(tex["albedo"], quality=93),
                      normal=W.texture(tex["normal"], quality=92), orm=W.texture(tex["orm"], quality=92),
                      occl_strength=0.55)
    prim["material"] = m_fl
    nodes.append(W.mesh("Flower_and_Leaves", [prim]))
    stats["parts"]["Flower_and_Leaves"] = len(prim["F"])

    # ------------------------------------------------------------ write
    W.group("TeddyBearInBucket", nodes)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    size = W.write(args.out)
    stats["file_bytes"] = size
    stats["triangles"] = int(sum(stats["parts"].values()))
    stats["texture_sizes"] = {"bucket/bear/hat": TEX, "sticker/bow/flower/hat-underside": TEX_S}
    with open(os.path.splitext(args.out)[0] + "_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    log(f"wrote {args.out}: {size / 1e6:.2f} MB, {stats['triangles']} triangles")


if __name__ == "__main__":
    main()
