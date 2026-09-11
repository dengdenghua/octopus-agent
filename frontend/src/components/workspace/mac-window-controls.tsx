/** @deprecated Window controls belong to the OS or browser host. */
export function WorkspaceNavigationControls(_props: { className?: string }) {
  return null;
}

// Keep the legacy export for separately built workbench consumers.
export const MacWindowControls = WorkspaceNavigationControls;
