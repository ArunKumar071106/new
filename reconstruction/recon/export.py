"""GLB export and validation."""
from __future__ import annotations

import io
import json
import struct

import numpy as np
import trimesh
from PIL import Image

from .texture import TexturedMesh


def export_glb(tm: TexturedMesh, path: str, jpeg_quality: int = 88, name: str = "ReconstructedObject") -> dict:
    buf = io.BytesIO()
    Image.fromarray(tm.texture).save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
    tex = Image.open(io.BytesIO(buf.getvalue()))  # keeps format == "JPEG" so trimesh embeds JPEG
    material = trimesh.visual.material.PBRMaterial(
        name="reconstructed", baseColorTexture=tex, metallicFactor=0.0, roughnessFactor=0.85, doubleSided=False)
    visual = trimesh.visual.TextureVisuals(uv=tm.uvs, material=material)
    mesh = trimesh.Trimesh(tm.vertices, tm.faces, vertex_normals=tm.normals, visual=visual, process=False)
    scene = trimesh.Scene()
    scene.add_geometry(mesh, node_name=name, geom_name=name)
    data = scene.export(file_type="glb")
    with open(path, "wb") as fh:
        fh.write(data)
    return {"bytes": len(data), "texture_bytes": len(buf.getvalue())}


def validate_glb(path: str) -> dict:
    """Structural validation: GLB header/chunks, then a full reload with trimesh."""
    with open(path, "rb") as fh:
        raw = fh.read()
    errors = []
    magic, version, length = struct.unpack_from("<4sII", raw, 0)
    if magic != b"glTF":
        errors.append("bad magic")
    if version != 2:
        errors.append(f"glTF version {version} != 2")
    if length != len(raw):
        errors.append("length mismatch")
    clen, ctype = struct.unpack_from("<I4s", raw, 12)
    gltf = json.loads(raw[20:20 + clen]) if ctype == b"JSON" else {}
    images = gltf.get("images", [])
    mime = [im.get("mimeType") for im in images]
    prim = gltf.get("meshes", [{}])[0].get("primitives", [{}])[0]
    attrs = sorted(prim.get("attributes", {}))
    if "TEXCOORD_0" not in attrs:
        errors.append("no UVs")
    if not images:
        errors.append("no embedded texture")
    loaded = trimesh.load(path, force="mesh")
    if len(loaded.faces) == 0:
        errors.append("empty mesh")
    ext = loaded.bounds[1] - loaded.bounds[0]
    return {
        "valid": not errors,
        "errors": errors,
        "attributes": attrs,
        "texture_mime": mime,
        "vertices": int(len(loaded.vertices)),
        "triangles": int(len(loaded.faces)),
        "watertight": _watertight(loaded),
        "bounds_m": loaded.bounds.tolist(),
        "size_m": {"x": float(ext[0]), "y": float(ext[1]), "z": float(ext[2])},
    }


def _watertight(m: trimesh.Trimesh) -> bool:
    w = trimesh.Trimesh(np.asarray(m.vertices), np.asarray(m.faces), process=True)
    return bool(w.is_watertight)
