/** Render service metadata without leaking JavaScript object coercion into UI. */
export function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "未读取";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value))
    return value.length ? value.map(displayValue).join("、") : "无";
  if (typeof value === "object")
    return (
      Object.entries(value)
        .map(([key, item]) => `${key}：${displayValue(item)}`)
        .join("；") || "无"
    );
  if (value === "healthy") return "指标正常";
  if (value === "none") return "无";
  return String(value);
}

/** A bare YAML block marker is metadata syntax, not a usable description. */
export function skillDescription(value: unknown): string {
  if (typeof value !== "string") return "暂无用途说明，可查看来源与版本。";
  const text = value
    .trim()
    .replace(/^[|>][-+]?\s*\n\s*/, "")
    .trim();
  return !text || /^[|>][-+]?$/.test(text)
    ? "暂无用途说明，可查看来源与版本。"
    : text;
}
