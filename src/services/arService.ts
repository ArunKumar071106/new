import * as THREE from 'three';
import { XREstimatedLight } from 'three/examples/jsm/webxr/XREstimatedLight.js';

/**
 * Genuine WebXR AR: an 'immersive-ar' session with camera passthrough composited by the
 * browser, plane hit testing (WebXR Hit Test API) for a placement reticle, tap-to-place,
 * and optional anchors / light estimation when the device offers them.
 *
 * The model is kept in world space (the XR reference space); ARCore tracking keeps it
 * fixed to the real surface as the phone moves. Nothing here draws the camera feed
 * manually - that is done by the XR compositor.
 */

export type ARPhase = 'idle' | 'starting' | 'scanning' | 'surface-found' | 'placed' | 'ended';

export interface ARState {
  phase: ARPhase;
  message: string;
  scale: number;
  rotationDeg: number;
  anchors: boolean;
  lightEstimation: boolean;
}

type Listener = (s: ARState) => void;

const UP = new THREE.Vector3(0, 1, 0);
const HORIZONTAL_COS = Math.cos(THREE.MathUtils.degToRad(20)); // surface normal within 20 deg of vertical

export class ARSession {
  private renderer!: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(70, 1, 0.01, 50);
  private session: XRSession | null = null;
  private hitTestSource: XRHitTestSource | null = null;
  private lastHit: XRHitTestResult | null = null;
  private anchor: XRAnchor | null = null;
  private reticle: THREE.Mesh;
  private holder = new THREE.Group(); // world placement (position + yaw)
  private shadowPlane: THREE.Mesh;
  private dirLight: THREE.DirectionalLight;
  private hemiLight: THREE.HemisphereLight;
  private xrLight: XREstimatedLight | null = null;
  private listeners = new Set<Listener>();
  private state: ARState = { phase: 'idle', message: '', scale: 1, rotationDeg: 0, anchors: false, lightEstimation: false };
  private onSelect = () => this.placeAtReticle();
  private onEnd = () => this.cleanup();
  private onResize = () => this.renderer?.setSize(window.innerWidth, window.innerHeight);

  constructor(private model: THREE.Object3D, private overlayRoot: HTMLElement) {
    // reticle: ring + centre dot lying flat on the detected surface
    const ring = new THREE.RingGeometry(0.045, 0.06, 40).rotateX(-Math.PI / 2);
    const dot = new THREE.CircleGeometry(0.008, 16).rotateX(-Math.PI / 2);
    const mat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, depthTest: false });
    this.reticle = new THREE.Mesh(ring, mat);
    this.reticle.add(new THREE.Mesh(dot, mat));
    this.reticle.matrixAutoUpdate = false;
    this.reticle.visible = false;
    this.reticle.renderOrder = 10;
    this.scene.add(this.reticle);

    // soft contact shadow on the real surface
    this.shadowPlane = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
      new THREE.ShadowMaterial({ opacity: 0.35 }),
    );
    this.shadowPlane.receiveShadow = true;

    this.holder.visible = false;
    this.holder.add(model);
    this.holder.add(this.shadowPlane);
    this.scene.add(this.holder);

    this.hemiLight = new THREE.HemisphereLight(0xffffff, 0x8a8a8a, 1.6);
    this.dirLight = new THREE.DirectionalLight(0xffffff, 1.6);
    this.dirLight.position.set(0.3, 1, 0.25);
    this.dirLight.castShadow = true;
    this.dirLight.shadow.mapSize.set(1024, 1024);
    this.dirLight.shadow.bias = -0.0005;
    this.scene.add(this.hemiLight, this.dirLight, this.dirLight.target);
    this.fitShadow();
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.state);
    return () => this.listeners.delete(fn);
  }

  private set(patch: Partial<ARState>) {
    this.state = { ...this.state, ...patch };
    for (const l of this.listeners) l(this.state);
  }

  private fitShadow() {
    const box = new THREE.Box3().setFromObject(this.model);
    const size = box.getSize(new THREE.Vector3());
    const r = Math.max(size.x, size.z) * 1.6 + 0.05;
    this.shadowPlane.scale.set(r * 2, 1, r * 2);
    const cam = this.dirLight.shadow.camera;
    cam.left = cam.bottom = -r;
    cam.right = cam.top = r;
    cam.near = 0.01;
    cam.far = 5;
    cam.updateProjectionMatrix();
  }

  /** Must be called from a user gesture (tap/click). */
  async start(): Promise<void> {
    const xr = navigator.xr;
    if (!xr) throw new DOMException('WebXR not available', 'NotSupportedError');
    this.set({ phase: 'starting', message: 'Requesting camera and AR session...' });

    const session = await xr.requestSession('immersive-ar', {
      requiredFeatures: ['hit-test'],
      optionalFeatures: ['dom-overlay', 'anchors', 'light-estimation', 'local-floor'],
      domOverlay: { root: this.overlayRoot },
    } as XRSessionInit);
    this.session = session;

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(window.innerWidth, window.innerHeight);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NoToneMapping;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.xr.enabled = true;
    this.renderer.xr.setReferenceSpaceType('local');
    // The XR compositor presents the frames (camera passthrough + our layer); the canvas
    // only needs to exist in the document.
    Object.assign(this.renderer.domElement.style, { position: 'fixed', inset: '0', zIndex: '-1', pointerEvents: 'none' });
    document.body.appendChild(this.renderer.domElement);
    window.addEventListener('resize', this.onResize);

    await this.renderer.xr.setSession(session);

    const viewerSpace = await session.requestReferenceSpace('viewer');
    const hts = await session.requestHitTestSource?.({ space: viewerSpace });
    if (!hts) {
      await session.end();
      throw new DOMException('Hit testing unavailable', 'NotSupportedError');
    }
    this.hitTestSource = hts;

    session.addEventListener('select', this.onSelect);
    session.addEventListener('end', this.onEnd);

    const enabled = (session as XRSession & { enabledFeatures?: string[] }).enabledFeatures ?? [];
    const anchors = enabled.includes('anchors');
    const lightEstimation = enabled.includes('light-estimation');
    if (lightEstimation) this.setupLightEstimation();

    this.set({
      phase: 'scanning',
      message: 'Move your phone slowly to find a table or floor.',
      anchors,
      lightEstimation,
    });
    this.renderer.setAnimationLoop((_t, frame) => this.onFrame(frame));
  }

  private setupLightEstimation() {
    const light = new XREstimatedLight(this.renderer);
    light.addEventListener('estimationstart', () => {
      this.scene.add(light);
      this.hemiLight.visible = false;
      if (light.environment) this.scene.environment = light.environment;
      // keep our directional light only for the contact shadow
      this.dirLight.intensity = 0.4;
    });
    light.addEventListener('estimationend', () => {
      this.scene.remove(light);
      this.scene.environment = null;
      this.hemiLight.visible = true;
      this.dirLight.intensity = 1.6;
    });
    this.xrLight = light;
  }

  private onFrame(frame?: XRFrame) {
    if (!frame || !this.session) return;
    const ref = this.renderer.xr.getReferenceSpace();
    if (!ref) return;

    // anchored placement: follow the anchor's tracked pose
    if (this.anchor && this.state.phase === 'placed') {
      const pose = frame.getPose(this.anchor.anchorSpace, ref);
      if (pose) {
        const p = pose.transform.position;
        this.holder.position.set(p.x, p.y, p.z);
      }
    }

    if (this.hitTestSource && this.state.phase !== 'placed') {
      const results = frame.getHitTestResults(this.hitTestSource);
      const hit = results.find((r) => this.isHorizontal(r.getPose(ref)));
      if (hit) {
        const pose = hit.getPose(ref)!;
        this.reticle.visible = true;
        this.reticle.matrix.fromArray(pose.transform.matrix);
        this.lastHit = hit;
        if (this.state.phase !== 'surface-found')
          this.set({ phase: 'surface-found', message: 'Surface found - tap the screen or "Place object".' });
      } else {
        this.reticle.visible = false;
        this.lastHit = null;
        if (this.state.phase === 'surface-found')
          this.set({
            phase: 'scanning',
            message: results.length ? 'Surface is not horizontal - aim at a table or floor.' : 'Looking for a surface...',
          });
      }
    } else {
      this.reticle.visible = false;
    }
    this.renderer.render(this.scene, this.camera);
  }

  private isHorizontal(pose?: XRPose): boolean {
    if (!pose) return false;
    const m = new THREE.Matrix4().fromArray(pose.transform.matrix);
    const normal = new THREE.Vector3().setFromMatrixColumn(m, 1).normalize();
    return normal.dot(UP) > HORIZONTAL_COS; // upward-facing (floor/table, not ceiling/wall)
  }

  placeAtReticle() {
    if (this.state.phase !== 'surface-found' || !this.reticle.visible) return;
    const pos = new THREE.Vector3().setFromMatrixPosition(this.reticle.matrix);
    this.holder.position.copy(pos);
    // face the user: yaw the model towards the camera
    const camPos = new THREE.Vector3();
    this.renderer.xr.getCamera().getWorldPosition(camPos);
    const yaw = Math.atan2(camPos.x - pos.x, camPos.z - pos.z);
    this.holder.rotation.set(0, yaw + THREE.MathUtils.degToRad(this.state.rotationDeg), 0);
    this.holder.userData.baseYaw = yaw;
    this.holder.visible = true;
    this.reticle.visible = false;
    this.dirLight.position.copy(pos).add(new THREE.Vector3(0.3, 1, 0.25));
    this.dirLight.target.position.copy(pos);
    this.set({ phase: 'placed', message: 'Placed. Walk around it, rotate or scale it.' });

    // pin to the real world with an anchor when supported (more stable over time)
    const hit = this.lastHit as (XRHitTestResult & { createAnchor?: () => Promise<XRAnchor> }) | null;
    this.anchor?.delete?.();
    this.anchor = null;
    hit?.createAnchor?.()
      .then((a) => {
        if (this.state.phase === 'placed') this.anchor = a;
        else a.delete();
      })
      .catch(() => {
        /* anchors optional */
      });
  }

  rotate(deltaDeg: number) {
    const rotationDeg = (this.state.rotationDeg + deltaDeg) % 360;
    this.holder.rotation.y = (this.holder.userData.baseYaw ?? 0) + THREE.MathUtils.degToRad(rotationDeg);
    this.set({ rotationDeg });
  }

  setScale(scale: number) {
    const s = THREE.MathUtils.clamp(scale, 0.1, 20);
    this.holder.scale.setScalar(s);
    this.set({ scale: s });
  }

  scaleBy(factor: number) {
    this.setScale(this.state.scale * factor);
  }

  /** Pick the model up again and show the reticle for re-placement. */
  resetPlacement() {
    this.anchor?.delete?.();
    this.anchor = null;
    this.holder.visible = false;
    this.set({ phase: 'scanning', message: 'Aim at a surface and tap to place again.' });
  }

  async end() {
    if (this.session) await this.session.end().catch(() => this.cleanup());
    else this.cleanup();
  }

  private cleanup() {
    if (this.state.phase === 'ended') return;
    this.hitTestSource?.cancel();
    this.hitTestSource = null;
    this.anchor?.delete?.();
    this.anchor = null;
    if (this.session) {
      this.session.removeEventListener('select', this.onSelect);
      this.session.removeEventListener('end', this.onEnd);
    }
    this.session = null;
    window.removeEventListener('resize', this.onResize);
    if (this.renderer) {
      this.renderer.setAnimationLoop(null);
      this.renderer.dispose();
      this.renderer.domElement.remove();
    }
    if (this.xrLight) {
      this.scene.remove(this.xrLight);
      (this.xrLight as XREstimatedLight & { dispose?: () => void }).dispose?.(); // present at runtime, missing from @types/three
      this.xrLight = null;
    }
    this.holder.remove(this.model);
    this.set({ phase: 'ended', message: 'AR session ended.' });
  }
}
