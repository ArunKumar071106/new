# 3D Reconstruction & AR Studio

Turns **six photos of one object** (front, back, left, right, top, elevated 45°) into a
**textured 3D model (GLB)**, shows it in an interactive Three.js viewer, and places it on a
real table or floor with **WebXR immersive AR** (surface hit testing, tap-to-place,
rotate and scale).

- Frontend: React 18, Vite 5, TypeScript, Tailwind CSS, Three.js r170 (GLTFLoader, WebXRManager)
- Reconstruction: Python. Segmentation with U²-Net (rembg) and GrabCut, then silhouette-based pose
  estimation, visual hull, marching cubes, xatlas UV unwrap and multi-view texture baking
- Runs on CPU only. No GPU, no paid APIs.

The sample photos in `public/samples/bear/` produce the model in
`public/models/reconstructed-object.glb`.

---

## Quick start

```bash
# 1. Python pipeline + API (needs Python >= 3.10)
python3 -m venv .venv
.venv/bin/pip install -r reconstruction/requirements.txt

# 2. Frontend
npm install

# 3. Run both (two terminals)
npm run api        # FastAPI on http://127.0.0.1:8000
npm run dev        # Vite on http://localhost:5173 (proxies /api to the API)
```

Open http://localhost:5173. Click **Use sample photos** (or upload your own six photos),
then **Analyze images** and **Start reconstruction**. When it finishes, the viewer switches to
the new model, and the file is also written to `public/models/reconstructed-object.glb`.

From the command line:

```bash
npm run reconstruct:sample          # sample photos -> public/models/reconstructed-object.glb (+ .report.json)
npm run validate:glb                # Khronos glTF-Validator on the result

.venv/bin/python reconstruction/pipeline.py \
  --front f.jpg --back b.jpg --left l.jpg --right r.jpg --top t.jpg --elevated e.jpg \
  --out out/model.glb --object-height-cm 11 --bottom-mode flat --grid-res 192 --texture-res 2048
```

The first run downloads the U²-Net segmentation model (176 MB) to `~/.u2net`.

## Testing AR on an Android phone

WebXR AR needs **Chrome on an ARCore-compatible Android device** and a **secure context**.
`localhost` counts as secure; a LAN IP over plain http does not.

**Option A (most reliable): USB port forwarding.**
1. Enable USB debugging on the phone and connect it.
2. On the computer, open `chrome://inspect/#devices`. Under **Port forwarding**, add `5173 -> localhost:5173`.
3. On the phone, open `http://localhost:5173` in Chrome. It is a secure origin, so WebXR is allowed.

**Option B: HTTPS on the LAN.** Run `npm run dev:https`, then open
`https://<computer-ip>:5173` on the phone and accept the self-signed certificate warning.

**Option C: an HTTPS tunnel** (e.g. cloudflared or ngrok) pointed at port 5173.

Also make sure **Google Play Services for AR** is installed and up to date on the phone.

In AR: move the phone slowly until the ring appears on a horizontal surface. Tap the screen
(or **Place object**) to place it. Drag with one finger to rotate and pinch to scale, or use
the buttons. **Reset position** picks the model up again. **Exit AR** ends the session.
The model appears at the real-world size given by *Real object height*.

### What the app checks, and what users see

| Situation | Behaviour |
|---|---|
| Not HTTPS / not localhost | "AR needs a secure (HTTPS) connection..." |
| No `navigator.xr` (most desktop browsers, iOS Safari) | WebXR unavailable message. iOS gets an explicit note that Safari has no WebXR AR; AR Quick Look is a different viewer and is **not** treated as equivalent |
| `isSessionSupported('immersive-ar')` is false | "Not ARCore-certified / Play Services for AR missing" |
| `hit-test` feature refused | "This device cannot start an AR session with surface hit testing" |
| Camera permission denied | Explains how to re-allow camera access |
| GLB missing or corrupt | Viewer shows the load error; Start AR stays disabled |
| Surface not horizontal (wall) | Reticle hidden: "aim at a table or floor" |

AR uses `requiredFeatures: ['hit-test']` and `optionalFeatures: ['dom-overlay', 'anchors',
'light-estimation', 'local-floor']`. When the device grants **anchors**, the placed model is
anchored to the surface for extra stability. When it grants **light estimation**, the
real-world lighting estimate drives the model's lighting. A shadow-catcher plane gives a
contact shadow.

---

## How the reconstruction works, and why

### Environment found (phase 1)
4 CPU cores, 15 GB RAM, **no GPU or CUDA**, no COLMAP, Meshroom or Blender installed. This rules
out GPU-bound AI multi-view generators (InstantMesh, LGM and similar) and heavy photogrammetry.

### Why not photogrammetry / SfM?
This was tested, not assumed. On the sample photos, COLMAP (via `pycolmap`) fails with
*"No good initial image pair found"*. The analysis step explains why:

- **22** geometrically verified feature matches lie on the object itself, versus **4,926** on
  the background.
- The flocked bear and the smooth plastic bucket have almost no texture.
- In the front, back, left and right photos the background is identical. The object was
  turned on the bed while the camera stayed still, so background matches describe a camera
  that never moved, which is a degenerate case for SfM.
- The top and elevated photos were taken on a different bedsheet, and share only about 10
  matches with the other views.

The app runs this check on every upload set (`/api/analyze`) and reports whether feature-based
SfM is viable.

### Pipeline (`reconstruction/`)

| Step | Module | What it does |
|---|---|---|
| Load | `recon/imageio.py` | EXIF orientation. Each image keeps its own size and aspect ratio (no stretching) |
| Segment | `recon/segment.py` | U²-Net mask, then **colour-model completion** (GrabCut in a band around the mask). This recovered the bucket rim that U²-Net dropped in the top view (+28% area) |
| Analyse | `recon/analysis.py` | Sharpness, exposure, cut-off detection, same-object check (white-balanced colour histograms), feature-overlap test, lighting / white-balance differences |
| Pose | `recon/pose.py` | **Turntable model** for front/back/left/right (shared camera elevation, roll, distance; per-view rotation and table shift). **Free 6-DoF** cameras for top/elevated, found by grid search. Everything is refined by **silhouette coherence**: the visual hull of all views must re-project onto every silhouette |
| Rotation angles | `recon/pose.py` | A round object's silhouette barely changes as it rotates, so the angle is chosen by **MAP**: silhouette coherence plus a Gaussian prior (σ = 25°) around the user's perspective label. The plausible range is reported |
| Consistency | `pipeline.py` | Re-projects the hull of the *other* views into each photo. Inconsistent masks are repaired with hull-guided GrabCut; views below an agreement threshold are used for texture only |
| Carve | `recon/carve.py` | Voxel visual hull (192³, about 0.8 mm voxels for this object). Out-of-frame points take the nearest border pixel, so a cut-off photo cannot slice the object |
| Base | `recon/mesh.py` | Cameras that look down leave a cone-shaped "skirt" under the object. The real base is found where the slice radius stops shrinking quickly; below it, a flat base is inferred (`--bottom-mode hull` keeps the raw hull instead) |
| Mesh | `recon/mesh.py` | Gaussian-smoothed occupancy, marching cubes, Taubin smoothing, quadric decimation (40k triangles). Watertight |
| Texture | `recon/texture.py` | xatlas UV atlas. Every texel is projected into all six photos and blended by visibility (ray-marched occlusion), viewing angle and distance from the silhouette edge. Views are white-balanced against the white flock. Unseen surface is filled by colour diffusion and reported |
| Export | `recon/export.py` | GLB with an embedded JPEG texture and PBR material, in metres, +Y up, front facing +Z, origin at the centre of the base. Re-loaded and structurally validated |

### Result on the sample photos

- 40,000 triangles, watertight, 2048² JPEG texture, **1.4 MB GLB**
- **Khronos glTF-Validator: 0 errors, 0 warnings**
- Size 5.4 × 11.0 × 5.5 cm. The height is the assumed 11 cm, since absolute scale is set by the user (see below)
- About 84% of the surface is textured from the photos. About 16%, mostly the base, is inferred
- Silhouette agreement per view (IoU): front 0.90, back 0.86, top 0.90, elevated 0.89, left 0.78, right 0.77

Every run writes a JSON report next to the GLB (`*.report.json`). It contains all metrics,
estimated cameras, angle ambiguity ranges, the processing log and a list of limitations.

### Limitations (stated, not hidden)

- **Underside:** never photographed, so its geometry (flat base) and colour (diffused from neighbouring surface) are inferred.
- **Concavities:** a visual hull cannot represent cavities. The open top of the bucket around the bear is filled in.
- **Few viewing directions:** only about four horizontal views exist, so cross-sections are somewhat polygonal and silhouette-cone intersections leave creases.
- **Rotation angles:** for near-symmetric objects, silhouettes allow roughly ±50° for the side views. The label prior picks a value consistent with the photos (for example, the bucket's handle lugs face the camera in the left and right shots), but small texture ghosting can remain where views meet.
- **No EXIF in the samples:** a typical phone focal length (26 mm-equivalent) is assumed. Elevation and perspective are estimated jointly and may be biased.
- **Absolute size** cannot come from photos. Set *Real object height* (default 11 cm).
- **Lighting is baked in:** the texture contains the original sunlight and shadows. The viewer has a "photo-baked (unlit)" toggle.

### Getting better results
Use a plain background that contrasts with the object, and diffuse light. Keep the object
fully in frame. Turn it in exact 90° steps. A textured object, or extra photos, will help too.
With strongly textured objects and many overlapping photos (30 or more), conventional
photogrammetry (COLMAP or Meshroom) would give finer geometry than six silhouettes can.

### Hosted AI alternatives (not used)
Hosted image-to-3D services (for example Meshy, Tripo or Rodin) can hallucinate unseen parts
and cavities, but they need an account and API key, and most bill per generation. Free tiers
and prices change often, so check each provider's current pricing page. This project calls no
external API and spends no credits.

---

## Project structure

```
public/
  models/reconstructed-object.glb (+ .report.json)   result for the sample photos
  samples/bear/*.webp                                the six sample photos
reconstruction/
  pipeline.py        CLI + orchestration          server.py   FastAPI (jobs, progress)
  recon/             imageio, segment, analysis, cameras, pose, photo, carve, mesh, texture, export
  requirements.txt
src/
  components/        ImageUploader, PerspectivePreview, ReconstructionStatus, ModelViewer, ARViewer, ARControls
  services/          imageAnalysis, reconstruction, modelLoader, arService (WebXR session, hit test, anchors)
  utils/             imageValidation, deviceCompatibility
scripts/validate-glb.mjs   Khronos glTF-Validator
```

### API

| Method | Path | |
|---|---|---|
| GET | `/api/health` | backend status, segmentation backend |
| POST | `/api/analyze` | multipart `front, back, left, right, top, elevated` → analysis + mask previews |
| POST | `/api/reconstruct` | same files + `options` JSON → `{id}` |
| GET | `/api/jobs/{id}` | state, progress, stage, log, report |
| GET | `/api/jobs/{id}/model.glb` | the model |

Production: `npm run build`, then `npm run api`. The API also serves `dist/` at `/`.

## Test status

| Area | Status |
|---|---|
| Pipeline on the sample photos | Done; GLB passes the Khronos validator with 0 errors and 0 warnings |
| Upload UI: six slots, preview, replace, remove, type/size/dimension validation, missing and duplicate detection | Tested in headless Chromium |
| Analyze, reconstruct, progress, report, viewer swaps to new model, GLB download | Tested end-to-end in headless Chromium |
| Viewer: orbit, zoom, reset, unlit toggle, loading and error states | Tested in headless Chromium (software WebGL) |
| Mobile layout (Pixel 7 viewport), light and dark themes | Tested; no horizontal overflow |
| AR fallback messaging on unsupported browsers | Tested (desktop and emulated Android Chromium report AR unsupported) |
| **AR on a physical ARCore phone** (session, hit test, placement, gestures, anchors, light estimation) | **Not tested.** No device was available in the build environment. The code follows the WebXR Hit Test / Anchors / DOM Overlay APIs and Three.js's WebXRManager, but it must be verified on a real device (see "Testing AR on an Android phone") |
