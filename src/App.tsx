import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type * as THREE from 'three';
import ARViewer from './components/ARViewer';
import ImageUploader from './components/ImageUploader';
import ModelViewer from './components/ModelViewer';
import ReconstructionStatus from './components/ReconstructionStatus';
import { analyseInBrowser, analyseOnServer } from './services/imageAnalysis';
import type { LoadedModel } from './services/modelLoader';
import { apiHealth, DEFAULT_OPTIONS, pollJob, startReconstruction } from './services/reconstruction';
import { PERSPECTIVES, type AnalysisResult, type ImageSet, type JobStatus, type Perspective } from './types';
import { isComplete, validateFile } from './utils/imageValidation';

const DEFAULT_MODEL = '/models/reconstructed-object.glb';

export default function App() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains('dark'));
  const [images, setImages] = useState<ImageSet>({});
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [analysisError, setAnalysisError] = useState<string | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [options, setOptions] = useState(DEFAULT_OPTIONS);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [modelUrl, setModelUrl] = useState<string | null>(DEFAULT_MODEL);
  const [model, setModel] = useState<THREE.Object3D | null>(null);
  const [modelError, setModelError] = useState<string | null>(null);
  const [loadingSample, setLoadingSample] = useState(false);
  const imagesRef = useRef(images);
  imagesRef.current = images;

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
    try {
      localStorage.setItem('theme', dark ? 'dark' : 'light');
    } catch {
      /* storage unavailable */
    }
  }, [dark]);

  useEffect(() => {
    apiHealth().then((h) => setApiOnline(!!h?.ok));
  }, []);

  useEffect(() => () => Object.values(imagesRef.current).forEach((i) => i && URL.revokeObjectURL(i.url)), []);

  const setFile = useCallback(async (p: Perspective, file: File) => {
    const err = validateFile(file);
    const url = URL.createObjectURL(file);
    setImages((prev) => {
      if (prev[p]) URL.revokeObjectURL(prev[p]!.url);
      return { ...prev, [p]: { file, url, error: err ?? undefined } };
    });
    setAnalysis(null);
    if (err) return;
    try {
      const stats = await analyseInBrowser(file);
      const dimErr = stats.warnings.find((w) => w.startsWith('Image is'));
      setImages((prev) => (prev[p]?.file === file ? { ...prev, [p]: { ...prev[p]!, stats, error: dimErr } } : prev));
    } catch {
      setImages((prev) => (prev[p]?.file === file ? { ...prev, [p]: { ...prev[p]!, error: 'This file could not be decoded as an image.' } } : prev));
    }
  }, []);

  const remove = useCallback((p: Perspective) => {
    setImages((prev) => {
      if (prev[p]) URL.revokeObjectURL(prev[p]!.url);
      const next = { ...prev };
      delete next[p];
      return next;
    });
    setAnalysis(null);
  }, []);

  const clear = () => {
    Object.values(images).forEach((i) => i && URL.revokeObjectURL(i.url));
    setImages({});
    setAnalysis(null);
  };

  const loadSample = async () => {
    setLoadingSample(true);
    try {
      await Promise.all(
        PERSPECTIVES.map(async (p) => {
          const r = await fetch(`/samples/bear/${p}.webp`);
          if (!r.ok) throw new Error(`sample ${p} missing`);
          const blob = await r.blob();
          await setFile(p, new File([blob], `${p}.webp`, { type: 'image/webp' }));
        }),
      );
    } finally {
      setLoadingSample(false);
    }
  };

  const ready = isComplete(images);

  const analyse = async () => {
    setAnalysing(true);
    setAnalysisError(null);
    try {
      setAnalysis(await analyseOnServer(images));
    } catch (e) {
      setAnalysisError((e as Error).message);
    } finally {
      setAnalysing(false);
    }
  };

  const reconstruct = async () => {
    setJobError(null);
    setJob(null);
    try {
      const id = await startReconstruction(images, options);
      const final = await pollJob(id, setJob);
      if (final.state === 'done' && final.model_url) {
        setModelUrl(`${final.model_url}?t=${Date.now()}`);
        document.getElementById('preview')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch (e) {
      setJobError((e as Error).message);
    }
  };

  const onLoaded = useCallback((m: LoadedModel | null) => {
    setModel(m?.root ?? null);
    setModelError(m ? null : 'the GLB could not be loaded');
  }, []);

  const busy = analysing || job?.state === 'running' || job?.state === 'queued';
  const usingDefault = useMemo(() => modelUrl === DEFAULT_MODEL, [modelUrl]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900 transition-colors dark:bg-slate-950 dark:text-slate-100">
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-slate-50/85 backdrop-blur dark:border-slate-800/80 dark:bg-slate-950/85">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="" className="h-7 w-7" />
            <h1 className="text-base font-semibold tracking-tight sm:text-lg">3D Reconstruction &amp; AR Studio</h1>
          </div>
          <button type="button" onClick={() => setDark((d) => !d)} className="grid h-9 w-9 place-items-center rounded-lg hover:bg-slate-200 dark:hover:bg-slate-800" aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'} title="Toggle theme">
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
              {dark ? <path d="M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z" /> : <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" />}
            </svg>
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-5xl space-y-6 px-4 py-6 sm:space-y-8 sm:py-10">
        <Section id="input" step="A" title="Image input" subtitle="Six photos of one object from fixed perspectives. No bottom photo is needed.">
          <ImageUploader images={images} analysis={analysis} onFile={setFile} onRemove={remove} onLoadSample={loadSample} onClear={clear} busy={!!busy} loadingSample={loadingSample} />
        </Section>

        <Section id="reconstruction" step="B" title="Reconstruction" subtitle="Segment, estimate cameras, carve the visual hull, mesh and bake textures from the photos.">
          <ReconstructionStatus
            ready={ready}
            apiOnline={apiOnline}
            analysing={analysing}
            analysis={analysis}
            analysisError={analysisError}
            onAnalyse={analyse}
            job={job}
            jobError={jobError}
            onStart={reconstruct}
            options={options}
            onOptions={setOptions}
          />
        </Section>

        <Section id="preview" step="C" title="3D preview" subtitle={usingDefault ? 'Showing the saved model at /models/reconstructed-object.glb.' : 'Showing the model you just reconstructed.'}>
          <ModelViewer url={modelUrl} onLoaded={onLoaded} />
        </Section>

        <Section id="ar" step="D" title="AR experience" subtitle="Place the model on a real table or floor with WebXR surface detection.">
          <ARViewer model={model} modelError={modelError} />
        </Section>
      </main>

      <footer className="mx-auto max-w-5xl px-4 pb-10 text-xs text-slate-500">
        Reconstruction runs on your own server (CPU). No paid APIs are used.
      </footer>
    </div>
  );
}

function Section({ id, step, title, subtitle, children }: { id: string; step: string; title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="scroll-mt-20 rounded-3xl border border-slate-200 bg-white/70 p-4 shadow-sm sm:p-6 dark:border-slate-800 dark:bg-slate-900/50">
      <div className="mb-4 flex items-start gap-3">
        <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-indigo-600 text-sm font-bold text-white">{step}</span>
        <div>
          <h2 id={`${id}-title`} className="text-lg font-semibold tracking-tight">
            {title}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">{subtitle}</p>
        </div>
      </div>
      {children}
    </section>
  );
}
