import { swallow } from "@/core/utils/log";
export async function copyTextToClipboard(text: string): Promise<void> {
  const value = String(text ?? "");

  if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch (e) {
      swallow(e);
      // Fall through to the DOM selection fallback below. Some embedded
      // browser shells expose Clipboard API but reject writes by permission.
    }
  }

  if (typeof document === "undefined" || !document.body) {
    throw new Error("Clipboard API is not available");
  }

  const selection = document.getSelection();
  const previousRange =
    selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  textarea.style.top = "0";

  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  let copied = false;
  try {
    copied = document.execCommand("copy");
  } finally {
    textarea.remove();
    if (selection) {
      selection.removeAllRanges();
      if (previousRange) selection.addRange(previousRange);
    }
  }

  if (!copied) {
    throw new Error("Clipboard copy was blocked");
  }
}
