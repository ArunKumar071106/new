#!/usr/bin/env bash
# Size optimisation of the reconstruction GLB. The input file is never modified.
# Geometry: Meshopt (EXT_meshopt_compression) with high-precision quantisation
# (KHR_mesh_quantization). Textures: left byte-for-byte as they are.
# requires: npm install @gltf-transform/cli@4.1.1
set -euo pipefail
IN=${1:-../output/teddy_bear_bucket.glb}
OUT=${2:-../output/teddy_bear_bucket_optimized.glb}
TMP=$(mktemp -d)
npx gltf-transform dedup "$IN" "$TMP/a.glb"          # merge duplicate accessors/textures/materials (none found)
npx gltf-transform prune "$TMP/a.glb" "$TMP/b.glb"    # drop unreferenced data (none found)
npx gltf-transform meshopt "$TMP/b.glb" "$OUT" --level high \
  --quantize-position 16 --quantize-texcoord 16 --quantize-normal 12
rm -rf "$TMP"
ls -l "$IN" "$OUT"
