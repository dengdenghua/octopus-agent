import { cn } from "@/lib/utils";

const inElectron = (): boolean =>
  typeof window !== "undefined" && !!window.octopus?.isElectron;

export function MacWindowControls({ className }: { className?: string }) {
  // Kimi-style skeuomorphic traffic lights, decorative only (no close/minimize
  // IPC exists in the preload bridge). Every Electron build already shows real
  // window controls in the same bar (native traffic lights in the darwin title
  // bar, win32 caption overlay on the right), so a second fake set must never
  // appear inside the shell. Pure web keeps the decoration on every OS.
  if (inElectron()) return null;
  return (
    <div
      aria-hidden="true"
      className={cn(
        "flex h-8 w-12 shrink-0 items-center justify-center gap-1.5",
        className,
      )}
    >
      <span className="block h-3 w-3 shrink-0 rounded-full border border-red-500/45 bg-red-400 shadow-[inset_0_0.5px_0_rgba(255,255,255,0.55)]" />
      <span className="block h-3 w-3 shrink-0 rounded-full border border-amber-500/45 bg-amber-400 shadow-[inset_0_0.5px_0_rgba(255,255,255,0.55)]" />
      <span className="block h-3 w-3 shrink-0 rounded-full border border-emerald-500/45 bg-emerald-400 shadow-[inset_0_0.5px_0_rgba(255,255,255,0.55)]" />
    </div>
  );
}
