"""Foreground segmentation.

Primary: U^2-Net salient-object model via `rembg` (CPU, ONNX, ~176 MB, downloaded once).
Fallback: OpenCV GrabCut seeded from a centred rectangle (no download, lower quality).
Also provides hull-guided mask repair (GrabCut seeded by the silhouette that the other
views predict), used when a view's mask is inconsistent with the rest.
"""
from __future__ import annotations

import cv2
import numpy as np

_SESSION = None


def _rembg_session(model: str):
    global _SESSION
    if _SESSION is None:
        from rembg import new_session  # optional dependency

        _SESSION = new_session(model)
    return _SESSION


def clean_mask(mask: np.ndarray) -> np.ndarray:
    """Keep the largest connected component and fill interior holes."""
    m = (mask > 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return m
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    m = (lab == biggest).astype(np.uint8)
    # fill holes: flood fill the background from the border
    pad = cv2.copyMakeBorder(m, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = pad.copy()
    cv2.floodFill(ff, None, (0, 0), 1)
    holes = (ff[1:-1, 1:-1] == 0)
    m[holes] = 1
    return m


def segment(img_bgr: np.ndarray, model: str = "u2net") -> tuple[np.ndarray, str]:
    try:
        from rembg import remove

        rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
        alpha = remove(rgb, session=_rembg_session(model), only_mask=True)
        alpha = np.asarray(alpha)
        return clean_mask(alpha > 127), f"rembg:{model}"
    except Exception as exc:  # pragma: no cover - fallback path
        return grabcut_rect(img_bgr), f"grabcut-fallback ({type(exc).__name__})"


def grabcut_rect(img_bgr: np.ndarray) -> np.ndarray:
    h, w = img_bgr.shape[:2]
    rect = (int(w * 0.15), int(h * 0.08), int(w * 0.7), int(h * 0.84))
    gc = np.zeros((h, w), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img_bgr, gc, rect, bgd, fgd, 6, cv2.GC_INIT_WITH_RECT)
    return clean_mask(np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD)))


def repair_with_prediction(img_bgr: np.ndarray, mask: np.ndarray, predicted: np.ndarray) -> np.ndarray:
    """GrabCut refinement: segmentation = sure FG, hull prediction = probable FG.

    The visual hull of the *other* views is a superset of the true object, so its
    projection bounds where the missing object pixels can be; GrabCut decides which of
    those pixels look like object (colour model) rather than background.
    """
    k = max(3, int(round(min(mask.shape) * 0.006)))
    sure_fg = cv2.erode(mask, np.ones((k, k), np.uint8))
    pred = cv2.dilate(predicted, np.ones((k, k), np.uint8))
    gc = np.full(mask.shape, cv2.GC_BGD, np.uint8)
    gc[pred > 0] = cv2.GC_PR_FGD
    gc[(mask > 0) & (sure_fg == 0)] = cv2.GC_PR_FGD
    gc[sure_fg > 0] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img_bgr, gc, None, bgd, fgd, 8, cv2.GC_INIT_WITH_MASK)
    out = np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8)
    out = cv2.morphologyEx(out, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    return clean_mask(out | mask)


def complete_mask(img_bgr: np.ndarray, mask: np.ndarray, band: float = 0.30) -> np.ndarray:
    """Recover object regions the saliency model dropped (e.g. a container rim seen from above).

    GrabCut learns object/background colour models with the network mask as foreground
    and a band around it (radius = band * sqrt(object area)) as *probable* background;
    pixels in the band that match the object's colours are added back. Pixels outside the
    band are fixed background, so this cannot leak far into the scene.
    """
    m = (mask > 0).astype(np.uint8)
    r = max(3, int(band * np.sqrt(m.sum())))
    k = max(3, int(round(0.006 * max(m.shape))))
    sure = cv2.erode(m, np.ones((k, k), np.uint8))
    ring = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    gc = np.full(m.shape, cv2.GC_BGD, np.uint8)
    gc[ring > 0] = cv2.GC_PR_BGD
    gc[m > 0] = cv2.GC_PR_FGD
    gc[sure > 0] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img_bgr, gc, None, bgd, fgd, 8, cv2.GC_INIT_WITH_MASK)
    return clean_mask(np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD)) | (m > 0))
