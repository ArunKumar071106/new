"""Camera pose estimation by silhouette coherence.

Feature-based SfM cannot be used for low-texture objects photographed in front of a
static background (features lock onto the background, not the rotating object). Instead
poses are initialised from the labelled perspectives and refined so the visual hull of
all views re-projects onto every silhouette as completely as possible
(silhouette coherence; cf. Hernandez, Schmitt & Cipolla, PAMI 2007).

Capture model
- front/back/left/right: "turntable" - one fixed camera, the object rotated about its
  vertical axis and possibly slid on the table. Shared: elevation, roll, distance, aim.
  Per view: rotation angle and table translation.
- top/elevated: independent 6-DoF cameras (often a different session/background).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.optimize import minimize

from .cameras import Camera, free_camera, turntable_camera
from .carve import carve, grid_for_box, iou, splat
from .photo import SurfaceProbe, photo_error

LABEL_AZ = {"front": 0.0, "right": 90.0, "back": 180.0, "left": -90.0}
AZ_PRIOR_SIGMA_DEG = 25.0  # Gaussian prior on each view's rotation around its labelled angle
AZ_PRIOR_WEIGHT = 0.015  # coherence units lost at 1 sigma deviation


def _mask_at(mask: np.ndarray, long_side: int) -> np.ndarray:
    h, w = mask.shape
    s = long_side / max(h, w)
    m = cv2.resize(mask.astype(np.float32), (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    return (m > 0.5).astype(np.uint8)


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    return xs.min(), xs.max(), ys.min(), ys.max()


@dataclass
class PoseState:
    shared: dict
    tt: dict  # name -> (az, tx, tz)
    free: dict = field(default_factory=dict)  # name -> (az, el, roll, d, tx, ty, tz)


class PoseEstimator:
    def __init__(self, masks: dict[str, np.ndarray], focal_ratio: float, height_m: float,
                 pose_res: int = 320, grid_res: int = 56, log=print):
        self.names = list(masks)
        self.tt_names = [n for n in ("front", "back", "left", "right") if n in masks]
        self.free_names = [n for n in self.names if n not in self.tt_names]
        self.masks = {n: _mask_at(m, pose_res) for n, m in masks.items()}
        self.focal_ratio = focal_ratio
        self.H = height_m
        self.log = log
        self.grid_res = grid_res
        self.evals = 0

    # ------------------------------------------------------------------ cameras
    def _f(self, n):
        h, w = self.masks[n].shape
        return self.focal_ratio * max(h, w), w, h

    def camera(self, st: PoseState, n: str) -> Camera:
        f, w, h = self._f(n)
        if n in st.tt:
            az, tx, tz = st.tt[n]
            return turntable_camera(st.shared, az, np.array([tx, 0.0, tz]), f, w, h)
        az, el, roll, d, tx, ty, tz = st.free[n]
        return free_camera(az, el, d, np.array([tx, ty, tz]), roll, f, w, h)

    # ------------------------------------------------------------------ init
    def initial_state(self) -> PoseState:
        ref = self.tt_names[0]
        f, w, h = self._f(ref)
        x0, x1, y0, y1 = _bbox(self.masks[ref])
        hpx = y1 - y0
        el = np.radians(12.0)
        d = f * self.H / hpx * 1.0
        uc, vc = (x0 + x1) / 2, (y0 + y1) / 2
        tx = -(uc - (w - 1) / 2) * d / f
        ty = (vc - (h - 1) / 2) * d / f
        shared = {"el": el, "roll": 0.0, "d": d, "tx": tx, "ty": ty}
        tt = {n: (np.radians(LABEL_AZ[n]), 0.0, 0.0) for n in self.tt_names}
        wpx = x1 - x0
        self.half = 0.5 * max(self.H, self.H * wpx / hpx) * 1.35
        self.grid = grid_for_box([-self.half] * 3, [self.half] * 3, self.grid_res, pad=0.0)
        self.pts = self.grid.points()
        return PoseState(shared, tt)

    # ------------------------------------------------------------------ objective
    def hull(self, st: PoseState, names: list[str]) -> np.ndarray:
        cams = [self.camera(st, n) for n in names]
        occ = carve(self.pts, cams, [self.masks[n] for n in names])
        return self.pts[occ]

    def view_iou(self, st: PoseState, hull_pts: np.ndarray, n: str) -> float:
        cam = self.camera(st, n)
        return iou(splat(cam, hull_pts, self.masks[n].shape, float(self.grid.voxel[0])), self.masks[n])

    def _tt_pack(self, st):
        s = st.shared
        v = [s["el"], s["roll"], s["tx"] / self.H, s["ty"] / self.H]
        for n in self.tt_names[1:]:
            az, tx, tz = st.tt[n]
            v += [az, tx / self.H, tz / self.H]
        return np.array(v)

    def _tt_unpack(self, v, st):
        shared = dict(st.shared, el=v[0], roll=v[1], tx=v[2] * self.H, ty=v[3] * self.H)
        tt = {self.tt_names[0]: st.tt[self.tt_names[0]]}
        for i, n in enumerate(self.tt_names[1:]):
            az, tx, tz = v[4 + 3 * i: 7 + 3 * i]
            tt[n] = (az, tx * self.H, tz * self.H)
        return PoseState(shared, tt, dict(st.free))

    def _prior(self, st: PoseState) -> float:
        pen = 0.0
        for n in self.tt_names:
            dev = np.degrees(np.angle(np.exp(1j * (st.tt[n][0] - np.radians(LABEL_AZ[n])))))
            # MAP: silhouettes of near-symmetric objects are flat in rotation, so without a prior the
            # angle drifts within the flat region; the user's perspective label is that prior.
            pen += AZ_PRIOR_WEIGHT * (dev / AZ_PRIOR_SIGMA_DEG) ** 2
        el = np.degrees(st.shared["el"])
        pen += max(0.0, -5 - el) ** 2 * 1e-3 + max(0.0, el - 50) ** 2 * 1e-3
        return pen

    def tt_score(self, st: PoseState) -> float:
        self.evals += 1
        hp = self.hull(st, self.tt_names)
        return float(np.mean([self.view_iou(st, hp, n) for n in self.tt_names])) - self._prior(st)

    def refine_turntable(self, st: PoseState, maxfev=900) -> PoseState:
        # coarse search over elevation first (shared, strongly coupled to all views)
        best = (self.tt_score(st), st)
        for el in (0, 6, 12, 18, 24, 30):
            cand = PoseState(dict(st.shared, el=np.radians(el)), dict(st.tt))
            sc = self.tt_score(cand)
            if sc > best[0]:
                best = (sc, cand)
        st = best[1]
        # coarse search over each view's rotation angle
        for n in self.tt_names[1:]:
            base = st.tt[n]
            best = (self.tt_score(st), st)
            for dz in range(-30, 31, 10):
                cand = PoseState(st.shared, dict(st.tt))
                cand.tt[n] = (np.radians(LABEL_AZ[n] + dz), base[1], base[2])
                sc = self.tt_score(cand)
                if sc > best[0]:
                    best = (sc, cand)
            st = best[1]
        self.log(f"  turntable coarse search: coherence={self.tt_score(st):.3f}")
        v0 = self._tt_pack(st)
        res = minimize(lambda v: -self.tt_score(self._tt_unpack(v, st)), v0, method="Powell",
                       options={"maxfev": maxfev, "xtol": 1e-3, "ftol": 1e-4,
                                "direc": np.diag(np.where(np.arange(len(v0)) < 2, 0.03, 0.02))})
        st = self._tt_unpack(res.x, st)
        self.log(f"  turntable refined: coherence={self.tt_score(st):.3f}")
        return st

    # ------------------------------------------------------------------ free views
    def _fit_scale_center(self, n, az, el, roll, hull_pts, d, target):
        """Adjust distance & target so the projected hull matches the mask's size and centroid."""
        m = self.masks[n]
        ys, xs = np.nonzero(m)
        mc = np.array([xs.mean(), ys.mean()])
        msize = np.sqrt(len(xs))
        f, w, h = self._f(n)
        for _ in range(3):
            cam = free_camera(az, el, d, target, roll, f, w, h)
            p = splat(cam, hull_pts, m.shape, float(self.grid.voxel[0]))
            if p.sum() < 10:
                return d, target
            py, px = np.nonzero(p)
            d *= np.sqrt(len(px)) / msize
            cam = free_camera(az, el, d, target, roll, f, w, h)
            p = splat(cam, hull_pts, m.shape, float(self.grid.voxel[0]))
            py, px = np.nonzero(p)
            if len(px) == 0:
                return d, target
            off = np.array([px.mean(), py.mean()]) - mc  # pixels the hull must move
            shift = (off[0] * cam.R[0] + off[1] * cam.R[1]) * d / f
            target = target + shift
        return d, target

    def init_free_view(self, st: PoseState, n: str, hull_pts: np.ndarray) -> PoseState:
        if n == "top":
            els, azs, rolls = (70, 80, 88), range(-180, 180, 15), (0.0,)
        else:
            els, azs, rolls = (25, 40, 55), range(-180, 180, 20), (-15, 0, 15)
        best = (-1.0, None)
        d0 = st.shared["d"]
        for el in els:
            for az in azs:
                for roll in rolls:
                    a, e, r = np.radians(az), np.radians(el), np.radians(roll)
                    d, tgt = self._fit_scale_center(n, a, e, r, hull_pts, d0, np.zeros(3))
                    f, w, h = self._f(n)
                    cam = free_camera(a, e, d, tgt, r, f, w, h)
                    sc = iou(splat(cam, hull_pts, self.masks[n].shape, float(self.grid.voxel[0])), self.masks[n])
                    if sc > best[0]:
                        best = (sc, (a, e, r, d, *tgt))
        st.free[n] = best[1]
        self.log(f"  {n}: grid-search init az={np.degrees(best[1][0]):.0f} el={np.degrees(best[1][1]):.0f} "
                 f"IoU={best[0]:.3f}")
        return st

    def refine_free_view(self, st: PoseState, n: str, hull_pts: np.ndarray, maxfev=500, quiet=False) -> PoseState:
        p0 = np.array(st.free[n], float)
        scale = np.array([1, 1, 1, 1 / self.H, 1 / self.H, 1 / self.H, 1 / self.H])

        def score(v):
            p = v / scale
            if not (0.05 * p0[3] < p[3] < 5 * p0[3]):
                return 0.0
            st.free[n] = tuple(p)
            return -self.view_iou(st, hull_pts, n)

        res = minimize(score, p0 * scale, method="Powell",
                       options={"maxfev": maxfev, "xtol": 1e-3, "ftol": 1e-4, "direc": np.eye(7) * 0.03})
        st.free[n] = tuple(res.x / scale)
        if not quiet:
            self.log(f"  {n}: refined IoU={-res.fun:.3f}")
        return st

    # ------------------------------------------------------------------ diagnostics
    def consistency(self, st: PoseState, names: list[str] | None = None) -> dict:
        """For each view: re-project the hull of all *other* views and compare with its mask."""
        names = names or self.names
        out = {}
        for n in names:
            others = [o for o in names if o != n]
            hp = self.hull(st, others)
            cam = self.camera(st, n)
            p = splat(cam, hp, self.masks[n].shape, float(self.grid.voxel[0])) > 0
            m = self.masks[n] > 0
            out[n] = {
                "iou": iou(p, m),
                "mask_explained": float((p & m).sum() / max(m.sum(), 1)),
                "predicted_outside_mask": float((p & ~m).sum() / max(p.sum(), 1)),
                "predicted": p,
            }
        return out

    # ------------------------------------------------------------------ photometric disambiguation
    def _photo(self, st: PoseState, names: list[str], labs: dict, involve: str) -> float:
        occ = carve(self.pts, [self.camera(st, n) for n in names], [self.masks[n] for n in names])
        probe = SurfaceProbe(occ.reshape(self.grid.res), self.grid.lo, float(self.grid.voxel[0]))
        return photo_error(probe, {n: self.camera(st, n) for n in names}, labs, involve=involve)

    def resolve_turntable_azimuths(self, st: PoseState, labs: dict, span=55, step=5) -> tuple[PoseState, dict]:
        """Dense scan of each view's rotation angle (Powell can stall on the flat plateau that
        near-symmetric silhouettes produce). The pick maximises the posterior: silhouette
        coherence plus the Gaussian label prior. Colour disagreement is recorded as a
        diagnostic only - under directional light on a turntable the shading changes with
        rotation, which made it unreliable in testing."""
        table = {}
        for n in self.tt_names[1:]:
            base = st.tt[n]
            rows = []
            for daz in range(-span, span + 1, step):
                cand = PoseState(st.shared, dict(st.tt), dict(st.free))
                cand.tt[n] = (base[0] + np.radians(daz), base[1], base[2])
                post = self.tt_score(cand)
                rows.append((daz, post, self._photo(cand, self.tt_names, labs, n), cand, post + self._prior(cand)))
            pick = max(rows, key=lambda r: r[1])
            st = pick[3]
            table[n] = {"angle_deg": float(np.degrees(st.tt[n][0])), "shift_deg": pick[0],
                        "posterior": pick[1], "photo_error": pick[2],
                        "scan": [(r[0], round(r[4], 4), round(r[2], 2)) for r in rows]}
            self.log(f"  {n}: angle {np.degrees(st.tt[n][0]):.0f} deg "
                     f"(shift {pick[0]:+d}, posterior={pick[1]:.3f}, colour err={pick[2]:.1f})")
        return st, table

    def init_free_view_candidates(self, st: PoseState, n: str, hull_pts: np.ndarray, labs: dict,
                                  keep: int = 6) -> PoseState:
        """Grid search, then pick among the best silhouette fits by photo-consistency."""
        if n == "top":
            els, azs, rolls = (70, 80, 88), range(-180, 180, 15), (0.0,)
        else:
            els, azs, rolls = (25, 40, 55), range(-180, 180, 20), (-15, 0, 15)
        f, w, h = self._f(n)
        cands = []
        for el in els:
            for az in azs:
                for roll in rolls:
                    a, e, r = np.radians(az), np.radians(el), np.radians(roll)
                    d, tgt = self._fit_scale_center(n, a, e, r, hull_pts, st.shared["d"], np.zeros(3))
                    cam = free_camera(a, e, d, tgt, r, f, w, h)
                    sc = iou(splat(cam, hull_pts, self.masks[n].shape, float(self.grid.voxel[0])), self.masks[n])
                    cands.append((sc, (a, e, r, d, *tgt)))
        cands.sort(key=lambda c: -c[0])
        top = [c for c in cands[: keep * 3] if c[0] >= cands[0][0] - 0.04]
        # de-duplicate near-identical angles
        uniq = []
        for c in top:
            if all(abs(np.angle(np.exp(1j * (c[1][0] - u[1][0])))) > np.radians(10) or abs(c[1][1] - u[1][1]) > 0.1
                   for u in uniq):
                uniq.append(c)
        uniq = uniq[:keep]
        best = None
        for sc, p in uniq:
            cand = PoseState(st.shared, dict(st.tt), dict(st.free))
            cand.free[n] = p
            cand = self.refine_free_view(cand, n, hull_pts, maxfev=200, quiet=True)
            sil = self.view_iou(cand, hull_pts, n)
            pe = self._photo(cand, self.tt_names + [n], labs, n)
            self.log(f"    {n} candidate az={np.degrees(p[0]):.0f} el={np.degrees(p[1]):.0f}: "
                     f"IoU={sil:.3f} colour err={pe:.1f}")
            score = sil - 0.0005 * pe  # colour only breaks near-ties
            if best is None or score > best[0]:
                best = (score, cand)
        return best[1]
