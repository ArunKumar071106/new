import { useCallback, useEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js';
import { disposeObject, loadModel, type LoadedModel } from '../services/modelLoader';

interface Props {
  url: string | null;
  onLoaded?: (m: LoadedModel | null) => void;
  downloadName?: string;
}

type Shading = 'studio' | 'photo';

export default function ModelViewer({ url, onLoaded, downloadName = 'reconstructed-object.glb' }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const mountRef = useRef<HTMLDivElement>(null);
  const ctx = useRef<{
    renderer: THREE.WebGLRenderer;
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    controls: OrbitControls;
    ground: THREE.Mesh;
    key: THREE.DirectionalLight;
    model: THREE.Object3D | null;
    home: { pos: THREE.Vector3; target: THREE.Vector3 } | null;
    materials: Map<THREE.Mesh, THREE.Material | THREE.Material[]>;
  } | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<LoadedModel | null>(null);
  const [shading, setShading] = useState<Shading>('studio');
  const [isFull, setIsFull] = useState(false);

  // --- scene setup (once) ---------------------------------------------------------------
  useEffect(() => {
    const mount = mountRef.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    mount.appendChild(renderer.domElement);
    renderer.domElement.style.touchAction = 'none';
    renderer.domElement.setAttribute('aria-label', '3D model viewer. Drag to rotate, pinch or scroll to zoom.');

    const scene = new THREE.Scene();
    const pmrem = new THREE.PMREMGenerator(renderer);
    const envTex = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    scene.environment = envTex; // image-based lighting + reflections

    const camera = new THREE.PerspectiveCamera(35, 1, 0.001, 100);
    camera.position.set(0.25, 0.18, 0.35);

    scene.add(new THREE.HemisphereLight(0xffffff, 0x666677, 0.6));
    const key = new THREE.DirectionalLight(0xffffff, 1.5);
    key.position.set(0.4, 0.8, 0.5);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0003;
    key.shadow.normalBias = 0.002;
    scene.add(key, key.target);

    const ground = new THREE.Mesh(new THREE.CircleGeometry(1, 64).rotateX(-Math.PI / 2), new THREE.ShadowMaterial({ opacity: 0.28 }));
    ground.receiveShadow = true;
    scene.add(ground);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = true;

    ctx.current = { renderer, scene, camera, controls, ground, key, model: null, home: null, materials: new Map() };

    const resize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      renderer.setSize(w, h);
      camera.aspect = w / Math.max(h, 1);
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(mount);
    resize();

    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      controls.update();
      renderer.render(scene, camera);
    };
    tick();

    const onFs = () => setIsFull(document.fullscreenElement === wrapRef.current);
    document.addEventListener('fullscreenchange', onFs);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener('fullscreenchange', onFs);
      controls.dispose();
      if (ctx.current?.model) disposeObject(ctx.current.model);
      envTex.dispose();
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      ctx.current = null;
    };
  }, []);

  const frame = useCallback((animate = false) => {
    const c = ctx.current;
    if (!c?.model) return;
    const box = new THREE.Box3().setFromObject(c.model);
    const sphere = box.getBoundingSphere(new THREE.Sphere());
    const fov = THREE.MathUtils.degToRad(c.camera.fov);
    const dist = (sphere.radius / Math.sin(fov / 2)) * 1.15;
    const dir = new THREE.Vector3(0.55, 0.38, 1).normalize();
    const target = sphere.center.clone();
    const pos = target.clone().addScaledVector(dir, dist);
    c.home = { pos, target };
    c.controls.minDistance = sphere.radius * 0.6;
    c.controls.maxDistance = sphere.radius * 12;
    c.camera.near = sphere.radius / 100;
    c.camera.far = sphere.radius * 100;
    c.camera.updateProjectionMatrix();
    if (!animate) {
      c.camera.position.copy(pos);
      c.controls.target.copy(target);
      return;
    }
    const p0 = c.camera.position.clone();
    const t0 = c.controls.target.clone();
    const start = performance.now();
    const step = (now: number) => {
      const k = Math.min(1, (now - start) / 450);
      const e = 1 - (1 - k) ** 3;
      c.camera.position.lerpVectors(p0, pos, e);
      c.controls.target.lerpVectors(t0, target, e);
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, []);

  // --- load model when url changes ----------------------------------------------------
  useEffect(() => {
    const c = ctx.current;
    if (!c) return;
    if (!url) {
      setStatus('idle');
      return;
    }
    let cancelled = false;
    setStatus('loading');
    setProgress(0);
    setError(null);
    loadModel(url, (f) => !cancelled && setProgress(f))
      .then((m) => {
        if (cancelled) {
          disposeObject(m.root);
          return;
        }
        if (c.model) {
          c.scene.remove(c.model);
          disposeObject(c.model);
        }
        c.materials.clear();
        c.model = m.root;
        c.scene.add(m.root);
        const box = new THREE.Box3().setFromObject(m.root);
        const size = box.getSize(new THREE.Vector3());
        const r = Math.max(size.x, size.y, size.z);
        c.ground.position.y = box.min.y;
        c.ground.scale.setScalar(r * 2.5);
        const sc = c.key.shadow.camera;
        sc.left = sc.bottom = -r * 1.5;
        sc.right = sc.top = r * 1.5;
        sc.near = r * 0.05;
        sc.far = r * 10;
        c.key.position.set(r * 1.2, r * 2.5, r * 1.6);
        c.key.target.position.copy(box.getCenter(new THREE.Vector3()));
        sc.updateProjectionMatrix();
        frame(false);
        setInfo(m);
        setStatus('ready');
        onLoaded?.(m);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message);
        setStatus('error');
        onLoaded?.(null);
      });
    return () => {
      cancelled = true;
    };
  }, [url, frame, onLoaded]);

  // --- shading mode: PBR studio lighting vs photo-baked (unlit) -------------------------
  useEffect(() => {
    const c = ctx.current;
    if (!c?.model) return;
    c.model.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (!mesh.isMesh) return;
      if (!c.materials.has(mesh)) c.materials.set(mesh, mesh.material);
      const original = c.materials.get(mesh) as THREE.MeshStandardMaterial;
      if (shading === 'photo') {
        mesh.material = new THREE.MeshBasicMaterial({ map: original.map ?? null, color: 0xffffff });
      } else if (mesh.material !== original) {
        (mesh.material as THREE.Material).dispose();
        mesh.material = original;
      }
    });
  }, [shading, info]);

  const toggleFullscreen = async () => {
    const el = wrapRef.current as (HTMLDivElement & { webkitRequestFullscreen?: () => void }) | null;
    if (!el) return;
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (el.requestFullscreen) await el.requestFullscreen().catch(() => setIsFull((v) => !v));
    else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
    else setIsFull((v) => !v); // CSS fallback (iOS Safari)
  };

  const fullClass = isFull && !document.fullscreenElement ? 'fixed inset-0 z-50 rounded-none' : '';

  return (
    <div ref={wrapRef} className={`relative overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-b from-slate-50 to-slate-200 dark:border-slate-800 dark:from-slate-900 dark:to-slate-950 ${fullClass}`}>
      <div ref={mountRef} className={`${isFull ? 'h-full min-h-screen' : 'h-[58vh] min-h-[320px] max-h-[640px]'} w-full`} />

      {status === 'loading' && (
        <div className="absolute inset-0 grid place-items-center bg-white/40 backdrop-blur-sm dark:bg-slate-950/40" role="status">
          <div className="w-48 text-center">
            <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-indigo-500 border-t-transparent" />
            <div className="h-1.5 overflow-hidden rounded bg-slate-300 dark:bg-slate-700">
              <div className="h-full bg-indigo-500 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
            </div>
            <p className="mt-2 text-xs text-slate-600 dark:text-slate-300">Loading model {Math.round(progress * 100)}%</p>
          </div>
        </div>
      )}
      {status === 'error' && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center" role="alert">
          <div>
            <p className="font-medium text-rose-600 dark:text-rose-400">Could not load the 3D model</p>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{error}</p>
          </div>
        </div>
      )}
      {status === 'idle' && (
        <div className="absolute inset-0 grid place-items-center p-6 text-center text-sm text-slate-500">
          Reconstruct a model to preview it here.
        </div>
      )}

      {status === 'ready' && (
        <>
          <div className="pointer-events-none absolute left-3 top-3 rounded-lg bg-white/80 px-2.5 py-1.5 text-[11px] leading-tight text-slate-700 shadow-sm backdrop-blur dark:bg-slate-900/80 dark:text-slate-300">
            {info && (
              <>
                <div>
                  {(info.size.x * 100).toFixed(1)} x {(info.size.y * 100).toFixed(1)} x {(info.size.z * 100).toFixed(1)} cm
                </div>
                <div>
                  {info.triangles.toLocaleString()} triangles{info.textureSize ? ` | ${info.textureSize} texture` : ''}
                </div>
              </>
            )}
          </div>
          <div className="absolute bottom-3 left-1/2 flex -translate-x-1/2 gap-1.5 rounded-xl bg-white/85 p-1.5 shadow-lg backdrop-blur dark:bg-slate-900/85">
            <ToolButton label="Reset camera" onClick={() => frame(true)}>
              <path d="M4 4v5h5M20 20v-5h-5M5.6 15A7 7 0 0 0 18.4 15M18.4 9A7 7 0 0 0 5.6 9" />
            </ToolButton>
            <ToolButton label={shading === 'studio' ? 'Show photo-baked colours (unlit)' : 'Show studio lighting'} onClick={() => setShading((s) => (s === 'studio' ? 'photo' : 'studio'))} active={shading === 'photo'}>
              <path d="M12 3v2M12 19v2M5 12H3M21 12h-2M6.3 6.3 4.9 4.9M19.1 19.1l-1.4-1.4M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z" />
            </ToolButton>
            <ToolButton label={isFull ? 'Exit fullscreen' : 'Fullscreen'} onClick={toggleFullscreen}>
              {isFull ? <path d="M9 4v5H4M15 4v5h5M9 20v-5H4M15 20v-5h5" /> : <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />}
            </ToolButton>
            {url && (
              <a href={url} download={downloadName} className="grid h-9 w-9 place-items-center rounded-lg text-slate-700 hover:bg-slate-200 dark:text-slate-200 dark:hover:bg-slate-700" title="Download GLB" aria-label="Download GLB">
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14" />
                </svg>
              </a>
            )}
          </div>
          <p className="pointer-events-none absolute right-3 top-3 hidden text-[11px] text-slate-500 sm:block">Drag to orbit | scroll / pinch to zoom | right-drag to pan</p>
        </>
      )}
    </div>
  );
}

function ToolButton({ label, onClick, children, active }: { label: string; onClick: () => void; children: React.ReactNode; active?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      className={`grid h-9 w-9 place-items-center rounded-lg transition ${active ? 'bg-indigo-600 text-white' : 'text-slate-700 hover:bg-slate-200 dark:text-slate-200 dark:hover:bg-slate-700'}`}
    >
      <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
        {children}
      </svg>
    </button>
  );
}
