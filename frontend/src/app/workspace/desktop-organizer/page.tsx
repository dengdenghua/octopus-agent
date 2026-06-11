import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  FolderKanbanIcon,
  type LucideIcon,
  MousePointerClickIcon,
  ShieldCheckIcon,
  SparklesIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";

const DESKTOP_ORGANIZER_ENABLED_KEY = "octopus:desktop-organizer-enabled";

export default function DesktopOrganizerPage() {
  const [enabled, setEnabled] = useState(false);
  const [busy, setBusy] = useState<"install" | "remove" | null>(null);
  const [contextMenuMessage, setContextMenuMessage] = useState("");
  const isElectron = typeof window !== "undefined" && !!window.octopus?.isElectron;

  useEffect(() => {
    setEnabled(localStorage.getItem(DESKTOP_ORGANIZER_ENABLED_KEY) === "true");
  }, []);

  const updateEnabled = (value: boolean) => {
    setEnabled(value);
    localStorage.setItem(DESKTOP_ORGANIZER_ENABLED_KEY, String(value));
  };

  const installContextMenu = async () => {
    setBusy("install");
    setContextMenuMessage("");
    const result = await window.octopus?.desktop?.installContextMenu?.();
    setBusy(null);
    setContextMenuMessage(result?.ok ? "系统右键命令已安装。" : result?.error || "当前环境不支持安装。");
  };

  const removeContextMenu = async () => {
    setBusy("remove");
    setContextMenuMessage("");
    const result = await window.octopus?.desktop?.removeContextMenu?.();
    setBusy(null);
    setContextMenuMessage(result?.ok ? "系统右键命令已移除。" : result?.error || "当前环境不支持移除。");
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 py-2">
          <section className="workspace-panel flex flex-col gap-5 rounded-[1.75rem] p-6">
            <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-3">
                <div className="flex size-11 items-center justify-center rounded-xl bg-gradient-to-br from-blue-500 to-cyan-500 text-white shadow-sm">
                  <FolderKanbanIcon className="size-5" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold tracking-tight">桌面助手</h1>
                  <p className="text-sm text-muted-foreground">
                    默认启动进入工作区；需要处理系统桌面文件时，再开启透明桌面助手。
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-3 rounded-xl border border-border bg-background/70 px-4 py-3">
                <span className="text-sm font-medium">
                  {enabled ? "已开启" : "未开启"}
                </span>
                <Switch checked={enabled} onCheckedChange={updateEnabled} />
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-3">
              <InfoTile
                icon={ShieldCheckIcon}
                title="不接管系统桌面"
                body="透明层只在你打开时出现，关闭后鼠标与窗口控制权还给 Windows。"
              />
              <InfoTile
                icon={MousePointerClickIcon}
                title="右键唤起助手"
                body="在整理层内右键可打开按类型归档的桌面文件抽屉。"
              />
              <InfoTile
                icon={SparklesIcon}
                title="安全预览优先"
                body="当前只做视图收纳，不自动移动文件；移动整理会单独加确认与撤销。"
              />
            </div>

            {!isElectron && (
              <div className="rounded-2xl border border-amber-500/20 bg-amber-500/[0.08] px-4 py-3 text-sm text-muted-foreground">
                当前打开的是网页环境，所以右键菜单安装/移除会保持禁用。切到桌面版后，这两项才会真正生效。
              </div>
            )}

            <div className="rounded-2xl border border-border bg-background/70 p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-sm font-semibold">系统右键菜单</h2>
                  <p className="mt-1 text-sm leading-6 text-muted-foreground">
                    在 Windows 桌面空白处右键显示 “Octopus 一键整理桌面”。
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={!enabled || busy === "install" || !isElectron}
                    onClick={installContextMenu}
                  >
                    {busy === "install" ? "安装中" : "安装右键命令"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={busy === "remove" || !isElectron}
                    onClick={removeContextMenu}
                  >
                    {busy === "remove" ? "移除中" : "移除"}
                  </Button>
                </div>
              </div>
              {contextMenuMessage && (
                <p className="mt-3 text-sm text-muted-foreground">{contextMenuMessage}</p>
              )}
            </div>

            <div className="flex flex-wrap gap-3">
              {enabled ? (
                <Button asChild>
                  <Link to="/desktop">打开桌面助手</Link>
                </Button>
              ) : (
                <Button disabled>打开桌面助手</Button>
              )}
              <Button variant="outline" asChild>
                <Link to="/workspace/realtime/new">回到工作区</Link>
              </Button>
            </div>
          </section>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function InfoTile({
  icon: Icon,
  title,
  body,
}: {
  icon: LucideIcon;
  title: string;
  body: string;
}) {
  return (
    <div className="rounded-2xl border border-border bg-background/70 p-4">
      <Icon className="mb-3 size-5 text-primary" />
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">{body}</p>
    </div>
  );
}
