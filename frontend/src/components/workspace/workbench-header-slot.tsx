import { createContext } from "react";

// Lets the layout place its size control in the workbench's own toolbar.
export const WorkbenchHeaderSlot = createContext<
  ((element: HTMLDivElement | null) => void) | undefined
>(undefined);
