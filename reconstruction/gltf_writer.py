"""Minimal, dependency-free glTF 2.0 binary (.glb) writer with embedded
textures and PBR (metal/rough) materials plus KHR_materials_sheen."""
import io
import json
import struct
import numpy as np
from PIL import Image, ImageFile

ImageFile.MAXBLOCK = 1 << 26


class GLBWriter:
    def __init__(self):
        self.bin = bytearray()
        self.j = {
            "asset": {"version": "2.0", "generator": "teddy-bucket photo-referenced reconstruction"},
            "scene": 0, "scenes": [{"name": "Scene", "nodes": []}],
            "nodes": [], "meshes": [], "materials": [], "accessors": [],
            "bufferViews": [], "buffers": [], "images": [], "textures": [], "samplers": [],
        }
        self.ext_used = set()
        self._tex_cache = {}
        self.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497})
        self.j["samplers"].append({"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071})

    # ---------------------------------------------------------------- buffers
    def _view(self, data, target=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        off = len(self.bin)
        self.bin.extend(data)
        bv = {"buffer": 0, "byteOffset": off, "byteLength": len(data)}
        if target:
            bv["target"] = target
        self.j["bufferViews"].append(bv)
        return len(self.j["bufferViews"]) - 1

    def _accessor(self, arr, kind, normalized=False, target=34962, minmax=False):
        arr = np.ascontiguousarray(arr)
        ctype = {np.dtype(np.float32): 5126, np.dtype(np.uint32): 5125,
                 np.dtype(np.uint16): 5123}[arr.dtype]
        bv = self._view(arr.tobytes(), target)
        acc = {"bufferView": bv, "componentType": ctype,
               "count": int(arr.shape[0]), "type": kind}
        if minmax:
            acc["min"] = [float(x) for x in arr.min(0)]
            acc["max"] = [float(x) for x in arr.max(0)]
        self.j["accessors"].append(acc)
        return len(self.j["accessors"]) - 1

    # ---------------------------------------------------------------- textures
    def texture(self, img, kind="jpeg", quality=92, clamp=False, key=None):
        if key and key in self._tex_cache:
            return self._tex_cache[key]
        if isinstance(img, np.ndarray):
            a = img
            if a.dtype != np.uint8:
                a = (np.clip(np.nan_to_num(a, nan=0.5), 0, 1) * 255 + 0.5).astype(np.uint8)
            img = Image.fromarray(a)
        buf = io.BytesIO()
        if kind == "png":
            img.save(buf, "PNG", optimize=True)
            mime = "image/png"
        else:
            img.convert("RGB").save(buf, "JPEG", quality=quality, subsampling=0, optimize=True)
            mime = "image/jpeg"
        bv = self._view(buf.getvalue())
        self.j["images"].append({"bufferView": bv, "mimeType": mime,
                                 "name": key or f"image{len(self.j['images'])}"})
        self.j["textures"].append({"source": len(self.j["images"]) - 1,
                                   "sampler": 1 if clamp else 0})
        idx = len(self.j["textures"]) - 1
        if key:
            self._tex_cache[key] = idx
        return idx

    def material(self, name, base=None, base_factor=(1, 1, 1, 1), normal=None, normal_scale=1.0,
                 orm=None, rough=1.0, metal=0.0, occl_strength=1.0, sheen=None,
                 alpha_mode=None, alpha_cutoff=0.5, double_sided=False):
        pbr = {"baseColorFactor": list(base_factor), "metallicFactor": metal, "roughnessFactor": rough}
        if base is not None:
            pbr["baseColorTexture"] = {"index": base}
        if orm is not None:
            pbr["metallicRoughnessTexture"] = {"index": orm}
        m = {"name": name, "pbrMetallicRoughness": pbr, "doubleSided": double_sided}
        if normal is not None:
            m["normalTexture"] = {"index": normal, "scale": normal_scale}
        if orm is not None:
            m["occlusionTexture"] = {"index": orm, "strength": occl_strength}
        if alpha_mode:
            m["alphaMode"] = alpha_mode
            if alpha_mode == "MASK":
                m["alphaCutoff"] = alpha_cutoff
        if sheen:
            m["extensions"] = {"KHR_materials_sheen": sheen}
            self.ext_used.add("KHR_materials_sheen")
        self.j["materials"].append(m)
        return len(self.j["materials"]) - 1

    # ---------------------------------------------------------------- meshes
    def mesh(self, name, prims):
        """prims: list of dicts with V,N,UV,TAN,F,material (mm units -> m)."""
        out = []
        for p in prims:
            attrs = {
                "POSITION": self._accessor((p["V"] * 0.001).astype(np.float32), "VEC3", minmax=True),
                "NORMAL": self._accessor(p["N"].astype(np.float32), "VEC3"),
            }
            if p.get("UV") is not None:
                attrs["TEXCOORD_0"] = self._accessor(p["UV"].astype(np.float32), "VEC2")
            if p.get("TAN") is not None:
                attrs["TANGENT"] = self._accessor(p["TAN"].astype(np.float32), "VEC4")
            F = p["F"].ravel()
            F = F.astype(np.uint16) if F.max() < 65535 else F.astype(np.uint32)
            ind = self._accessor(F, "SCALAR", target=34963)
            out.append({"attributes": attrs, "indices": ind, "material": p["material"], "mode": 4})
        self.j["meshes"].append({"name": name, "primitives": out})
        mi = len(self.j["meshes"]) - 1
        self.j["nodes"].append({"name": name, "mesh": mi})
        return len(self.j["nodes"]) - 1

    def group(self, name, children):
        self.j["nodes"].append({"name": name, "children": children})
        idx = len(self.j["nodes"]) - 1
        self.j["scenes"][0]["nodes"].append(idx)
        return idx

    # ---------------------------------------------------------------- write
    def write(self, path):
        while len(self.bin) % 4:
            self.bin.append(0)
        self.j["buffers"] = [{"byteLength": len(self.bin)}]
        if self.ext_used:
            self.j["extensionsUsed"] = sorted(self.ext_used)
        js = json.dumps(self.j, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        total = 12 + 8 + len(js) + 8 + len(self.bin)
        with open(path, "wb") as f:
            f.write(struct.pack("<III", 0x46546C67, 2, total))
            f.write(struct.pack("<II", len(js), 0x4E4F534A))
            f.write(js)
            f.write(struct.pack("<II", len(self.bin), 0x004E4942))
            f.write(self.bin)
        return total
