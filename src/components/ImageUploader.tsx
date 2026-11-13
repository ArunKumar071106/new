import { PERSPECTIVES, type AnalysisResult, type ImageSet, type Perspective } from '../types';
import { duplicateSlots, missingPerspectives } from '../utils/imageValidation';
import PerspectivePreview from './PerspectivePreview';

interface Props {
  images: ImageSet;
  analysis: AnalysisResult | null;
  onFile: (p: Perspective, f: File) => void;
  onRemove: (p: Perspective) => void;
  onLoadSample: () => void;
  onClear: () => void;
  busy: boolean;
  loadingSample: boolean;
}

export default function ImageUploader({ images, analysis, onFile, onRemove, onLoadSample, onClear, busy, loadingSample }: Props) {
  const missing = missingPerspectives(images);
  const dups = duplicateSlots(images);
  const count = PERSPECTIVES.length - missing.length;
  return (
    <div className="space-y-4">
      <details className="group rounded-xl bg-slate-100 px-4 py-3 text-sm text-slate-600 dark:bg-slate-800/60 dark:text-slate-300">
        <summary className="cursor-pointer select-none font-medium text-slate-800 dark:text-slate-100">How to photograph the object</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>All six photos must show the <b>same object</b>, fully in frame, not cut off at the edges.</li>
          <li>Front, back, left and right: keep the camera at the same height. Turning the object on a table is fine.</li>
          <li>Top: straight down. Elevated: from the front, looking down about 45 degrees.</li>
          <li>Use even light and a background that contrasts with the object. Avoid motion blur.</li>
          <li>No photo of the underside is needed. The base is inferred and reported as such.</li>
          <li>JPEG, PNG or WebP, at least 480px on the short side. Photos are never stretched.</li>
        </ul>
      </details>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
        {PERSPECTIVES.map((p, i) => (
          <PerspectivePreview
            key={p}
            perspective={p}
            index={i}
            image={images[p]}
            maskPreview={analysis?.mask_previews?.[p]}
            serverWarnings={analysis?.per_view?.[p]?.warnings}
            onFile={onFile}
            onRemove={onRemove}
            disabled={busy}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div className="flex items-center gap-2">
          <div className="h-1.5 w-28 overflow-hidden rounded bg-slate-200 dark:bg-slate-800" aria-hidden>
            <div className="h-full bg-indigo-500 transition-all" style={{ width: `${(count / 6) * 100}%` }} />
          </div>
          <span className="text-slate-600 dark:text-slate-400">{count} of 6 perspectives</span>
        </div>
        {missing.length > 0 && count > 0 && <span className="text-amber-700 dark:text-amber-400">Missing: {missing.join(', ')}</span>}
        <div className="ml-auto flex gap-2">
          <button type="button" onClick={onLoadSample} disabled={busy || loadingSample} className="rounded-lg border border-slate-300 px-3 py-1.5 font-medium hover:bg-slate-100 disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800">
            {loadingSample ? 'Loading...' : 'Use sample photos'}
          </button>
          {count > 0 && (
            <button type="button" onClick={onClear} disabled={busy} className="rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:text-slate-400 dark:hover:bg-slate-800">
              Clear all
            </button>
          )}
        </div>
      </div>
      {dups.map((d) => (
        <p key={d.join()} className="text-sm text-amber-700 dark:text-amber-400">
          The same file is used for {d.join(' and ')}. Each perspective needs its own photo.
        </p>
      ))}
    </div>
  );
}
