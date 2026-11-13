"""Pinhole cameras in the object frame.

Object frame: +Y up, the object's front faces +Z, units = metres.
Camera frame: OpenCV convention (x right, y down, z forward).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def rot_y(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def look_at(C: np.ndarray, T: np.ndarray, roll: float = 0.0) -> np.ndarray:
    fwd = T - C
    fwd = fwd / np.linalg.norm(fwd)
    up = np.array([0.0, 1.0, 0.0])
    if abs(fwd @ up) > 0.9999:  # looking straight down/up: pick a stable reference
        up = np.array([0.0, 0.0, -1.0])
    right = np.cross(fwd, up)
    right /= np.linalg.norm(right)
    down = np.cross(fwd, right)
    R = np.stack([right, down, fwd])
    return rot_z(roll) @ R


@dataclass
class Camera:
    f: float
    cx: float
    cy: float
    R: np.ndarray  # world -> camera rotation
    C: np.ndarray  # camera centre in object frame
    width: int
    height: int

    def to_cam(self, X: np.ndarray) -> np.ndarray:
        return (X - self.C) @ self.R.T

    def project(self, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return pixel coords (N,2) and depth (N,)."""
        Xc = self.to_cam(X)
        z = Xc[:, 2]
        zs = np.where(z > 1e-9, z, 1e-9)
        uv = np.stack([self.f * Xc[:, 0] / zs + self.cx, self.f * Xc[:, 1] / zs + self.cy], axis=1)
        return uv, z

    def scaled(self, s: float) -> "Camera":
        """Same camera for an image resized by factor s."""
        return Camera(self.f * s, (self.cx + 0.5) * s - 0.5, (self.cy + 0.5) * s - 0.5, self.R, self.C,
                      round(self.width * s), round(self.height * s))

    def view_dir(self) -> np.ndarray:
        return self.R[2]

    def to_dict(self) -> dict:
        return {"f": self.f, "cx": self.cx, "cy": self.cy, "R": self.R.tolist(), "C": self.C.tolist(),
                "width": self.width, "height": self.height}


def turntable_camera(p_shared: dict, az: float, t: np.ndarray, f: float, w: int, h: int) -> Camera:
    """Fixed camera, object rotated by `az` about +Y and slid by t=(tx,0,tz) on the table."""
    el, roll, d = p_shared["el"], p_shared["roll"], p_shared["d"]
    T0 = np.array([p_shared["tx"], p_shared["ty"], 0.0])
    C0 = T0 + d * np.array([0.0, np.sin(el), np.cos(el)])
    R0 = look_at(C0, T0, roll)
    Ry = rot_y(az)
    return Camera(f, (w - 1) / 2, (h - 1) / 2, R0 @ Ry, Ry.T @ (C0 - t), w, h)


def free_camera(az: float, el: float, d: float, target: np.ndarray, roll: float, f: float, w: int, h: int) -> Camera:
    C = target + d * np.array([np.cos(el) * np.sin(az), np.sin(el), np.cos(el) * np.cos(az)])
    return Camera(f, (w - 1) / 2, (h - 1) / 2, look_at(C, target, roll), C, w, h)
