import { useAppState } from "@/state/appStateContext";

/** Floating notification stack. */
export function Toasts() {
  const { toasts, dismissToast } = useAppState();
  if (toasts.length === 0) {
    return null;
  }
  return (
    <div className="toast-stack">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={"toast " + toast.tone}
          onClick={() => dismissToast(toast.id)}
          role="alert"
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}
