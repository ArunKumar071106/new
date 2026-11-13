import type { AnalysisResult, JobStatus, ReconstructionOptions, ReconstructionReport } from '../types';

interface Props {
  ready: boolean;
  apiOnline: boolean | null;
  analysing: boolean;
  analysis: AnalysisResult | null;
  analysisError: string | null;
  onAnalyse: () => void;
  job: JobStatus | null;
  jobError: string | null;
  onStart: () => void;
  options: ReconstructionOptions;
  onOptions: (o: ReconstructionOptions) => void;
}

const QUALITY: Record<string, Pick<ReconstructionOptions, 'grid_res' | 'texture_res' | 'target_faces'>> = {
  draft: { grid_res: 128, texture_res: 1024, target_faces: 20000 },
  standard: { grid_res: 192, texture_res: 2048, target_faces: 40000 },
  high: { grid_res: 256, texture_res: 4096, target_faces: 80000 },
};

export default function ReconstructionStatus(p: Props) {
  const running = p.job?.state === 'running' || p.job?.state === 'queued';
  const quality = Object.entries(QUALITY).find(([, q]) => q.grid_res === p.options.grid_res)?.[0] ?? 'standard';
  const disabled = !p.ready || running || p.analysing || p.apiOnline === false;

  return (
    <div className="space-y-5">
      {p.apiOnline === false && (
        <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
          The reconstruction server is not reachable. Start it with <code className="font-mono">npm run api</code> (see README). The viewer and AR still work with the existing model.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block font-medium">Real object height</span>
          <div className="flex items-center gap-2">
            <input
              type="number"
              min={1}
              max={500}
              step={0.5}
              value={p.options.object_height_cm}
              disabled={running}
              onChange={(e) => p.onOptions({ ...p.options, object_height_cm: Math.max(1, Number(e.target.value) || 1) })}
              className="w-24 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 dark:border-slate-700 dark:bg-slate-900"
            />
            <span className="text-slate-500">cm</span>
          </div>
          <span className="mt-1 block text-xs text-slate-500">Photos cannot reveal absolute size; this sets the AR scale.</span>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Unseen bottom</span>
          <select
            value={p.options.bottom_mode}
            disabled={running}
            onChange={(e) => p.onOptions({ ...p.options, bottom_mode: e.target.value as 'flat' | 'hull' })}
            className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="flat">Infer flat base (recommended)</option>
            <option value="hull">Raw visual hull (no inference)</option>
          </select>
          <span className="mt-1 block text-xs text-slate-500">No bottom photo exists, so its geometry is inferred.</span>
        </label>
        <label className="text-sm">
          <span className="mb-1 block font-medium">Quality</span>
          <select
            value={quality}
            disabled={running}
            onChange={(e) => p.onOptions({ ...p.options, ...QUALITY[e.target.value] })}
            className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 dark:border-slate-700 dark:bg-slate-900"
          >
            <option value="draft">Draft (~1 min, 1K texture)</option>
            <option value="standard">Standard (~2 min, 2K texture)</option>
            <option value="high">High (slower, 4K texture)</option>
          </select>
        </label>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row">
        <button type="button" onClick={p.onAnalyse} disabled={disabled} className="rounded-xl border border-slate-300 px-5 py-2.5 font-semibold transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:hover:bg-slate-800">
          {p.analysing ? 'Analysing images...' : 'Analyze images'}
        </button>
        <button type="button" onClick={p.onStart} disabled={disabled} className="rounded-xl bg-indigo-600 px-5 py-2.5 font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 dark:disabled:bg-slate-800">
          {running ? 'Reconstructing...' : 'Start reconstruction'}
        </button>
        {!p.ready && <span className="self-center text-sm text-slate-500">Upload all six perspectives to continue.</span>}
      </div>

      {p.analysing && <Indeterminate label="Segmenting the object in each photo and comparing views..." />}
      {p.analysisError && <ErrorBox text={p.analysisError} />}
      {p.analysis && !running && !p.job?.report && <AnalysisSummary a={p.analysis} />}

      {p.job && (running || p.job.state === 'error') && (
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium capitalize">{p.job.stage || p.job.state}</span>
            <span className="tabular-nums text-slate-500">{Math.round(p.job.progress * 100)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" role="progressbar" aria-valuenow={Math.round(p.job.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
            <div className="h-full rounded-full bg-indigo-500 transition-all duration-500" style={{ width: `${p.job.progress * 100}%` }} />
          </div>
          {p.job.message && <p className="text-sm text-slate-500">{p.job.message}</p>}
        </div>
      )}
      {(p.jobError || p.job?.error) && <ErrorBox text={p.jobError || p.job?.error || ''} />}
      {p.job?.report && <ReportSummary r={p.job.report} />}
      {p.job && p.job.log.length > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer select-none text-slate-500">Processing log ({p.job.log.length} lines)</summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-slate-950 p-3 font-mono leading-relaxed text-slate-300">{p.job.log.join('\n')}</pre>
        </details>
      )}
    </div>
  );
}

function Indeterminate({ label }: { label: string }) {
  return (
    <div className="space-y-2" role="status">
      <div className="relative h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
        <div className="absolute inset-y-0 w-1/3 animate-[slide_1.2s_ease-in-out_infinite] rounded-full bg-indigo-500" />
      </div>
      <p className="text-sm text-slate-500">{label}</p>
    </div>
  );
}

function ErrorBox({ text }: { text: string }) {
  return (
    <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
      {text}
    </p>
  );
}

function Pill({ ok, children }: { ok: boolean | 'warn'; children: React.ReactNode }) {
  const cls =
    ok === true
      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300'
      : ok === 'warn'
        ? 'bg-amber-50 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300'
        : 'bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300';
  return <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${cls}`}>{children}</span>;
}

function AnalysisSummary({ a }: { a: AnalysisResult }) {
  const warnCount = Object.values(a.per_view).reduce((n, v) => n + v.warnings.length, 0);
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 p-4 text-sm dark:border-slate-800">
      <div className="flex flex-wrap gap-2">
        <Pill ok={a.same_object.outliers.length === 0}>Same object: {a.same_object.verdict}</Pill>
        <Pill ok={warnCount === 0 ? true : 'warn'}>{warnCount === 0 ? 'Image quality OK' : `${warnCount} image warning(s)`}</Pill>
        <Pill ok={a.lighting.inconsistent.length === 0 ? true : 'warn'}>
          {a.lighting.inconsistent.length === 0 ? 'Lighting consistent' : `Lighting differs: ${a.lighting.inconsistent.join(', ')} (auto white-balanced)`}
        </Pill>
        <Pill ok="warn">Feature SfM {a.overlap.feature_sfm_viable ? 'viable' : 'not viable'}</Pill>
      </div>
      <p className="text-slate-600 dark:text-slate-400">
        Feature matches on the object: <b>{a.overlap.matches_on_object}</b>, on the background: <b>{a.overlap.matches_on_background}</b>. {a.overlap.explanation}
      </p>
      <ul className="list-disc space-y-0.5 pl-5 text-slate-600 dark:text-slate-400">
        {a.missing_information.map((m) => (
          <li key={m}>{m}</li>
        ))}
      </ul>
      <p className="text-xs text-slate-500">Green outlines on the photos above show the segmented object. Check that each one covers the whole object.</p>
    </div>
  );
}

function ReportSummary({ r }: { r: ReconstructionReport }) {
  const v = r.validation;
  const s = v.size_m;
  return (
    <div className="space-y-4 rounded-xl border border-slate-200 p-4 text-sm dark:border-slate-800">
      <div className="flex flex-wrap gap-2">
        <Pill ok={v.valid}>{v.valid ? 'GLB valid' : `GLB invalid: ${v.errors.join(', ')}`}</Pill>
        <Pill ok={v.watertight}>{v.watertight ? 'Watertight mesh' : 'Mesh has holes'}</Pill>
        <Pill ok={true}>{v.triangles.toLocaleString()} triangles</Pill>
        <Pill ok={true}>
          {(s.x * 100).toFixed(1)} x {(s.y * 100).toFixed(1)} x {(s.z * 100).toFixed(1)} cm
        </Pill>
        <Pill ok={true}>{(r.export.bytes / 1e6).toFixed(2)} MB</Pill>
      </div>
      <p className="text-slate-600 dark:text-slate-400">{r.method}.</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <Stat label="Surface seen in photos" value={`${(r.texture.observed_surface_fraction * 100).toFixed(1)}%`} />
        <Stat label="Surface inferred (never photographed)" value={`${(r.texture.inferred_surface_fraction * 100).toFixed(1)}%`} />
      </div>

      <div>
        <h4 className="mb-2 font-medium">Per-view silhouette agreement</h4>
        <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 sm:grid-cols-3">
          {Object.entries(r.consistency).map(([n, c]) => (
            <div key={n} className="flex items-center gap-2">
              <span className="w-16 capitalize text-slate-600 dark:text-slate-400">{n}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded bg-slate-200 dark:bg-slate-800">
                <div className={`h-full ${c.iou >= 0.85 ? 'bg-emerald-500' : c.iou >= 0.72 ? 'bg-amber-500' : 'bg-rose-500'}`} style={{ width: `${c.iou * 100}%` }} />
              </div>
              <span className="w-10 text-right tabular-nums text-xs text-slate-500">{c.iou.toFixed(2)}</span>
            </div>
          ))}
        </div>
        {r.views_texture_only.length > 0 && <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">Used for texture only: {r.views_texture_only.join(', ')}</p>}
      </div>

      <div>
        <h4 className="mb-1 font-medium">Estimated cameras</h4>
        <p className="text-slate-600 dark:text-slate-400">
          Side views: camera elevation {r.poses.turntable.elevation_deg.toFixed(0)} deg; rotation{' '}
          {Object.entries(r.poses.turntable.angles_deg)
            .map(([n, a]) => `${n} ${a.toFixed(0)} deg`)
            .join(', ')}
          . {Object.entries(r.poses.free)
            .map(([n, f]) => `${n}: elevation ${f.elevation_deg.toFixed(0)} deg`)
            .join('; ')}
          .
        </p>
        <p className="mt-1 text-xs text-slate-500">
          Rotation ranges that fit the silhouettes equally well:{' '}
          {Object.entries(r.poses.angle_ambiguity)
            .map(([n, a]) => `${n} ${a.silhouette_plausible_range_deg[0].toFixed(0)} to ${a.silhouette_plausible_range_deg[1].toFixed(0)} deg`)
            .join('; ')}
          .
        </p>
      </div>

      <div>
        <h4 className="mb-1 font-medium">Limitations of this reconstruction</h4>
        <ul className="list-disc space-y-0.5 pl-5 text-slate-600 dark:text-slate-400">
          {r.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-100 px-3 py-2 dark:bg-slate-800/60">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
    </div>
  );
}
