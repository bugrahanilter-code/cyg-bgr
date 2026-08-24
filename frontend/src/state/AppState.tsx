/**
 * Global UI state provider.
 *
 * Deliberately tiny: the backend owns all trading state, the frontend only
 * remembers user interface preferences and transient notifications.
 */

import { useCallback, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { AppStateContext } from "@/state/appStateContext";
import type { Toast } from "@/state/appStateContext";

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
