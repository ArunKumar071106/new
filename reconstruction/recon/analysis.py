"""Pre-reconstruction image analysis: quality, same-object check, overlap, lighting."""
from __future__ import annotations

import itertools

import cv2
import numpy as np

from .photo import colour_gains


def _quality(v) -> dict:
    img, m = v.work, v.mask > 0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    inner = cv2.erode(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    sharp = float(lap[inner].var()) if inner.any() else 0.0
    lum = gray[m]
    ys, xs = np.nonzero(m)
    h, w = m.shape
    border = bool(xs.min() <= 1 or ys.min() <= 1 or xs.max() >= w - 2 or ys.max() >= h - 2)
    warnings = []
    if sharp < 15:
        warnings.append("object region looks blurry / out of focus")
    if lum.mean() < 60:
        warnings.append("object is underexposed")
    if (lum > 250).mean() > 0.06:
        warnings.append(f"{(lum > 250).mean() * 100:.0f}% of the object is overexposed (detail lost in highlights)")
    if m.mean() < 0.03:
        warnings.append("object occupies less than 3% of the frame")
    if border:
        warnings.append("object touches the image border (may be cut off); geometry beyond the frame is not "
                        "carved by this view")
    return {
        "original_size": list(v.original_size),
        "aspect_ratio": round(v.original_size[0] / v.original_size[1], 4),
        "mask_source": v.mask_source,
        "object_area_fraction": round(float(m.mean()), 4),
        "object_bbox_px": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())],
        "sharpness_laplacian_var": round(sharp, 1),
        "mean_luminance": round(float(lum.mean()), 1),
        "highlight_clip_fraction": round(float((lum > 250).mean()), 4),
        "touches_border": border,
        "warnings": warnings,
    }


def _hist(img, m):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], (m > 0).astype(np.uint8), [30, 16], [0, 180, 0, 256])
    return cv2.normalize(h, h, 1, 0, cv2.NORM_L1)


def same_object_check(views: dict, gains: dict) -> dict:
    """Colour-distribution similarity of the segmented objects (after white balancing)."""
    from .photo import apply_gain

    hists = {n: _hist(apply_gain(v.work, gains[n]), v.mask) for n, v in views.items()}
    names = list(views)
    sim = {}
    for a, b in itertools.combinations(names, 2):
        sim[f"{a}-{b}"] = round(1 - float(cv2.compareHist(hists[a], hists[b], cv2.HISTCMP_BHATTACHARYYA)), 3)
    per_view = {n: round(float(np.mean([s for k, s in sim.items() if n in k.split("-")])), 3) for n in names}
    med = float(np.median(list(per_view.values())))
    outliers = [n for n, s in per_view.items() if s < med - 0.2 or s < 0.35]
    return {"pairwise_similarity": sim, "mean_similarity": per_view, "outliers": outliers,
            "verdict": "consistent" if not outliers else "possible different object in: " + ", ".join(outliers)}


def overlap_analysis(views: dict) -> dict:
    """SIFT matches between views, split into object vs background, to decide whether
    feature-based SfM is viable."""
    sift = cv2.SIFT_create(4000)
    feats = {}
    for n, v in views.items():
        g = cv2.cvtColor(v.work, cv2.COLOR_BGR2GRAY)
        kp, des = sift.detectAndCompute(g, None)
        on_obj = np.array([v.mask[int(k.pt[1]), int(k.pt[0])] > 0 for k in kp], bool) if kp else np.zeros(0, bool)
        feats[n] = (kp, des, on_obj)
    bf = cv2.BFMatcher()
    pairs = {}
    obj_total = bg_total = 0
    for a, b in itertools.combinations(views, 2):
        ka, da, oa = feats[a]
        kb, db, ob = feats[b]
        if da is None or db is None or len(da) < 2 or len(db) < 2:
            pairs[f"{a}-{b}"] = {"inliers": 0, "on_object": 0}
            continue
        good = [m for m, n2 in bf.knnMatch(da, db, k=2) if m.distance < 0.75 * n2.distance]
        inl_obj = inl_bg = 0
        if len(good) >= 8:
            pa = np.float32([ka[m.queryIdx].pt for m in good])
            pb = np.float32([kb[m.trainIdx].pt for m in good])
            _, mask = cv2.findFundamentalMat(pa, pb, cv2.FM_RANSAC, 2.0, 0.999)
            if mask is not None:
                for m, keep in zip(good, mask.ravel()):
                    if keep:
                        if oa[m.queryIdx] and ob[m.trainIdx]:
                            inl_obj += 1
                        else:
                            inl_bg += 1
        pairs[f"{a}-{b}"] = {"inliers": inl_obj + inl_bg, "on_object": inl_obj}
        obj_total += inl_obj
        bg_total += inl_bg
    obj_feats = {n: int(f[2].sum()) for n, f in feats.items()}
    viable = obj_total >= 200 and all(c >= 150 for c in obj_feats.values())
    return {
        "object_keypoints": obj_feats,
        "pairs": pairs,
        "matches_on_object": obj_total,
        "matches_on_background": bg_total,
        "feature_sfm_viable": viable,
        "explanation": (
            "Enough textured overlap on the object for feature-based SfM." if viable else
            "Too few geometrically-consistent feature matches on the object itself"
            + (" (most matches lie on the background, which suggests the object was turned while the camera"
               " stayed still)" if bg_total > obj_total else "")
            + "; using silhouette-based reconstruction instead."),
    }


def analyse(views: dict, ref: str = "front") -> dict:
    gains = colour_gains(views, ref)
    return {
        "per_view": {n: _quality(v) for n, v in views.items()},
        "same_object": same_object_check(views, gains),
        "overlap": overlap_analysis(views),
        "lighting": {
            "white_balance_gains_bgr": {n: [round(float(x), 3) for x in g] for n, g in gains.items()},
            "inconsistent": [n for n, g in gains.items() if np.abs(np.log(g)).max() > np.log(1.25)],
        },
        "missing_information": [
            "No photograph shows the underside: base geometry and texture will be inferred.",
            "Silhouettes cannot capture concavities (e.g. the inside of an open container).",
        ],
    }
