"""Ribbon seeval (ribbon pakoda) pieces: geometry + food textures.

Each piece is a closed solid strip of fried dough extruded through a ribbed
die: parallel rounded ridges on both faces, concentric arcs when the strip
curves, comb-like broken ends (every ridge strand snaps at its own length),
curl / cup / twist and slight thickness irregularity. Units are millimetres.
"""
import numpy as np
from scipy.spatial import cKDTree
from scipy import ndimage

CELL_MM = 40.0          # texture cell covers 40 x 40 mm
GRID = 6                # 6 x 6 cells: top + bottom face of 17 pieces, last 2 cells = edge crust
EDGE_CELL = GRID * GRID - 2


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


class Piece:
    def __init__(self, idx, rng):
        self.idx = idx
        self.rng = rng
        r = rng
        self.L = r.uniform(17, 31)                 # length along the ribbon (mid line)
        self.pitch = r.uniform(1.75, 2.05)        # ridge spacing
        self.nrib = int(r.integers(6, 12))
        self.W = self.nrib * self.pitch           # ribbon width
        self.Rc = np.inf if r.random() < 0.22 else r.uniform(16, 55) * r.choice([-1, 1])
        self.t = r.uniform(0.75, 0.95)            # web thickness between strands
        self.h_top = r.uniform(0.62, 0.80)        # strand relief (crest ~2 mm thick)
        self.h_bot = r.uniform(0.40, 0.55)
        self.cu = r.uniform(-0.025, 0.045)        # curl along length
        self.cv = r.uniform(-0.03, 0.06)          # cupping across width
        self.tw = r.uniform(-0.025, 0.025)        # twist
        self.phase = r.uniform(0, 1)
        # every ridge strand breaks at its own length (comb-like ends)
        self.e_end = np.clip(r.normal(0, 1.3, self.nrib + 2), -2.8, 2.8)
        self.e_sta = np.clip(r.normal(0, 1.3, self.nrib + 2), -2.8, 2.8)
        if r.random() < 0.35:                     # one cleanly snapped end
            self.e_sta *= 0.25
        self.wob = r.uniform(0, 100, 4)

    # ridge profile 0 (groove) .. 1 (crest)
    def rib(self, v):
        x = (v + self.W / 2) / self.pitch          # 0 at strand boundaries, .5 at centres
        return 0.5 - 0.5 * np.cos(2 * np.pi * x)

    def rib_index(self, v):
        return np.clip(np.floor((v + self.W / 2) / self.pitch).astype(int), 0, self.nrib - 1)

    def u_limits(self, v):
        k = self.rib_index(v)
        vc = -self.W / 2 + (k + 0.5) * self.pitch          # strand centre
        q = np.clip(np.abs(v - vc) / (self.pitch / 2), 0, 1)
        tip = 0.9 * np.sqrt(np.clip(1 - q ** 2, 0, 1))      # rounded strand ends
        # the web between two strands tears at the shorter strand's length
        side = np.where(v >= vc, 1, -1)
        kn = np.clip(k + side, 0, self.nrib - 1)
        w = smoothstep(0.55, 1.0, q)
        ee = (1 - w) * self.e_end[k] + w * np.minimum(self.e_end[k], self.e_end[kn])
        es = (1 - w) * self.e_sta[k] + w * np.maximum(self.e_sta[k], self.e_sta[kn])
        u1 = self.L / 2 + ee - 0.9 + tip
        u0 = -self.L / 2 + es + 0.9 - tip
        return u0, u1

    def mid_surface(self, u, v):
        if np.isinf(self.Rc):
            x, y = u, v
        else:
            R = self.Rc + v * np.sign(self.Rc)
            phi = u / abs(self.Rc)
            x = R * np.sin(phi)
            y = (abs(self.Rc) - R * np.cos(phi)) * np.sign(self.Rc)
        w0, w1, w2, w3 = self.wob
        z = (self.cu * u * u + self.cv * v * v + self.tw * u * v
             + 0.25 * np.sin(u / 5.0 + w0) * np.cos(v / 4.0 + w1)
             + 0.15 * np.sin(u / 2.7 + w2 + v / 3.1))
        return np.stack([x, y, z], -1)

    def build(self, nu=17, per_pitch=6):
        nv = self.nrib * per_pitch + 1
        v = np.linspace(-self.W / 2, self.W / 2, nv)
        u0, u1 = self.u_limits(v)
        s = np.linspace(0, 1, nu)
        U = u0[None, :] + (u1 - u0)[None, :] * s[:, None]      # (nu, nv)
        V = np.broadcast_to(v[None, :], U.shape)
        P = self.mid_surface(U, V)
        e = 0.02
        Pu = self.mid_surface(U + e, V) - self.mid_surface(U - e, V)
        Pv = self.mid_surface(U, V + e) - self.mid_surface(U, V - e)
        n = np.cross(Pu, Pv)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        rb = self.rib(V)
        thick = 1 + 0.10 * np.sin(U / 3.3 + self.wob[3]) * np.cos(V / 2.9)
        # ridges taper towards the broken ends
        endf = smoothstep(0.0, 1.2, np.minimum(U - u0[None, :], u1[None, :] - U))
        # dough is never perfectly smooth: small lumps along the strands
        lump = 0.06 * np.sin(U * 2.1 + V * 0.7 + self.wob[0]) * np.sin(U * 1.3 - V * 1.9 + self.wob[1])
        top = P + n * (self.t / 2 * thick + self.h_top * rb * (0.4 + 0.6 * endf) + lump)[..., None]
        bot = P - n * (self.t / 2 * thick + self.h_bot * rb * (0.4 + 0.6 * endf))[..., None]
        # texture cells: top face -> cell 2*idx, bottom -> 2*idx+1
        def cell_uv(ci, U, V, mirror=False):
            cx, cy = ci % GRID, ci // GRID
            a = (U / CELL_MM + 0.5)
            b = (V / CELL_MM + 0.5)
            if mirror:
                b = 1 - b
            return np.stack([(cx + a) / GRID, (cy + b) / GRID], -1)
        uvT = cell_uv(2 * self.idx, U, V)
        uvB = cell_uv(2 * self.idx + 1, U, V, mirror=True)
        Vs, UVs, Fs = [], [], []
        def grid(Pg, UVg, flip):
            base = sum(len(a) for a in Vs)
            Vs.append(Pg.reshape(-1, 3)); UVs.append(UVg.reshape(-1, 2))
            a = np.arange(Pg.shape[0] - 1)[:, None] * Pg.shape[1] + np.arange(Pg.shape[1] - 1)[None, :]
            a = a.ravel()
            b, c, d = a + Pg.shape[1], a + Pg.shape[1] + 1, a + 1
            f = np.concatenate([np.stack([a, b, c], 1), np.stack([a, c, d], 1)]) if not flip else \
                np.concatenate([np.stack([a, c, b], 1), np.stack([a, d, c], 1)])
            Fs.append(f + base)
        grid(top, uvT, False)
        grid(bot, uvB, True)
        # side walls along the boundary loop (u-ends and v-edges)
        loop = ([(0, j) for j in range(nv)] + [(i, nv - 1) for i in range(1, nu)] +
                [(nu - 1, j) for j in range(nv - 2, -1, -1)] + [(i, 0) for i in range(nu - 2, 0, -1)])
        li = np.array(loop)
        T = top[li[:, 0], li[:, 1]]
        B = bot[li[:, 0], li[:, 1]]
        wall = np.stack([np.concatenate([T, T[:1]]), np.concatenate([B, B[:1]])], 1)
        arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(wall[:, 0], axis=0), axis=1))])
        ec = EDGE_CELL + (self.idx % 2)
        cx, cy = ec % GRID, ec // GRID
        rows = (self.idx // 2) % 8                           # 8 crust strips per cell
        a = (arc % (CELL_MM - 1.0)) / CELL_MM + 0.5 / CELL_MM
        b0 = (rows + 0.15) / 8
        b1 = (rows + 0.85) / 8
        wuv = np.stack([np.stack([(cx + a) / GRID, (cy + np.full_like(a, b0)) / GRID], -1),
                        np.stack([(cx + a) / GRID, (cy + np.full_like(a, b1)) / GRID], -1)], 1)
        grid(wall, wuv, True)
        V_ = np.concatenate(Vs)
        UV_ = np.concatenate(UVs)
        F_ = np.concatenate(Fs)
        # orient outward
        vol = np.einsum("ij,ij->i", V_[F_[:, 0]], np.cross(V_[F_[:, 1]], V_[F_[:, 2]])).sum()
        if vol < 0:
            F_ = F_[:, ::-1]
        self.V, self.UV, self.F = V_, UV_, F_
        # sample points for packing / collision
        self.samples = np.concatenate([top[::3, ::3].reshape(-1, 3), bot[::4, ::4].reshape(-1, 3)])
        return self


# ---------------------------------------------------------------------------
# food texture atlas
# ---------------------------------------------------------------------------
def _scatter(rng, n, size_mm):
    return rng.uniform(0, size_mm, (n, 2))


def snack_textures(pieces, res=4096, seed=3):
    """Albedo (sRGB), height (mm), roughness, AO for the whole atlas."""
    rng = np.random.default_rng(seed)
    cpx = res // GRID
    pxmm = cpx / CELL_MM
    alb = np.zeros((res, res, 3), np.float32)
    hgt = np.zeros((res, res), np.float32)
    rough = np.zeros((res, res), np.float32)
    ao = np.ones((res, res), np.float32)
    yy, xx = np.mgrid[0:cpx, 0:cpx]
    Umm = (xx + 0.5) / pxmm - CELL_MM / 2          # along the ribbon
    Vmm = (yy + 0.5) / pxmm - CELL_MM / 2          # across
    pts_xy = np.stack([(xx + 0.5) / pxmm, (yy + 0.5) / pxmm], -1).reshape(-1, 2)
    palette = [np.array([0.82, 0.62, 0.38]), np.array([0.80, 0.57, 0.34]),
               np.array([0.76, 0.52, 0.31]), np.array([0.85, 0.67, 0.43])]
    for p in pieces:
        for face in (0, 1):
            ci = 2 * p.idx + face
            cx, cy = ci % GRID, ci // GRID
            V = Vmm if face == 0 else -Vmm
            # outline distance -> fried edges
            u0, u1 = p.u_limits(np.clip(V, -p.W / 2, p.W / 2))
            dist = np.minimum.reduce([Umm - u0, u1 - Umm, p.W / 2 - np.abs(V)])
            edge = smoothstep(1.4, 0.0, dist)
            rb = p.rib(np.clip(V, -p.W / 2, p.W / 2))
            base = palette[int(rng.integers(len(palette)))] * rng.uniform(0.96, 1.03)
            # low-frequency frying / seasoning variation
            lf = ndimage.gaussian_filter(rng.normal(size=(cpx // 16 + 2, cpx // 16 + 2)), 1.2)
            lf = ndimage.zoom(lf, cpx / lf.shape[0], order=1)[:cpx, :cpx]
            lf = lf / (np.abs(lf).max() + 1e-6)
            col = base[None, None, :] * (1 + 0.06 * lf[..., None])
            # chilli dusting is slightly redder on the crests
            col = col * (1 - 0.05 * rb[..., None] * np.array([0, 0.6, 1.0]))
            # fried, darker edges and broken ends
            col = col * (1 - 0.30 * edge[..., None] * np.array([0.75, 1.0, 1.15]))
            h = np.zeros((cpx, cpx), np.float32)
            rgh = 0.78 - 0.08 * rb
            # pinholes / pores (steam escaping while frying)
            n_p = int(CELL_MM * CELL_MM * 1.6)
            pp = _scatter(rng, n_p, CELL_MM)
            pr = rng.uniform(0.06, 0.16, n_p)
            d, k = cKDTree(pp).query(pts_xy)
            d = d.reshape(cpx, cpx); k = k.reshape(cpx, cpx)
            pore = smoothstep(pr[k], pr[k] * 0.3, d)
            h -= 0.07 * pore
            col *= (1 - 0.18 * pore)[..., None]
            # small oil blisters
            n_b = int(CELL_MM * CELL_MM * 0.35)
            bp = _scatter(rng, n_b, CELL_MM)
            br = rng.uniform(0.25, 0.7, n_b)
            d, k = cKDTree(bp).query(pts_xy)
            d = d.reshape(cpx, cpx); k = k.reshape(cpx, cpx)
            bl = np.clip(1 - (d / br[k]) ** 2, 0, 1) ** 0.6
            h += 0.09 * bl * (br[k] / 0.7)
            col *= (1 + 0.05 * bl)[..., None]
            rgh -= 0.25 * bl
            # flour granules
            gr = ndimage.gaussian_filter(rng.normal(size=(cpx, cpx)), 0.9)
            h += 0.012 * gr
            col *= (1 + 0.035 * gr)[..., None]
            # chilli-powder specks (dark red) and pale salt / sesame flecks
            n_c = int(CELL_MM * CELL_MM * 5.0)
            cp = _scatter(rng, n_c, CELL_MM)
            d, k = cKDTree(cp).query(pts_xy)
            cr = rng.uniform(0.02, 0.05, n_c)
            sp = 0.55 * smoothstep(cr[k.reshape(cpx, cpx)], 0, d.reshape(cpx, cpx))
            # fine chilli dust also tints the surface unevenly
            dust = ndimage.gaussian_filter(rng.random((cpx, cpx)), 2.0)
            dust = (dust - dust.mean()) / (dust.std() + 1e-6)
            col = col * (1 - 0.03 * dust[..., None] * np.array([-0.2, 0.6, 1.0]))
            col = col * (1 - sp[..., None]) + np.array([0.55, 0.20, 0.09]) * sp[..., None]
            n_w = int(CELL_MM * CELL_MM * 0.10)
            wp = _scatter(rng, n_w, CELL_MM)
            d, k = cKDTree(wp).query(pts_xy)
            wr = rng.uniform(0.06, 0.16, n_w)
            ws = smoothstep(wr[k.reshape(cpx, cpx)], 0, d.reshape(cpx, cpx))
            col = col * (1 - ws[..., None]) + np.array([0.95, 0.89, 0.72]) * ws[..., None]
            h += 0.03 * ws
            # hairline cracks along some crests
            ck = (np.sin(Umm * 0.9 + rng.uniform(0, 6)) * np.sin(V * 2.3 + rng.uniform(0, 6)) > 0.93) & (rb > 0.8)
            ck = ndimage.binary_dilation(ck & (rng.random(ck.shape) > 0.2))
            h -= 0.04 * ck
            col *= (1 - 0.15 * ck)[..., None]
            # oil sheen patches: some areas noticeably glossier than the dry dusted ones
            oil = smoothstep(0.25, 0.7, lf * 0.5 + 0.5 + 0.2 * ndimage.gaussian_filter(rng.normal(size=(cpx, cpx)), 25) * 6)
            rgh = rgh - 0.22 * oil
            rgh = rgh + 0.10 * pore
            a_o = 1 - 0.45 * pore - 0.15 * (1 - rb) - 0.25 * edge * 0.5
            sl = np.s_[cy * cpx:(cy + 1) * cpx, cx * cpx:(cx + 1) * cpx]
            alb[sl] = np.clip(col, 0, 1)
            hgt[sl] = h
            rough[sl] = np.clip(rgh, 0.3, 0.95)
            ao[sl] = np.clip(a_o, 0.3, 1)
    for ec in (EDGE_CELL, EDGE_CELL + 1):
        cx, cy = ec % GRID, ec // GRID
        g1 = ndimage.gaussian_filter(rng.normal(size=(cpx, cpx)), 1.0)
        g2 = ndimage.gaussian_filter(rng.normal(size=(cpx, cpx)), 4.0)
        crumb = smoothstep(0.6, 1.4, g1 * 1.5)
        col = np.array([0.66, 0.42, 0.22])[None, None, :] * (1 + 0.08 * g2[..., None] / (np.abs(g2).max() + 1e-6) * 3)
        col = col * (1 + 0.10 * crumb[..., None])
        sl = np.s_[cy * cpx:(cy + 1) * cpx, cx * cpx:(cx + 1) * cpx]
        alb[sl] = np.clip(col, 0, 1)
        hgt[sl] = 0.05 * g1 + 0.04 * crumb
        rough[sl] = 0.85 - 0.1 * crumb
        ao[sl] = 0.85 + 0.1 * crumb
    return alb, hgt, rough, ao, pxmm
