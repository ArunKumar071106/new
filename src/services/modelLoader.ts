import * as THREE from 'three';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

export interface LoadedModel {
  root: THREE.Object3D;
  size: THREE.Vector3; // metres
  triangles: number;
  textureSize: string | null;
}

const loader = new GLTFLoader();

/** Check the GLB container before parsing so a bad download gives a clear message. */
function checkGlbHeader(buf: ArrayBuffer): void {
  if (buf.byteLength < 20) throw new Error('File is too small to be a GLB.');
  const dv = new DataView(buf);
  const magic = dv.getUint32(0, true);
  if (magic !== 0x46546c67) {
    const head = new TextDecoder().decode(new Uint8Array(buf, 0, Math.min(64, buf.byteLength)));
    if (head.trimStart().startsWith('<')) throw new Error('Server returned an HTML page instead of a GLB (model not found?).');
    throw new Error('Not a GLB file (bad magic header).');
  }
  const version = dv.getUint32(4, true);
  if (version !== 2) throw new Error(`Unsupported glTF version ${version}; expected 2.`);
  const length = dv.getUint32(8, true);
  if (length !== buf.byteLength) throw new Error('GLB is truncated or corrupted (length mismatch).');
}

export async function loadModel(url: string, onProgress?: (fraction: number) => void): Promise<LoadedModel> {
  const res = await fetch(url, { cache: 'no-cache' });
  if (!res.ok) throw new Error(res.status === 404 ? 'No reconstructed model found yet.' : `Download failed: ${res.status}`);
  const total = Number(res.headers.get('content-length')) || 0;
  let buf: ArrayBuffer;
  if (res.body && total && onProgress) {
    const reader = res.body.getReader();
    const chunks: Uint8Array[] = [];
    let got = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      got += value.length;
      onProgress(Math.min(1, got / total));
    }
    const all = new Uint8Array(got);
    let o = 0;
    for (const c of chunks) {
      all.set(c, o);
      o += c.length;
    }
    buf = all.buffer;
  } else {
    buf = await res.arrayBuffer();
    onProgress?.(1);
  }
  checkGlbHeader(buf);
  const gltf = await loader.parseAsync(buf, '');
  const root = gltf.scene;

  let triangles = 0;
  let textureSize: string | null = null;
  root.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.castShadow = true;
    mesh.receiveShadow = false;
    const g = mesh.geometry;
    triangles += g.index ? g.index.count / 3 : g.attributes.position.count / 3;
    const mat = mesh.material as THREE.MeshStandardMaterial;
    const img = mat.map?.image as { width?: number; height?: number } | undefined;
    if (img?.width) textureSize = `${img.width}x${img.height}`;
    if (mat.map) mat.map.anisotropy = 8;
  });
  if (triangles === 0) throw new Error('The GLB contains no mesh geometry.');
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  if (!Number.isFinite(size.x) || size.length() === 0) throw new Error('The model has invalid bounds.');
  return { root, size, triangles, textureSize };
}

export function disposeObject(obj: THREE.Object3D): void {
  obj.traverse((o) => {
    const mesh = o as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry.dispose();
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const m of mats) {
      for (const v of Object.values(m)) if (v instanceof THREE.Texture) v.dispose();
      m.dispose();
    }
  });
}
