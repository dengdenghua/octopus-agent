import {
  type MouseEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  ActivityIcon,
  CheckCircle2Icon,
  ClockIcon,
  EyeIcon,
  ListChecksIcon,
  KeyboardIcon,
  MonitorCheckIcon,
  ScanSearchIcon,
  MousePointerClickIcon,
  PlayIcon,
  RefreshCwIcon,
  ShieldAlertIcon,
  ShieldCheckIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import {
  askVisionModelForComputerActions,
  captureComputerScreen,
  executeComputerAction,
  getComputerStatus,
  groundComputerActions,
  planComputerActions,
  previewComputerAction,
  releaseComputerLease,
  type ComputerActionPlan,
  type ComputerAction,
  type ComputerExecuteResult,
  type ComputerLease,
  type ComputerLeaseOwner,
  type ComputerMatchedControl,
  type ComputerPreview,
  type ComputerScreenshot,
  type ComputerStatus,
} from "@/core/computer/api";
import { swallow } from "@/core/utils/log";
import { loadModels } from "@/core/models/api";
import type { Model } from "@/core/models/types";
import { cn } from "@/lib/utils";

type ActionKind = "click" | "move" | "type" | "key" | "wait";
type LogItem = {
  id: string;
  title: string;
  detail: string;
  tone: "ok" | "warn" | "error";
};
type ScreenPoint = { x: number; y: number };
type VisualTarget = ScreenPoint & {
  label: string;
  tone: "preview" | "candidate" | "selected";
};
type ScreenshotImageBox = {
  left: number;
  top: number;
  width: number;
  height: number;
  naturalWidth: number;
  naturalHeight: number;
};

export default function ComputerAutomationPage() {
  const [status, setStatus] = useState<ComputerStatus | null>(null);
  const [screenshot, setScreenshot] = useState<ComputerScreenshot | null>(null);
  const [actionKind, setActionKind] = useState<ActionKind>("click");
  const [x, setX] = useState("400");
  const [y, setY] = useState("300");
  const [text, setText] = useState("");
  const [keys, setKeys] = useState("ctrl+l");
  const [waitMs, setWaitMs] = useState("500");
  const [goal, setGoal] = useState("");
  const [visionModelId, setVisionModelId] = useState("");
  const [models, setModels] = useState<Model[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [visionOutput, setVisionOutput] = useState("");
  const [plan, setPlan] = useState<ComputerActionPlan | null>(null);
  const [preview, setPreview] = useState<ComputerPreview | null>(null);
  const [previewExpiresAt, setPreviewExpiresAt] = useState<number | null>(null);
  const [selectedPoint, setSelectedPoint] = useState<{
    x: number;
    y: number;
  } | null>(null);
  const [highlightedAction, setHighlightedAction] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [screenshotImageBox, setScreenshotImageBox] =
    useState<ScreenshotImageBox | null>(null);
  const [leaseOwner, setLeaseOwner] = useState<ComputerLeaseOwner | null>(null);
  const [logs, setLogs] = useState<LogItem[]>([]);
  const [busy, setBusy] = useState<
    | "status"
    | "capture"
    | "ground"
    | "vision"
    | "plan"
    | "preview"
    | "execute"
    | "release"
    | null
  >(null);
  const screenshotFrameRef = useRef<HTMLDivElement | null>(null);
  const screenshotImageRef = useRef<HTMLImageElement | null>(null);

  const addLog = useCallback((item: Omit<LogItem, "id">) => {
    setLogs((prev) =>
      [{ ...item, id: crypto.randomUUID() }, ...prev].slice(0, 12),
    );
  }, []);

  useEffect(() => {
    const key = "octopus:computer-lease-owner";
    let ownerId = window.localStorage.getItem(key);
    if (!ownerId) {
      ownerId = crypto.randomUUID();
      window.localStorage.setItem(key, ownerId);
    }
    setLeaseOwner({
      owner_id: ownerId,
      owner_label: "本地电脑自动化页",
    });
  }, []);

  // ── Preview lifecycle ────────────────────────────────────────
  // The backend issues a token with a 90 s TTL (_PENDING_TTL_SECONDS
  // in computer_router.py). We mirror the deadline locally so the UI
  // can show a countdown chip and auto-clear once the server would
  // 404 anyway. ``apiSeconds`` is the value the backend returns in
  // ``expires_in_seconds`` — kept as the source of truth so a future
  // tweak on the server (eg. a per-action TTL) flows through here
  // without a frontend change.
  const applyPreview = (next: ComputerPreview) => {
    setPreview(next);
    const ttl = Math.max(1, Number(next.expires_in_seconds || 90));
    setPreviewExpiresAt(Date.now() + ttl * 1000);
  };

  const clearPreview = useCallback(() => {
    setPreview(null);
    setPreviewExpiresAt(null);
  }, []);

  // Tick state for the preview-token countdown chip. Re-rendered
  // every second while a preview is queued; null otherwise so we
  // don't burn a timer on the idle case.
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    if (previewExpiresAt === null) return;
    setNow(Date.now());
    const handle = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(handle);
  }, [previewExpiresAt]);

  const previewSecondsLeft =
    previewExpiresAt === null
      ? null
      : Math.max(0, Math.ceil((previewExpiresAt - now) / 1000));
  const previewExpired = previewExpiresAt !== null && previewSecondsLeft === 0;
  const deviceState = getDeviceState(status);
  const activeAction = getActiveAction({
    busy,
    preview,
    previewSecondsLeft,
    plan,
    screenshot,
  });
  const cursorPoint = getCursorPoint(status);
  const visualTarget = getVisualTarget({
    highlightedAction,
    plan,
    preview,
    selectedPoint,
  });
  const leaseState = getLeaseState(status?.lease, leaseOwner);
  const leaseBlocked = leaseState.tone === "blocked";
  const computerUnavailable =
    !status || !status.ok || !status.pyautogui_available;
  const computerActionDisabled = busy !== null || computerUnavailable;

  const mergeLease = useCallback((lease?: ComputerLease) => {
    if (!lease) return;
    setStatus((current) => (current ? { ...current, lease } : current));
  }, []);

  // Auto-clear once the server-side token would be 404. We log it so
  // the operator knows why the confirm card vanished — silently
  // dropping it would feel like a bug.
  useEffect(() => {
    if (!previewExpired) return;
    addLog({
      title: "确认队列已过期",
      detail: "token 已在服务端清除，请重新预演动作",
      tone: "warn",
    });
    clearPreview();
  }, [addLog, clearPreview, previewExpired]);

  const openModelSettings = () => {
    window.dispatchEvent(
      new CustomEvent("octopus:open-settings", {
        detail: { tab: "models" },
      }),
    );
  };

  const refreshStatus = useCallback(async () => {
    setBusy("status");
    try {
      const data = await getComputerStatus();
      setStatus(data);
      addLog({
        title: data.ok ? "本机助手可用" : "本机助手不可用",
        detail: data.ok
          ? `屏幕 ${data.screen.width}x${data.screen.height}`
          : data.screen.error || "",
        tone: data.ok ? "ok" : "error",
      });
    } catch (error) {
      swallow(error);
      addLog({ title: "状态读取失败", detail: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  }, [addLog]);

  const measureScreenshotImage = useCallback(() => {
    const frame = screenshotFrameRef.current;
    const image = screenshotImageRef.current;
    if (!frame || !image || !image.naturalWidth || !image.naturalHeight) return;

    const frameRect = frame.getBoundingClientRect();
    const imageRect = image.getBoundingClientRect();
    setScreenshotImageBox({
      left: imageRect.left - frameRect.left,
      top: imageRect.top - frameRect.top,
      width: imageRect.width,
      height: imageRect.height,
      naturalWidth: image.naturalWidth,
      naturalHeight: image.naturalHeight,
    });
  }, []);

  useEffect(() => {
    if (!screenshot?.data_url) {
      setScreenshotImageBox(null);
      return;
    }

    const frame = screenshotFrameRef.current;
    const image = screenshotImageRef.current;
    if (!frame || !image) return;

    const resizeObserver = new ResizeObserver(measureScreenshotImage);
    resizeObserver.observe(frame);
    resizeObserver.observe(image);
    window.addEventListener("resize", measureScreenshotImage);
    const frameId = window.requestAnimationFrame(measureScreenshotImage);

    return () => {
      resizeObserver.disconnect();
      window.removeEventListener("resize", measureScreenshotImage);
      window.cancelAnimationFrame(frameId);
    };
  }, [measureScreenshotImage, screenshot?.data_url]);

  const capture = async () => {
    setBusy("capture");
    try {
      const data = await captureComputerScreen();
      setScreenshot(data);
      setHighlightedAction(null);
      addLog({
        title: data.ok ? "已观察当前屏幕" : "截图失败",
        detail: data.ok ? `${data.size_bytes || 0} bytes` : data.error || "",
        tone: data.ok ? "ok" : "error",
      });
    } catch (error) {
      swallow(error);
      addLog({ title: "截图请求失败", detail: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  const action = useMemo<ComputerAction>(() => {
    if (actionKind === "click" || actionKind === "move") {
      return {
        action: actionKind,
        x: Number(x),
        y: Number(y),
        button: "left",
        clicks: 1,
      };
    }
    if (actionKind === "type") {
      return { action: "type", text, interval: 0.01 };
    }
    if (actionKind === "key") {
      return { action: "key", keys };
    }
    return { action: "wait", ms: Number(waitMs) };
  }, [actionKind, keys, text, waitMs, x, y]);

  const visionModels = useMemo(
    () => models.filter((model) => model.supports_vision === true),
    [models],
  );

  const selectedVisionModel = useMemo(
    () => models.find((model) => model.id === visionModelId),
    [models, visionModelId],
  );

  const previewAction = async () => {
    setBusy("preview");
    clearPreview();
    try {
      const data = await previewComputerAction(action, { leaseOwner });
      mergeLease(data.lease);
      applyPreview(data);
      addLog({
        title: "动作已进入确认队列",
        detail: `${data.action.action} · ${data.risk.level}`,
        tone: data.risk.level === "high" ? "warn" : "ok",
      });
    } catch (error) {
      swallow(error);
      addLog({ title: "动作预演失败", detail: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  const previewSelectedPoint = async () => {
    if (!selectedPoint) return;
    setBusy("preview");
    clearPreview();
    setHighlightedAction(null);
    try {
      const data = await previewComputerAction(
        {
          action: "click",
          x: selectedPoint.x,
          y: selectedPoint.y,
          button: "left",
          clicks: 1,
        },
        { leaseOwner },
      );
      mergeLease(data.lease);
      applyPreview(data);
      addLog({
        title: "截图坐标已进入确认队列",
        detail: `${selectedPoint.x}, ${selectedPoint.y} · ${data.risk.level}`,
        tone: data.risk.level === "high" ? "warn" : "ok",
      });
    } catch (error) {
      swallow(error);
      addLog({
        title: "坐标点击预演失败",
        detail: String(error),
        tone: "error",
      });
    } finally {
      setBusy(null);
    }
  };

  const planNextActions = async () => {
    setBusy("plan");
    setPlan(null);
    setHighlightedAction(null);
    clearPreview();
    try {
      const data = await planComputerActions(goal, {
        capture: true,
        leaseOwner,
      });
      setPlan(data);
      mergeLease(data.lease);
      if (data.screenshot) setScreenshot(data.screenshot);
      addLog({
        title: data.suggestions.length ? "已生成下一步计划" : "没有可用计划",
        detail: data.suggestions.length
          ? `${data.suggestions.length} 个候选动作等待确认`
          : "请补充更明确的任务目标",
        tone: data.suggestions.length ? "ok" : "warn",
      });
    } catch (error) {
      swallow(error);
      addLog({ title: "计划生成失败", detail: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  const acceptSuggestion = (
    suggestion: ComputerActionPlan["suggestions"][number],
  ) => {
    setHighlightedAction(null);
    applyPreview({
      ok: true,
      token: suggestion.token,
      action: suggestion.action,
      risk: suggestion.risk,
      expires_in_seconds: suggestion.expires_in_seconds,
    });
    addLog({
      title: "候选动作已放入确认队列",
      detail: `${suggestion.action.action} · ${suggestion.risk.level}`,
      tone: suggestion.risk.level === "high" ? "warn" : "ok",
    });
  };

  const groundVisionOutput = async () => {
    setBusy("ground");
    setPlan(null);
    setHighlightedAction(null);
    clearPreview();
    try {
      const data = await groundComputerActions(goal, visionOutput, {
        capture: true,
        leaseOwner,
      });
      setPlan(data);
      mergeLease(data.lease);
      if (data.screenshot) setScreenshot(data.screenshot);
      addLog({
        title: data.suggestions.length ? "视觉输出已校验" : "没有解析到动作",
        detail: data.suggestions.length
          ? `${data.suggestions.length} 个动作等待确认`
          : "请粘贴标准 JSON 动作",
        tone: data.suggestions.length ? "ok" : "warn",
      });
    } catch (error) {
      swallow(error);
      addLog({
        title: "视觉输出解析失败",
        detail: String(error),
        tone: "error",
      });
    } finally {
      setBusy(null);
    }
  };

  const askVisionModel = async () => {
    setBusy("vision");
    setPlan(null);
    setHighlightedAction(null);
    clearPreview();
    try {
      const data = await askVisionModelForComputerActions(goal, visionModelId, {
        leaseOwner,
      });
      setPlan(data);
      mergeLease(data.lease);
      if (data.screenshot) setScreenshot(data.screenshot);
      addLog({
        title: data.ok ? "视觉模型已返回动作" : "视觉模型未就绪",
        detail: data.ok
          ? `${data.suggestions.length} 个动作等待确认`
          : (data as unknown as { error?: string }).error || "请配置视觉模型",
        tone: data.ok ? "ok" : "warn",
      });
    } catch (error) {
      swallow(error);
      addLog({
        title: "视觉模型调用失败",
        detail: String(error),
        tone: "error",
      });
    } finally {
      setBusy(null);
    }
  };

  const selectScreenshotPoint = (event: MouseEvent<HTMLImageElement>) => {
    const img = screenshotImageRef.current;
    if (!img) return;
    const rect = img.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const realX = Math.round(
      ((event.clientX - rect.left) / rect.width) * img.naturalWidth,
    );
    const realY = Math.round(
      ((event.clientY - rect.top) / rect.height) * img.naturalHeight,
    );
    const clampedX = Math.max(0, Math.min(realX, img.naturalWidth - 1));
    const clampedY = Math.max(0, Math.min(realY, img.naturalHeight - 1));
    setScreenshotImageBox((current) =>
      current
        ? {
            ...current,
            naturalWidth: img.naturalWidth,
            naturalHeight: img.naturalHeight,
          }
        : current,
    );
    setSelectedPoint({ x: clampedX, y: clampedY });
    setActionKind("click");
    setX(String(clampedX));
    setY(String(clampedY));
    addLog({
      title: "已从截图选中坐标",
      detail: `${clampedX}, ${clampedY}`,
      tone: "ok",
    });
  };

  const executePreview = async () => {
    if (!preview) return;
    setBusy("execute");
    try {
      const data = await executeComputerAction(preview.token, { leaseOwner });
      mergeLease(data.lease);
      clearPreview();
      addLog({
        title: data.ok ? "动作已执行" : "动作执行失败",
        detail: summarizeResult(data),
        tone: data.ok ? "ok" : "error",
      });
    } catch (error) {
      swallow(error);
      addLog({ title: "执行请求失败", detail: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  const releaseLease = async () => {
    if (!leaseOwner) return;
    setBusy("release");
    try {
      const data = await releaseComputerLease(leaseOwner);
      mergeLease(data.lease);
      addLog({
        title: "已释放电脑接管",
        detail: "其他项目现在可以接管这台电脑。",
        tone: "ok",
      });
    } catch (error) {
      swallow(error);
      addLog({ title: "释放接管失败", detail: String(error), tone: "error" });
    } finally {
      setBusy(null);
    }
  };

  useEffect(() => {
    void refreshStatus();
    void loadModels()
      .then((data) => {
        setModels(data);
        const firstVisionModel = data.find(
          (model) => model.supports_vision === true,
        );
        if (firstVisionModel) {
          setVisionModelId((current) => current || firstVisionModel.id);
        }
      })
      .catch((error) => setModelsError(String(error)));
  }, [refreshStatus]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex size-full max-w-7xl flex-col gap-4 py-2">
          <section className="workspace-panel flex flex-col gap-4 rounded-[1.75rem] p-5">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl bg-emerald-600 text-white shadow-sm">
                  <MonitorCheckIcon className="size-5" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold tracking-tight">
                    本机助手
                  </h1>
                  <p className="text-sm text-muted-foreground">
                    让 Agent 看见并操作这台电脑。每一步先预演，再由你确认。
                  </p>
                </div>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={refreshStatus}
                  disabled={busy !== null}
                >
                  <RefreshCwIcon className="size-4" />
                  刷新状态
                </Button>
                <Button onClick={capture} disabled={computerActionDisabled}>
                  <EyeIcon className="size-4" />
                  观察屏幕
                </Button>
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-[1.1fr_1.2fr_1fr]">
              <DeviceStatePanel state={deviceState} />
              <PermissionGuardPanel
                hasScreenshot={Boolean(screenshot?.data_url)}
                hasPreview={Boolean(preview)}
                leaseState={leaseState}
                onReleaseLease={releaseLease}
                releaseDisabled={busy !== null}
                previewSecondsLeft={previewSecondsLeft}
              />
              <CurrentActionPanel action={activeAction} />
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-5">
              <StatusTile
                label="确认方式"
                value={status?.mode ? "先预演再确认" : "加载中"}
              />
              <StatusTile
                label="屏幕"
                value={
                  status?.screen.width
                    ? `${status.screen.width} × ${status.screen.height}`
                    : status?.screen.error || "-"
                }
              />
              <StatusTile
                label="鼠标位置"
                value={
                  status?.screen.cursor_x != null
                    ? `${status.screen.cursor_x}, ${status.screen.cursor_y}`
                    : "-"
                }
              />
              <StatusTile
                label="电脑控制"
                value={status?.pyautogui_available ? "已就绪" : "未就绪"}
              />
              <StatusTile label="接管租约" value={leaseState.label} />
            </div>

            {computerUnavailable && status && (
              <div className="rounded-2xl border border-amber-300/70 bg-amber-50 px-4 py-3 text-sm leading-6 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-100">
                <div className="flex items-start gap-2">
                  <ShieldAlertIcon className="mt-0.5 size-4 shrink-0" />
                  <div>
                    <div className="font-medium">本机控制依赖未就绪</div>
                    <p className="mt-1">
                      {status.screen.error ||
                        "后端已启动，但 pyautogui 不可用，暂时不能截图、预演或执行鼠标键盘动作。"}
                    </p>
                    <p className="mt-1 font-mono text-xs">
                      python -m pip install pyautogui
                    </p>
                  </div>
                </div>
              </div>
            )}
          </section>

          <div className="grid min-h-0 flex-1 gap-4 md:grid-cols-[1.35fr_0.95fr]">
            <section className="workspace-panel flex min-h-0 flex-col overflow-hidden rounded-[1.75rem] p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">屏幕观察</h2>
                {screenshot?.created_at && (
                  <span className="text-xs text-muted-foreground">
                    {new Date(
                      screenshot.created_at * 1000,
                    ).toLocaleTimeString()}
                  </span>
                )}
              </div>
              <div
                ref={screenshotFrameRef}
                className="relative flex min-h-0 flex-1 items-center justify-center overflow-hidden rounded-2xl border border-border bg-muted/30"
              >
                {screenshot?.data_url ? (
                  <>
                    <p id="screenshot-help" className="sr-only">
                      点击截图选择坐标；按 Enter 可选择屏幕中心点。
                    </p>
                    <img
                      ref={screenshotImageRef}
                      src={screenshot.data_url}
                      alt="当前屏幕截图"
                      aria-describedby="screenshot-help"
                      role="button"
                      tabIndex={0}
                      className="max-h-full max-w-full cursor-crosshair object-contain focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
                      onLoad={measureScreenshotImage}
                      onClick={selectScreenshotPoint}
                      onKeyDown={(e) => {
                        if (e.key !== "Enter" && e.key !== " ") return;
                        e.preventDefault();
                        const img = screenshotImageRef.current;
                        if (!img || !img.naturalWidth || !img.naturalHeight)
                          return;
                        const cx = Math.floor(img.naturalWidth / 2);
                        const cy = Math.floor(img.naturalHeight / 2);
                        setSelectedPoint({ x: cx, y: cy });
                        setActionKind("click");
                        setX(String(cx));
                        setY(String(cy));
                        addLog({
                          title: "已从截图选中坐标",
                          detail: `${cx}, ${cy}`,
                          tone: "ok",
                        });
                      }}
                    />
                    <ScreenshotActionOverlay
                      cursor={cursorPoint}
                      imageBox={screenshotImageBox}
                      target={visualTarget}
                    />
                    {visualTarget && (
                      <div className="pointer-events-none absolute left-3 top-3 rounded-full border border-border bg-background/90 px-3 py-1 text-xs font-medium shadow-sm">
                        {visualTarget.label} · {Math.round(visualTarget.x)},{" "}
                        {Math.round(visualTarget.y)}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="flex flex-col items-center gap-2 text-sm text-muted-foreground">
                    <EyeIcon className="size-7" />
                    点击“观察屏幕”获取当前桌面截图
                  </div>
                )}
              </div>
            </section>

            <aside className="flex min-h-0 flex-col gap-4">
              <section className="workspace-panel rounded-[1.75rem] p-4">
                <div className="mb-3 flex items-center gap-2">
                  <ListChecksIcon className="size-4 text-primary" />
                  <h2 className="text-sm font-semibold">任务计划</h2>
                </div>
                <div className="flex flex-col gap-3">
                  <Textarea
                    value={goal}
                    onChange={(e) => setGoal(e.target.value)}
                    placeholder="例如：打开 Edge 并访问 https://gemini.google.com"
                    className="min-h-20"
                  />
                  <Button
                    onClick={planNextActions}
                    disabled={computerActionDisabled}
                  >
                    <ListChecksIcon className="size-4" />
                    观察并生成下一步
                  </Button>
                  {plan?.suggestions.length ? (
                    <div className="flex max-h-56 flex-col gap-2 overflow-y-auto pr-1">
                      {plan.suggestions.map((item) => (
                        <div
                          key={item.id}
                          className={cn(
                            "rounded-2xl border border-border bg-background/70 p-3 transition-colors",
                            highlightedAction === item.action &&
                              "border-emerald-300 bg-emerald-50/60 dark:border-emerald-900/70 dark:bg-emerald-950/20",
                          )}
                          onMouseEnter={() => setHighlightedAction(item.action)}
                          onMouseLeave={() => setHighlightedAction(null)}
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className="text-sm font-semibold">
                                {item.title}
                              </div>
                              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                                {item.rationale}
                              </p>
                            </div>
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => acceptSuggestion(item)}
                            >
                              加入确认
                            </Button>
                          </div>
                          <pre className="mt-2 max-h-24 overflow-auto rounded-xl bg-black/5 p-2 text-xs dark:bg-white/10">
                            {JSON.stringify(item.action, null, 2)}
                          </pre>
                          <MatchedControlSummary action={item.action} />
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {selectedPoint && (
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <Button
                        variant="outline"
                        onClick={() => {
                          setActionKind("click");
                          setX(String(selectedPoint.x));
                          setY(String(selectedPoint.y));
                        }}
                      >
                        <MousePointerClickIcon className="size-4" />
                        填入坐标
                      </Button>
                      <Button
                        onClick={previewSelectedPoint}
                        disabled={computerActionDisabled}
                      >
                        <ShieldAlertIcon className="size-4" />
                        加入确认
                      </Button>
                    </div>
                  )}
                </div>
              </section>

              <section className="workspace-panel rounded-[1.75rem] p-4">
                <div className="mb-3 flex items-center gap-2">
                  <ScanSearchIcon className="size-4 text-primary" />
                  <h2 className="text-sm font-semibold">视觉输出</h2>
                </div>
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col gap-2 sm:grid sm:grid-cols-[1fr_auto]">
                    {visionModels.length > 0 ? (
                      <Select
                        value={visionModelId}
                        onValueChange={setVisionModelId}
                      >
                        <SelectTrigger className="w-full">
                          <SelectValue placeholder="选择视觉模型" />
                        </SelectTrigger>
                        <SelectContent>
                          {visionModels.map((model) => (
                            <SelectItem key={model.id} value={model.id}>
                              {model.display_name || model.name || model.id}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    ) : (
                      <Input
                        value={visionModelId}
                        onChange={(e) => setVisionModelId(e.target.value)}
                        placeholder="视觉模型 ID，例如 glm-vision"
                      />
                    )}
                    <Button
                      onClick={askVisionModel}
                      disabled={
                        computerActionDisabled ||
                        !goal.trim() ||
                        !visionModelId.trim()
                      }
                    >
                      <ScanSearchIcon className="size-4" />
                      调用模型
                    </Button>
                  </div>
                  {visionModels.length > 0 ? (
                    <div className="flex items-center justify-between rounded-xl border border-border bg-background/70 px-3 py-2 text-xs text-muted-foreground">
                      <span>
                        当前：
                        {selectedVisionModel?.display_name ||
                          selectedVisionModel?.name ||
                          visionModelId}
                      </span>
                      <span>{visionModels.length} 个视觉模型</span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-100">
                      <span>
                        {modelsError
                          ? "模型列表读取失败，可手动输入模型 ID。"
                          : "暂无标记 supports_vision 的模型，可先在设置里给自定义模型开启视觉能力。"}
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={openModelSettings}
                      >
                        去模型设置
                      </Button>
                    </div>
                  )}
                  <p className="text-xs leading-5 text-muted-foreground">
                    调用模型会把当前屏幕截图发送到所选视觉模型；返回动作仍需确认后才执行。
                  </p>
                  <Textarea
                    value={visionOutput}
                    onChange={(e) => setVisionOutput(e.target.value)}
                    placeholder='{"action":"click","x":420,"y":320,"button":"left"}'
                    className="min-h-24 font-mono text-xs"
                  />
                  <Button
                    variant="outline"
                    onClick={groundVisionOutput}
                    disabled={computerActionDisabled || !visionOutput.trim()}
                  >
                    <ScanSearchIcon className="size-4" />
                    解析并加入候选
                  </Button>
                </div>
              </section>

              <section className="workspace-panel rounded-[1.75rem] p-4">
                <div className="mb-3 flex items-center gap-2">
                  <KeyboardIcon className="size-4 text-primary" />
                  <h2 className="text-sm font-semibold">动作预演</h2>
                </div>
                <div className="flex flex-col gap-3">
                  <Select
                    value={actionKind}
                    onValueChange={(value) =>
                      setActionKind(value as ActionKind)
                    }
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="click">点击坐标</SelectItem>
                      <SelectItem value="move">移动鼠标</SelectItem>
                      <SelectItem value="type">输入文字</SelectItem>
                      <SelectItem value="key">快捷键</SelectItem>
                      <SelectItem value="wait">等待</SelectItem>
                    </SelectContent>
                  </Select>

                  {(actionKind === "click" || actionKind === "move") && (
                    <div className="grid grid-cols-2 gap-2">
                      <Input
                        value={x}
                        onChange={(e) => setX(e.target.value)}
                        placeholder="x"
                      />
                      <Input
                        value={y}
                        onChange={(e) => setY(e.target.value)}
                        placeholder="y"
                      />
                    </div>
                  )}
                  {actionKind === "type" && (
                    <Textarea
                      value={text}
                      onChange={(e) => setText(e.target.value)}
                      placeholder="要输入到当前焦点的文字"
                      className="min-h-24"
                    />
                  )}
                  {actionKind === "key" && (
                    <Input
                      value={keys}
                      onChange={(e) => setKeys(e.target.value)}
                      placeholder="ctrl+l 或 enter"
                    />
                  )}
                  {actionKind === "wait" && (
                    <Input
                      value={waitMs}
                      onChange={(e) => setWaitMs(e.target.value)}
                      placeholder="毫秒"
                    />
                  )}

                  <Button
                    onClick={previewAction}
                    disabled={computerActionDisabled}
                  >
                    <ShieldAlertIcon className="size-4" />
                    生成确认
                  </Button>
                </div>
              </section>

              <section className="workspace-panel rounded-[1.75rem] p-4">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <h2 className="text-sm font-semibold">确认队列</h2>
                  {preview && previewSecondsLeft !== null ? (
                    <CountdownChip secondsLeft={previewSecondsLeft} />
                  ) : null}
                </div>
                {preview ? (
                  <div className="flex flex-col gap-3">
                    <div
                      className={cn(
                        "rounded-2xl border p-3 text-sm",
                        preview.risk.level === "high"
                          ? "border-amber-300 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100"
                          : "border-border bg-background",
                      )}
                    >
                      <div className="font-semibold">
                        风险：{preview.risk.level}
                      </div>
                      <p className="mt-1 leading-6">{preview.risk.reason}</p>
                      <pre className="mt-2 overflow-auto rounded-xl bg-black/5 p-2 text-xs dark:bg-white/10">
                        {JSON.stringify(preview.action, null, 2)}
                      </pre>
                      <MatchedControlSummary action={preview.action} />
                      {leaseBlocked ? (
                        <div className="mt-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-100">
                          {leaseState.detail}
                        </div>
                      ) : null}
                    </div>
                    <Button
                      onClick={executePreview}
                      disabled={
                        computerActionDisabled || previewExpired || leaseBlocked
                      }
                    >
                      <PlayIcon className="size-4" />
                      确认执行
                    </Button>
                  </div>
                ) : (
                  <p className="text-sm leading-6 text-muted-foreground">
                    这里会显示待确认的鼠标、键盘动作。确认前不会操作系统。
                  </p>
                )}
              </section>

              <section className="workspace-panel min-h-0 flex-1 rounded-[1.75rem] p-4">
                <h2 className="mb-3 text-sm font-semibold">操作记录</h2>
                <div className="flex max-h-72 flex-col gap-2 overflow-y-auto pr-1">
                  {logs.length === 0 ? (
                    <p className="text-sm text-muted-foreground">还没有记录</p>
                  ) : (
                    logs.map((item) => (
                      <div
                        key={item.id}
                        className="rounded-xl border border-border bg-background/70 p-3"
                      >
                        <div className="flex items-center gap-2 text-sm font-medium">
                          <CheckCircle2Icon
                            className={cn(
                              "size-4",
                              item.tone === "ok" && "text-emerald-500",
                              item.tone === "warn" && "text-amber-500",
                              item.tone === "error" && "text-destructive",
                            )}
                          />
                          {item.title}
                        </div>
                        {item.detail && (
                          <p className="mt-1 break-words text-xs leading-5 text-muted-foreground">
                            {item.detail}
                          </p>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </section>
            </aside>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function StatusTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-border bg-background/70 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold">{value}</div>
    </div>
  );
}

type DeviceState = {
  label: string;
  detail: string;
  tone: "ok" | "warn" | "error" | "loading";
};

type ActiveAction = {
  label: string;
  detail: string;
  tone: "idle" | "active" | "warn" | "ok";
};

type LeaseState = {
  label: string;
  detail: string;
  tone: "idle" | "own" | "blocked";
  canRelease: boolean;
};

function getLeaseState(
  lease: ComputerLease | null | undefined,
  owner: ComputerLeaseOwner | null,
): LeaseState {
  if (!lease?.held) {
    return {
      label: "空闲",
      detail: "当前没有项目接管真实鼠标键盘。",
      tone: "idle",
      canRelease: false,
    };
  }
  const ttl =
    typeof lease.ttl_seconds === "number" ? Math.max(0, lease.ttl_seconds) : 0;
  const ownerLabel = lease.owner_label || "其他项目";
  if (owner && lease.owner_id === owner.owner_id) {
    return {
      label: `本项目 · ${ttl}s`,
      detail: `本项目正在接管真实鼠标键盘，${ttl}s 内会阻止其他项目抢占。`,
      tone: "own",
      canRelease: true,
    };
  }
  return {
    label: `${ownerLabel} · ${ttl}s`,
    detail: `${ownerLabel} 正在接管真实鼠标键盘，${ttl}s 后自动释放。`,
    tone: "blocked",
    canRelease: false,
  };
}

function getDeviceState(status: ComputerStatus | null): DeviceState {
  if (!status) {
    return {
      label: "正在检查",
      detail: "正在确认这台电脑是否可以被 Agent 观察和操作。",
      tone: "loading",
    };
  }
  if (!status.ok) {
    return {
      label: "不可用",
      detail: status.screen.error || "当前环境还不能读取屏幕或执行电脑动作。",
      tone: "error",
    };
  }
  if (!status.pyautogui_available) {
    return {
      label: "需要补能力",
      detail: "后端已响应，但电脑控制能力还没有就绪。",
      tone: "warn",
    };
  }
  const screen = status.screen.width
    ? `${status.screen.width} × ${status.screen.height}`
    : "屏幕已连接";
  return {
    label: "已连接",
    detail: `可以观察当前屏幕，并在确认后执行动作。${screen}`,
    tone: "ok",
  };
}

function getActiveAction({
  busy,
  preview,
  previewSecondsLeft,
  plan,
  screenshot,
}: {
  busy: string | null;
  preview: ComputerPreview | null;
  previewSecondsLeft: number | null;
  plan: ComputerActionPlan | null;
  screenshot: ComputerScreenshot | null;
}): ActiveAction {
  if (preview) {
    return {
      label: "等待你确认",
      detail: `${formatActionLabel(preview.action)} · ${preview.risk.reason}${
        previewSecondsLeft !== null ? ` · ${previewSecondsLeft}s 后过期` : ""
      }`,
      tone: preview.risk.level === "high" ? "warn" : "active",
    };
  }
  if (busy) {
    const labelMap: Record<string, string> = {
      status: "检查连接",
      capture: "观察屏幕",
      ground: "解析动作",
      vision: "请求视觉模型",
      plan: "生成计划",
      preview: "生成确认",
      execute: "执行动作",
      release: "释放接管",
    };
    return {
      label: labelMap[busy] || "正在处理",
      detail: "当前动作完成前，新的电脑动作会先排队等待。",
      tone: "active",
    };
  }
  if (plan?.suggestions.length) {
    return {
      label: "有候选动作",
      detail: `${plan.suggestions.length} 个候选动作，选择后会进入确认队列。`,
      tone: "ok",
    };
  }
  if (screenshot?.data_url) {
    return {
      label: "已观察屏幕",
      detail: "可以点击截图选坐标，或让视觉模型生成下一步。",
      tone: "idle",
    };
  }
  return {
    label: "等待任务",
    detail: "先观察屏幕，或描述你希望 Agent 在电脑上完成什么。",
    tone: "idle",
  };
}

function formatActionLabel(action: Record<string, unknown>) {
  const kind = String(action.action || "动作");
  if (
    (kind === "click" || kind === "move") &&
    action.x != null &&
    action.y != null
  ) {
    const target = getControlIdentity(getMatchedControl(action));
    const coordinate = `${action.x}, ${action.y}`;
    return target
      ? `${kind === "click" ? "点击" : "移动"} ${target} · ${coordinate}`
      : `${kind === "click" ? "点击" : "移动"} ${coordinate}`;
  }
  if (kind === "type") return "输入文字";
  if (kind === "key")
    return `快捷键 ${Array.isArray(action.keys) ? action.keys.join("+") : action.keys || ""}`;
  if (kind === "wait") return `等待 ${action.ms || 0}ms`;
  return kind;
}

function ScreenshotActionOverlay({
  cursor,
  imageBox,
  target,
}: {
  cursor: ScreenPoint | null;
  imageBox: ScreenshotImageBox | null;
  target: VisualTarget | null;
}) {
  if (!imageBox || (!cursor && !target)) return null;

  const cursorPosition = cursor ? projectScreenPoint(cursor, imageBox) : null;
  const targetPosition = target ? projectScreenPoint(target, imageBox) : null;
  const shouldDrawPath =
    cursorPosition &&
    targetPosition &&
    Math.hypot(
      cursorPosition.left - targetPosition.left,
      cursorPosition.top - targetPosition.top,
    ) > 12;

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      {shouldDrawPath ? (
        <svg className="absolute inset-0 size-full" aria-hidden="true">
          <line
            x1={cursorPosition.left}
            y1={cursorPosition.top}
            x2={targetPosition.left}
            y2={targetPosition.top}
            stroke="rgb(16 185 129 / 0.85)"
            strokeDasharray="7 6"
            strokeLinecap="round"
            strokeWidth="2.5"
          />
        </svg>
      ) : null}
      {cursorPosition ? (
        <div
          className="absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: cursorPosition.left, top: cursorPosition.top }}
        >
          <span className="block size-2.5 rounded-full bg-foreground shadow-sm ring-2 ring-white dark:bg-white dark:ring-background" />
          <span className="absolute left-3 top-2 whitespace-nowrap rounded-md bg-background/90 px-1.5 py-0.5 text-[10px] font-medium text-foreground shadow-sm">
            当前鼠标
          </span>
        </div>
      ) : null}
      {target && targetPosition ? (
        <div
          className="absolute -translate-x-1/2 -translate-y-1/2"
          style={{ left: targetPosition.left, top: targetPosition.top }}
        >
          <span
            className={cn(
              "absolute -inset-4 rounded-full border-2 animate-ping",
              target.tone === "preview"
                ? "border-blue-400/80"
                : target.tone === "candidate"
                  ? "border-emerald-400/80"
                  : "border-amber-400/80",
            )}
          />
          <span
            className={cn(
              "relative grid size-8 place-items-center rounded-full text-white shadow-lg ring-2 ring-white/90",
              target.tone === "preview"
                ? "bg-blue-600"
                : target.tone === "candidate"
                  ? "bg-emerald-600"
                  : "bg-amber-500",
            )}
          >
            <MousePointerClickIcon className="size-4" />
          </span>
          <span className="absolute left-6 top-6 max-w-56 truncate whitespace-nowrap rounded-md border border-border bg-background/95 px-2 py-1 text-[11px] font-medium text-foreground shadow-sm">
            {target.label}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function getCursorPoint(status: ComputerStatus | null): ScreenPoint | null {
  if (
    typeof status?.screen.cursor_x !== "number" ||
    typeof status.screen.cursor_y !== "number"
  ) {
    return null;
  }
  return { x: status.screen.cursor_x, y: status.screen.cursor_y };
}

function getVisualTarget({
  highlightedAction,
  plan,
  preview,
  selectedPoint,
}: {
  highlightedAction: Record<string, unknown> | null;
  plan: ComputerActionPlan | null;
  preview: ComputerPreview | null;
  selectedPoint: ScreenPoint | null;
}): VisualTarget | null {
  if (preview) {
    return getActionVisualTarget(
      preview.action,
      formatActionLabel(preview.action),
      "preview",
    );
  }

  if (highlightedAction) {
    return getActionVisualTarget(
      highlightedAction,
      formatActionLabel(highlightedAction),
      "candidate",
    );
  }

  const firstPointSuggestion = plan?.suggestions.find((item) =>
    getActionPoint(item.action),
  );
  if (firstPointSuggestion) {
    return getActionVisualTarget(
      firstPointSuggestion.action,
      firstPointSuggestion.title,
      "candidate",
    );
  }

  if (selectedPoint) {
    return {
      ...selectedPoint,
      label: "手动选点",
      tone: "selected",
    };
  }

  return null;
}

function getActionVisualTarget(
  action: Record<string, unknown>,
  label: string,
  tone: VisualTarget["tone"],
): VisualTarget | null {
  const point = getActionPoint(action);
  if (!point) return null;
  return {
    ...point,
    label,
    tone,
  };
}

function getActionPoint(
  action: Record<string, unknown> | null | undefined,
): ScreenPoint | null {
  if (!action) return null;
  const kind = String(action.action || "");
  if (kind !== "click" && kind !== "move") return null;
  const x = toFiniteNumber(action.x);
  const y = toFiniteNumber(action.y);
  if (x === null || y === null) return null;
  return { x, y };
}

function projectScreenPoint(point: ScreenPoint, imageBox: ScreenshotImageBox) {
  const x = clamp(point.x, 0, Math.max(0, imageBox.naturalWidth - 1));
  const y = clamp(point.y, 0, Math.max(0, imageBox.naturalHeight - 1));
  return {
    left: imageBox.left + (x / imageBox.naturalWidth) * imageBox.width,
    top: imageBox.top + (y / imageBox.naturalHeight) * imageBox.height,
  };
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function toFiniteNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function MatchedControlSummary({
  action,
}: {
  action: Record<string, unknown>;
}) {
  const control = getMatchedControl(action);
  if (!control) return null;

  const identity = getControlIdentity(control) || "未命名控件";
  const typeText = [control.control_type, control.class_name]
    .filter(Boolean)
    .join(" · ");
  const centerText = formatPoint(control.center);
  const scoreText =
    typeof control.score === "number" && Number.isFinite(control.score)
      ? Math.round(control.score)
      : null;

  return (
    <div className="mt-2 rounded-xl border border-emerald-200 bg-emerald-50/70 p-2.5 text-xs leading-5 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-100">
      <div className="flex items-start gap-2">
        <ScanSearchIcon className="mt-0.5 size-3.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-semibold">
            <span className="break-words">UIA 命中：{identity}</span>
            {scoreText !== null ? (
              <span className="rounded-md border border-emerald-300/80 px-1.5 py-0.5 font-mono text-[11px] dark:border-emerald-700">
                {scoreText}
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-emerald-900/80 dark:text-emerald-100/80">
            {typeText ? <span>{typeText}</span> : null}
            {centerText ? <span>中心 {centerText}</span> : null}
            {control.query ? <span>查询 {control.query}</span> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function getMatchedControl(
  action: Record<string, unknown>,
): ComputerMatchedControl | null {
  const value = action.matched_control;
  if (!isRecord(value)) return null;
  return value as ComputerMatchedControl;
}

function getControlIdentity(control: ComputerMatchedControl | null) {
  if (!control) return "";
  return firstText(control.name, control.automation_id, control.id);
}

function firstText(...values: Array<unknown>) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value))
      return String(value);
  }
  return "";
}

function formatPoint(value: unknown) {
  if (!isRecord(value)) return "";
  const x = formatNumber(value.x);
  const y = formatNumber(value.y);
  return x && y ? `${x}, ${y}` : "";
}

function formatNumber(value: unknown) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "";
  return String(Math.round(value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function DeviceStatePanel({ state }: { state: DeviceState }) {
  const toneClass = {
    ok: "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-100",
    warn: "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-100",
    error: "border-destructive/30 bg-destructive/10 text-destructive",
    loading: "border-border bg-background text-foreground",
  }[state.tone];
  return (
    <div className={cn("rounded-2xl border p-4", toneClass)}>
      <div className="flex items-center gap-2 text-sm font-semibold">
        <ActivityIcon className="size-4" />
        这台电脑 · {state.label}
      </div>
      <p className="mt-2 text-xs leading-5 opacity-80">{state.detail}</p>
    </div>
  );
}

function PermissionGuardPanel({
  hasScreenshot,
  hasPreview,
  leaseState,
  onReleaseLease,
  previewSecondsLeft,
  releaseDisabled,
}: {
  hasScreenshot: boolean;
  hasPreview: boolean;
  leaseState: LeaseState;
  onReleaseLease: () => void;
  previewSecondsLeft: number | null;
  releaseDisabled: boolean;
}) {
  const rows = [
    {
      label: "观察",
      value: hasScreenshot ? "已获取屏幕截图" : "只在你点击后观察屏幕",
    },
    {
      label: "确认",
      value: hasPreview ? "有动作等待确认" : "鼠标键盘不会直接执行",
    },
    {
      label: "过期",
      value:
        previewSecondsLeft !== null
          ? `${previewSecondsLeft}s 后自动清除`
          : "确认令牌短时有效",
    },
    {
      label: "接管",
      value: leaseState.detail,
    },
  ];
  return (
    <div className="rounded-2xl border border-border bg-background/70 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <ShieldCheckIcon className="size-4 text-emerald-600" />
          权限护栏
        </div>
        {leaseState.canRelease ? (
          <Button
            size="sm"
            variant="outline"
            onClick={onReleaseLease}
            disabled={releaseDisabled}
          >
            释放接管
          </Button>
        ) : null}
      </div>
      <div className="mt-3 grid gap-2">
        {rows.map((row) => (
          <div
            key={row.label}
            className="grid grid-cols-[3.5rem_1fr] gap-2 text-xs leading-5"
          >
            <span className="text-muted-foreground">{row.label}</span>
            <span className="font-medium">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function CurrentActionPanel({ action }: { action: ActiveAction }) {
  const toneClass = {
    idle: "border-border bg-background/70",
    active:
      "border-blue-200 bg-blue-50 text-blue-950 dark:border-blue-900/60 dark:bg-blue-950/20 dark:text-blue-100",
    warn: "border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-100",
    ok: "border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/20 dark:text-emerald-100",
  }[action.tone];
  return (
    <div className={cn("rounded-2xl border p-4", toneClass)}>
      <div className="flex items-center gap-2 text-sm font-semibold">
        <MousePointerClickIcon className="size-4" />
        当前动作 · {action.label}
      </div>
      <p className="mt-2 text-xs leading-5 opacity-80">{action.detail}</p>
    </div>
  );
}

// Token-TTL countdown chip. Color shifts from neutral → amber as the
// 90 s window narrows so the operator notices before the server-side
// token 404s. ``secondsLeft === 0`` is rendered explicitly because
// the auto-clear effect only runs after the next render cycle, so the
// UI may briefly show the expired state.
function CountdownChip({ secondsLeft }: { secondsLeft: number }) {
  const tone =
    secondsLeft === 0
      ? "border-destructive/40 bg-destructive/10 text-destructive"
      : secondsLeft <= 15
        ? "border-amber-300 bg-amber-50 text-amber-950 dark:bg-amber-950/20 dark:text-amber-100"
        : "border-border bg-background text-muted-foreground";
  const label = secondsLeft === 0 ? "已过期" : `${secondsLeft}s`;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-mono",
        tone,
      )}
      aria-live="polite"
    >
      <ClockIcon className="size-3" />
      {label}
    </span>
  );
}

function summarizeResult(data: ComputerExecuteResult) {
  const result = data.result || {};
  if (typeof result.error === "string") return result.error;
  return JSON.stringify(result);
}
