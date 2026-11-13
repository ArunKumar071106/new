// Validates a GLB with the official Khronos glTF-Validator. Exit code 1 on errors.
import { readFile } from 'node:fs/promises';
import validator from 'gltf-validator';

const path = process.argv[2] ?? 'public/models/reconstructed-object.glb';
const data = new Uint8Array(await readFile(path));
const report = await validator.validateBytes(data, { maxIssues: 50 });
const { numErrors, numWarnings, numInfos, messages } = report.issues;
const info = report.info ?? {};
console.log(JSON.stringify({
  file: path,
  version: info.version,
  errors: numErrors,
  warnings: numWarnings,
  infos: numInfos,
  totalTriangleCount: info.totalTriangleCount,
  totalVertexCount: info.totalVertexCount,
  materialCount: info.materialCount,
  hasTextures: info.hasTextures,
  resources: (info.resources ?? []).map((r) => ({ pointer: r.pointer, mimeType: r.mimeType, byteLength: r.byteLength, image: r.image })),
  messages: messages.map((m) => `${m.severity === 0 ? 'ERROR' : m.severity === 1 ? 'WARN' : 'INFO'} ${m.code} ${m.pointer ?? ''} ${m.message}`),
}, null, 2));
process.exit(numErrors > 0 ? 1 : 0);
