# GLB optimisation report

| | Original | Optimized |
|---|---|---|
| File | `teddy_bear_bucket.glb` (left untouched, SHA-256 `2403e129…fe345e8`, same before and after) | `teddy_bear_bucket_optimized.glb` |
| File size | **15,053,816 bytes (15.05 MB)** | **9,499,800 bytes (9.50 MB)** |
| Reduction | | **−5.55 MB, 36.9% smaller** |
| Triangles | 201,808 | 201,808 (no simplification) |
| Vertices | 121,502 | 121,502 |
| Meshes / primitives / materials | 9 / 12 / 8 | 9 / 12 / 8 |
| Textures | 19 (8.07 MB) | 19 (8.07 MB), byte-for-byte identical |
| Geometry data | ≈ 6.9 MB | ≈ 1.35 MB |
| Gzip over HTTP (`gzip -9`) | 13.08 MB | 8.94 MB |
| Validator (Khronos glTF-Validator 2.0.0-dev.3.10) | 0 errors, 0 warnings | 0 errors, 0 warnings |

**About the "24 MB / 279K triangles" figure.** That was an intermediate build. It was
replaced before delivery by the 15.05 MB / 201,808-triangle file, which already had a
lighter hat mesh, 16-bit indices and 1024² bucket textures. This optimisation starts from
that delivered file. Counted from the 24.13 MB intermediate build, the total reduction is
60.6%.

## What was done

1. **Dedup and prune** (`gltf-transform dedup`, `prune`). These found no duplicate or
   unused textures, materials or accessors. The 8 materials describe 8 different physical
   surfaces, so none were merged.
2. **Geometry: Meshopt compression** (`EXT_meshopt_compression`, level *high*) with
   quantisation (`KHR_mesh_quantization`). I used higher precision than the gltf-transform
   defaults:
   - **positions:** 16-bit, default 14
   - **texture coordinates:** 16-bit, default 12; 12-bit would put UV seams off by up to
     half a texel on the 2048² maps
   - **normals and tangents:** 12-bit, default 10
3. **Textures were not re-encoded** (see the decisions below).

## Physical size and shape check

The script decoded both files, applied every node transform, and compared each mesh
point by point.

| Check | Result |
|---|---|
| Overall extents (W × H × D) | original 64.3424 × 123.1514 × 61.0096 mm → optimized 64.3427 × 123.1514 × 61.0103 mm |
| Bounding box min / max | matches to within 0.0007 mm on every axis |
| Largest vertex deviation, any mesh | **1.07 µm** (0.001 mm), on the bear body; the beads move by 0.09 µm |
| Per-mesh triangle and vertex counts | identical for all 12 primitives |
| Scale and units | unchanged: metres, Y-up, base at y = 0 |

## Visual comparison

Both files were rendered with three.js r170 from the six reference-photo viewpoints plus a
face close-up, at 1600×1200, with identical lighting. Rendering the original twice gives
138 dB, so the renderer is deterministic and every difference below comes from the file.

| View | PSNR | SSIM | Largest pixel difference |
|---|---|---|---|
| 01_front | 59.0 dB | 0.9998 | 75 |
| 02_left_side | 60.2 dB | 0.9998 | 60 |
| 03_back | 62.2 dB | 0.9999 | 36 |
| 04_right_side | 61.2 dB | 0.9999 | 58 |
| 05_top | 62.5 dB | 0.9999 | 64 |
| 06_three_quarter | 59.5 dB | 0.9999 | 63 |
| closeup_face | 54.4 dB | 0.9997 | 86 |

Above about 45 dB, a render is visually indistinguishable from the original. The few
larger single-pixel differences come from tiny specular glints on the glossy black beads
and from anti-aliasing at silhouette edges, caused by the 12-bit normals.
`previews/optimization_before_after.jpg` shows the two side by side with the difference
amplified ×10.

## Compatibility testing

- **three.js r170** `GLTFLoader` with `setMeshoptDecoder(MeshoptDecoder)`: loads, all
  8 materials present, bounding box as above.
- **Google `<model-viewer>` 3.5.0**: loads and reports dimensions of
  0.064343 × 0.123151 × 0.061010 m, with all 8 materials. It needs its Meshopt decoder,
  which loads by default from jsDelivr, or from a local copy via
  `ModelViewerElement.meshoptDecoderLocation`.
- **Blender** ≥ 3.6 imports `EXT_meshopt_compression`. Older versions cannot read it;
  use the original GLB there.
- **Any viewer must support `EXT_meshopt_compression` and `KHR_mesh_quantization`**
  (both marked as required). three.js, model-viewer, Babylon.js and Blender ≥ 3.6 do;
  some older AR viewers may not. In those cases use the original file.

## Decisions and compromises

- **KTX2 / Basis Universal was not applied.** The KTX-Software encoder is a downloaded
  binary, and the sandbox policy blocked running it, so I did not try to work around
  that. KTX2 is also mainly a GPU-memory saving, not a file-size one:
  - UASTC files are usually larger than these JPEGs.
  - ETC1S is smaller but visibly blurs fine detail such as the sticker text and the
    glitter print.

  To cut GPU memory for mobile AR, KTX2 can be added later, for example with
  `gltf-transform uastc` on normal maps and `gltf-transform etc1s` on ORM maps.
- **WebP was tested and rejected**, on measurement:
  - **Colour and AO/roughness/metal maps:** WebP made them larger (9.50 → 10.54 MB),
    because the original full-chroma JPEGs are already compact.
  - **Normal maps:** WebP was the only place it saved space (down to 7.86 MB), but lossy
    WebP always halves colour (chroma) resolution. On normal maps that corrupts the
    direction data, and the face close-up fell to 38 dB with visible damage to the
    flocking texture. The normal maps were therefore kept as their original 4:4:4 JPEGs.
- **Texture resolutions are unchanged:**
  - Bear and hat crown: 2048². These carry the flocking detail and the photographed
    glitter print.
  - Bucket, sticker, hat underside, bow and flower: 1024².

  Reducing these would have saved more space but lost real surface detail, which the
  brief ruled out.

## Reproduce

```
cd reconstruction && ./optimize.sh ../output/teddy_bear_bucket.glb ../output/teddy_bear_bucket_optimized.glb
```
