/**
 * Global UI state.
 *
 * Deliberately tiny: the backend owns all trading state, the frontend only
 * remembers user interface preferences.
 */

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

export interface Toast {
  id: number;
  message: string;
  tone: "success" | "error" | "info";
}

interface AppStateValue {
  toasts: Toast[];
  pushToast: (message: string, tone?: Toast["tone"]) => void;
  dismissToast: (id: number) => void;
  refreshPaused: boolean;
  setRefreshPaused: (value: boolean) => void;
}

const AppStateContext = createContext<AppStateValue | null>(null);

let toastId = 0;

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [refreshPaused, setRefreshPaused] = useState(false);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const pushToast = useCallback(
    (message: string, tone: Toast["tone"] = "info") => {
      toastId += 1;
      const toast = { id: toastId, message, tone };
      setToasts((current) => [...current, toast]);
      window.setTimeout(() => dismissToast(toast.id), 6000);
    },
    [dismissToast],
  );

  const value = useMemo(
    () => ({ toasts, pushToast, dismissToast, refreshPaused, setRefreshPaused }),
    [toasts, pushToast, dismissToast, refreshPaused],
  );

  return <AppStateContext.Provider value={value}>{children}</AppStateContext.Provider>;
}

export function useAppState(): AppStateValue {
  const context = useContext(AppStateContext);
  if (!context) {
    throw new Error("useAppState must be used inside AppStateProvider");
  }
  return context;
}
