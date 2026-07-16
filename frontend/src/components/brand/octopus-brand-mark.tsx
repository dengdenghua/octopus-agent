import { cn } from "@/lib/utils";

type OctopusBrandMarkProps = {
  className?: string;
  size?: "md" | "lg";
};

const sizeClass = {
  md: {
    outer: "size-9 rounded-[11px]",
    ring: "size-4",
    core: "size-1.5",
    node: "size-1",
    inset: "inset-1.5 rounded-[7px]",
  },
  lg: {
    outer: "size-11 rounded-[13px]",
    ring: "size-5",
    core: "size-2",
    node: "size-1.5",
    inset: "inset-2 rounded-[8px]",
  },
} as const;

export function OctopusBrandMark({
  className,
  size = "md",
}: OctopusBrandMarkProps) {
  const token = sizeClass[size];

  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative inline-grid shrink-0 place-items-center overflow-hidden border border-foreground/15 bg-background/95 text-foreground shadow-[var(--shadow-xs)]",
        token.outer,
        className,
      )}
    >
      <span
        className={cn(
          "absolute border border-foreground/10",
          token.inset,
        )}
      />
      <span
        className={cn(
          "relative grid place-items-center rounded-full border border-foreground/45",
          token.ring,
        )}
      >
        <span className={cn("rounded-full bg-primary", token.core)} />
      </span>
      <span
        className={cn(
          "absolute rounded-full bg-foreground/55",
          token.node,
          size === "lg" ? "left-2 top-2" : "left-1.5 top-1.5",
        )}
      />
      <span
        className={cn(
          "absolute rounded-full bg-primary",
          token.node,
          size === "lg" ? "right-2 top-2" : "right-1.5 top-1.5",
        )}
      />
      <span
        className={cn(
          "absolute rounded-full bg-foreground/35",
          token.node,
          size === "lg" ? "bottom-2 left-2" : "bottom-1.5 left-1.5",
        )}
      />
      <span
        className={cn(
          "absolute rounded-full bg-foreground/55",
          token.node,
          size === "lg" ? "bottom-2 right-2" : "bottom-1.5 right-1.5",
        )}
      />
    </span>
  );
}
