import type { AnalysisResult, ClientImageStats, ImageSet } from '../types';
import { PERSPECTIVES } from '../types';
import { validateDimensions } from '../utils/imageValidation';

/**
 * Quick in-browser checks (no upload needed): decoded size, exposure and focus.
 * Images are analysed at their own aspect ratio - never stretched.
 */
export async function analyseInBrowser(file: File): Promise<ClientImageStats> {
  const bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' } as ImageBitmapOptions);
  const { width, height } = bitmap;
  const scale = 512 / Math.max(width, height);
  const w = Math.max(1, Math.round(width * scale));
  const h = Math.max(1, Math.round(height * scale));
  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  if (!ctx) throw new Error('Canvas 2D not available');
  ctx.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  const { data } = ctx.getImageData(0, 0, w, h);

  const gray = new Float32Array(w * h);
  let sum = 0;
  for (let i = 0, j = 0; i < data.length; i += 4, j++) {
    const y = 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2];
    gray[j] = y;
    sum += y;
  }
  const mean = sum / gray.length;

  // variance of the Laplacian over the central region (where the object usually is)
  let lsum = 0;
  let lsq = 0;
  let n = 0;
  const x0 = Math.floor(w * 0.2), x1 = Math.ceil(w * 0.8), y0 = Math.floor(h * 0.15), y1 = Math.ceil(h * 0.85);
  for (let y = Math.max(1, y0); y < Math.min(h - 1, y1); y++) {
    for (let x = Math.max(1, x0); x < Math.min(w - 1, x1); x++) {
      const k = y * w + x;
      const lap = gray[k - 1] + gray[k + 1] + gray[k - w] + gray[k + w] - 4 * gray[k];
      lsum += lap;
      lsq += lap * lap;
      n++;
    }
  }
  const sharpness = n ? lsq / n - (lsum / n) ** 2 : 0;

  const warnings: string[] = [];
  const dimErr = validateDimensions(width, height);
  if (dimErr) warnings.push(dimErr);
  if (mean < 50) warnings.push('Very dark photo');
  if (mean > 225) warnings.push('Very bright / overexposed photo');
  if (sharpness < 20) warnings.push('Photo may be blurry');

  return { width, height, aspect: width / height, meanLuminance: mean, sharpness, warnings };
}

/** Object-level analysis on the server: segmentation, same-object check, feature overlap, lighting. */
export async function analyseOnServer(images: ImageSet, signal?: AbortSignal): Promise<AnalysisResult> {
  const form = new FormData();
  for (const p of PERSPECTIVES) {
    const img = images[p];
    if (!img) throw new Error(`Missing ${p} image`);
    form.append(p, img.file, img.file.name);
  }
  const res = await fetch('/api/analyze', { method: 'POST', body: form, signal });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as AnalysisResult;
}

export async function errorText(res: Response): Promise<string> {
  try {
    const j = await res.json();
    return j.detail ?? JSON.stringify(j);
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}
