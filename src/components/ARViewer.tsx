import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type * as THREE from 'three';
import { ARSession, type ARState } from '../services/arService';
import { checkARSupport, explainSessionError, platformInfo, type ARSupport } from '../utils/deviceCompatibility';
import ARControls from './ARControls';

interface Props {
  model: THREE.Object3D | null;
  modelError?: string | null;
}

export default function ARViewer({ model, modelError }: Props) {
  const [support, setSupport] = useState<ARSupport | null>(null);
  const [arState, setArState] = useState<ARState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [overlayEl, setOverlayEl] = useState<HTMLDivElement | null>(null);
  const sessionRef = useRef<ARSession | null>(null);
  const gesture = useRef<{ x: number; dist: number; scale: number } | null>(null);

  useEffect(() => {
    checkARSupport().then(setSupport);
  }, []);

  // overlay root for WebXR DOM Overlay: lives directly under <body>
  useEffect(() => {
    const el = document.createElement('div');
    el.id = 'ar-overlay';
    el.style.display = 'none';
    document.body.appendChild(el);
    // taps on our controls must not also trigger an XR "select" (placement)
    const stop = (e: Event) => {
      if ((e.target as HTMLElement).closest?.('[data-ar-ui]')) e.preventDefault();
    };
    el.addEventListener('beforexrselect', stop);
    setOverlayEl(el);
    return () => {
      el.removeEventListener('beforexrselect', stop);
      el.remove();
    };
  }, []);

  useEffect(() => () => void sessionRef.current?.end(), []);

  const active = !!arState && arState.phase !== 'ended' && arState.phase !== 'idle';

  const start = async () => {
    setError(null);
    if (!model || !overlayEl) return;
    const s = new ARSession(model.clone(true), overlayEl);
    sessionRef.current = s;
    const unsub = s.subscribe((st) => {
      setArState(st);
      if (st.phase === 'ended') {
        overlayEl.style.display = 'none';
        sessionRef.current = null;
        unsub();
      }
    });
    overlayEl.style.display = 'block';
    try {
      await s.start();
    } catch (e) {
      overlayEl.style.display = 'none';
      setError(explainSessionError(e));
      setArState(null);
      sessionRef.current = null;
      unsub();
    }
  };

  // one-finger drag = rotate, two-finger pinch = scale (only after placement)
  const onTouchStart = (e: React.TouchEvent) => {
    if ((e.target as HTMLElement).closest('[data-ar-ui]') || arState?.phase !== 'placed') return;
    const t = e.touches;
    gesture.current = {
      x: t[0].clientX,
      dist: t.length > 1 ? Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY) : 0,
      scale: arState.scale,
    };
  };
  const onTouchMove = (e: React.TouchEvent) => {
    const g = gesture.current;
    const s = sessionRef.current;
    if (!g || !s) return;
    const t = e.touches;
    if (t.length > 1 && g.dist > 0) {
      const d = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      s.setScale(g.scale * (d / g.dist));
    } else if (t.length === 1) {
      const dx = t[0].clientX - g.x;
      g.x = t[0].clientX;
      s.rotate(dx * 0.5);
    }
  };
  const onTouchEnd = () => {
    gesture.current = null;
  };

  const p = platformInfo();
  const canStart = !!support?.supported && !!model && !active;

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <button
          type="button"
          onClick={start}
          disabled={!canStart}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-indigo-600 px-5 py-3 font-semibold text-white shadow-sm transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:text-slate-500 dark:disabled:bg-slate-800"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinejoin="round">
            <path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
            <path d="M4 7.5l8 4.5 8-4.5M12 12v9" />
          </svg>
          Start AR
        </button>
        <StatusLine support={support} model={model} modelError={modelError} />
      </div>

      {error && (
        <p role="alert" className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700 dark:border-rose-900 dark:bg-rose-950/40 dark:text-rose-300">
          {error}
        </p>
      )}

      <ol className="grid gap-2 text-sm text-slate-600 sm:grid-cols-3 dark:text-slate-400">
        <li className="rounded-xl bg-slate-100 p-3 dark:bg-slate-800/60"><b className="text-slate-800 dark:text-slate-200">1. Scan.</b> Point the camera at a table or the floor and move slowly until the ring appears.</li>
        <li className="rounded-xl bg-slate-100 p-3 dark:bg-slate-800/60"><b className="text-slate-800 dark:text-slate-200">2. Place.</b> Tap the screen or "Place object". It is shown at its real size.</li>
        <li className="rounded-xl bg-slate-100 p-3 dark:bg-slate-800/60"><b className="text-slate-800 dark:text-slate-200">3. Adjust.</b> Drag to rotate, pinch or use +/- to scale, "Reset position" to move it.</li>
      </ol>

      <p className="text-xs text-slate-500">
        Requires Chrome on an ARCore-compatible Android device over HTTPS. {p.isIOS ? 'iOS Safari has no WebXR AR support; ' : ''}Desktop
        browsers show the 3D viewer only.
      </p>

      {overlayEl &&
        active &&
        arState &&
        createPortal(
          <div className="fixed inset-0 touch-none select-none" onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd}>
            <ARControls
              state={arState}
              onPlace={() => sessionRef.current?.placeAtReticle()}
              onRotate={(d) => sessionRef.current?.rotate(d)}
              onScale={(f) => sessionRef.current?.scaleBy(f)}
              onResetScale={() => sessionRef.current?.setScale(1)}
              onReset={() => sessionRef.current?.resetPlacement()}
              onExit={() => sessionRef.current?.end()}
            />
          </div>,
          overlayEl,
        )}
    </div>
  );
}

function StatusLine({ support, model, modelError }: { support: ARSupport | null; model: THREE.Object3D | null; modelError?: string | null }) {
  let tone = 'text-slate-500';
  let text = 'Checking WebXR support...';
  if (support && !support.supported) {
    tone = 'text-amber-700 dark:text-amber-400';
    text = support.message;
  } else if (!model) {
    tone = 'text-amber-700 dark:text-amber-400';
    text = modelError ? `Model unavailable: ${modelError}` : 'Load or reconstruct a model first.';
  } else if (support?.supported) {
    tone = 'text-emerald-700 dark:text-emerald-400';
    text = 'Immersive AR is supported on this device.';
  }
  return (
    <p className={`text-sm ${tone}`} role="status">
      {text}
    </p>
  );
}
