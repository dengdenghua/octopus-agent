import { useState, type RefObject } from "react";
import { useNavigate } from "react-router-dom";
import {
  CloudSun,
  Grip,
  Search,
  Settings,
  UserRound,
  ArrowUpRight,
  type LucideIcon,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAuth } from "@/providers/AuthProvider";
import { cn } from "@/lib/utils";
import "./browser-start-page.css";

const WALLPAPER_KEY = "echo.browser.start.wallpaper.v1";
const WALLPAPERS = [
  {
    id: "ocean",
    name: "星海",
    url: "/images/browser-wallpapers/milky-way-ocean.png",
  },
  {
    id: "forest",
    name: "森林",
    url: "/images/browser-wallpapers/forest-calm.png",
  },
  { id: "sky", name: "晴空", url: "/images/browser-wallpapers/sky-studio.png" },
] as const;

interface StartApp {
  name: string;
  url: string;
  icon: LucideIcon;
  description: string;
  category: string;
}
interface Props {
  active: boolean;
  query: string;
  onQueryChange: (query: string) => void;
  onSearch: () => void;
  searchInputRef: RefObject<HTMLInputElement | null>;
  engines: { name: string }[];
  selectedEngine: number;
  onEngineChange: (index: number) => void;
  apps: StartApp[];
  onOpen: (url: string) => void;
  onManageDesktop: () => void;
}

export function BrowserStartPage({
  active,
  query,
  onQueryChange,
  onSearch,
  searchInputRef,
  engines,
  selectedEngine,
  onEngineChange,
  apps,
  onOpen,
  onManageDesktop,
}: Props) {
  const { user, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [panel, setPanel] = useState<"apps" | "settings" | "account" | null>(
    null,
  );
  const [appQuery, setAppQuery] = useState("");
  const [wallpaper, setWallpaper] = useState(() => {
    try {
      return localStorage.getItem(WALLPAPER_KEY) || "ocean";
    } catch {
      return "ocean";
    }
  });
  const image =
    WALLPAPERS.find((item) => item.id === wallpaper) ?? WALLPAPERS[0];
  const visibleApps = apps.filter((app) =>
    `${app.name} ${app.description}`
      .toLowerCase()
      .includes(appQuery.trim().toLowerCase()),
  );
  const chooseWallpaper = (id: string) => {
    setWallpaper(id);
    try {
      localStorage.setItem(WALLPAPER_KEY, id);
    } catch {
      /* Session preference still works. */
    }
  };
  const manageDesktop = () => {
    setPanel(null);
    onManageDesktop();
  };
  return (
    <section
      aria-label="浏览器主页"
      className="browser-start-page"
      style={{ display: active ? undefined : "none" }}
    >
      <img
        className="browser-start-wallpaper"
        src={image.url}
        alt=""
        fetchPriority="high"
        decoding="async"
        draggable={false}
      />
      <header className="browser-start-header">
        <button
          type="button"
          className="browser-start-icon"
          aria-label="应用"
          title="应用"
          aria-haspopup="dialog"
          onClick={() => setPanel("apps")}
        >
          <Grip size={20} strokeWidth={1.75} />
        </button>
        <div className="browser-start-actions">
          <button
            type="button"
            className="browser-start-weather"
            title="查看天气"
            onClick={() =>
              onOpen(
                "https://www.bing.com/search?q=" +
                  encodeURIComponent("当地天气"),
              )
            }
          >
            <CloudSun size={20} strokeWidth={1.75} />
            <span>天气</span>
          </button>
          <button
            type="button"
            className="browser-start-icon"
            aria-label="主页设置"
            title="主页设置"
            aria-haspopup="dialog"
            onClick={() => setPanel("settings")}
          >
            <Settings size={20} strokeWidth={1.75} />
          </button>
          <button
            type="button"
            className="browser-start-account"
            aria-label={isAuthenticated ? "账号" : "登录"}
            title={isAuthenticated ? "账号" : "登录"}
            onClick={() =>
              isAuthenticated
                ? setPanel("account")
                : navigate("/login?returnTo=%2Fbrowser")
            }
          >
            {isAuthenticated ? (
              <UserRound size={20} strokeWidth={1.75} aria-hidden="true" />
            ) : (
              "登录"
            )}
          </button>
        </div>
      </header>
      <form
        className="browser-start-search"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch();
        }}
      >
        <input
          ref={searchInputRef}
          aria-label="搜索网页"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="搜索网页"
          autoComplete="off"
          spellCheck={false}
          enterKeyHint="search"
        />
        <button
          type="submit"
          aria-label="搜索"
          title={`使用 ${engines[selectedEngine]?.name ?? "搜索引擎"} 搜索`}
        >
          <Search size={22} strokeWidth={1.8} />
        </button>
      </form>
      <Dialog
        open={active && panel !== null}
        onOpenChange={(open) => {
          if (!open) setPanel(null);
        }}
      >
        <DialogContent
          className={cn(
            "browser-start-panel flex flex-col overflow-hidden",
            panel === "apps" && "browser-start-app-panel",
          )}
        >
          <DialogHeader className="shrink-0 pr-8 text-left">
            <DialogTitle>
              {panel === "apps"
                ? "应用"
                : panel === "account"
                  ? "账号"
                  : "主页设置"}
            </DialogTitle>
            <DialogDescription>
              {panel === "apps"
                ? "打开常用网站与 Echo 工作台"
                : panel === "account"
                  ? "当前 Echo 登录账号"
                  : "设置主页背景、搜索引擎与应用"}
            </DialogDescription>
          </DialogHeader>
          <div className="min-h-0 overflow-y-auto overscroll-contain">
            {panel === "apps" ? (
              <>
                <input
                  className="browser-start-app-search"
                  aria-label="搜索应用"
                  placeholder="搜索应用…"
                  value={appQuery}
                  onChange={(event) => setAppQuery(event.target.value)}
                />
                <div className="browser-start-apps">
                  {visibleApps.map((app) => (
                    <button
                      type="button"
                      key={app.url}
                      title={app.description}
                      onClick={() => {
                        setPanel(null);
                        onOpen(app.url);
                      }}
                    >
                      <span>
                        <app.icon size={23} strokeWidth={1.6} />
                      </span>
                      <span>{app.name}</span>
                    </button>
                  ))}
                </div>
                {!visibleApps.length && (
                  <p className="py-8 text-center text-sm text-muted-foreground">
                    没有找到相关应用
                  </p>
                )}
                <button
                  type="button"
                  className="browser-start-setting-row"
                  onClick={manageDesktop}
                >
                  管理应用与小组件
                  <ArrowUpRight size={16} />
                </button>
              </>
            ) : panel === "account" ? (
              <>
                <p className="mb-4 text-sm font-medium">
                  {user?.username || "本地账号"}
                </p>
                <button
                  type="button"
                  className="browser-start-setting-row"
                  onClick={() => navigate("/settings?section=account")}
                >
                  账号设置
                  <ArrowUpRight size={16} />
                </button>
              </>
            ) : (
              <>
                <p className="mb-3 text-xs font-medium text-muted-foreground">
                  主页背景
                </p>
                <div className="browser-start-wallpapers">
                  {WALLPAPERS.map((item) => (
                    <button
                      type="button"
                      key={item.id}
                      aria-pressed={image.id === item.id}
                      onClick={() => chooseWallpaper(item.id)}
                    >
                      <img src={item.url} alt="" />
                      <span>{item.name}</span>
                    </button>
                  ))}
                </div>
                {panel === "settings" && (
                  <label className="mt-6 block text-sm">
                    搜索引擎
                    <select
                      className="browser-start-app-search mt-2"
                      value={selectedEngine}
                      onChange={(event) =>
                        onEngineChange(Number(event.target.value))
                      }
                    >
                      {engines.map((engine, index) => (
                        <option key={engine.name} value={index}>
                          {engine.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <button
                  type="button"
                  className="browser-start-setting-row mt-5"
                  onClick={manageDesktop}
                >
                  管理应用与小组件
                  <ArrowUpRight size={16} />
                </button>
              </>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
