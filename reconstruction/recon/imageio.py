"""Image loading. Images keep their own resolution and aspect ratio (never stretched)."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image, ImageOps


@dataclass
class ViewImage:
    name: str
    path: str
    original_size: tuple[int, int]  # (width, height) after EXIF orientation
    work: np.ndarray  # BGR uint8, long side == work_size (pose / segmentation)
    tex: np.ndarray  # BGR uint8, long side == tex_size (texture sampling)
    mask: np.ndarray | None = None  # uint8 {0,1} at work resolution
    mask_source: str = "segmentation"
    meta: dict = field(default_factory=dict)

    @property
    def work_scale(self) -> float:
        return self.work.shape[1] / self.original_size[0]


def _resize_long(img: np.ndarray, long_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    s = long_side / max(h, w)
    if abs(s - 1) < 1e-6:
        return img.copy()
    interp = cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (round(w * s), round(h * s)), interpolation=interp)


def load_view(name: str, path: str, work_size: int = 1024, tex_size: int = 2048) -> ViewImage:
    pil = Image.open(path)
    pil = ImageOps.exif_transpose(pil).convert("RGB")
    rgb = np.asarray(pil)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    return ViewImage(
        name=name,
        path=path,
        original_size=(w, h),
        work=_resize_long(bgr, work_size),
        tex=_resize_long(bgr, min(tex_size, max(h, w))),
    )
