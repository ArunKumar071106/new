/**
 * WebXR AR capability detection. Browser-based AR with hit testing needs:
 *  - a secure context (HTTPS or localhost),
 *  - the WebXR Device API (navigator.xr),
 *  - 'immersive-ar' session support (today: Chrome on ARCore-capable Android),
 *  - the 'hit-test' feature (only verifiable when the session is requested).
 * iOS Safari does not implement WebXR immersive-ar; AR Quick Look is a different,
 * non-programmable viewer without WebXR hit testing, so it is not treated as equivalent.
 */
export type ARSupport =
  | { supported: true; notes: string[] }
  | { supported: false; reason: ARUnsupportedReason; message: string; notes: string[] };

export type ARUnsupportedReason = 'insecure-context' | 'no-webxr' | 'no-immersive-ar' | 'ios' | 'check-failed';

export function platformInfo() {
  const ua = navigator.userAgent;
  const isIOS = /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const isChrome = /Chrome\/\d+/.test(ua) && !/Edg\//.test(ua) && !/OPR\//.test(ua);
  const isMobile = isIOS || isAndroid || /Mobi/i.test(ua);
  return { isIOS, isAndroid, isChrome, isMobile };
}

export async function checkARSupport(): Promise<ARSupport> {
  const p = platformInfo();
  const notes: string[] = [];
  if (!window.isSecureContext) {
    return {
      supported: false,
      reason: 'insecure-context',
      message:
        'AR needs a secure (HTTPS) connection. Open this page over https:// (e.g. `npm run dev:https`) or via localhost with USB port forwarding.',
      notes,
    };
  }
  const xr = (navigator as Navigator & { xr?: XRSystem }).xr;
  if (!xr) {
    if (p.isIOS) {
      return {
        supported: false,
        reason: 'ios',
        message:
          'iOS Safari does not support WebXR immersive AR with hit testing. Use Chrome on an ARCore-compatible Android device. The 3D viewer still works here.',
        notes,
      };
    }
    return {
      supported: false,
      reason: 'no-webxr',
      message: p.isMobile
        ? 'This browser does not expose WebXR. Use an up-to-date Chrome on an ARCore-compatible Android device.'
        : 'WebXR AR is not available on this device. Desktop browsers can use the 3D viewer; open the page on an ARCore-compatible Android phone in Chrome for AR.',
      notes,
    };
  }
  try {
    const ok = await xr.isSessionSupported('immersive-ar');
    if (!ok) {
      return {
        supported: false,
        reason: 'no-immersive-ar',
        message: p.isAndroid
          ? 'Immersive AR is not supported here. The device may not be ARCore-certified, or "Google Play Services for AR" is missing/out of date.'
          : 'This device/browser supports WebXR but not immersive AR sessions (common on desktops and VR-only headsets).',
        notes,
      };
    }
  } catch (e) {
    return { supported: false, reason: 'check-failed', message: `Could not query WebXR support: ${String(e)}`, notes };
  }
  notes.push('Surface hit testing is confirmed when the AR session starts.');
  return { supported: true, notes };
}

/** Map a requestSession() failure to a user-facing explanation. */
export function explainSessionError(err: unknown): string {
  const e = err as DOMException;
  switch (e?.name) {
    case 'NotAllowedError':
    case 'SecurityError':
      return 'Camera access was denied or the request was not triggered by a tap. Allow camera access for this site in the browser settings and try again.';
    case 'NotSupportedError':
      return 'This device cannot start an AR session with surface hit testing (hit-test feature unsupported).';
    case 'InvalidStateError':
      return 'Another immersive session is already running. Close it and retry.';
    default:
      return `Could not start AR: ${e?.message || String(err)}`;
  }
}
