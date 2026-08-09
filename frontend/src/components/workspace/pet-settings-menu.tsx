/**
 * 助手对话页 header 的「宠物设置」入口。
 *
 * 宠物 = 助手的人格化形象，因此设置入口放在助手页内：一个极简开关面板，
 * 控制输入框角落宠物是否显示。状态全局持久化，见 core/pet/pet-settings.ts。
 */
import { useState } from "react";
import { PawPrintIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import {
  setPetSettings,
  usePetSettings,
} from "@/core/pet/pet-settings";
import { cn } from "@/lib/utils";

export function PetSettingsMenu() {
  const [open, setOpen] = useState(false);
  const settings = usePetSettings();

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          aria-label="宠物设置"
          title="宠物设置"
          className={cn(
            "flex size-[42px] items-center justify-center rounded-lg border shadow-none transition-all duration-base focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 sm:size-8",
            open
              ? "border-transparent bg-transparent text-foreground/82 hover:border-border-default hover:bg-muted/55 hover:text-foreground"
              : "border-transparent bg-transparent text-muted-foreground hover:border-border-default hover:bg-muted/55 hover:text-foreground",
          )}
        >
          <PawPrintIcon className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" sideOffset={8}>
        <div className="flex min-w-[10rem] items-center justify-between gap-6 px-3 py-2.5">
          <span className="text-sm text-foreground">显示宠物</span>
          <Switch
            checked={settings.visible}
            onCheckedChange={(checked) => setPetSettings({ visible: checked })}
            aria-label="显示宠物"
          />
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
