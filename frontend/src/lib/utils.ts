import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// Custom font-size names must be registered; otherwise text-ui is treated as
// a color and gets removed when a component also supplies text-foreground.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: ["ui", "ui-caption", "ui-body", "ui-title"] },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Shared class for external links (underline by default). */
export const externalLinkClass =
  "text-primary underline underline-offset-2 hover:no-underline";
/** Link style without underline by default (e.g. for streaming/loading). */
export const externalLinkClassNoUnderline = "text-primary hover:underline";
