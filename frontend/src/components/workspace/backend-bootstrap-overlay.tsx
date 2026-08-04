import { useEffect, useState } from "react";

import { getOctopusBaseURL } from "@/core/config";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

/**
 * First-launch bootstrap gate for the packaged Electron app.
 *
 * The desktop app ships a lean core and uses `uv` to create a venv + install
 * deps on first run (see backend-runtime.cjs). While that happens the backend
 * is unreachable, so we show a full-screen overlay instead of a broken shell.
 *
 * Detection: only in the *packaged* shell (`isElectron` + `file://` protocol).
 * Dev mode loads the renderer from the Vite server (http://localhost:3000) and
 * runs the backend externally, so it never triggers this gate.
 *
 * We just track raw backend reachability: show the gate whenever the backend
 * is down, and refine the copy from `backend:bootstrap-progress` events (which
 * may be missed if the renderer mounts mid-install, hence the health poll).
 */

interface BootstrapProgress {
  stage?: string;
  message?: string;
}

const HEALTH_POLL_MS = 1500;
const HEALTH_TIMEOUT_MS = 2000;

function isPackagedShell(): boolean {
  return (
    typeof window !== "undefined" &&
    !!window.octopus?.isElectron &&
    window.location.protocol === "file:"
  );
}

async function backendReady(): Promise<boolean> {
  try {
    const res = await fetch(`${getOctopusBaseURL()}/health`, {
      method: "GET",
      signal: AbortSignal.timeout(HEALTH_TIMEOUT_MS),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function BackendBootstrapOverlay() {
  // null = undetermined (first check pending); true = backend up; false = down.
  const [ready, setReady] = useState<boolean | null>(null);
  const [message, setMessage] = useState("正在启动后端…");
  const [percent, setPercent] = useState<number | undefined>(undefined);

  useEffect(() => {
    const packaged = isPackagedShell();
    if (!packaged) return;

    let active = true;

    const check = async () => {
      const ok = await backendReady();
      if (!active) return;
      setReady(ok);
    };

    // Refine the message from the main process as it progresses through
    // venv creation → core dep install → optional dep install.
    const off = window.octopus?.on(
      "backend:bootstrap-progress",
      (payload: unknown) => {
        const p = payload as BootstrapProgress;
        if (p?.message) setMessage(p.message);
        if (p?.stage === "deps") setPercent(40);
        else if (p?.stage === "optional") setPercent(75);
      },
    );

    // Immediate check (avoids a flash when the backend is already up), then poll.
    void check();
    const timer = setInterval(check, HEALTH_POLL_MS);

    return () => {
      active = false;
      off?.();
      clearInterval(timer);
    };
  }, []);

  const visible = isPackagedShell() && ready === false;
  if (!visible) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/90 backdrop-blur-sm">
      <Card className="w-[min(90vw,420px)] border-none p-6">
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="size-8 animate-pulse rounded-full bg-primary/60" />
          <div className="space-y-1">
            <p className="text-sm font-medium text-foreground">{message}</p>
            <p className="text-xs text-muted-foreground">
              首次启动需安装后端依赖，请稍候
            </p>
          </div>
          {percent !== undefined && (
            <Progress value={percent} className="w-full" />
          )}
        </div>
      </Card>
    </div>
  );
}