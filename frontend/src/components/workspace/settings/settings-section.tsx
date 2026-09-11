import { cn } from "@/lib/utils";

export function SettingsSection({
  className,
  title,
  description,
  children,
}: {
  className?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className={cn(className)}>
      <header className="space-y-1.5">
        <div
          role="heading"
          aria-level={3}
          className="text-base font-semibold tracking-tight"
        >
          {title}
        </div>
        {description && (
          <div className="text-ui leading-6 text-muted-foreground">
            {description}
          </div>
        )}
      </header>
      <div className="mt-4">{children}</div>
    </section>
  );
}
