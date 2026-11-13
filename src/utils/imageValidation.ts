import { PERSPECTIVES, type ImageSet, type Perspective } from '../types';

export const ACCEPTED_TYPES = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp'];
export const ACCEPT_ATTR = '.jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp';
export const MAX_FILE_BYTES = 30 * 1024 * 1024;
export const MIN_SIDE_PX = 480;

/** Synchronous checks that do not need the image to be decoded. */
export function validateFile(file: File): string | null {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  const typeOk = ACCEPTED_TYPES.includes(file.type) || ['jpg', 'jpeg', 'png', 'webp'].includes(ext);
  if (!typeOk) return `Unsupported format "${file.type || ext}". Use JPEG, PNG or WebP.`;
  if (file.size > MAX_FILE_BYTES) return `File is ${(file.size / 1e6).toFixed(1)} MB; the limit is 30 MB.`;
  if (file.size === 0) return 'File is empty.';
  return null;
}

export function validateDimensions(width: number, height: number): string | null {
  if (Math.min(width, height) < MIN_SIDE_PX)
    return `Image is ${width}x${height}px; at least ${MIN_SIDE_PX}px on the short side is needed.`;
  return null;
}

export function missingPerspectives(set: ImageSet): Perspective[] {
  return PERSPECTIVES.filter((p) => !set[p] || set[p]?.error);
}

export function isComplete(set: ImageSet): boolean {
  return missingPerspectives(set).length === 0;
}

/** Same file uploaded into two slots is almost certainly a mistake. */
export function duplicateSlots(set: ImageSet): Perspective[][] {
  const byKey = new Map<string, Perspective[]>();
  for (const p of PERSPECTIVES) {
    const img = set[p];
    if (!img) continue;
    const key = `${img.file.name}|${img.file.size}|${img.file.lastModified}`;
    byKey.set(key, [...(byKey.get(key) ?? []), p]);
  }
  return [...byKey.values()].filter((v) => v.length > 1);
}
