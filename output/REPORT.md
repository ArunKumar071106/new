# Reconstruction report — flocked teddy bear in pink "Lover Grass" gift bucket

**Deliverable:** `output/teddy_bear_bucket.glb`

| | |
|---|---|
| File size | 15.05 MB (15,053,816 bytes), single self-contained binary glTF 2.0 |
| Triangles / vertices | 201,808 triangles / 121,502 vertices |
| Meshes | 9 named nodes, 12 primitives, 8 PBR materials, 19 embedded textures |
| Texture resolution | 2048² for the bear and the hat crown, 1024² for everything else (bucket, sticker, hat underside, bow, flower) |
| Real-world size | 64.3 × 123.2 × 61.0 mm (W × H × D), Y-up, metres in file, base at y = 0 |
| Validation | Khronos glTF-Validator: **0 errors, 0 warnings, 0 infos, 0 hints** (`validation_report.json`) |
| Loads in | three.js r170 GLTFLoader (used for every preview in `previews/`). It uses only core glTF plus `KHR_materials_sheen`, which Blender ≥ 3.x, three.js and `<model-viewer>` all support |

## How it was made (and what this method is)

Six handheld photos with moving sunlight are too few, and too inconsistent, for
dense photogrammetry. Also, the bear and its bucket were rotated against each
other between some shots (the bucket's handle tabs sit at different angles
relative to the bear). So this is a **measured, photo-referenced
reconstruction**, not an automatic photogrammetric scan:

1. **Measurement.** Proportions were measured in pixels on the photos and
   cross-checked between views. Examples: rim height = 1.00 × rim diameter;
   base Ø = 0.76 × rim Ø; handle tabs are 6.8 mm tall with a Ø2 mm hole; the
   hat brim is 0.73 × rim Ø; head width is 0.71 × rim Ø. The camera elevation
   was derived from the aspect ratio of the rim ellipse.
2. **Geometry.**
   - **Bucket, bear and flower:** signed distance fields with smooth blends
     wherever the real part has fillets, meshed with marching cubes (0.075–0.24 mm voxels),
     decimated, then re-projected onto the exact surface.
   - **Ribbon bow and hat:** parametric surfaces given real thickness
     (ribbon 0.32 mm, brim 0.9 mm).
   - **Eyes and nose:** domed beads, partly sunk into the flocking as on the toy.

   The bow and flower were relaxed onto the body surface so nothing
   intersects. The hat is bedded 0.7 mm into the flock, where it is glued.
3. **Textures taken from the photos themselves.**
   - **Heart sticker:** back-projected off the curved bucket wall in the
     front photo (cylindrical unwrap), so the "Lover Grass / Blessing
     thoughts" text and the rose bouquet are the real print. It was
     white-balanced and de-lit against the surrounding plastic, then placed
     as a conforming decal (42.8 × 34.8 mm) 0.09 mm above the wall.
   - **Hat crown:** the glitter-swirl satin, rectified from the left-side
     photo using an ellipse fitted to the brim outline. Lighting was removed
     by normalising against a robust low-pass of the photo. The glitter was
     masked out to a **metallic, low-roughness** channel so it sparkles under
     light.
4. **Procedural PBR materials** (colours sampled from the photos):
   - flocked white bear: rough base, fibre normal map, `KHR_materials_sheen`
   - glossy pastel-pink polypropylene with faint handling scuffs in roughness
   - lavender grosgrain with ribs every 0.6 mm (in the normal map) and cream polka dots
   - pale felt under the hat brim
   - magenta trumpet flower with frosted petal tips, a yellow-orange stamen,
     and yellow and amber serrated leaves
   - black glass-like beads

   Procedural maps were baked in 3D surface space, so there are no UV seams.
   Ambient occlusion is a separate occlusion map, not baked into the colour.

## Mesh quality (`mesh_integrity.json`)

- Bucket, bear, flower and leaves, bow (2 wings + knot) and beads: each one
  **closed / watertight**, consistently wound, and a single connected component.
- Hat: its top (satin) and underside (felt) primitives together form one
  closed surface.
- Sticker: an intentionally open decal sheet.
- No degenerate faces, floating pieces or hidden internal geometry. Every part
  is a separate named node:
  `Bucket, Sticker_Heart, Bear_Body, Bead_eye_left/right, Bead_nose, Hat, Bow, Flower_and_Leaves`.

## Validation views

`previews/01_front … 06_three_quarter.jpg` are rendered from the same
viewpoints as the six reference photos, plus `closeup_face.jpg`.
`previews/comparison_photo_vs_model.jpg` puts each photo beside its render.

What matches well:
- bucket taper and rim band
- the two raised handle tabs with holes
- sticker placement and artwork
- hat size, tilt and its position on the bear's left
- the bow's span and polka dots
- the asymmetric face: the nose sits nearer the bear's right eye in both the
  front and the three-quarter photos, and this was kept rather than
  "corrected" to symmetric
- overall proportions

## Known limitations — stated honestly

- **Absolute scale is assumed.** There is no ruler in the photos. The rim was
  taken as Ø60 mm, typical for this gift item. Every other dimension is a
  measured ratio, so if the real rim differs, scale the model uniformly.
- **Hidden geometry is a conservative guess.** None of the photos shows the
  following:
  - the bucket's underside (modelled as a flat 1.4 mm base with a 1.6 mm
    edge fillet)
  - the bear's lower body inside the bucket (modelled as a smooth rounded torso)
  - the bear's left ear, which is fully under the hat (not modelled)
  - the inside of the hat crown (modelled as a closed, padded crown)
- **The bear's pose varies between photos** (it can turn inside the bucket),
  so the hat's tilt is a least-squares compromise across views, not one exact
  pose.
- **The flocked bear, ribbon and flower are not pixel-projected from the
  photos.** The photos are too sun-blown and blurred for usable texture there.
  These are clean procedural materials matched to the sampled colours, so fine
  dirt, individual stray fibres and the exact petal edge serrations are
  approximate.
- **Colours are estimates of the true albedo.** The photos are warm and
  partly over-exposed, so the pastel pink of the bucket in particular is
  slightly saturated relative to how it looks in direct sun.
- **Some lighting remains in the photo textures.** The sticker and hat-crown
  textures still carry a little residual shading from the original photos.

## Reproducing

```
pip install numpy scipy pillow scikit-image xatlas fast_simplification trimesh
cd reconstruction && python build.py          # ~4–5 min on 4 cores
python build.py --quick                        # low-res preview in ~20 s
```

Previews: serve a folder containing `preview/render.html` and the three.js
`node_modules`, then run `node preview/render.mjs <server> <model.glb> <outdir>`.
