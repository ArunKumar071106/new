#!/usr/bin/env python3
"""Six-view silhouette-based 3D reconstruction -> textured GLB.

Usage:
  python reconstruction/pipeline.py --front f.jpg --back b.jpg --left l.jpg --right r.jpg \
      --top t.jpg --elevated e.jpg --out public/models/reconstructed-object.glb

Stages: load -> segment (+completion) -> analyse -> pose (silhouette coherence +
photo-consistency) -> consistency check / mask repair -> high-res visual hull ->
base inference -> mesh -> UV unwrap + multi-view texture bake -> GLB export -> validation.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from recon import VIEWS  # noqa: E402
from recon.analysis import analyse  # noqa: E402
from recon.carve import carve, grid_for_box  # noqa: E402
from recon.export import export_glb, validate_glb  # noqa: E402
from recon.imageio import load_view  # noqa: E402
from recon.mesh import infer_base, occupancy_to_mesh  # noqa: E402
from recon.photo import apply_gain, colour_gains, to_lab  # noqa: E402
from recon.pose import PoseEstimator  # noqa: E402
from recon.segment import complete_mask, repair_with_prediction, segment  # noqa: E402
from recon.texture import bake  # noqa: E402


@dataclass
class Options:
    object_height_cm: float = 11.0  # real-world height used for metric scale (not recoverable from photos)
    focal_ratio: float = 0.75  # focal length / long image side (~26 mm-equivalent phone lens)
    work_size: int = 1024
    tex_source_size: int = 2048
    grid_res: int = 192
    target_faces: int = 40000
    smooth_sigma: float = 1.4  # Gaussian smoothing of the occupancy field (voxels) before meshing
    texture_res: int = 2048
    bottom_mode: str = "flat"  # "flat": infer a flat base | "hull": keep raw visual-hull underside
    mask_tolerance_px: int = 2  # silhouette dilation at work resolution, tolerates small pose error
    consistency_threshold: float = 0.72  # below this a view is used for texture only
    segmentation_model: str = "u2net"


class Progress:
    def __init__(self, cb=None):
        self.cb = cb
        self.t0 = time.time()
        self.lines: list[str] = []

    def __call__(self, frac: float, stage: str, msg: str = ""):
        line = f"[{time.time() - self.t0:6.1f}s] {int(frac * 100):3d}% {stage}{': ' + msg if msg else ''}"
        self.lines.append(line)
        print(line, flush=True)
        if self.cb:
            self.cb(frac, stage, msg)

    def log(self, msg: str):
        self.lines.append(msg)
        print(msg, flush=True)


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items() if not isinstance(v, np.ndarray) or v.size < 64}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return o


def run(paths: dict[str, str], out_glb: str, report_path: str | None = None, opts: Options | None = None,
        progress_cb=None, debug_dir: str | None = None) -> dict:
    opts = opts or Options()
    P = Progress(progress_cb)
    missing = [v for v in VIEWS if v not in paths]
    if missing:
        raise ValueError(f"missing perspectives: {missing}")
    report: dict = {"options": asdict(opts), "status": "running"}

    # 1. load ---------------------------------------------------------------
    P(0.02, "load", "reading images (EXIF orientation applied, aspect ratios preserved)")
    views = {n: load_view(n, paths[n], opts.work_size, opts.tex_source_size) for n in VIEWS}

    # 2. segmentation -------------------------------------------------------
    for i, n in enumerate(VIEWS):
        P(0.05 + 0.03 * i, "segment", n)
        m, src = segment(views[n].work, opts.segmentation_model)
        before = int(m.sum())
        m2 = complete_mask(views[n].work, m)
        gain = m2.sum() / max(before, 1) - 1
        views[n].mask = m2
        views[n].mask_source = src + (f" + colour completion (+{gain * 100:.1f}% area)" if gain > 0.005 else "")
        views[n].meta["completion_gain"] = float(gain)

    # 3. analysis -----------------------------------------------------------
    P(0.25, "analyse", "quality, same-object check, feature overlap, lighting")
    report["analysis"] = analyse(views)
    for n in VIEWS:
        if views[n].meta["completion_gain"] > 0.10:
            report["analysis"]["per_view"][n]["warnings"].append(
                f"segmentation model missed {views[n].meta['completion_gain'] * 100:.0f}% of the object; "
                "recovered by colour-model completion")
    if report["analysis"]["same_object"]["outliers"]:
        P.log("WARNING: " + report["analysis"]["same_object"]["verdict"])

    # 4. pose ---------------------------------------------------------------
    P(0.30, "pose", "turntable model for front/back/left/right (silhouette coherence)")
    pe = PoseEstimator({n: v.mask for n, v in views.items()}, opts.focal_ratio, opts.object_height_cm / 100,
                       log=P.log)
    st = pe.initial_state()
    st = pe.refine_turntable(st)
    gains = colour_gains(views, "front")
    labs = {}
    for n, v in views.items():
        m = pe.masks[n]
        im = cv2.resize(apply_gain(v.work, gains[n]), (m.shape[1], m.shape[0]), interpolation=cv2.INTER_AREA)
        labs[n] = to_lab(cv2.GaussianBlur(im, (0, 0), 1.0))
    P(0.42, "pose", "dense rotation-angle scan (silhouettes + label prior)")
    st, az_table = pe.resolve_turntable_azimuths(st, labs)
    st = pe.refine_turntable(st, maxfev=300)
    hull_tt = pe.hull(st, pe.tt_names)
    for n in pe.free_names:
        P(0.50, "pose", f"{n}: grid search + photo-consistency + refinement")
        st = pe.init_free_view_candidates(st, n, hull_tt, labs)
        st = pe.refine_free_view(st, n, hull_tt)

    # 5. consistency & repair ----------------------------------------------
    P(0.58, "consistency", "re-projecting the hull of the other views into each photo")
    cons = pe.consistency(st)
    repaired = []
    for n, c in cons.items():
        if c["predicted_outside_mask"] > 0.15 and c["mask_explained"] > 0.85:
            # others say "object" where this mask says "background": try to recover missed regions
            pred = cv2.resize(c["predicted"].astype(np.uint8), (views[n].mask.shape[1], views[n].mask.shape[0]),
                              interpolation=cv2.INTER_NEAREST)
            new = repair_with_prediction(views[n].work, views[n].mask, pred)
            if new.sum() > views[n].mask.sum() * 1.01:
                views[n].mask = new
                pe.masks[n] = cv2.resize(new, (pe.masks[n].shape[1], pe.masks[n].shape[0]),
                                         interpolation=cv2.INTER_NEAREST)
                repaired.append(n)
    if repaired:
        P.log(f"  masks repaired with hull guidance: {repaired}")
        cons = pe.consistency(st)
    carve_views = [n for n in VIEWS if cons[n]["iou"] >= opts.consistency_threshold]
    if len(carve_views) < 3:
        carve_views = sorted(VIEWS, key=lambda n: -cons[n]["iou"])[:3]
    confidence = {n: float(np.clip((cons[n]["iou"] - 0.5) / 0.4, 0.15, 1.0)) for n in VIEWS}

    # 6. high resolution carving -------------------------------------------
    P(0.62, "carve", f"visual hull from {carve_views} at {opts.grid_res}^3")
    cams_work = {n: pe.camera(st, n).scaled(views[n].work.shape[1] / pe.masks[n].shape[1]) for n in VIEWS}
    k = 2 * opts.mask_tolerance_px + 1
    masks_carve = {n: cv2.dilate(views[n].mask, np.ones((k, k), np.uint8)) for n in VIEWS}
    coarse = hull_tt if len(hull_tt) else pe.pts
    full_coarse = pe.hull(st, carve_views)
    if len(full_coarse) > 50:
        coarse = full_coarse
    grid = grid_for_box(coarse.min(0), coarse.max(0), opts.grid_res, pad=0.12)
    pts = grid.points()
    occ = carve(pts, [cams_work[n] for n in carve_views], [masks_carve[n] for n in carve_views])
    occ3d = occ.reshape(grid.res)
    P.log(f"  occupied voxels: {int(occ.sum())} / {occ.size}, voxel = {grid.voxel[0] * 1000:.2f} mm")
    if occ.sum() < 1000:
        raise RuntimeError("visual hull is empty or tiny: camera poses or masks are inconsistent")

    base = infer_base(occ3d, grid)
    if opts.bottom_mode == "flat":
        occ3d[:, : base["base_index"], :] = False
    P.log(f"  base plane: removed {base['skirt_height_m'] * 1000:.1f} mm visual-hull skirt below the base"
          if opts.bottom_mode == "flat" else "  base: raw visual hull kept")

    # 7. mesh -------------------------------------------------------------
    P(0.70, "mesh", "marching cubes, Taubin smoothing, decimation")
    mesh = occupancy_to_mesh(occ3d, grid, smooth_sigma=opts.smooth_sigma, target_faces=opts.target_faces,
                             taubin_iters=15)
    P.log(f"  mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} triangles, watertight={mesh.is_watertight}")

    # 8. texture ----------------------------------------------------------
    P(0.76, "texture", f"UV unwrap + bake from 6 photos into {opts.texture_res}px atlas")
    from scipy import ndimage

    field = ndimage.gaussian_filter(occ3d.astype(np.float32), 1.0)
    tex_imgs, tex_masks, tex_cams = {}, {}, {}
    for n, v in views.items():
        s = v.tex.shape[1] / v.work.shape[1]
        tex_imgs[n] = apply_gain(v.tex, gains[n])
        tex_masks[n] = cv2.resize(v.mask, (v.tex.shape[1], v.tex.shape[0]), interpolation=cv2.INTER_NEAREST)
        tex_cams[n] = cams_work[n].scaled(s)
    tm = bake(np.asarray(mesh.vertices), np.asarray(mesh.faces), np.asarray(mesh.vertex_normals), tex_cams,
              tex_imgs, tex_masks, confidence, field, grid.lo, float(grid.voxel[0]), opts.texture_res, log=P.log)

    # 9. metric frame: base centre at origin, +Y up, front towards +Z, height = object_height
    V = tm.vertices
    lo, hi = V.min(0), V.max(0)
    scale = (opts.object_height_cm / 100) / (hi[1] - lo[1])
    offset = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
    tm.vertices = (V - offset) * scale

    P(0.93, "export", "writing GLB")
    os.makedirs(os.path.dirname(os.path.abspath(out_glb)), exist_ok=True)
    exp = export_glb(tm, out_glb)
    P(0.97, "validate", "re-loading and checking the GLB")
    val = validate_glb(out_glb)

    report.update({
        "status": "ok" if val["valid"] else "invalid",
        "method": "silhouette-based multi-view reconstruction (visual hull) with silhouette-coherence pose "
                  "estimation, photo-consistency disambiguation and multi-view texture baking",
        "segmentation": {n: views[n].mask_source for n in VIEWS},
        "poses": {
            "focal_ratio_assumed": opts.focal_ratio,
            "turntable": {"elevation_deg": float(np.degrees(st.shared["el"])),
                          "roll_deg": float(np.degrees(st.shared["roll"])),
                          "angles_deg": {n: float(np.degrees(st.tt[n][0])) for n in pe.tt_names}},
            "free": {n: {"azimuth_deg": float(np.degrees(p[0])), "elevation_deg": float(np.degrees(p[1])),
                         "roll_deg": float(np.degrees(p[2]))} for n, p in st.free.items()},
            "angle_ambiguity": {n: {"chosen_deg": r["angle_deg"],
                                    "silhouette_plausible_range_deg": _plausible_range(r, st, n)}
                                for n, r in az_table.items()},
            "cameras_object_frame": {n: cams_work[n].to_dict() for n in VIEWS},
        },
        "consistency": {n: {k2: round(v2, 3) for k2, v2 in c.items() if k2 != "predicted"} for n, c in cons.items()},
        "views_used_for_carving": carve_views,
        "views_texture_only": [n for n in VIEWS if n not in carve_views],
        "masks_repaired": repaired,
        "texture_confidence": confidence,
        "base": {**base, "mode": opts.bottom_mode},
        "texture": tm.stats,
        "scale": {"object_height_m": opts.object_height_cm / 100, "note": "metric scale is assumed from "
                  "object_height_cm; photos alone cannot determine absolute size"},
        "export": exp,
        "validation": val,
        "limitations": _limitations(tm.stats, cons, carve_views, opts),
        "log": P.lines,
    })
    report = _jsonable(report)
    if report_path:
        with open(report_path, "w") as fh:
            json.dump(report, fh, indent=2)
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "texture.jpg"), cv2.cvtColor(tm.texture, cv2.COLOR_RGB2BGR))
        for n in VIEWS:
            vis = views[n].work // 2
            cnt, _ = cv2.findContours(views[n].mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            cv2.drawContours(vis, cnt, -1, (0, 255, 0), 2)
            cv2.imwrite(os.path.join(debug_dir, f"mask_{n}.jpg"), vis)
    P(1.0, "done", f"{val['triangles']} triangles, {exp['bytes'] / 1e6:.2f} MB")
    return report


def _plausible_range(row: dict, st, n) -> list[float]:
    best = max(s for _, s, _ in row["scan"])
    ok = [d for d, s, _ in row["scan"] if s >= best - 0.03]
    base = row["angle_deg"] - row["shift_deg"]
    return [base + min(ok), base + max(ok)]


def _limitations(tex_stats, cons, carve_views, opts) -> list[str]:
    out = [
        f"Underside never photographed: {tex_stats['inferred_surface_fraction'] * 100:.1f}% of the surface "
        f"(mostly the base) has inferred geometry ({opts.bottom_mode}) and colour diffused from neighbouring "
        "observed surface.",
        "Visual hulls cannot represent concavities; cavities such as the inside of an open container are "
        "filled in.",
        "No EXIF focal length: a typical phone focal length was assumed (focal_ratio); perspective strength "
        "and camera elevation are estimated jointly and may be biased.",
        "Absolute size comes from object_height_cm, not from the photos.",
    ]
    weak = [n for n, c in cons.items() if c["iou"] < 0.85]
    if weak:
        out.append(f"Lower silhouette agreement for {weak}: geometry there is less certain.")
    if len(carve_views) < 6:
        out.append(f"Views excluded from carving (texture only): {[n for n in VIEWS if n not in carve_views]}.")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for v in VIEWS:
        ap.add_argument(f"--{v}", required=True, help=f"{v} view image")
    ap.add_argument("--out", default="public/models/reconstructed-object.glb")
    ap.add_argument("--report", default=None, help="JSON report path (default: next to --out)")
    ap.add_argument("--debug-dir", default=None)
    for f, val in asdict(Options()).items():
        ap.add_argument("--" + f.replace("_", "-"), type=type(val), default=val)
    a = ap.parse_args()
    opts = Options(**{f: getattr(a, f) for f in asdict(Options())})
    report_path = a.report or os.path.splitext(a.out)[0] + ".report.json"
    rep = run({v: getattr(a, v) for v in VIEWS}, a.out, report_path, opts, debug_dir=a.debug_dir)
    sys.exit(0 if rep["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
