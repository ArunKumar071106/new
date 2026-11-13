import type { ARState } from '../services/arService';

interface Props {
  state: ARState;
  onPlace: () => void;
  onRotate: (deg: number) => void;
  onScale: (factor: number) => void;
  onResetScale: () => void;
  onReset: () => void;
  onExit: () => void;
}

/** On-screen AR controls rendered inside the WebXR DOM overlay. */
export default function ARControls({ state, onPlace, onRotate, onScale, onResetScale, onReset, onExit }: Props) {
  const placed = state.phase === 'placed';
  const canPlace = state.phase === 'surface-found';
  return (
    <div className="pointer-events-none fixed inset-0 flex flex-col justify-between p-4 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))] text-white">
      <div className="flex items-start justify-between gap-3">
        <div className="pointer-events-auto max-w-[75%] rounded-xl bg-black/55 px-3 py-2 text-sm backdrop-blur" role="status" aria-live="polite">
          {state.message}
          {placed && (
            <div className="mt-0.5 text-xs text-white/70">
              scale {state.scale.toFixed(2)}x | {Math.round(((state.rotationDeg % 360) + 360) % 360)} deg
              {state.anchors ? ' | anchored' : ''}
            </div>
          )}
        </div>
        <button data-ar-ui type="button" onClick={onExit} className="pointer-events-auto rounded-xl bg-black/55 px-3 py-2 text-sm font-medium backdrop-blur active:bg-black/70">
          Exit AR
        </button>
      </div>

      <div data-ar-ui className="pointer-events-auto mx-auto w-full max-w-md space-y-2">
        {!placed ? (
          <button type="button" disabled={!canPlace} onClick={onPlace} className="w-full rounded-2xl bg-indigo-600 py-3.5 text-base font-semibold shadow-lg transition disabled:bg-white/25 disabled:text-white/60">
            {canPlace ? 'Place object' : 'Scanning for a surface...'}
          </button>
        ) : (
          <>
            <div className="grid grid-cols-4 gap-2">
              <ArBtn label="Rotate left" onClick={() => onRotate(-15)}>
                &#8634;
              </ArBtn>
              <ArBtn label="Rotate right" onClick={() => onRotate(15)}>
                &#8635;
              </ArBtn>
              <ArBtn label="Scale down" onClick={() => onScale(1 / 1.2)}>
                &minus;
              </ArBtn>
              <ArBtn label="Scale up" onClick={() => onScale(1.2)}>
                +
              </ArBtn>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <button type="button" onClick={onResetScale} className="rounded-xl bg-black/55 py-2.5 text-sm backdrop-blur active:bg-black/70">
                Real size (1x)
              </button>
              <button type="button" onClick={onReset} className="rounded-xl bg-black/55 py-2.5 text-sm backdrop-blur active:bg-black/70">
                Reset position
              </button>
            </div>
            <p className="text-center text-[11px] text-white/70">Drag with one finger to rotate | pinch to scale</p>
          </>
        )}
      </div>
    </div>
  );
}

function ArBtn({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} className="rounded-xl bg-black/55 py-3 text-2xl leading-none backdrop-blur active:bg-black/70">
      {children}
    </button>
  );
}
