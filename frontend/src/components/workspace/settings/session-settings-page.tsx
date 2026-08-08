import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

/**
 * Conversation/session behaviour settings.
 *
 * Currently hosts the "auto-new-session" toggle: when enabled, sending a
 * message into a thread that has been idle longer than the threshold opens a
 * fresh thread instead of stacking onto the stale one. The actual enforcement
 * lives in the realtime thread page; this page only owns the preference.
 */
export default function SessionSettingsPage() {
  const [settings, setSettings] = useLocalSettings();
  const hours = settings.session.auto_new_session_hours;
  const enabled = hours > 0;

  const handleToggle = (next: boolean) => {
    setSettings("session", { auto_new_session_hours: next ? 6 : 0 });
  };

  const handleHoursChange = (value: string) => {
    const n = Math.max(1, Math.floor(Number(value) || 1));
    setSettings("session", { auto_new_session_hours: n });
  };

  return (
    <SettingsSection
      title="会话"
      description="控制长时间未对话时是否自动开启新会话，避免上下文过长、节省 Token。"
    >
      <div className="flex flex-col gap-4">
        <div className="flex items-center justify-between gap-4 rounded-lg border bg-card p-4">
          <div className="min-w-0">
            <p className="text-sm font-medium">自动新起会话</p>
            <p className="text-muted-foreground mt-1 text-xs leading-5">
              超过设定时长未对话时，下次发送会自动开启一个新会话，而不是继续在旧会话里堆叠上下文。
            </p>
          </div>
          <Switch
            checked={enabled}
            onCheckedChange={handleToggle}
            aria-label="自动新起会话"
          />
        </div>

        {enabled && (
          <div className="flex items-center gap-3 rounded-lg border bg-card p-4">
            <label
              htmlFor="auto-new-session-hours"
              className="text-sm font-medium whitespace-nowrap"
            >
              空闲超过
            </label>
            <Input
              id="auto-new-session-hours"
              type="number"
              min={1}
              max={720}
              value={hours}
              onChange={(e) => handleHoursChange(e.target.value)}
              className="w-24"
            />
            <span className="text-sm text-muted-foreground whitespace-nowrap">
              小时后自动开启新会话
            </span>
          </div>
        )}
      </div>
    </SettingsSection>
  );
}
