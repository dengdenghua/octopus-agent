import { cn } from "@/lib/utils";

export interface OnboardingStepProps {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
}

export function OnboardingStep({
  title,
  description,
  children,
  className,
}: OnboardingStepProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-6 px-2 py-4 text-center",
        className,
      )}
    >
      <div className="space-y-2">
        <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
        {description && (
          <p className="text-muted-foreground text-sm max-w-md mx-auto">
            {description}
          </p>
        )}
      </div>
      <div className="w-full">{children}</div>
    </div>
  );
}
