let pendingCustomModelSetup = false;
export const CUSTOM_MODEL_SETUP_EVENT = "octopus:add-custom-model";

export function openCustomModelSetup() {
  pendingCustomModelSetup = true;
  window.dispatchEvent(
    new CustomEvent("octopus:open-settings", { detail: { tab: "models" } }),
  );
  window.dispatchEvent(new Event(CUSTOM_MODEL_SETUP_EVENT));
}

export function consumeCustomModelSetup() {
  const pending = pendingCustomModelSetup;
  pendingCustomModelSetup = false;
  return pending;
}
