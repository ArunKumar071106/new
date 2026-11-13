import type { ImageSet, JobStatus, ReconstructionOptions } from '../types';
import { PERSPECTIVES } from '../types';
import { errorText } from './imageAnalysis';

export const DEFAULT_OPTIONS: ReconstructionOptions = {
  object_height_cm: 11,
  bottom_mode: 'open',
  grid_res: 192,
  texture_res: 2048,
  target_faces: 40000,
};

export async function apiHealth(): Promise<{ ok: boolean; segmentation: string; busy: boolean } | null> {
  try {
    const r = await fetch('/api/health');
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

export async function startReconstruction(images: ImageSet, options: ReconstructionOptions): Promise<string> {
  const form = new FormData();
  for (const p of PERSPECTIVES) {
    const img = images[p];
    if (!img) throw new Error(`Missing ${p} image`);
    form.append(p, img.file, img.file.name);
  }
  form.append('options', JSON.stringify(options));
  const res = await fetch('/api/reconstruct', { method: 'POST', body: form });
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()).id as string;
}

export async function getJob(id: string): Promise<JobStatus> {
  const res = await fetch(`/api/jobs/${id}`);
  if (!res.ok) throw new Error(await errorText(res));
  return (await res.json()) as JobStatus;
}

/** Poll a job until it finishes; calls onUpdate for every status change. */
export async function pollJob(id: string, onUpdate: (j: JobStatus) => void, signal?: AbortSignal): Promise<JobStatus> {
  for (;;) {
    if (signal?.aborted) throw new DOMException('aborted', 'AbortError');
    const job = await getJob(id);
    onUpdate(job);
    if (job.state === 'done' || job.state === 'error') return job;
    await new Promise((r) => setTimeout(r, 1000));
  }
}
