import { cn } from "@/lib/utils";

export function Section({
  className,
  title,
  subtitle,
  children,
}: {
  className?: string;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("mx-auto flex flex-col py-20", className)}>
      <header className="flex flex-col items-center justify-between">
        <div className="mb-6 bg-gradient-to-r from-purple-400 via-pink-400 to-blue-400 bg-clip-text text-center text-5xl font-bold text-transparent">
          {title}
        </div>
        {subtitle && (
          <div className="max-w-2xl text-center text-lg leading-relaxed text-muted-foreground">
            {subtitle}
          </div>
        )}
      </header>
      <main className="mt-8">{children}</main>
    </section>
  );
}
