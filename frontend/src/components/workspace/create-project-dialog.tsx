import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useCreateProject } from "@/core/projects/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { isIMEComposing } from "@/lib/ime";

interface CreateProjectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function CreateProjectDialog({
  open,
  onOpenChange,
}: CreateProjectDialogProps) {
  const { t } = useI18n();
  const CATEGORY_PRESETS = useMemo(
    () => [
      {
        label: t.createProjectDialog.categoryInvest,
        icon: "📈",
        category: "investment",
      },
      {
        label: t.createProjectDialog.categoryHomework,
        icon: "📝",
        category: "homework",
      },
      {
        label: t.createProjectDialog.categoryWriting,
        icon: "✍️",
        category: "writing",
      },
      {
        label: t.createProjectDialog.categoryTravel,
        icon: "✈️",
        category: "travel",
      },
    ],
    [t],
  );
  const [name, setName] = useState("");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);
  const [selectedIcon, setSelectedIcon] = useState<string>("📁");
  const { mutate: createProject, isPending } = useCreateProject();

  const resetForm = () => {
    setName("");
    setSelectedCategory(null);
    setSelectedIcon("📁");
  };

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) resetForm();
    onOpenChange(nextOpen);
  };

  const handleCategorySelect = (preset: (typeof CATEGORY_PRESETS)[number]) => {
    if (selectedCategory === preset.category) {
      setSelectedCategory(null);
      setSelectedIcon("📁");
    } else {
      setSelectedCategory(preset.category);
      setSelectedIcon(preset.icon);
      if (!name) {
        setName(preset.label);
      }
    }
  };

  const handleSubmit = () => {
    if (!name.trim() || isPending) return;
    createProject(
      {
        name: name.trim(),
        icon: selectedIcon,
        category: selectedCategory ?? undefined,
      },
      {
        onSuccess: () => {
          resetForm();
          onOpenChange(false);
        },
      },
    );
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-[425px]">
        <DialogHeader>
          <DialogTitle>{t.createProjectDialog.title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-4">
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t.createProjectDialog.placeholder}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isIMEComposing(e)) {
                e.preventDefault();
                handleSubmit();
              }
            }}
          />
          <div className="flex flex-col gap-2">
            <span className="text-muted-foreground text-sm">
              {t.createProjectDialog.quickCategory}
            </span>
            <div className="flex flex-wrap gap-2">
              {CATEGORY_PRESETS.map((preset) => (
                <Button
                  key={preset.category}
                  variant={
                    selectedCategory === preset.category ? "default" : "outline"
                  }
                  size="sm"
                  onClick={() => handleCategorySelect(preset)}
                >
                  <span className="mr-1">{preset.icon}</span>
                  {preset.label}
                </Button>
              ))}
            </div>
          </div>
          <p className="text-muted-foreground text-xs">
            {t.createProjectDialog.hint}
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            {t.createProjectDialog.cancel}
          </Button>
          <Button onClick={handleSubmit} disabled={!name.trim() || isPending}>
            {t.createProjectDialog.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
