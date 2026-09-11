import { swallow } from "@/core/utils/log";

export type LinkOpenTarget = "external" | "in_app";

const LINK_OPEN_TARGET_KEY = "octopus:automation:link-open-target";
const LINK_OPEN_TARGET_EVENT = "octopus:link-open-target-changed";

export function getLinkOpenTarget(local = false): LinkOpenTarget {
  if (typeof window === "undefined") return "external";
  try {
    return (window.localStorage.getItem(
      local ? `${LINK_OPEN_TARGET_KEY}:local` : LINK_OPEN_TARGET_KEY,
    ) ?? (local ? "in_app" : "external")) === "in_app"
      ? "in_app"
      : "external";
  } catch (error) {
    swallow(error, "storage");
    return "external";
  }
}

export function setLinkOpenTarget(target: LinkOpenTarget, local = false): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      local ? `${LINK_OPEN_TARGET_KEY}:local` : LINK_OPEN_TARGET_KEY,
      target,
    );
    if (local) return;
    window.dispatchEvent(
      new CustomEvent<LinkOpenTarget>(LINK_OPEN_TARGET_EVENT, {
        detail: target,
      }),
    );
  } catch (error) {
    swallow(error, "storage");
  }
}

export function subscribeLinkOpenTarget(
  listener: (target: LinkOpenTarget) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const onChange = (event: Event) => {
    listener(
      (event as CustomEvent<LinkOpenTarget>).detail ?? getLinkOpenTarget(),
    );
  };
  const onStorage = (event: StorageEvent) => {
    if (event.key === LINK_OPEN_TARGET_KEY) listener(getLinkOpenTarget());
  };
  window.addEventListener(LINK_OPEN_TARGET_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(LINK_OPEN_TARGET_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}
