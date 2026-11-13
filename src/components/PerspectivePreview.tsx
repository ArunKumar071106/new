import { useRef, useState } from 'react';
import { PERSPECTIVE_INFO, type Perspective, type UploadedImage } from '../types';
import { ACCEPT_ATTR } from '../utils/imageValidation';

interface Props {
  perspective: Perspective;
  index: number;
  image?: UploadedImage;
  maskPreview?: string;
  serverWarnings?: string[];
  onFile: (p: Perspective, f: File) => void;
  onRemove: (p: Perspective) => void;
  disabled?: boolean;
}

export default function PerspectivePreview({ perspective, index, image, maskPreview, serverWarnings, onFile, onRemove, disabled }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [showMask, setShowMask] = useState(true);
  const info = PERSPECTIVE_INFO[perspective];
  const warnings = [...(image?.stats?.warnings ?? []), ...(serverWarnings ?? [])];

  const pick = () => !disabled && input.current?.click();
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDrag(false);
    const f = e.dataTransfer.files?.[0];
    if (f && !disabled) onFile(perspective, f);
  };

  return (
    <div className="flex flex-col rounded-2xl border border-slate-200 bg-white p-2.5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-2 flex items-center justify-between px-0.5">
        <div className="flex items-center gap-2">
          <span className="grid h-5 w-5 place-items-center rounded-full bg-indigo-100 text-[11px] font-semibold text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300">{index + 1}</span>
          <span className="text-sm font-semibold">{info.label}</span>
        </div>
        {image && !image.error && <span className="text-[11px] text-emerald-600 dark:text-emerald-400">Ready</span>}
      </div>

      <div
        role="button"
        tabIndex={0}
        aria-label={image ? `Replace ${info.label} photo` : `Upload ${info.label} photo`}
        onClick={pick}
        onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && pick()}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        className={`relative aspect-[4/3] cursor-pointer overflow-hidden rounded-xl border-2 border-dashed transition ${
          drag ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950/40' : image ? 'border-transparent' : 'border-slate-300 hover:border-indigo-400 dark:border-slate-700'
        } ${disabled ? 'cursor-not-allowed opacity-70' : ''}`}
      >
        {image ? (
          <>
            {/* object-contain: the photo keeps its own aspect ratio, never stretched */}
            <img src={image.url} alt={`${info.label} upload`} className="h-full w-full bg-slate-100 object-contain dark:bg-slate-800" />
            {maskPreview && showMask && <img src={maskPreview} alt="" aria-hidden className="pointer-events-none absolute inset-0 h-full w-full object-contain mix-blend-normal" />}
          </>
        ) : (
          <div className="flex h-full flex-col items-center justify-center gap-1 p-3 text-center">
            <svg viewBox="0 0 24 24" className="h-7 w-7 text-slate-400" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round">
              <path d="M12 16V4m0 0-4 4m4-4 4 4M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
            </svg>
            <span className="text-xs font-medium text-slate-600 dark:text-slate-300">Tap or drop photo</span>
            <span className="hidden text-[11px] leading-snug text-slate-500 sm:block">{info.hint}</span>
          </div>
        )}
      </div>
      <input
        ref={input}
        type="file"
        accept={ACCEPT_ATTR}
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(perspective, f);
          e.target.value = '';
        }}
      />

      {image && (
        <div className="mt-2 space-y-1.5 px-0.5">
          <div className="flex items-center justify-between gap-2 text-[11px] text-slate-500">
            <span className="truncate" title={image.file.name}>
              {image.stats ? `${image.stats.width}x${image.stats.height}` : 'analysing...'} | {(image.file.size / 1e6).toFixed(1)} MB
            </span>
            <div className="flex shrink-0 gap-1">
              {maskPreview && (
                <button type="button" onClick={() => setShowMask((v) => !v)} className="rounded-md px-1.5 py-0.5 hover:bg-slate-100 dark:hover:bg-slate-800" aria-pressed={showMask}>
                  {showMask ? 'Hide' : 'Show'} mask
                </button>
              )}
              <button type="button" disabled={disabled} onClick={pick} className="rounded-md px-1.5 py-0.5 text-indigo-600 hover:bg-indigo-50 disabled:opacity-50 dark:text-indigo-400 dark:hover:bg-indigo-950">
                Replace
              </button>
              <button type="button" disabled={disabled} onClick={() => onRemove(perspective)} className="rounded-md px-1.5 py-0.5 text-rose-600 hover:bg-rose-50 disabled:opacity-50 dark:text-rose-400 dark:hover:bg-rose-950">
                Remove
              </button>
            </div>
          </div>
          {image.error && <p className="text-[11px] text-rose-600 dark:text-rose-400">{image.error}</p>}
          {warnings.map((w) => (
            <p key={w} className="text-[11px] leading-snug text-amber-700 dark:text-amber-400">
              {w}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
