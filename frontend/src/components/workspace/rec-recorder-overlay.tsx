/**
 * Floating REC recorder overlay (P1 of the screen-recorder feature).
 *
 * Replaces the old window.confirm() start/stop flow with a proper floating
 * recorder: name the task -> 3·2·1 countdown -> a live recording pill (elapsed
 * timer + step counter) -> stop, which forges a reusable skill from the recorded
 * trajectory (existing teach-repeat / SkillForge backend — no backend change in
 * this phase). The richer replay-timeline + skill-card review is a later phase;
 * here the done state shows the forge result and points at the skill library.
 *
 * Copy is now driven by the teachRepeat i18n namespace.
 */

import {
  CircleDotIcon,
  Loader2Icon,
  SparklesIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import {
  getRecordingStatus,
  startRecording,
  stopRecording,
} from "@/core/teach-repeat/api";
import type { StopRecordingResponse } from "@/core/teach-repeat/types";
import { useI18n } from "@/core/i18n/hooks";
import { swallow } from "@/core/utils/log";
import { cn } from "@/lib/utils";

type Phase = "idle" | "countdown" | "recording" | "stopping" | "done";

const COUNTDOWN_FROM = 3;
const COUNTDOWN_STEP_MS = 800;

export interface RecRecorderOverlayProps {
  open: boolean;
  threadId: string;
  defaultName: string;
  /** Jump straight to the recording pill when opened mid-recording. */
  initiallyRecording?: boolean;
  onClose: () => void;
  /** Fires when recording starts (true) / stops (false) so the REC chip can
   * reflect state. */
  onRecordingChange?: (recording: boolean) => void;
}

function formatElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function RecRecorderOverlay({
  open,
  threadId,
  defaultName,
  initiallyRecording = false,
  onClose,
  onRecordingChange,
}: RecRecorderOverlayProps) {
  const { t } = useI18n();
  const [phase, setPhase] = useState<Phase>("idle");
  const [name, setName] = useState(defaultName);
  const [countdown, setCountdown] = useState(COUNTDOWN_FROM);
  const [elapsed, setElapsed] = useState(0);
  const [stepCount, setStepCount] = useState(0);
  const [result, setResult] = useState<StopRecordingResponse | null>(null);
  const recStartRef = useRef<number | null>(null);
  const startingRef = useRef(false);
  const canRecord = !!threadId && threadId !== "new";

  // Sync phase to open/initiallyRecording when the overlay is (re)opened.
  useEffect(() => {
    if (!open) return;
    setPhase(initiallyRecording ? "recording" : "idle");
    setName(defaultName);
    setResult(null);
    setCountdown(COUNTDOWN_FROM);
    setElapsed(0);
    if (initiallyRecording) recStartRef.current = Date.now();
  }, [open, initiallyRecording, defaultName]);

  const beginRecording = useCallback(async () => {
    if (startingRef.current) return;
    startingRef.current = true;
    try {
      await startRecording({
        thread_id: threadId,
        name: name.trim() || t.teachRepeat.defaultName,
        description: t.teachRepeat.defaultDescription,
      });
      recStartRef.current = Date.now();
      setElapsed(0);
      setStepCount(0);
      setPhase("recording");
      onRecordingChange?.(true);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.teachRepeat.startFailed);
      setPhase("idle");
    } finally {
      startingRef.current = false;
    }
  }, [threadId, name, onRecordingChange]);

  // Countdown driver.
  useEffect(() => {
    if (phase !== "countdown") return;
    if (countdown <= 0) {
      void beginRecording();
      return;
    }
    const t = window.setTimeout(
      () => setCountdown((c) => c - 1),
      COUNTDOWN_STEP_MS,
    );
    return () => window.clearTimeout(t);
  }, [phase, countdown, beginRecording]);

  // Elapsed timer while recording.
  useEffect(() => {
    if (phase !== "recording") return;
    const t = window.setInterval(() => {
      setElapsed(Date.now() - (recStartRef.current ?? Date.now()));
    }, 500);
    return () => window.clearInterval(t);
  }, [phase]);

  // Poll live step count while recording.
  useEffect(() => {
    if (phase !== "recording" || !canRecord) return;
    const poll = async () => {
      try {
        const s = await getRecordingStatus(threadId);
        setStepCount(s.step_count);
      } catch (error) {
        swallow(error, "rec-overlay-status");
      }
    };
    void poll();
    const t = window.setInterval(() => void poll(), 3000);
    return () => window.clearInterval(t);
  }, [phase, threadId, canRecord]);

  const handleStop = useCallback(async () => {
    setPhase("stopping");
    try {
      const res = await stopRecording({ thread_id: threadId, use_llm: true });
      setResult(res);
      setPhase("done");
      onRecordingChange?.(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t.teachRepeat.stopFailed);
      setPhase("recording");
    }
  }, [threadId, onRecordingChange]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-label={t.teachRepeat.recorderTitle}
      className="fixed bottom-5 right-5 z-[120] w-[260px] rounded-2xl border border-border/60 bg-background/95 p-4 shadow-2xl ring-1 ring-border/30 backdrop-blur"
    >
      <div className="mb-2 flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
          <CircleDotIcon
            className={cn(
              "size-3.5",
              phase === "recording" && "animate-pulse text-red-500",
            )}
          />
          {t.teachRepeat.recorderTitle}
        </span>
        {(phase === "idle" || phase === "done") && (
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground transition-colors hover:text-foreground"
            aria-label={t.common.close}
          >
            <XIcon className="size-4" />
          </button>
        )}
      </div>

      {phase === "idle" && (
        <div className="space-y-3">
          <div>
            <label className="mb-1 block text-[11px] text-muted-foreground">
              {t.teachRepeat.taskLabel}
            </label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t.teachRepeat.taskPlaceholder}
              className="w-full rounded-lg border border-border bg-transparent px-2.5 py-1.5 text-xs text-foreground outline-none focus:border-border-strong"
            />
          </div>
          <button
            type="button"
            disabled={!canRecord}
            onClick={() => {
              setCountdown(COUNTDOWN_FROM);
              setPhase("countdown");
            }}
            className={cn(
              "flex w-full items-center justify-center gap-1.5 rounded-lg px-3 py-2 text-xs font-medium transition-colors",
              "bg-red-500/12 text-red-600 hover:bg-red-500/18 dark:text-red-400",
              !canRecord && "opacity-50",
            )}
          >
            <CircleDotIcon className="size-3.5" />
            {t.teachRepeat.startRecording}
          </button>
          <p className="text-[10px] leading-tight text-muted-foreground">
            {t.teachRepeat.recordingHint}
          </p>
        </div>
      )}

      {phase === "countdown" && (
        <div className="flex flex-col items-center justify-center gap-2 py-4">
          <div className="flex size-16 items-center justify-center rounded-full border-2 border-red-500/60 text-3xl font-semibold text-red-600 dark:text-red-400">
            {countdown > 0 ? countdown : "·"}
          </div>
          <span className="text-[11px] text-muted-foreground">{t.teachRepeat.countdownReady}</span>
        </div>
      )}

      {phase === "recording" && (
        <div className="space-y-3">
          <div className="flex items-center gap-2.5 rounded-xl border border-red-500/30 bg-red-500/5 px-3 py-2">
            <span className="size-2.5 animate-pulse rounded-full bg-red-500" />
            <span className="font-mono text-sm font-semibold text-foreground">
              {formatElapsed(elapsed)}
            </span>
            <span className="text-[11px] text-muted-foreground">
              {t.teachRepeat.elapsedSteps(stepCount)}
            </span>
          </div>
          <button
            type="button"
            onClick={() => void handleStop()}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-red-500/12 px-3 py-2 text-xs font-medium text-red-600 transition-colors hover:bg-red-500/18 dark:text-red-400"
          >
            <SquareIcon className="size-3.5" />
            {t.teachRepeat.stopAndExtract}
          </button>
        </div>
      )}

      {phase === "stopping" && (
        <div className="flex flex-col items-center justify-center gap-2 py-5">
          <Loader2Icon className="size-5 animate-spin text-muted-foreground" />
          <span className="text-[11px] text-muted-foreground">
            {t.teachRepeat.analyzing}
          </span>
        </div>
      )}

      {phase === "done" && (
        <div className="space-y-3">
          <DoneSummary result={result} />
          <button
            type="button"
            onClick={onClose}
            className="w-full rounded-lg border border-border-strong bg-transparent px-3 py-2 text-xs font-medium text-foreground transition-colors hover:bg-muted"
          >
            {t.teachRepeat.done}
          </button>
        </div>
      )}
    </div>
  );
}

function DoneSummary({ result }: { result: StopRecordingResponse | null }) {
  const { t } = useI18n();
  const forged = result?.forged ?? [];
  const status = result?.status;

  if (status === "promoted" && forged.length) {
    return (
      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3">
        <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
          <SparklesIcon className="size-3.5" />
          {t.teachRepeat.learnedSkill}
        </div>
        <div className="text-[11px] text-foreground">{forged.join("、")}</div>
        <p className="mt-1.5 text-[10px] text-muted-foreground">
          {t.teachRepeat.skillLibraryHint}
        </p>
      </div>
    );
  }
  if (status === "quarantined") {
    return (
      <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-3 text-[11px] text-amber-700 dark:text-amber-300">
        {t.teachRepeat.quarantined}
      </div>
    );
  }
  if (status === "no_successful_trajectory") {
    return (
      <div className="rounded-xl border border-border bg-muted/40 p-3 text-[11px] text-muted-foreground">
        {t.teachRepeat.noTrajectory}
      </div>
    );
  }
  return (
    <div className="rounded-xl border border-border bg-muted/40 p-3 text-[11px] text-muted-foreground">
      {t.teachRepeat.recordingComplete(result?.name)}
    </div>
  );
}
