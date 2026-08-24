import type { ReactNode } from "react";

export function Loading({ label = "Yükleniyor…" }: { label?: string }) {
  return <div className="loading">{label}</div>;
}

export function ErrorState({ error, hint }: { error: unknown; hint?: string }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="error-state">
      <div>{message}</div>
      {hint && <div className="small muted" style={{ marginTop: 6 }}>{hint}</div>}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="table-empty">{children}</div>;
}

export function Banner({
  tone = "info",
  children,
}: {
  tone?: "info" | "warning" | "danger" | "success";
  children: ReactNode;
}) {
  return <div className={"banner banner-" + tone}>{children}</div>;
}
