/**
 * Global UI state: the context and the hook.
 *
 * Kept in a component-free module so the provider file exports a component
 * only, which is what React Fast Refresh needs.
 */

import { createContext, useContext } from "react";

export interface Toast {
  id: number;
  message: string;
  tone: "success" | "error" | "info";
}

export interface AppStateValue {
  toasts: Toast[];
  pushToast: (message: string, tone?: Toast["tone"]) => void;
  dismissToast: (id: number) => void;
  refreshPaused: boolean;
  setRefreshPaused: (value: boolean) => void;
}

export const AppStateContext = createContext<AppStateValue | null>(null);

/** Access the global UI state. Throws when used outside the provider. */
export function useAppState(): AppStateValue {
  const context = useContext(AppStateContext);
  if (!context) {
    throw new Error("useAppState must be used inside AppStateProvider");
  }
  return context;
}
