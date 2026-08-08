/**
 * Desktop pet entry point.
 *
 * Historical: this directory previously hosted a Canvas-2D pet engine plus
 * Three.js GLTF/FBX 3D characters. Those have been removed in preparation
 * for a Live2D Cubism migration.
 *
 * The Electron desktop pet still lives in `pet-sidecar/` (Godot-based),
 * driven by `frontend/electron/pet-sidecar.cjs` over UDP 8765. That pipeline
 * is independent from this in-page slot and is NOT touched by this module.
 *
 * To re-enable an in-page mascot, expose a `DesktopPetMascot` component
 * here and mount it inside `ChatComposer`. The component must accept at
 * minimum: `mood: "idle" | "thinking" | "happy" | "working" | "error"`
 * and a `size: "sm" | "md" | "lg"` prop, so callers can swap engines
 * without touching the chat composer.
 *
 * Live2D integration plan (target stack):
 *   - npm: `pixi-live2d-display` + `pixi.js`
 *   - assets: `live2d/<model>/<model>.model3.json` + textures
 *   - mount: <canvas/> inside a transparent DOM element, sized via `size`
 *   - mood mapping: drive Live2D motion groups
 *       idle     -> idle.motion3.json
 *       thinking -> tap_head.motion3.json (loop)
 *       happy    -> happy.motion3.json
 *       working  -> idle.motion3.json + expression F01 (focused)
 *       error    -> idle.motion3.json + expression F02 (sad)
 */
export type PetMood = "idle" | "thinking" | "happy" | "working" | "error";
export type PetSize = "sm" | "md" | "lg";

export interface DesktopPetMascotProps {
  mood?: PetMood;
  size?: PetSize;
  className?: string;
}

/**
 * Placeholder. Render nothing until the Live2D engine lands.
 *
 * Kept as a real (no-op) React component so callers can mount it
 * unconditionally; replacing the body is the only change needed
 * when the Live2D engine is wired in.
 */
export function DesktopPetMascot(_props: DesktopPetMascotProps): null {
  return null;
}

export default DesktopPetMascot;
