"""The printed film bag: geometry, print atlas (built from the photographs)
and window (transmission) mask.

Atlas layout: U = position around the bag perimeter (0 = centre of the
front face, increasing towards the right side), V = profile parameter from
the ruffled top edge (V=0) down the shoulder, body and across the bottom to
its centre (V=1). Units are millimetres.
"""
import os
import numpy as np
from PIL import Image
from scipy import ndimage
from skimage.transform import ProjectiveTransform, warp

REF = os.path.join(os.path.dirname(__file__), "reference")

# ------------------------------------------------------------------ dimensions
W, D, RC = 130.0, 80.0, 12.0       # body width (x), depth (z), corner radius
HB = 70.0                          # top of the straight body
HT = 128.0                         # thread tie height
HR = 150.0                         # top of the ruffle
R_NECK = 6.8
A, B = W / 2, D / 2
STRAIGHT_F = W - 2 * RC
STRAIGHT_S = D - 2 * RC
ARC = np.pi / 2 * RC
PERIM = 2 * (STRAIGHT_F + STRAIGHT_S) + 4 * ARC
# profile parameter breakpoints
T_BOT, T_FIL, T_BODY, T_SH, T_NECK = 0.16, 0.20, 0.50, 0.83, 0.87


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def rrect(p):
    """Point and outward normal on the rounded-rectangle outline at
    perimeter distance p (0 = front centre, +x direction first)."""
    p = np.mod(np.asarray(p, float) + STRAIGHT_F / 2, PERIM)   # 0 = front-left corner start
    segs = [STRAIGHT_F, ARC, STRAIGHT_S, ARC, STRAIGHT_F, ARC, STRAIGHT_S, ARC]
    edges = np.cumsum([0] + segs)
    x = np.zeros_like(p); z = np.zeros_like(p); nx = np.zeros_like(p); nz = np.zeros_like(p)
    corners = [(A - RC, B - RC, np.pi / 2), (A - RC, -(B - RC), 0.0),
               (-(A - RC), -(B - RC), -np.pi / 2), (-(A - RC), B - RC, -np.pi)]
    for i in range(8):
        m = (p >= edges[i]) & (p < edges[i + 1] + (1e-9 if i == 7 else 0))
        q = p[m] - edges[i]
        if i == 0:   # front, left -> right
            x[m] = -(A - RC) + q; z[m] = B; nz[m] = 1
        elif i == 2:  # right side, front -> back
            x[m] = A; z[m] = (B - RC) - q; nx[m] = 1
        elif i == 4:  # back, right -> left
            x[m] = (A - RC) - q; z[m] = -B; nz[m] = -1
        elif i == 6:  # left side, back -> front
            x[m] = -A; z[m] = -(B - RC) + q; nx[m] = -1
        else:
            cx, cz, a0 = corners[i // 2]
            ang = a0 - q / RC
            x[m] = cx + RC * np.cos(ang); z[m] = cz + RC * np.sin(ang)
            nx[m] = np.cos(ang); nz[m] = np.sin(ang)
    return x, z, nx, nz


def face_of(p):
    """0 front, 1 right, 2 back, 3 left; and the coordinate along that face
    measured from the face centre (left->right as seen from outside)."""
    q = np.mod(np.asarray(p, float), PERIM)
    f_half = STRAIGHT_F / 2 + ARC / 2
    s_len = STRAIGHT_S + ARC
    centers = [0.0, STRAIGHT_F / 2 + ARC + STRAIGHT_S / 2,
               STRAIGHT_F + 2 * ARC + STRAIGHT_S + STRAIGHT_F / 2 - STRAIGHT_F / 2 + STRAIGHT_F / 2,
               PERIM - (STRAIGHT_F / 2 + ARC + STRAIGHT_S / 2)]
    centers[2] = PERIM / 2
    face = np.full(q.shape, 0)
    loc = q.copy()
    loc = np.where(q > PERIM / 2 + 1e-9, q - PERIM, q)          # front: [-PERIM/2, PERIM/2]
    out_face = np.zeros(q.shape, int)
    out_loc = loc.copy()
    for fi, c in enumerate(centers):
        d = np.angle(np.exp(1j * (q - c) / PERIM * 2 * np.pi)) / (2 * np.pi) * PERIM
        half = f_half if fi in (0, 2) else s_len / 2
        m = np.abs(d) <= half + 1e-9
        out_face[m] = fi
        out_loc[m] = d[m]
    return out_face, out_loc


# ------------------------------------------------------------------ geometry
class BagShape:
    def __init__(self, seed=5):
        self.rng = np.random.default_rng(seed)
        r = self.rng
        self.pleat_ph = r.uniform(0, 2 * np.pi, 6)
        self.ruffle_ph = r.uniform(0, 2 * np.pi, 6)
        self.top_ph = r.uniform(0, 2 * np.pi, 5)

    def profile(self, t):
        """y, horizontal blend factor towards the neck circle, radial scale."""
        t = np.asarray(t, float)
        y = np.zeros_like(t); scale = np.ones_like(t); toneck = np.zeros_like(t)
        m = t < T_BOT                                     # flat bottom (sealed, slightly lifted)
        s = t[m] / T_BOT
        scale[m] = 0.90 * s; y[m] = 0.8 + 1.2 * s ** 3
        m = (t >= T_BOT) & (t < T_FIL)                    # bottom fillet
        s = (t[m] - T_BOT) / (T_FIL - T_BOT)
        ang = s * np.pi / 2
        scale[m] = 0.90 + 0.10 * np.sin(ang); y[m] = 2.0 + 5.0 * (1 - np.cos(ang))
        m = (t >= T_FIL) & (t < T_BODY)                   # straight body
        s = (t[m] - T_FIL) / (T_BODY - T_FIL)
        y[m] = 7.0 + (HB - 7.0) * s
        m = (t >= T_BODY) & (t < T_SH)                    # gathered shoulder (dome)
        s = (t[m] - T_BODY) / (T_SH - T_BODY)
        y[m] = HB + (HT - 2 - HB) * np.sin(s * np.pi / 2) ** 0.9
        toneck[m] = 1 - np.cos(s * np.pi / 2)
        m = (t >= T_SH) & (t < T_NECK)                    # tied neck
        s = (t[m] - T_SH) / (T_NECK - T_SH)
        y[m] = HT - 2 + 6 * s; toneck[m] = 1
        m = t >= T_NECK                                   # ruffle above the tie
        s = (t[m] - T_NECK) / (1 - T_NECK)
        y[m] = HT + 4 + (HR - HT - 4) * s; toneck[m] = 1
        scale[m] = 1 + 2.4 * s ** 0.8
        return y, toneck, scale

    def surface(self, P, T, pleats=True):
        """P: perimeter position (mm), T: profile parameter. Returns xyz."""
        x, z, nx, nz = rrect(P)
        y, toneck, scale = self.profile(T)
        ang = P / PERIM * 2 * np.pi + np.pi / 2           # matching angle on the neck circle
        cxn, czn = np.cos(ang - np.pi / 2 + np.pi / 2), np.sin(ang)
        cxn = np.sin(P / PERIM * 2 * np.pi)
        czn = np.cos(P / PERIM * 2 * np.pi)
        body = (T >= T_FIL) & (T < T_SH)
        # pillow bulge of the filled faces
        fface, floc = face_of(P)
        halfw = np.where((fface == 0) | (fface == 2), A, B)
        bul = np.where(body, 1, 0) * (1 - np.clip(floc / halfw, -1, 1) ** 2) * \
            np.sin(np.clip((y - 2) / (HB + 15), 0, 1) * np.pi) ** 0.7
        bul_amt = np.where((fface == 0) | (fface == 2), 5.0, 3.5) * bul
        xb = x * scale + nx * bul_amt
        zb = z * scale + nz * bul_amt
        X = xb * (1 - toneck) + cxn * R_NECK * toneck * scale
        Z = zb * (1 - toneck) + czn * R_NECK * toneck * scale
        Y = y
        if pleats:
            th = P / PERIM * 2 * np.pi
            ph = self.pleat_ph
            pl = (np.sin(11 * th + ph[0]) + 0.6 * np.sin(17 * th + ph[1]) + 0.4 * np.sin(29 * th + ph[2]))
            sh = np.clip((T - T_BODY) / (T_SH - T_BODY), 0, 1)
            amp = np.where(T < T_SH, 7.5 * sh ** 1.4 * (1 - 0.55 * sh), 0)
            neck = (T >= T_SH) & (T < T_NECK)
            amp = np.where(neck, 0.9, amp)
            rf = np.clip((T - T_NECK) / (1 - T_NECK), 0, 1)
            pr = (np.sin(7 * th + self.ruffle_ph[0]) + 0.7 * np.sin(13 * th + self.ruffle_ph[1]) +
                  0.4 * np.sin(23 * th + self.ruffle_ph[2]))
            amp = np.where(T >= T_NECK, 6.5 * rf ** 0.7, amp)
            pl = np.where(T >= T_NECK, pr, pl)
            rad = np.sqrt(X * X + Z * Z) + 1e-9
            X = X + X / rad * amp * pl
            Z = Z + Z / rad * amp * pl
            # twist of the gathered neck
            tw = np.where(T > T_BODY, 0.55 * np.clip((T - T_BODY) / (T_NECK - T_BODY), 0, 1) ** 2, 0)
            c, s_ = np.cos(tw), np.sin(tw)
            X, Z = X * c - Z * s_, X * s_ + Z * c
            # ragged top edge of the ruffle and crumpled bottom
            Y = Y + np.where(T > 0.97, 2.5 * np.sin(5 * th + self.top_ph[0]) * (T - 0.97) / 0.03, 0)
            bot = T < T_FIL
            Y = Y + np.where(bot, 0.6 * np.sin(9 * th + self.top_ph[1]) * np.sin(T * 40 + self.top_ph[2]), 0)
        return np.stack([X, Y, Z], -1)

    def mesh(self, nu=300, nt=220):
        # non-uniform profile sampling: denser in the shoulder / neck / ruffle
        tt = np.concatenate([np.linspace(0, T_BODY, int(nt * 0.42), endpoint=False),
                             np.linspace(T_BODY, 1.0, nt - int(nt * 0.42))])
        pp = np.linspace(0, PERIM, nu + 1)
        Pg, Tg = np.meshgrid(pp, tt, indexing="xy")      # (nt, nu+1)
        Vg = self.surface(Pg, Tg)
        # bottom centre collapses to (nearly) one point: keep as a tiny ring
        UV = np.stack([Pg / PERIM, 1 - Tg], -1)
        nrow, ncol = Vg.shape[:2]
        idx = np.arange(nrow * ncol).reshape(nrow, ncol)
        a = idx[:-1, :-1].ravel(); b = idx[1:, :-1].ravel(); c = idx[1:, 1:].ravel(); d = idx[:-1, 1:].ravel()
        F = np.concatenate([np.stack([a, c, b], 1), np.stack([a, d, c], 1)])
        V = Vg.reshape(-1, 3)
        UV = UV.reshape(-1, 2)
        # outward orientation check (bottom faces must point down)
        fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        cen = V[F].mean(1)
        side = (cen[:, 1] > 20) & (cen[:, 1] < 60)
        if np.einsum("ij,ij->i", fn[side][:, [0, 2]], cen[side][:, [0, 2]]).mean() < 0:
            F = F[:, ::-1]
        return V, UV, F, (nrow, ncol)

    # ---------------------------------------------------- inside test for packing
    def inside_sdf(self, p):
        """Approximate signed distance to the inner wall (negative inside)."""
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        s = np.clip((y - HB) / (HT - 2 - HB), 0, 1)
        sh = np.arcsin(s ** (1 / 0.9)) / (np.pi / 2)
        k = np.where(y > HB, np.cos(sh * np.pi / 2), 1.0)
        a = A * k + R_NECK * (1 - k)
        b = B * k + R_NECK * (1 - k)
        rc = np.minimum(RC * k + R_NECK * (1 - k), np.minimum(a, b) - 1e-3)
        qx = np.abs(x) - (a - rc)
        qz = np.abs(z) - (b - rc)
        d = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qz, 0) ** 2) + np.minimum(np.maximum(qx, qz), 0) - rc
        d = np.maximum(d, 2.0 - y)
        d = np.maximum(d, y - (HT - 6))
        return d


# ------------------------------------------------------------------ print atlas
C_MAROON = np.array([0.30, 0.075, 0.055])
C_ORANGE = np.array([0.84, 0.29, 0.10])
C_BADGE = np.array([0.93, 0.40, 0.14])
C_GREEN = np.array([0.80, 0.87, 0.70])
C_WHITE = np.array([0.94, 0.93, 0.90])
C_BROWN = np.array([0.24, 0.10, 0.07])
C_SKIN = np.array([0.90, 0.72, 0.62])


def _load(name):
    return np.asarray(Image.open(os.path.join(REF, name)).convert("RGB")).astype(np.float64) / 255


def _warp_quad(img, quad, out_w, out_h):
    """Rectify the image quad (TL, TR, BR, BL in px) to out_w x out_h."""
    src = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], float)
    tf = ProjectiveTransform()
    tf = ProjectiveTransform.from_estimate(src, np.array(quad, float))
    return warp(img, tf, output_shape=(out_h, out_w), order=1, mode="edge")


def _text_mask(img, box, kind="light"):
    x0, y0, x1, y1 = box
    c = img[y0:y1, x0:x1]
    v = c.max(-1); s = (c.max(-1) - c.min(-1)) / np.maximum(v, 1e-3)
    if kind == "light":     # white top-hat: lettering vs the ink around it
        bg = ndimage.grey_opening(v, size=(71, 71))
        bg = ndimage.uniform_filter(bg, 31)
        m = (v - bg > 0.20) & (s < 0.38)
    else:
        bg = ndimage.grey_closing(v, size=(41, 41))
        m = (bg - v > 0.18)
    m = ndimage.binary_opening(m, iterations=1)
    lab, n = ndimage.label(m)
    if n:
        sizes = ndimage.sum(m, lab, range(1, n + 1))
        keep = np.isin(lab, 1 + np.nonzero(sizes > 40)[0])
        m = m & keep
    return ndimage.gaussian_filter(m.astype(float), 0.8)


def print_atlas(shape, res_u=4096, res_v=2048):
    """Returns albedo (sRGB, H x W x 3) and window mask (1 = clear film)."""
    U, Vv = np.meshgrid((np.arange(res_u) + 0.5) / res_u, (np.arange(res_v) + 0.5) / res_v)
    P = U * PERIM
    T = 1 - Vv
    y, toneck, _ = shape.profile(T)
    face, loc = face_of(P)
    col = np.zeros((res_v, res_u, 3))
    ink = np.zeros((res_v, res_u), bool)
    col[:] = 0.96
    sh = np.clip((T - T_BODY) / (T_SH - T_BODY), 0, 1)
    upper = T >= T_BODY

    # ---------------- neck, ruffle and upper shoulder: orange swirl print
    orange_zone = (T >= T_BODY + 0.62 * (T_SH - T_BODY)) | (T >= T_SH)
    th = P / PERIM * 2 * np.pi
    sw = np.zeros_like(P)
    rng = np.random.default_rng(9)
    for _ in range(14):      # brown swirl outlines (concentric rings) like the photos
        cu, cv = rng.uniform(0, 1), rng.uniform(0.0, 0.2)
        rr = np.hypot((U - cu) * PERIM / 1.0, (Vv - cv) * 210)
        rr = np.minimum(rr, np.hypot((U - cu - 1) * PERIM, (Vv - cv) * 210))
        rr = np.minimum(rr, np.hypot((U - cu + 1) * PERIM, (Vv - cv) * 210))
        lines = np.abs(np.sin(rr / 2.2 * np.pi)) < 0.10
        sw = np.maximum(sw, lines * (rr < rng.uniform(9, 16)))
    col[orange_zone] = C_ORANGE
    col[orange_zone & (sw > 0)] = C_ORANGE * 0.55 + C_BROWN * 0.45
    ink |= orange_zone

    # ---------------- front: maroon wave panel, swoosh, badge, lettering
    fr = face == 0
    xf = loc
    tt = np.linspace(T_BODY, T_SH, 400)
    cl = shape.surface(np.zeros_like(tt), tt, pleats=False)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(cl, axis=0), axis=1))])
    yf = np.where(upper, HB + np.interp(T, tt, arc), y)        # arc length up the shoulder
    wave_x = np.array([-80, -66, -55, -45, -35, -22, -5, 10, 20, 28, 36, 44, 48, 52, 56, 66, 80])
    wave_y = np.array([63, 63, 58, 52, 47, 44, 43, 45, 49, 53, 57, 66, 74, 69, 63, 62, 62])
    top = np.interp(xf, wave_x, wave_y)
    maroon = fr & (yf < top)
    bc = np.array([29.0, 68.0]); br = 16.5
    db = np.hypot(xf - bc[0], yf - bc[1])
    ang = np.degrees(np.arctan2(yf - bc[1], xf - bc[0]))
    swoosh = fr & (np.abs(db - 22.5) < 1.3) & (ang > -45) & (ang < 125)
    badge = fr & (db < br)
    col[maroon | swoosh] = C_MAROON
    col[badge] = C_BADGE
    ink |= maroon | swoosh | badge
    img1 = _load("01_front.jpg")
    # "RIBBON SEEVAL" lettering (white) from the front photo
    tm = _text_mask(img1, (1360, 2010, 3200, 2290), "light")
    tx0, tx1, tyc = -50.0, 46.0, 30.0
    th_mm = (tx1 - tx0) * tm.shape[0] / tm.shape[1]
    m = fr & (xf > tx0) & (xf < tx1) & (np.abs(yf - tyc) < th_mm / 2)
    iu = ((xf[m] - tx0) / (tx1 - tx0) * (tm.shape[1] - 1)).astype(int)
    iv = ((tyc + th_mm / 2 - yf[m]) / th_mm * (tm.shape[0] - 1)).astype(int)
    a = tm[iv, iu][:, None]
    col[m] = col[m] * (1 - a) + C_WHITE * a
    # "250g" (dark brown) inside the badge
    bm = _text_mask(img1, (2650, 1300, 3110, 1600), "dark")
    bw, bh = 23.0, 23.0 * bm.shape[0] / bm.shape[1]
    m = badge & (np.abs(xf - bc[0]) < bw / 2) & (np.abs(yf - bc[1]) < bh / 2)
    iu = ((xf[m] - (bc[0] - bw / 2)) / bw * (bm.shape[1] - 1)).astype(int)
    iv = (((bc[1] + bh / 2) - yf[m]) / bh * (bm.shape[0] - 1)).astype(int)
    a = bm[iv, iu][:, None]
    col[m] = col[m] * (1 - a) + C_BROWN * a

    # ---------------- right side: orange chef panel (from the side photo)
    rt = face == 1
    img3 = _load("03_side.jpg")
    pw, ph = 600, 950                                  # 60 mm x 95 mm at 10 px/mm
    # panel coordinate: z' from front edge (0) to 60 mm back, y from 0 to 95
    quad = [(2560, 1960), (2560, 860), (640, 1000), (640, 2150)]   # (y=95,z=0),(y=95,z=60),(y=0,z=60),(y=0,z=0)
    chef = _warp_quad(img3, quad, pw, ph)              # rows: y 95 -> 0 ; cols: z 0 -> 60
    # quantise to the printed inks to remove glare and show-through
    pal = np.stack([C_ORANGE, C_WHITE, C_MAROON, C_SKIN, C_BROWN])
    cv_ = chef.max(-1); cs_ = (chef.max(-1) - chef.min(-1)) / np.maximum(cv_, 1e-3)
    loc_v = ndimage.median_filter(cv_, size=41)
    rel = cv_ / np.maximum(loc_v, 1e-3)                  # lighting-independent brightness
    lab = np.zeros(cv_.shape, int)                         # orange by default
    lab[(cs_ < 0.32) & (rel > 0.95)] = 1                   # white coat / trousers
    lab[(cs_ >= 0.25) & (cs_ < 0.52) & (rel > 1.0) & (chef[..., 0] > chef[..., 2] + 0.15)] = 3   # skin
    lab[rel < 0.62] = 4                                    # drawn outlines
    lab[(cv_ < 0.33) & (rel < 0.85)] = 2                   # maroon band / dark ink
    lab = ndimage.median_filter(lab, 5)
    chef_q = pal[lab]
    zr = loc + (STRAIGHT_S + ARC) / 2                   # 0 at front edge of the right face
    m = rt & (y < 95) & (zr < 52)
    iz = np.clip((zr[m] / 60 * (pw - 1)).astype(int), 0, pw - 1)
    iy = np.clip(((95 - y[m]) / 95 * (ph - 1)).astype(int), 0, ph - 1)
    col[m] = chef_q[iy, iz]
    ink |= m
    col[rt & (y < 95) & (zr < 6)] = C_MAROON          # dark band along the front edge

    # ---------------- back: pale green information label (from the back photo)
    bk = face == 2
    img8 = _load("08_back_left.jpg")
    lw, lh = 700, 920
    lab_img = _warp_quad(img8, [(2650, 620), (3430, 770), (3480, 2430), (2620, 2300)], lw, lh)
    v = lab_img.max(-1)
    dark = (ndimage.grey_closing(v, size=(15, 15)) - v) > 0.08
    red = (lab_img[..., 0] > lab_img[..., 1] + 0.15) & (v < 0.7)
    lab_q = np.ones(lab_img.shape) * C_GREEN
    lab_q[red] = C_MAROON
    lab_q[dark & ~red] = C_BROWN
    lab_q = ndimage.median_filter(lab_q, size=(2, 2, 1))
    xb = loc                                            # left->right seen from behind
    m = bk & (y < 102)
    col[m] = C_GREEN
    mm = bk & (y < 100) & (xb > -15) & (xb < 55) & (y > 8)
    ix = np.clip(((xb[mm] + 15) / 70 * (lw - 1)).astype(int), 0, lw - 1)
    iy = np.clip(((100 - y[mm]) / 92 * (lh - 1)).astype(int), 0, lh - 1)
    col[mm] = lab_q[iy, ix]
    ink |= m

    # ---------------- left side: clear, green top band, maroon foot
    lf = face == 3
    m = lf & (y < 14)
    col[m] = C_MAROON
    ink |= m
    m = lf & (y > 88) & (y < 102)
    col[m] = C_GREEN
    ink |= m
    # right side: maroon foot strip continuing from the front
    m = rt & (y < 10)
    col[m] = C_MAROON; ink |= m
    # bottom: maroon
    m = T < T_FIL
    col[m] = C_MAROON; ink |= m

    window = (~ink).astype(float)
    window = ndimage.gaussian_filter(window, 1.0)
    return np.clip(col, 0, 1), window


def film_normal(res_u=2048, res_v=1024, seed=12):
    """Crinkles in the film: many short sharp creases + fine wrinkles."""
    rng = np.random.default_rng(seed)
    h = np.zeros((res_v, res_u))
    yy, xx = np.mgrid[0:res_v, 0:res_u]
    for _ in range(420):
        cx, cy = rng.uniform(0, res_u), rng.uniform(0, res_v)
        L = rng.uniform(20, 160); a = rng.uniform(0, np.pi)
        dx, dy = np.cos(a), np.sin(a)
        x0, x1 = int(max(cx - L, 0)), int(min(cx + L, res_u))
        y0, y1 = int(max(cy - L, 0)), int(min(cy + L, res_v))
        X, Y = xx[y0:y1, x0:x1] - cx, yy[y0:y1, x0:x1] - cy
        along = X * dx + Y * dy
        across = -X * dy + Y * dx
        w = rng.uniform(1.2, 3.5)
        prof = np.clip(1 - np.abs(across) / w, 0, 1) * np.clip(1 - np.abs(along) / L, 0, 1) ** 0.5
        h[y0:y1, x0:x1] += rng.choice([-1, 1]) * rng.uniform(0.3, 1.0) * prof
    h += 0.25 * ndimage.gaussian_filter(rng.normal(size=h.shape), 6)
    return h
