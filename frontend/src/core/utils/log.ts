const isDev = typeof process !== "undefined" && process.env.NODE_ENV === "development";

export function swallow(error: unknown, context?: string) {
  if (isDev) {
    console.warn(`[swallow${context ? `:${context}` : ""}]`, error);
  }
}
